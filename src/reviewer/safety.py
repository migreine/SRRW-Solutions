"""Adversarial safety reviewer. Deterministic, no LLM. Owner: Rohan (L).

Written independently of src/rules/ (separate session, separate prompt, rules code not read):
- re-derive FUEL / DUTY / WAKE for the chosen candidate from Scenario + Candidate.params only
- re-derive the delay the chosen candidate causes and compare with est_delay_min (note only)
- check every value a supporting agent cited in `cited_fields` against the Scenario
- compare its own pass/fail with the engine's rule_results *after* deciding, to report disagreement

rule_results never feed the re-derivation. The one way they affect the verdict is
safety-conservative: if the engine failed the chosen candidate on any rule, the verdict is REJECT.

Every constant below is ASSUMED: docs/regulatory_sources.md did not exist when this was written.
Reconcile against that doc when it lands, never against src/rules/.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel

from src.schemas import Candidate, Recommendation, Scenario, Tagged, Turn

Verdict = Literal["APPROVE", "REJECT", "MODIFY"]

# ---- constants (all assumed, pending docs/regulatory_sources.md) ---------------------------------
FUEL_FINAL_RESERVE_MIN = 45.0  # 14 CFR 121.639
CRUISE_NM_PER_MIN = 7.0  # 420 kt
DIVERT_GROUND_MIN = 60.0  # ground time at the alternate

# WAKE (FAA JO 7110.65 5-5-4). Required spacing is per runway, so the airport-wide arrival rate is
# split over an assumed number of arrival runways before the two are compared.
ASSUMED_LEADER_CATEGORY = "L"  # Large
WAKE_SEP_NM_BEHIND_LARGE = 3.0  # radar minimum; the same for every follower category (H/L/S)
ASSUMED_ARRIVAL_RUNWAYS = 2
APPROACH_KT = 140.0
MIN_EFFECTIVE_AAR = 1.0
DELAY_REL_TOL = 0.20
DELAY_ABS_TOL_MIN = 5.0
CITE_ABS_TOL = 1.0
CITE_REL_TOL = 0.02

CIT_FUEL = "14 CFR 121.639; 45-min final reserve: assumed"
CIT_DIVERT = "assumed: 420 kt cruise = 7 NM/min, 60 min ground time at alternate"
CIT_DUTY = "14 CFR 117; duty remaining >= 0 at arrival: assumed"
CIT_WAKE_LEADER = (
    "assumed: leader category L (Large), 3 NM radar minimum behind it for every follower category"
)
CIT_WAKE_RUNWAYS = "assumed: 2 arrival runways share the airport arrival rate"
CIT_WAKE_APPROACH = "assumed: 140 kt approach speed"
CIT_WAKE = f"FAA JO 7110.65 5-5-4; {CIT_WAKE_LEADER}; {CIT_WAKE_RUNWAYS}; {CIT_WAKE_APPROACH}"
CIT_DELAY = "assumed: reviewer delay tolerance 20% and 5 min"
CIT_CITED = "reviewer cross-check vs Scenario, tolerance max(1.0, 2%): assumed"

ENGINE_PREFIX = {"R-FUEL": "FUEL", "R-DUTY": "DUTY", "R-WAKE": "WAKE"}
CHECKS = ("FUEL", "DUTY", "WAKE")

# Provenance of untagged top-level Scenario fields, taken from the comments in src/schemas.py.
_FIELD_SOURCE = {
    "scenario_id": "data",
    "row_index": "data",
    "flight": "data",
    "downstream_legs": "data",
    "alternates": "data",
    "gates": "synthetic",
    "connections": "estimated",
}


# ---- small helpers -------------------------------------------------------------------------------
def _fmt(x: Any) -> str:
    if x is None:
        return "n/a"
    f = _to_float(x)
    if f is None:
        return repr(x)
    if math.isinf(f):
        return str(f)
    r = round(f, 1)
    return str(int(r)) if r == int(r) else f"{r:.1f}"


def _to_float(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _param_num(c: Candidate, key: str, notes: list[str], default: float = 0.0) -> float:
    if key not in c.params:
        notes.append(
            f"PARAMS: {c.candidate_id} ({c.kind}) has no '{key}' param, so the reviewer used "
            f"{_fmt(default)} [assumed: safe default]."
        )
        return default
    f = _to_float(c.params.get(key))
    if f is None:
        notes.append(
            f"PARAMS: {c.candidate_id} param '{key}'={c.params.get(key)!r} is not numeric, so the "
            f"reviewer used {_fmt(default)} [assumed: safe default]."
        )
        return default
    return f


def _find_alternate(s: Scenario, iata: Any) -> dict | None:
    if not isinstance(iata, str):
        return None
    for alt in s.alternates:
        if isinstance(alt, dict) and str(alt.get("iata", "")).upper() == iata.strip().upper():
            return alt
    return None


# ---- re-derivation -------------------------------------------------------------------------------
def _motion(s: Scenario, c: Candidate) -> dict:
    """Extra airborne minutes and total delay a candidate causes, from params only.

    Returns {"airborne_extra", "delay", "how", "notes"}. airborne_extra/delay are None when the
    candidate cannot be derived (divert to an unknown alternate); FUEL and DUTY then fail closed.
    """
    notes: list[str] = []
    k = c.kind
    if k == "hold":
        m = _param_num(c, "minutes", notes)
        return {"airborne_extra": m, "delay": m, "how": f"hold {_fmt(m)} min", "notes": notes}
    if k == "slot_shift":
        sh = _param_num(c, "shift_min", notes)
        return {
            "airborne_extra": max(sh, 0.0),
            "delay": sh,
            "how": f"slot shift {_fmt(sh)} min",
            "notes": notes,
        }
    if k == "divert":
        iata = c.params.get("iata")
        alt = _find_alternate(s, iata)
        dist = _to_float(alt.get("distance_nm")) if alt else None
        if dist is None:
            notes.append(
                f"PARAMS: {c.candidate_id} diverts to {iata!r}, which has no usable distance_nm in "
                f"Scenario.alternates (data), so FUEL and DUTY cannot be derived and fail "
                f"[assumed: fail closed]."
            )
            return {"airborne_extra": None, "delay": None, "how": f"divert {iata}", "notes": notes}
        t = dist / CRUISE_NM_PER_MIN
        return {
            "airborne_extra": t,
            "delay": t + DIVERT_GROUND_MIN,
            "how": f"divert {alt.get('iata')} {_fmt(dist)} NM / {_fmt(CRUISE_NM_PER_MIN)} NM/min "
            f"= {_fmt(t)} min airborne",
            "notes": notes,
        }
    if k == "ground_hold":
        m = _param_num(c, "minutes", notes)
        return {"airborne_extra": 0.0, "delay": m, "how": f"ground hold {_fmt(m)} min", "notes": notes}
    if k == "gate_swap":
        f = _to_float(c.params.get("extra_taxi_min", 0)) or 0.0
        return {"airborne_extra": 0.0, "delay": f, "how": f"gate swap +{_fmt(f)} min taxi", "notes": notes}
    # tail_swap: params {} by convention; no airborne or crew delay in this model.
    return {"airborne_extra": 0.0, "delay": 0.0, "how": f"{k}, no delay modelled", "notes": notes}


def _check_fuel(s: Scenario, c: Candidate, mo: dict) -> tuple[dict, str]:
    fuel = _to_float(s.fuel_reserve_min.value)
    src = s.fuel_reserve_min.source
    extra = mo["airborne_extra"]
    if fuel is None or extra is None:
        derived, passed = None, False
    else:
        derived = fuel - extra
        passed = derived >= FUEL_FINAL_RESERVE_MIN
    entry = {
        "check": "FUEL",
        "candidate_id": c.candidate_id,
        "derived": derived,
        "threshold": FUEL_FINAL_RESERVE_MIN,
        "passed": passed,
        "citation": CIT_FUEL,
        "inputs": {"fuel_reserve_min": fuel, "fuel_source": src, "airborne_extra_min": extra},
    }
    cit = CIT_FUEL + ("; " + CIT_DIVERT if c.kind == "divert" else "")
    need = None if extra is None else extra + FUEL_FINAL_RESERVE_MIN
    note = (
        f"FUEL re-derived: {c.candidate_id} ({mo['how']}) needs {_fmt(extra)}+"
        f"{_fmt(FUEL_FINAL_RESERVE_MIN)}={_fmt(need)} min; fuel_reserve_min={_fmt(fuel)} ({src}) "
        f"leaves {_fmt(derived)} min reserve -> {'PASS' if passed else 'FAIL'} [{cit}]."
    )
    return entry, note


def _check_duty(s: Scenario, c: Candidate, mo: dict) -> tuple[dict, str]:
    duty = _to_float(s.crew_duty_remaining_min.value)
    src = s.crew_duty_remaining_min.source
    delay = mo["delay"]
    if duty is None or delay is None:
        derived, passed = None, False
    else:
        derived = duty - delay
        passed = derived >= 0
    entry = {
        "check": "DUTY",
        "candidate_id": c.candidate_id,
        "derived": derived,
        "threshold": 0.0,
        "passed": passed,
        "citation": CIT_DUTY,
        "inputs": {"crew_duty_remaining_min": duty, "duty_source": src, "delay_min": delay},
    }
    how = mo["how"] + (f" + {_fmt(DIVERT_GROUND_MIN)} min ground" if c.kind == "divert" else "")
    cit = CIT_DUTY + ("; " + CIT_DIVERT if c.kind == "divert" else "")
    note = (
        f"DUTY re-derived: {c.candidate_id} ({how}) adds {_fmt(delay)} min; "
        f"crew_duty_remaining_min={_fmt(duty)} ({src}) leaves {_fmt(derived)} min, >= 0 required "
        f"-> {'PASS' if passed else 'FAIL'} [{cit}]."
    )
    return entry, note


def _check_wake(s: Scenario, c: Candidate) -> tuple[dict, str]:
    """Per-runway spacing available vs. the separation behind an assumed Large leader.

    required_s  = 3 NM / (140 kt / 3600)                                  (77.1 s)
    available_s = 3600 * runways / max(nominal_aar - dest_disruption, 1)  (per-runway gap)
    The follower's wake_category is recorded but does not change the 3 NM behind a Large leader.
    """
    cat_raw = str(s.wake_category.value).strip().upper()
    cat_src = s.wake_category.source
    cat_note = "" if cat_raw in ("H", "L", "S") else f", unknown {s.wake_category.value!r}"
    sep_nm = WAKE_SEP_NM_BEHIND_LARGE
    required_s = sep_nm / (APPROACH_KT / 3600.0)
    aar = _to_float(s.nominal_aar.value)
    dis = _to_float(s.dest_disruption.value)
    if aar is None or dis is None:
        eff, avail_s, passed = None, None, False
    else:
        eff = max(aar - dis, MIN_EFFECTIVE_AAR)
        avail_s = 3600.0 * ASSUMED_ARRIVAL_RUNWAYS / eff
        passed = avail_s >= required_s
    entry = {
        "check": "WAKE",
        "candidate_id": c.candidate_id,
        "derived": avail_s,
        "threshold": required_s,
        "passed": passed,
        "citation": CIT_WAKE,
        "inputs": {
            "wake_category": cat_raw,
            "wake_source": cat_src,
            "leader_category": ASSUMED_LEADER_CATEGORY,
            "sep_nm": sep_nm,
            "arrival_runways": ASSUMED_ARRIVAL_RUNWAYS,
            "nominal_aar": aar,
            "aar_source": s.nominal_aar.source,
            "dest_disruption": dis,
            "disruption_source": s.dest_disruption.source,
            "effective_aar": eff,
        },
    }
    note = (
        f"WAKE re-derived: {c.candidate_id} wake_category={cat_raw} ({cat_src}{cat_note}) behind "
        f"an assumed Large leader needs {_fmt(sep_nm)} NM = {_fmt(required_s)} s at "
        f"{_fmt(APPROACH_KT)} kt; nominal_aar={_fmt(aar)} ({s.nominal_aar.source}) - "
        f"dest_disruption={_fmt(dis)} ({s.dest_disruption.source}) = {_fmt(eff)}/h over "
        f"{ASSUMED_ARRIVAL_RUNWAYS} assumed arrival runways gives {_fmt(avail_s)} s per runway "
        f"-> {'PASS' if passed else 'FAIL'} [{CIT_WAKE}]."
    )
    return entry, note


def _rederive(s: Scenario, c: Candidate) -> tuple[dict, list[dict], list[str]]:
    mo = _motion(s, c)
    f, fn = _check_fuel(s, c, mo)
    d, dn = _check_duty(s, c, mo)
    w, wn = _check_wake(s, c)
    return mo, [f, d, w], mo["notes"] + [fn, dn, wn]


# ---- cited-value cross-check ---------------------------------------------------------------------
_PART = re.compile(r"^([^\[\]]+)((?:\[\d+\])*)$")
_IDX = re.compile(r"\[(\d+)\]")
_MISSING = object()


def _resolve(s: Scenario, path: str) -> tuple[Any, str]:
    """Resolve a dotted path with [i] indexes against the Scenario -> (value, source tag).

    value is _MISSING when the path does not resolve. A Tagged resolves to its .value.
    """
    path = path.strip()
    if not path:
        return _MISSING, ""
    obj: Any = s
    source = ""
    for depth, part in enumerate(path.split(".")):
        m = _PART.match(part.strip())
        if not m:
            return _MISSING, ""
        name = m.group(1).strip()
        if isinstance(obj, BaseModel):
            if name not in type(obj).model_fields:
                return _MISSING, ""
            obj = getattr(obj, name)
        elif isinstance(obj, dict):
            if name not in obj:
                return _MISSING, ""
            obj = obj[name]
        else:
            return _MISSING, ""
        if depth == 0:
            source = _FIELD_SOURCE.get(name, source)
        for idx in _IDX.findall(m.group(2)):
            i = int(idx)
            if not isinstance(obj, list) or i >= len(obj):
                return _MISSING, ""
            obj = obj[i]
        if isinstance(obj, Tagged):
            source = obj.source
    if isinstance(obj, Tagged):
        obj = obj.value
    return obj, source


# Agents see values as "path=value (source)" and often copy the source tag into their citation.
_SOURCE_SUFFIX = re.compile(r"\s*\((?:data|estimated|assumed|synthetic)\)\s*$", re.IGNORECASE)


def _compare(cited: str, actual: Any) -> tuple[bool, float | None, str]:
    """-> (match, tolerance, reason)."""
    if isinstance(actual, (dict, list, BaseModel)):
        return False, None, "non_scalar"
    a_num = _to_float(actual)
    if a_num is not None:
        tol = max(CITE_ABS_TOL, CITE_REL_TOL * abs(a_num))
        c_num = _to_float(cited.strip())
        if c_num is None:
            return False, tol, "not_numeric"
        return abs(c_num - a_num) <= tol, tol, "value"
    return cited.strip().lower() == str(actual).strip().lower(), None, "value"


def _citations(entry: dict) -> list[str]:
    """cited_fields (list or str) on rankings; cited_field (str) on vetoes per schemas.py."""
    out: list[str] = []
    cf = entry.get("cited_fields")
    if isinstance(cf, str):
        out.append(cf)
    elif isinstance(cf, list):
        out.extend(x for x in cf if isinstance(x, str))
    single = entry.get("cited_field")
    if isinstance(single, str):
        out.append(single)
    return out


def _supporting_agents(turns: list[Turn], chosen_id: str) -> set[str]:
    """Agents whose latest valid message has the chosen candidate in `acceptable`."""
    last: dict[str, tuple[int, list[str]]] = {}
    for t in turns:
        for msg in t.messages:
            r = max(msg.round, t.round)
            if msg.agent not in last or r >= last[msg.agent][0]:
                last[msg.agent] = (r, msg.acceptable)
    return {a for a, (_, acc) in last.items() if chosen_id in acc}


_CANDIDATE_FIELDS = {"est_delay_min", "est_knock_on_min", "kind"}


def _cross_check(
    s: Scenario, turns: list[Turn], chosen_id: str, cand_by_id: dict[str, Candidate] | None = None
) -> tuple[list[dict], list[str], int, int]:
    """-> (mismatches, notes, citations checked, citations checked that carry "=value")."""
    cand_by_id = cand_by_id or {}
    mismatches: list[dict] = []
    notes: list[str] = []
    checked = 0
    with_value = 0
    supporters = _supporting_agents(turns, chosen_id)
    for t in turns:
        for msg in t.messages:
            if msg.agent not in supporters:
                continue
            entries = [("ranked", e) for e in msg.ranking] + [("vetoed", e) for e in msg.vetoes]
            for verb, e in entries:
                if not isinstance(e, dict):
                    continue
                cid = str(e.get("candidate_id", "?"))
                for raw in _citations(e):
                    checked += 1
                    path, sep, cited = raw.partition("=")
                    with_value += bool(sep)
                    path, cited = path.strip(), _SOURCE_SUFFIX.sub("", cited.strip())
                    actual, src = _resolve(s, path)
                    if actual is _MISSING and path in _CANDIDATE_FIELDS and cid in cand_by_id:
                        # Agents also cite fields of the option they are ranking, not just the Scenario.
                        actual, src = getattr(cand_by_id[cid], path), "estimated"
                    base = {"agent": msg.agent, "round": msg.round, "candidate_id": cid, "path": path}
                    if actual is _MISSING:
                        mismatches.append(
                            base
                            | {
                                "cited": cited if sep else None,
                                "actual": "unknown_field",
                                "tolerance": None,
                                "reason": "unknown_field",
                            }
                        )
                        notes.append(
                            f"CITED: {msg.agent} {verb} {cid} in round {msg.round} citing "
                            f"'{raw.strip()}', but that path does not exist in Scenario "
                            f"-> mismatch unknown_field [{CIT_CITED}]."
                        )
                        continue
                    if not sep:
                        continue  # no "=": existence check only
                    ok, tol, reason = _compare(cited, actual)
                    if ok:
                        continue
                    mismatches.append(
                        base | {"cited": cited, "actual": actual, "tolerance": tol, "reason": reason}
                    )
                    tol_txt = f", tolerance {tol:.2f}" if tol is not None else ""
                    notes.append(
                        f"CITED: {msg.agent} {verb} {cid} in round {msg.round} citing "
                        f"{path}={cited}; scenario has {_fmt(actual)} ({src or 'unknown'}{tol_txt}) "
                        f"-> mismatch [{CIT_CITED}]."
                    )
    return mismatches, notes, checked, with_value


# ---- engine comparison ---------------------------------------------------------------------------
def _engine_check(rule_id: str) -> str | None:
    rid = rule_id.upper()
    for prefix, check in ENGINE_PREFIX.items():
        if rid.startswith(prefix):
            return check
    return None


def _describe(entry: dict) -> str:
    c = entry["check"]
    if c == "WAKE":
        return f"required {_fmt(entry['threshold'])} s, available {_fmt(entry['derived'])} s"
    if c == "FUEL":
        return f"reserve left {_fmt(entry['derived'])} min vs {_fmt(entry['threshold'])} min required"
    return f"duty left {_fmt(entry['derived'])} min vs >= {_fmt(entry['threshold'])} required"


# ---- public API ----------------------------------------------------------------------------------
def review_detail(
    s: Scenario,
    rec: Recommendation,
    turns: list[Turn],
    *,
    candidates: list[Candidate] | None = None,
) -> dict:
    """Structured review.

    `candidates` (optional, keyword-only) is the full candidate menu. With it, every candidate is
    re-derived and compared with the engine. Without it, only rec.chosen can be re-derived because
    Recommendation carries no other candidate params, and the engine results for the other
    candidates are listed in `not_rederived`.
    """
    notes: list[str] = []
    reject = False
    modify = False

    chosen = rec.chosen
    pool: dict[str, Candidate] = {c.candidate_id: c for c in (candidates or [])}
    if chosen is not None:
        pool[chosen.candidate_id] = chosen

    # 1. Re-derive every candidate we have params for. rule_results are not read here.
    re_derived: list[dict] = []
    by_key: dict[tuple[str, str], dict] = {}
    chosen_notes: list[str] = []
    derived_delay: float | None = None
    for cid, c in pool.items():
        mo, entries, cnotes = _rederive(s, c)
        re_derived.extend(entries)
        for e in entries:
            by_key[(e["check"], cid)] = e
        if chosen is not None and cid == chosen.candidate_id:
            chosen_notes = cnotes
            derived_delay = mo["delay"]

    # 2. Verdict inputs for the chosen candidate.
    if chosen is None:
        reject = True
        notes.append(
            "CHOSEN: no candidate was chosen (chosen=None), so there is nothing to execute "
            "-> REJECT [reviewer rule: no recommendation without a candidate]."
        )
    else:
        notes.extend(chosen_notes)
        if any(not by_key[(chk, chosen.candidate_id)]["passed"] for chk in CHECKS):
            reject = True
        est = chosen.est_delay_min
        if derived_delay is not None:
            diff = abs(derived_delay - est)
            if diff > DELAY_ABS_TOL_MIN and diff > DELAY_REL_TOL * abs(est):
                modify = True
                notes.append(
                    f"DELAY: {chosen.candidate_id} re-derived delay is {_fmt(derived_delay)} min but "
                    f"est_delay_min={_fmt(est)} (estimated), off by {_fmt(diff)} min "
                    f"(> 20% and > 5 min) -> disagreement [{CIT_DELAY}]."
                )
        # Engine failed the chosen candidate on any rule -> REJECT (safety-conservative).
        for rr in rec.rule_results:
            if rr.candidate_id == chosen.candidate_id and not rr.passed:
                reject = True
                notes.append(
                    f"ENGINE: {rr.rule_id} failed chosen {chosen.candidate_id} (observed "
                    f"{rr.observed}, threshold {rr.threshold}, {rr.source}) -> REJECT, "
                    f"safety-conservative [{rr.citation}]."
                )

    # 3. Cited-value cross-check among the agents that support the chosen candidate.
    cited_mismatches: list[dict] = []
    n_cited = n_cited_value = 0
    if chosen is not None:
        cand_by_id = {c.candidate_id: c for c in candidates or []}
        cand_by_id.setdefault(chosen.candidate_id, chosen)
        cited_mismatches, cnotes, n_cited, n_cited_value = _cross_check(
            s, turns, chosen.candidate_id, cand_by_id
        )
        notes.extend(cnotes)
        if cited_mismatches:
            modify = True

    # 4. Engine comparison, after the re-derivations are fixed.
    engine_disagreements: list[dict] = []
    not_rederived: set[str] = set()
    for rr in rec.rule_results:
        chk = _engine_check(rr.rule_id)
        if chk is None:
            continue
        mine = by_key.get((chk, rr.candidate_id))
        if mine is None:
            not_rederived.add(rr.candidate_id)
            continue
        if bool(rr.passed) != bool(mine["passed"]):
            engine_disagreements.append(
                {
                    "rule_id": rr.rule_id,
                    "candidate_id": rr.candidate_id,
                    "engine_passed": rr.passed,
                    "reviewer_passed": mine["passed"],
                }
            )
            notes.append(
                f"ENGINE: {rr.rule_id} {'passed' if rr.passed else 'failed'} {rr.candidate_id}, "
                f"reviewer {'fails' if rr.passed else 'passes'} it ({_describe(mine)}) "
                f"-> disagreement [{mine['citation']}]."
            )
    if engine_disagreements:
        modify = True
    if not_rederived:
        notes.append(
            f"ENGINE: no params were passed for {', '.join(sorted(not_rederived))}, so the reviewer "
            f"did not re-derive them and cannot confirm the engine there [reviewer scope note]."
        )

    verdict: Verdict = "REJECT" if reject else ("MODIFY" if modify else "APPROVE")
    return {
        "verdict": verdict,
        "notes": notes,
        "re_derived": re_derived,
        "cited_mismatches": cited_mismatches,
        "engine_disagreements": engine_disagreements,
        "derived_delay_min": derived_delay,
        "citations_checked": n_cited,
        "citations_with_value": n_cited_value,
        "not_rederived": sorted(not_rederived),
    }


def review(
    s: Scenario,
    rec: Recommendation,
    turns: list[Turn],
    *,
    candidates: list[Candidate] | None = None,
) -> tuple[Verdict, list[str]]:
    """Frozen interface: (verdict, notes). Also stores the structured detail on rec.reviewer_detail."""
    detail = review_detail(s, rec, turns, candidates=candidates)
    rec.reviewer_detail = detail
    return detail["verdict"], detail["notes"]
