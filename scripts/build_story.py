"""Build the judges' story demo: demo/story.html.

Reads the saved runs, eval results and flights.csv at build time, extracts what each chapter
needs, and writes one self-contained HTML file (inline CSS + JS, data embedded as a JSON blob,
no network requests). Re-run after any new results:

    python scripts/build_story.py
"""

from __future__ import annotations

import csv
import functools
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The showcase flight is chosen from the evaluation and saved under fixed names, so the story can be
# rebuilt for a different flight without code changes.
SHOWCASE = ROOT / "runs" / "showcase.json"
SHOWCASE_LOG = ROOT / "runs" / "showcase.jsonl"
LIVE = ROOT / "runs" / "live" / "showcase.json"
FAILURE = ROOT / "runs" / "failure_showcase.json"
FAILURE_LOG = ROOT / "runs" / "failure_showcase.jsonl"
SUMMARY = ROOT / "eval" / "results" / "summary.csv"
PER_SCENARIO = ROOT / "eval" / "results" / "per_scenario.csv"
FLIGHTS = ROOT / "data" / "flights.csv"
AIRPORTS = ROOT / "data" / "airports.csv"
FAILURE_DOC = ROOT / "docs" / "failure_case.md"
BRIEF_RD = ROOT / "docs" / "waseem_industry_rd.md"
BRIEF_RE = ROOT / "docs" / "waseem_reverse_engineer.md"
OUT = ROOT / "demo" / "story.html"

URL_RE = re.compile(r"https?://\S+")

# Figures quoted from our industry brief. They are NOT our measurements. Each one is checked
# against the brief at build time (`must_contain`), so the page cannot drift from the source.
BRIEF_FIGURES = [
    {
        "id": "cost",
        "figure": "$98.41",
        "label": "per block minute of delay for US airlines (2025): $37.01 crew, $29.34 fuel",
        "cite": "docs/waseem_reverse_engineer.md §7, ref [1] Airlines for America; also docs/waseem_industry_rd.md (Pilots)",
        "doc": BRIEF_RE,
        "must_contain": "$98.41 per block minute",
    },
    {
        "id": "calls",
        "figure": "5–10",
        "label": "distinct voice calls across frequencies and phone lines to manage a single aircraft after one runway closure",
        "cite": "docs/waseem_reverse_engineer.md §1 (Current-State Workflow)",
        "doc": BRIEF_RE,
        "must_contain": "five to ten distinct voice calls",
    },
    {
        "id": "lag",
        "figure": "5–15 min",
        "label": "communication lag per coordination step in today's manual process (the brief's own conservative assumption)",
        "cite": "docs/waseem_reverse_engineer.md §1, Implications",
        "doc": BRIEF_RE,
        "must_contain": "5 to 15-minute communication lag",
    },
    {
        "id": "controllers",
        "figure": "~11,000",
        "label": "certified US controllers vs a target of 12,563; 2.2M overtime hours in 2024",
        "cite": "docs/waseem_industry_rd.md (Air traffic controllers), Spokesman-Review / Avionics International",
        "doc": BRIEF_RD,
        "must_contain": "About 11,000 certified controllers",
    },
    {
        "id": "extension",
        "figure": "2 h",
        "label": "cap on a Part 117 flight-duty extension, negotiated under stress during IROPS",
        "cite": "docs/waseem_reverse_engineer.md §8, ref [29] 14 CFR 117.19",
        "doc": BRIEF_RE,
        "must_contain": "duty extensions (up to 2 hours) [29]",
    },
    {
        "id": "cascade",
        "figure": "72.9%",
        "label": "of delay minutes in the dataset are late-aircraft delay (vs 9.8% weather): the cascade, not the storm, is where the cost sits",
        "cite": "docs/waseem_industry_rd.md (TL;DR, dataset profile)",
        "doc": BRIEF_RD,
        "must_contain": "Late-aircraft delay accounts for 72.9% of delay minutes",
    },
]

# Pain points named in the brief (paraphrased short labels + where the brief says it).
PAIN_POINTS = {
    "phone": ("Sequential voice/phone coordination", "TRACON → TMU → airline ops centre → crew → ramp, one call at a time (brief §1)"),
    "cascade": ("Delay cascades through the aircraft's day", "late-aircraft delay dominates the dataset (industry brief, TL;DR)"),
    "ramp": ("Ops-centre-to-ramp blind spot", "ground handlers are often last to know of an airborne hold (brief §1, §8)"),
    "duty": ("Crew duty limits", "Part 117 FDP cliffs; extension stress during IROPS (brief §8)"),
    "fuel": ("Holding fuel", "the 45-min reserve cannot be spent on holding (industry brief, Pilots)"),
    "atc": ("Controller workload", "one agreed plan for approval, not a stream of options (industry brief, ATC)"),
}


def _clean(obj):
    """Strip any URL from embedded strings so the page never links out."""
    if isinstance(obj, str):
        return URL_RE.sub("[link removed]", obj)
    if isinstance(obj, list):
        return [_clean(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    return obj


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def hhmm_to_min(v) -> int:
    v = int(float(v))
    return (v // 100) * 60 + v % 100


def tail_day(tail: str, year: int, month: int, day: int) -> list[dict]:
    legs = []
    with open(FLIGHTS, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["TAIL_NUMBER"] != tail:
                continue
            if (int(r["YEAR"]), int(r["MONTH"]), int(r["DAY"])) != (year, month, day):
                continue
            sd = hhmm_to_min(r["SCHEDULED_DEPARTURE"])
            sa = hhmm_to_min(r["SCHEDULED_ARRIVAL"])
            if sa < sd:
                sa += 1440
            dd = int(float(r["DEPARTURE_DELAY"] or 0))
            ad = int(float(r["ARRIVAL_DELAY"] or 0))
            legs.append({
                "flight": f"{r['AIRLINE']}{r['FLIGHT_NUMBER']}",
                "origin": r["ORIGIN_AIRPORT"],
                "dest": r["DESTINATION_AIRPORT"],
                "sched_dep": sd,
                "sched_arr": sa,
                "act_dep": sd + dd,
                "act_arr": sa + ad,
                "dep_delay": dd,
                "arr_delay": ad,
                "weather_delay": int(float(r["WEATHER_DELAY"] or 0)),
                "late_aircraft_delay": int(float(r["LATE_AIRCRAFT_DELAY"] or 0)),
            })
    legs.sort(key=lambda x: x["sched_dep"])
    return legs


def load_summary() -> dict:
    out: dict = {}
    with open(SUMMARY, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            out.setdefault(r["mode"], {})[r["metric"]] = {
                "value": r["value"], "unit": r["unit"], "n": r["n"],
                "definition": r["definition"], "note": r["note"],
            }
    return out


def load_per_scenario() -> dict:
    with open(PER_SCENARIO, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    by_mode: dict = {}
    for mode in sorted({r["mode"] for r in rows}):
        rs = [r for r in rows if r["mode"] == mode]
        by_mode[mode] = {
            "n": len(rs),
            "escalated": sum(1 for r in rs if not r["chosen_id"]),
            "decided_by": dict(Counter(r["decided_by"] for r in rs)),
            "fallback_reason": dict(Counter(r["fallback_reason"] or "none" for r in rs)),
            "verdict": dict(Counter(r["verdict"] for r in rs)),
        }
    return by_mode


def _fact(scn: dict, key: str) -> dict | None:
    v = scn.get(key)
    if isinstance(v, dict) and "value" in v:
        return {"key": key, "value": v["value"], "source": v.get("source", ""), "note": v.get("note", "")}
    return None


def summarize_event(e: dict) -> str:
    ev = e.get("event", "")
    if ev == "run_start":
        return f"agents={e.get('agents_mode')} model={e.get('model')} seed={e.get('seed')} git={e.get('git_sha')}"
    if ev == "scenario_built":
        tags = ", ".join(f"{k}:{v}" for k, v in (e.get("source_tag_counts") or {}).items())
        return f"scenario built; source tags {tags}"
    if ev == "candidates_generated":
        return f"{e.get('n')} candidates generated by code"
    if ev == "round_start":
        return f"round {e.get('round')} of {e.get('max_rounds')}"
    if ev == "agent_message":
        acc = e.get("acceptable") or []
        vet = [v.get("candidate_id") for v in (e.get("vetoes") or [])]
        rk = e.get("ranking") or []
        top = rk[0].get("candidate_id") if rk else None
        s = f"{e.get('agent')} r{e.get('round')}: accepts {len(acc)}"
        if top:
            s += f", top pick {top}"
        if vet:
            s += f", vetoes {', '.join(vet)}"
        return s
    if ev == "intersection":
        a = e.get("acceptable_intersection") or []
        p = e.get("rules_pass_intersection") or []
        return f"round {e.get('round')}: {len(a)} options all three accept, {len(p)} of them pass every rule"
    if ev == "consensus":
        return f"consensus on {e.get('candidate_id')} (summed score {e.get('summed_score')})"
    if ev == "fallback_fired":
        return f"deterministic fallback: reason={e.get('reason')}, eligible={e.get('n_eligible')}, pick={e.get('candidate_id')}"
    if ev == "reviewer_verdict":
        return f"reviewer {e.get('verdict')} on {e.get('candidate_id')} (stage {e.get('stage')})"
    if ev == "recommendation":
        return f"recommendation: {e.get('candidate_id')} decided by {e.get('decided_by')}, reviewer {e.get('reviewer_verdict')}"
    if ev == "human_decision":
        return f"human decision: {e.get('decision')}"
    if ev == "run_end":
        return f"run end: {e.get('latency_s')} s, ${e.get('cost_usd')}"
    keys = [k for k in e if k not in ("ts", "event", "scenario_id")]
    return ", ".join(f"{k}={e[k]}" for k in keys[:4])


def log_timeline(events: list[dict]) -> list[dict]:
    """Collapse the 66 rule_check events into one line; keep everything else."""
    out: list[dict] = []
    i = 0
    while i < len(events):
        e = events[i]
        if e.get("event") == "rule_check":
            j = i
            fails = 0
            while j < len(events) and events[j].get("event") == "rule_check":
                if events[j].get("passed") is False:
                    fails += 1
                j += 1
            out.append({"ts": e.get("ts"), "event": "rule_check",
                        "text": f"{j - i} rule checks (candidate × rule), {fails} FAIL; before any agent is asked"})
            i = j
            continue
        out.append({"ts": e.get("ts"), "event": e.get("event"), "text": summarize_event(e)})
        i += 1
    return out


@functools.lru_cache(maxsize=1)
def airport_coords() -> dict:
    out: dict = {}
    with open(AIRPORTS, encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                out[r["IATA_CODE"]] = (float(r["LATITUDE"]), float(r["LONGITUDE"]))
            except (TypeError, ValueError, KeyError):
                pass
    return out


def bearing_nm(a: tuple, b: tuple) -> tuple[float, float]:
    """True bearing (deg) and great-circle distance (nm) from a to b, both (lat, lon)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    d = lon2 - lon1
    y = math.sin(d) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d)
    brg = (math.degrees(math.atan2(y, x)) + 360) % 360
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d / 2) ** 2
    return round(brg, 1), round(2 * 3440.065 * math.asin(math.sqrt(h)), 1)


SCOPE_RANGES_NM = (40, 60, 80, 100, 120, 160, 200, 240, 320)


def scope_geo(scn: dict) -> dict | None:
    """Geometry for the story's radar scope: alternates and origin by bearing from the destination.

    Display only. Positions come from airports.csv; the aircraft blip is drawn schematically.
    """
    f = scn.get("flight") or {}
    co = airport_coords()
    dest, org = f.get("DESTINATION_AIRPORT"), f.get("ORIGIN_AIRPORT")
    if dest not in co:
        return None
    alts = []
    for a in scn.get("alternates") or []:
        if a.get("lat") is None or a.get("lon") is None:
            continue
        b, n = bearing_nm(co[dest], (a["lat"], a["lon"]))
        alts.append({"iata": a["iata"], "brg": b, "nm": n})
    origin = None
    if org in co:
        b, n = bearing_nm(co[dest], co[org])
        origin = {"iata": org, "brg": b, "nm": n}
    far = max([a["nm"] for a in alts] or [50]) * 1.15
    rng = next((r for r in SCOPE_RANGES_NM if r >= far), SCOPE_RANGES_NM[-1])
    return {"dest": {"iata": dest}, "origin": origin, "alternates": alts, "range_nm": rng}


def digest_run(run: dict, events: list[dict] | None = None) -> dict:
    scn = run["scenario"]
    f = scn["flight"]
    rules = run.get("rule_results") or []
    rule_ids: list[str] = []
    for r in rules:
        if r["rule_id"] not in rule_ids:
            rule_ids.append(r["rule_id"])
    rule_source = {}
    for r in rules:
        rule_source.setdefault(r["rule_id"], r.get("source"))
    fails_by_cand: dict = {}
    for r in rules:
        if not r["passed"]:
            fails_by_cand.setdefault(r["candidate_id"], []).append(r["rule_id"])

    turns = []
    top_picks = []
    for t in run.get("turns") or []:
        msgs = []
        for m in t.get("messages") or []:
            rk = m.get("ranking") or []
            msgs.append({
                "agent": m["agent"],
                "acceptable": m.get("acceptable") or [],
                "ranking": rk,
                "vetoes": m.get("vetoes") or [],
            })
            if rk:
                top = rk[0]["candidate_id"]
                top_picks.append({"round": t["round"], "agent": m["agent"], "candidate_id": top,
                                  "fails": fails_by_cand.get(top, [])})
        turns.append({"round": t["round"], "messages": msgs,
                      "intersection": t.get("intersection") or [],
                      "invalid": len(t.get("invalid_messages") or [])})

    facts = [x for x in (_fact(scn, k) for k in (
        "dest_disruption", "taxi_congestion", "wake_category", "fuel_reserve_min",
        "crew_duty_remaining_min", "nominal_aar")) if x]
    gates = scn.get("gates") or {}
    conns = scn.get("connections") or []
    rec = run.get("recommendation") or {}
    rev = run.get("reviewer") or {}
    meta = run.get("meta") or {}
    return {
        "scenario_id": scn["scenario_id"],
        "row_index": scn.get("row_index"),
        "meta": {k: meta.get(k) for k in ("agents", "model", "cost_usd", "latency_s", "n_agent_calls",
                                           "tokens_in", "tokens_out", "git_sha", "started_at", "max_rounds")},
        "flight": {k: f.get(k) for k in (
            "date", "AIRLINE", "FLIGHT_NUMBER", "TAIL_NUMBER", "ORIGIN_AIRPORT", "DESTINATION_AIRPORT",
            "SCHEDULED_DEPARTURE", "SCHEDULED_ARRIVAL", "DEPARTURE_DELAY", "ARRIVAL_DELAY", "ARRIVAL_TIME",
            "WEATHER_DELAY", "LATE_AIRCRAFT_DELAY", "AIR_SYSTEM_DELAY", "DISTANCE", "AIR_TIME")},
        "facts": facts,
        "gates": {"airport": gates.get("airport"), "assigned_gate": gates.get("assigned_gate"),
                  "min_turnaround_min": gates.get("min_turnaround_min"),
                  "turnaround_source": gates.get("turnaround_source"),
                  "source": gates.get("source", "synthetic")},
        "connections": {"n": len(conns), "pax": sum(int(c.get("est_pax") or 0) for c in conns),
                        "source": conns[0].get("source") if conns else None,
                        "first_min_after": conns[0].get("minutes_after_arrival") if conns else None},
        "alternates": [{"iata": a["iata"], "name": a.get("name"), "distance_nm": a.get("distance_nm")}
                       for a in scn.get("alternates") or []],
        "downstream": scn.get("downstream_legs") or [],
        "candidates": run.get("candidates") or [],
        "rule_ids": rule_ids,
        "rule_source": rule_source,
        "rules": rules,
        "turns": turns,
        "top_picks": top_picks,
        "recommendation": {
            "chosen": rec.get("chosen"),
            "decided_by": rec.get("decided_by"),
            "rounds_used": rec.get("rounds_used"),
            "reviewer_verdict": rec.get("reviewer_verdict"),
            "notes": rec.get("reviewer_notes") or [],
            "human_decision": rec.get("human_decision"),
        },
        "fallback": run.get("fallback") or {},
        "reviewer": {
            "verdict": rev.get("verdict"),
            "notes": rev.get("notes") or [],
            "re_derived": rev.get("re_derived") or [],
            "engine_disagreements": rev.get("engine_disagreements") or [],
            "cited_mismatches": rev.get("cited_mismatches") or [],
            "citations_checked": rev.get("citations_checked"),
            "escalated": rev.get("escalated"),
            "candidate_id": rev.get("candidate_id"),
        },
        "timeline": log_timeline(events or []),
        "scope": scope_geo(scn),
    }


def failure_doc_facts() -> dict:
    """Pull the reviewer-bug story numbers out of docs/failure_case.md (not typed by hand)."""
    text = FAILURE_DOC.read_text(encoding="utf-8") if FAILURE_DOC.exists() else ""
    out: dict = {"found": bool(text)}
    m = re.search(r"fell\s+from\s+([\d.]+)%\s+to\s+([\d.]+)%", text)
    if m:
        out["disagree_before_pct"], out["disagree_after_pct"] = m.group(1), m.group(2)
    m = re.search(r"first run \(commit `([0-9a-f]+)`\)", text)
    if m:
        out["bug_commit"] = m.group(1)
    m = re.search(r"Commit `([0-9a-f]+)` fixed it", text)
    if m:
        out["fix_commit"] = m.group(1)
    m = re.search(r"it computed (\d+) − (\d+) = (\d+) ≥ 0", text)
    if m:
        out["bug_example"] = f"{m.group(1)} − {m.group(2)} = {m.group(3)} ≥ 0"
    m = re.search(r"\(`SLOT\+15`: (\d+) − (\d+) − (\d+) = (−?\d+)\)", text)
    if m:
        out["fix_example"] = f"{m.group(1)} − {m.group(2)} − {m.group(3)} = {m.group(4)}"
    m = re.search(r"listed\s+(\d+)\s+`R-DUTY-01`\s+engine\s+disagreements", text)
    if m:
        out["bug_disagreements"] = m.group(1)
    return out


def brief_figures() -> list[dict]:
    out = []
    cache: dict = {}
    for b in BRIEF_FIGURES:
        doc = b["doc"]
        if doc not in cache:
            cache[doc] = doc.read_text(encoding="utf-8") if doc.exists() else ""
        if b["must_contain"] not in cache[doc]:
            print(f"warning: brief figure '{b['id']}' not found in {doc.name}; omitted", file=sys.stderr)
            continue
        out.append({k: b[k] for k in ("id", "figure", "label", "cite")})
    return out


def build_data() -> dict:
    show = load_json(SHOWCASE)
    live = load_json(LIVE) if LIVE.exists() else None
    fail = load_json(FAILURE)
    f = show["scenario"]["flight"]
    y, mth, d = (int(x) for x in str(f["date"]).split("-"))
    return _clean({
        "showcase": digest_run(show, load_jsonl(SHOWCASE_LOG)),
        "live": digest_run(live) if live else None,
        "failure": digest_run(fail, load_jsonl(FAILURE_LOG)),
        "tail_day": {"tail": f["TAIL_NUMBER"], "date": f["date"],
                     "legs": tail_day(f["TAIL_NUMBER"], y, mth, d)},
        "summary": load_summary(),
        "per_scenario": load_per_scenario(),
        "failure_doc": failure_doc_facts(),
        "brief": brief_figures(),
        "pain": {k: {"title": v[0], "where": v[1]} for k, v in PAIN_POINTS.items()},
    })


def render(data: dict) -> str:
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    blob = blob.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    html = TEMPLATE.replace("__DATA__", blob)
    if URL_RE.search(html):
        raise SystemExit("story.html would contain an http(s) URL; refusing to write")
    return html


def main() -> int:
    data = build_data()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(data), encoding="utf-8")
    s = data["summary"].get("haiku", {})
    print(f"wrote {OUT.relative_to(ROOT)}  "
          f"(legs={len(data['tail_day']['legs'])}, candidates={len(data['showcase']['candidates'])}, "
          f"consensus_rate={s.get('consensus_rate', {}).get('value')})")
    return 0


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SRRW: one disrupted arrival, start to finish</title>
<style>
/* Two worlds side by side. Left: the radar console (phosphor green on black), fixed, following the
   scroll. Right: the briefing, a cool chart-paper page set in airport-signage type (Bahnschrift/DIN),
   with a flight track running down its left edge that fills as you pass each phase. Chart convention:
   magenta marks the chosen route. */
:root{
  --paper:#F1F4F0; --card:#FFFFFF; --ink:#0D1A14; --ink-2:#36443D; --ink-3:#66766D; --line:#DCE3DD; --line-2:#C5CFC8;
  --go:#12804A; --caution:#B26A00; --stop:#C2362B; --route:#B0249E; --sky:#0B6AA2; --teal:#0D8577; --violet:#6D3FD6; --orange:#C2531A;
  --red:var(--stop); --green:var(--go); --amber:var(--caution);
  --c-atc:#2563EB; --c-pilot:#0D8577; --c-ground:#15803D; --c-rules:#B26A00; --c-review:#6D3FD6; --c-human:#0D1A14;
  --display:"Bahnschrift","DIN Alternate","DIN Next","Barlow Semi Condensed","Arial Narrow",sans-serif;
  --sans:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif;
  --mono:"Cascadia Mono","Cascadia Code",Consolas,"SF Mono",Menlo,monospace;
  --rail-w:340px; --spine-x:44px;
  --shadow:0 1px 2px rgba(13,26,20,.05),0 10px 30px -14px rgba(13,26,20,.18);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
html,body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.55;-webkit-font-smoothing:antialiased}
::selection{background:rgba(176,36,158,.16)}
:focus-visible{outline:2px solid var(--sky);outline-offset:3px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
@keyframes glow{0%,100%{text-shadow:0 0 4px rgba(51,255,51,.4)}50%{text-shadow:0 0 8px rgba(51,255,51,.6),0 0 16px rgba(51,255,51,.2)}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes hazard{0%,100%{opacity:.45}50%{opacity:.9}}
@keyframes blink{0%,60%,100%{opacity:1}70%,90%{opacity:.15}}
@keyframes flip{from{opacity:0;transform:translateY(-3px)}to{opacity:1;transform:none}}
@keyframes cue{0%,100%{transform:translateY(0)}50%{transform:translateY(5px)}}

/* ================= LEFT: radar console ================= */
.rail{
  --bg-deep:#050805; --bg-mid:#0a0e0a; --bg-surface:#0f140f; --bg-raised:#141a14; --bg-overlay:#1a221a;
  --border-dim:#121e12; --border-mid:#1a2e1a; --border-bright:#243a24;
  --nominal:#33ff33; --warning:#ffaa00; --critical:#ff3333;
  --text-primary:#d0e8d0; --text-secondary:#98bb98; --text-dim:#6a8e6a; --text-muted:#4a6a4a;
  --c-atc:#4488ff; --c-pilot:#33ccff; --c-ground:#33ff33; --c-rules:#ffaa00; --c-review:#aa88ff; --c-human:#d0e8d0;
  --rmono:"IBM Plex Mono","Cascadia Mono",Consolas,"SF Mono",Menlo,monospace;
  position:fixed;inset:0 auto 0 0;width:var(--rail-w);z-index:20;overflow:auto;
  background:radial-gradient(420px 320px at 50% 26%,rgba(51,255,51,.06),transparent 70%),var(--bg-mid);
  border-right:1px solid var(--border-mid);box-shadow:4px 0 24px rgba(0,0,0,.35);
  color:var(--text-primary);font-family:var(--rmono);display:flex;flex-direction:column;
  scrollbar-width:thin;scrollbar-color:var(--border-bright) transparent}
.rail :focus-visible{outline-color:var(--nominal)}
.rail.hidden{display:none}
.brand{display:flex;align-items:center;gap:10px;padding:14px 14px 10px}
.brand svg{width:28px;height:28px;flex-shrink:0}
.brand-name{font-size:14px;font-weight:600;letter-spacing:.12em}
.brand-sub{font-size:11px;color:var(--text-dim)}
.rail-status{display:flex;justify-content:space-between;align-items:center;padding:0 14px 10px;font-size:11px}
.live{display:flex;gap:6px;align-items:center;color:var(--nominal);letter-spacing:.08em;font-weight:600}
.live i{width:6px;height:6px;border-radius:50%;background:var(--nominal);box-shadow:0 0 6px var(--nominal);animation:pulse 2s ease-in-out infinite}
.counter{font-weight:600;letter-spacing:.08em;font-variant-numeric:tabular-nums;color:var(--text-primary)}
.scn{font-size:10.5px;color:var(--text-dim);margin-top:2px;letter-spacing:.02em}
.flash{display:flex;gap:4px;flex-wrap:wrap;padding:0 14px 12px}
.fchip{display:flex;align-items:center;gap:5px;padding:2px 7px;border:1px solid var(--border-mid);border-radius:6px;
  background:var(--bg-surface);font-size:10px;letter-spacing:.06em;color:var(--text-muted);
  transition:color .25s ease,border-color .25s ease,box-shadow .25s ease,background-color .25s ease}
.fchip i{width:5px;height:5px;border-radius:50%;background:#2a332a}
.fchip.on{color:var(--ac);border-color:var(--ac);font-weight:600;
  background:color-mix(in srgb,var(--ac) 10%,var(--bg-surface));box-shadow:0 0 8px color-mix(in srgb,var(--ac) 35%,transparent)}
.fchip.on i{background:var(--ac);box-shadow:0 0 6px var(--ac);animation:pulse 2s ease-in-out infinite}
.ph{padding:8px 14px;border-top:1px solid var(--border-mid);border-bottom:1px solid var(--border-mid);
  background:linear-gradient(180deg,var(--bg-overlay),var(--bg-mid));display:flex;justify-content:space-between;align-items:center;gap:8px}
.pt{font-size:12px;font-weight:600;color:var(--nominal);letter-spacing:.1em;text-transform:uppercase;animation:glow 4s ease-in-out infinite}
.pm{font-size:11px;color:var(--text-dim);letter-spacing:.04em}
.scope-wrap{position:relative;width:calc(100% - 28px);max-width:300px;aspect-ratio:1;margin:12px auto 10px}
.scope-wrap > #scope, .scope-wrap > #scope svg{position:absolute;inset:0;width:100%;height:100%}
.sweep{position:absolute;inset:7.14%;border-radius:50%;pointer-events:none;
  background:conic-gradient(from 0deg,transparent 0deg 290deg,rgba(51,255,51,.03) 300deg,rgba(51,255,51,.24) 360deg);
  animation:spin 4s linear infinite}
#scope .wx{animation:hazard 3s ease-in-out infinite}
#scope .blinking{animation:blink 1s steps(1,end) infinite}
.readout{margin:0 14px 14px;padding:8px 10px;border:1px solid var(--border-dim);border-radius:8px;background:var(--bg-deep);font-size:11.5px;line-height:1.75}
.readout div{display:flex;justify-content:space-between;gap:10px}
.readout span{color:var(--text-dim);letter-spacing:.06em}
.readout b{color:var(--text-primary);font-weight:500;text-align:right;animation:flip .35s ease-out both}
.readout b.ok{color:var(--nominal)} .readout b.no{color:var(--critical)} .readout b.mid{color:var(--warning)} .readout b.dim{color:var(--text-secondary)}
.readout .note{display:block;color:var(--text-dim);font-size:10.5px;line-height:1.4;margin-top:6px;border-top:1px solid var(--border-dim);padding-top:6px}
nav#index{display:flex;flex-direction:column;padding:6px 8px 12px;position:relative}
nav#index a{display:flex;gap:10px;align-items:center;padding:6px 10px;border-radius:8px;color:var(--text-secondary);
  font-size:12.5px;cursor:pointer;border:1px solid transparent;transition:background-color .15s ease,color .15s ease}
nav#index a .n{color:var(--text-dim);font-weight:600;font-variant-numeric:tabular-nums}
nav#index a .d{width:7px;height:7px;border-radius:50%;border:1px solid var(--text-dim);flex-shrink:0;margin-left:auto}
nav#index a.past .d{background:var(--text-dim)}
nav#index a:hover{background:var(--bg-raised);color:var(--text-primary)}
nav#index a.on{border-color:var(--nominal);background:rgba(51,255,51,.08);color:var(--nominal);box-shadow:0 0 6px rgba(51,255,51,.1)}
nav#index a.on .n{color:var(--nominal)}
nav#index a.on .d{background:var(--nominal);border-color:var(--nominal);box-shadow:0 0 6px var(--nominal)}
.rail-foot{margin-top:auto;padding:10px 14px;border-top:1px solid var(--border-dim);font-size:10.5px;color:var(--text-dim)}

/* ================= RIGHT: the briefing ================= */
main#stage{margin-left:var(--rail-w);position:relative;outline:none}
.spine{position:fixed;top:0;bottom:0;left:calc(var(--rail-w) + var(--spine-x));width:2px;background:var(--line);z-index:5}
.spine i{display:block;width:100%;height:0;background:linear-gradient(180deg,var(--sky),var(--route));transition:height .12s linear}
.chap,.hero{position:relative;padding:112px 64px 112px calc(var(--spine-x) + 64px);border-top:1px solid var(--line)}
.chap > *{max-width:1180px}
.chap > h1{max-width:21ch}
.chap > p.lead{max-width:60ch}
.chap::after{content:attr(data-n);position:absolute;top:84px;right:56px;font-family:var(--display);font-weight:700;
  font-size:168px;line-height:1;color:transparent;-webkit-text-stroke:1.5px var(--line-2);letter-spacing:-.02em;pointer-events:none;z-index:0}
.chap > *:not(.node){position:relative;z-index:1}
.node{position:absolute;left:calc(var(--spine-x) - 8px);top:118px;width:18px;height:18px;border-radius:50%;
  background:var(--paper);border:2px solid var(--line-2);z-index:6;transition:border-color .3s ease,background-color .3s ease,box-shadow .3s ease}
.chap.past .node{border-color:var(--sky);background:var(--sky)}
.chap.on .node{border-color:var(--route);background:var(--card);box-shadow:0 0 0 6px rgba(176,36,158,.14)}
.chap.on .node::after{content:"";position:absolute;inset:3px;border-radius:50%;background:var(--route)}

/* hero: the flight progress strip */
.hero{min-height:92vh;display:flex;flex-direction:column;justify-content:center;border-top:0;
  background:radial-gradient(900px 500px at 85% 10%,rgba(11,106,162,.08),transparent 60%),radial-gradient(700px 500px at 10% 100%,rgba(176,36,158,.06),transparent 60%)}
.hero .node{top:50%;border-color:var(--route);background:var(--route)}
.eyebrow{font-size:13px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3)}
.hero h1{font-family:var(--display);font-weight:700;font-stretch:87.5%;font-size:clamp(46px,6.4vw,104px);line-height:.96;letter-spacing:-.02em;
  margin:18px 0 18px;max-width:14ch;color:var(--ink)}
.hero h1 em{font-style:normal;color:var(--route)}
.hero .sub{font-size:20px;color:var(--ink-2);margin:0 0 40px;max-width:46ch}
.strip{display:grid;grid-template-columns:auto repeat(4,minmax(0,1fr));align-items:stretch;max-width:980px;background:var(--card);
  border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);overflow:hidden}
.strip > div{padding:16px 20px;border-left:1px solid var(--line)}
.strip > div:first-child{border-left:0;background:var(--ink);color:#fff;display:flex;flex-direction:column;justify-content:center;min-width:170px}
.strip .k{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-3);font-weight:600}
.strip > div:first-child .k{color:#9fb3a8}
.strip .v{font-family:var(--display);font-weight:600;font-size:28px;line-height:1.15;margin-top:4px;font-variant-numeric:tabular-nums}
.strip > div:first-child .v{font-size:36px;letter-spacing:.02em}
.strip .v.mid{color:var(--caution)}
.cue{margin-top:44px;display:flex;align-items:center;gap:12px;color:var(--ink-3);font-size:14px}
.cue svg{animation:cue 2s ease-in-out infinite}

/* chapter type */
.kicker{display:flex;align-items:center;gap:10px;font-size:13px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--sky)}
.kicker::before{content:"";width:22px;height:2px;background:currentColor}
h1{font-family:var(--display);font-weight:700;font-stretch:87.5%;font-size:clamp(34px,3.7vw,58px);line-height:1.02;letter-spacing:-.015em;
  margin:18px 0 14px;max-width:20ch;color:var(--ink);text-wrap:balance}
h2{font-size:12.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3);margin:44px 0 16px;
  display:flex;align-items:center;gap:14px}
h2::after{content:"";flex:1;height:1px;background:var(--line)}
h3{font-size:17px;font-weight:600;margin:0 0 6px;color:var(--ink);letter-spacing:-.005em}
p.lead{font-size:19px;color:var(--ink-2);max-width:60ch;margin:0 0 28px}
.small{font-size:14px}
.dim{color:var(--ink-3)}
.mono{font-family:var(--mono)}
.ok{color:var(--go)} .no{color:var(--stop)} .mid{color:var(--caution)}
b.ok,b.no,b.mid{font-weight:700}

/* panels */
.grid{display:grid;gap:18px}
.g2{grid-template-columns:repeat(2,minmax(0,1fr))}
.g3{grid-template-columns:repeat(3,minmax(0,1fr))}
.g4{grid-template-columns:repeat(4,minmax(0,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px 22px;box-shadow:var(--shadow);min-width:0;
  transition:transform .25s ease,box-shadow .25s ease,border-color .25s ease}
.card:hover{transform:translateY(-2px);box-shadow:0 1px 2px rgba(13,26,20,.05),0 18px 40px -18px rgba(13,26,20,.25)}
.card:has(> table){overflow-x:auto}
.card:has(> table):hover{transform:none}
.card.hl{border-color:rgba(18,128,74,.4);box-shadow:0 0 0 4px rgba(18,128,74,.07),var(--shadow)}
.card.warn{border-color:rgba(178,106,0,.35);background:linear-gradient(180deg,#FFF8EC,var(--card))}
.tag{font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-3);font-weight:700}
.big{font-family:var(--display);font-weight:600;font-size:44px;line-height:1.05;color:var(--ink);font-variant-numeric:tabular-nums;margin:6px 0 6px;overflow-wrap:anywhere}
.chip{display:inline-flex;align-items:center;padding:2px 9px;border-radius:999px;font-size:11.5px;font-weight:600;letter-spacing:.02em;
  border:1px solid transparent;margin:2px 4px 2px 0;white-space:nowrap;vertical-align:middle;line-height:1.5}
.src-data{color:#0E6B3D;background:#E3F4EA;border-color:#C4E7D2}
.src-estimated{color:#0B6A60;background:#E0F3F0;border-color:#BFE6E0}
.src-assumed{color:#8A5200;background:#FCF0D9;border-color:#F2DCB0}
.src-synthetic{color:#A3410F;background:#FCE7DB;border-color:#F4CDB6}
.src-brief{color:#0B5A8A;background:#E2F0F9;border-color:#C1DEF0}
.pain{display:inline-flex;gap:6px;align-items:center;font-size:12.5px;color:var(--caution);border:1px dashed rgba(178,106,0,.4);
  border-radius:999px;padding:2px 10px;margin:3px 6px 3px 0}
.legend{font-size:13px;color:var(--ink-3);margin-top:10px}
.cite{font-size:12.5px;color:var(--ink-3);margin-top:6px}
.bubble{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-top:10px;font-size:14px;color:var(--ink-2);overflow-wrap:anywhere}
.bubble b{color:var(--ink)}
.score{float:right;color:var(--go);font-weight:700;font-family:var(--mono)}
.agent{display:flex;align-items:center;gap:12px;margin-bottom:10px}
.agent svg{width:38px;height:38px;flex-shrink:0}
.comms{border-top:4px solid var(--ac)}
.comms h3{color:var(--ac)}
.pencil{display:inline-block;font-size:12px;padding:1px 8px;margin:2px 4px 2px 0;border-radius:999px;border:1px solid;font-family:var(--mono)}
.pencil.strike{color:var(--stop);border-color:rgba(194,54,43,.35);background:#FDEDEB;text-decoration:line-through}
.pencil.ring{color:var(--go);border-color:rgba(18,128,74,.4);background:#E3F4EA;font-size:10px;letter-spacing:.06em;text-transform:uppercase;font-family:var(--sans);font-weight:700}
.banner{padding:14px 18px;border-radius:12px;font-size:16px;font-weight:500}
.banner.green{background:#E6F4EC;color:#0E5C35;border:1px solid #C4E7D2}
.banner.red{background:#FDECEA;color:#8F2219;border:1px solid #F5C9C3;font-weight:600}
table{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}
th{font-size:11px;letter-spacing:.06em;color:var(--ink-3);text-align:left;font-weight:700;padding:8px;border-bottom:1px solid var(--line-2);vertical-align:bottom}
td{padding:8px;border-bottom:1px solid var(--line)}
tr:last-child td{border-bottom:0}
.c{text-align:center}
td.cell{cursor:pointer;font-weight:700;font-size:12px;letter-spacing:.04em;transition:box-shadow .15s ease}
td.cell.pass{color:var(--go)}
td.cell.fail{color:#9E2318;background:#FBE3E0}
td.cell:hover{box-shadow:inset 0 0 0 1px var(--line-2)}
td.cell.sel{box-shadow:inset 0 0 0 2px var(--route)}
.stamp{display:inline-block;padding:6px 16px;border-radius:999px;font-weight:700;letter-spacing:.12em;font-size:16px;font-family:var(--sans)}
.stamp.ok{color:#fff;background:var(--go)} .stamp.mid{color:#fff;background:var(--caution)} .stamp.no{color:#fff;background:var(--stop)}
.tl{display:flex;flex-direction:column;max-height:440px;overflow:auto;font-size:12.5px;border:1px solid var(--line);border-radius:12px;background:var(--paper);font-family:var(--mono)}
.ev{padding:7px 12px;border-bottom:1px solid var(--line);color:var(--ink-2)}
.ev .tag{color:var(--ink-3);font-weight:400;letter-spacing:0;text-transform:none;font-size:12px}
.ev b{color:var(--ev,var(--ink-2))}
.e-agent_message{--ev:var(--teal)} .e-rule_check{--ev:var(--caution)} .e-reviewer_verdict{--ev:var(--violet)}
.e-fallback_fired{--ev:var(--orange)} .e-consensus,.e-recommendation,.e-intersection{--ev:var(--go)} .e-human_decision{--ev:var(--ink)}
.ev.rej{background:#FDECEA}
.toast{margin:14px 0 8px;padding:10px 12px;border-radius:10px;background:var(--paper);border:1px solid var(--line);font-size:14px}
.btn{font:inherit;font-size:15px;font-weight:600;padding:10px 20px;min-height:44px;background:var(--card);color:var(--ink);border:1px solid var(--line-2);
  border-radius:999px;cursor:pointer;transition:transform .1s ease,box-shadow .2s ease,background-color .2s ease}
.btn:hover{box-shadow:var(--shadow)}
.btn:active{transform:scale(.98)}
.btn.primary{background:var(--go);border-color:var(--go);color:#fff}
.thesis{margin:56px 0 28px;font-family:var(--display);font-weight:700;font-stretch:87.5%;font-size:clamp(32px,3.6vw,56px);line-height:1.04;letter-spacing:-.015em;max-width:22ch}
.thesis::after{content:"";display:block;width:120px;height:4px;margin-top:20px;background:linear-gradient(90deg,var(--sky),var(--route));border-radius:2px}
.mandatory{display:inline-block;padding:12px 26px;border:2px solid var(--stop);color:var(--stop);border-radius:999px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;background:#fff}
.chap .mandatory{margin:0}
.chap div[style*="justify-content:center"]{justify-content:flex-start!important}
.svgbox{background:var(--card)}
.svgbox svg{display:block;width:100%;height:auto}
ul.tight{margin:8px 0;padding-left:0;list-style:none}
ul.tight li{position:relative;padding-left:20px;margin:7px 0}
ul.tight li::before{content:"";position:absolute;left:2px;top:.6em;width:8px;height:2px;background:var(--sky)}
.cand{display:flex;flex-direction:column;gap:4px}
.bar{height:6px;background:var(--paper);border-radius:3px;overflow:hidden;margin-top:8px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--caution),var(--orange));border-radius:3px}
.flow{display:flex;gap:18px;flex-wrap:wrap}
.flow .step{flex:1;min-width:170px;position:relative}
.flow .step:not(:last-child)::after{content:"";position:absolute;right:-14px;top:50%;width:10px;height:2px;background:var(--line-2)}
.mx-wrap{grid-template-columns:minmax(0,1fr)}
.mx-wrap > div:last-child{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;align-items:start}
.mx-wrap > div:last-child > .card{margin-top:0!important}
@media (max-width:960px){.mx-wrap > div:last-child{grid-template-columns:minmax(0,1fr)}}
.tile .def{font-size:12.5px;color:var(--ink-3);margin-top:8px;font-family:var(--mono)}

/* scroll reveal (only once the observer is running) */
.reveal .chap > *:not(.node){opacity:0;transform:translateY(18px);transition:opacity .6s ease,transform .6s cubic-bezier(.2,.7,.2,1)}
.reveal .chap.in > *:not(.node){opacity:1;transform:none}
.reveal .chap.in > *:nth-child(3){transition-delay:.06s} .reveal .chap.in > *:nth-child(4){transition-delay:.12s}
.reveal .chap.in > *:nth-child(5){transition-delay:.18s} .reveal .chap.in > *:nth-child(n+6){transition-delay:.24s}

/* ================= responsive ================= */
@media (max-width:1180px){
  .g4{grid-template-columns:repeat(2,minmax(0,1fr))}
  .chap::after{font-size:120px}
}
@media (max-width:960px){
  .rail{position:sticky;inset:auto;top:0;width:auto;height:auto;max-height:none;flex-direction:row;flex-wrap:wrap;align-items:center;
    box-shadow:0 4px 18px rgba(0,0,0,.3);border-right:0;border-bottom:1px solid var(--border-mid)}
  .rail .brand{padding:8px 12px}
  .rail .scope-wrap{width:96px;margin:6px 12px;order:-1}
  .rail .readout,.rail nav#index,.rail .ph,.rail .rail-foot,.rail .brand-sub,.rail .scn{display:none}
  .rail .flash{padding:0 12px 8px;width:100%}
  .rail .rail-status{margin-left:auto;padding:8px 12px}
  main#stage{margin-left:0}
  .spine{display:none}
  .chap,.hero{padding:72px 20px}
  .node{display:none}
  .chap::after{font-size:84px;top:60px;right:16px}
  .g3,.g2{grid-template-columns:minmax(0,1fr)}
  .grid[style]{grid-template-columns:minmax(0,1fr)!important}
  .strip{grid-template-columns:repeat(2,minmax(0,1fr))}
  .strip > div:first-child{grid-column:1 / -1}
  .strip > div:nth-child(2){border-left:0}
}
@media (max-width:600px){
  .g4{grid-template-columns:minmax(0,1fr)}
  .rail .flash{display:none}
  .chap::after{display:none}
  .rail{flex-wrap:nowrap}
  .rail .scope-wrap{width:58px;margin:6px 4px 6px 10px}
  .rail .brand{padding:8px 4px}
  .rail .brand svg,.rail .live{display:none}
  .rail .brand-name{font-size:11.5px}
  .strip .v{font-size:22px;white-space:nowrap}
  .strip > div:first-child .v{font-size:28px}
}
@media (prefers-reduced-motion:reduce){
  html{scroll-behavior:auto}
  *,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}
  .sweep{display:none}
  .reveal .chap > *:not(.node){opacity:1;transform:none}
}
</style>
</head>
<body>
<noscript><p style="padding:30px">This story needs JavaScript enabled (no network access required).</p></noscript>
<aside class="rail" id="rail" aria-label="Radar console">
  <div class="brand">
    <svg viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="10" fill="#04150a"/><path d="M32 32 L13 9 A30 30 0 0 1 51 9 Z" fill="#2dff6b" opacity="0.22"/><circle cx="32" cy="32" r="24" fill="none" stroke="#2dff6b" stroke-width="2" opacity="0.55"/><line x1="32" y1="4" x2="32" y2="9" stroke="#2dff6b" stroke-width="2" opacity="0.6"/><line x1="32" y1="55" x2="32" y2="60" stroke="#2dff6b" stroke-width="2" opacity="0.6"/><line x1="4" y1="32" x2="9" y2="32" stroke="#2dff6b" stroke-width="2" opacity="0.6"/><line x1="55" y1="32" x2="60" y2="32" stroke="#2dff6b" stroke-width="2" opacity="0.6"/><polygon points="32,20 39,44 32,39 25,44" fill="#39ff7a"/></svg>
    <div><div class="brand-name">SRRW · DISRUPTION DESK</div><div class="brand-sub">AI-assisted, human-decided</div><div class="scn" id="scn"></div></div>
  </div>
  <div class="rail-status"><span class="live" title="Replays saved runs; nothing is called live"><i></i>RECORDED RUN</span><span class="counter" id="counter"></span></div>
  <div class="flash" id="flash" role="list" aria-label="Who acts in this phase"></div>
  <div class="ph"><span class="pt" id="scopeTitle">Scope</span><span class="pm" id="scopeRange"></span></div>
  <div class="scope-wrap"><div id="scope"></div><div class="sweep" aria-hidden="true"></div></div>
  <div class="readout" id="readout"></div>
  <div class="ph"><span class="pt">Sequence</span><span class="pm">10 phases</span></div>
  <nav id="index" aria-label="Chapters"></nav>
  <div class="rail-foot">← → jump between phases</div>
</aside>
<div class="spine" aria-hidden="true"><i id="bar"></i></div>
<main id="stage" tabindex="-1"></main>
<script type="application/json" id="story-data">__DATA__</script>
<script>
(function(){
"use strict";
const D = JSON.parse(document.getElementById("story-data").textContent);
const S = D.showcase, F = D.failure, L = D.live, SUM = D.summary, PS = D.per_scenario;
const H = SUM.haiku || {}, N0 = SUM.none || {}, DATA = SUM.data || {};

/* ---------- helpers ---------- */
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pct = (v, d=1) => (Number(v)*100).toFixed(d) + "%";
const num = (v, d=0) => Number(v).toLocaleString("en-US",{maximumFractionDigits:d,minimumFractionDigits:d});
const hhmm = m => { m = Math.round(m); const day = Math.floor(m/1440); m = ((m%1440)+1440)%1440;
  return String(Math.floor(m/60)).padStart(2,"0") + ":" + String(m%60).padStart(2,"0") + (day>0?" +"+day+"d":""); };
const hhmmInt = v => { v = Number(v); return String(Math.floor(v/100)).padStart(2,"0")+":"+String(v%100).padStart(2,"0"); };
const chip = src => src ? `<span class="chip src-${esc(src)}">${esc(src)}</span>` : "";
const brief = () => `<span class="chip src-brief">reported in our industry brief</span>`;
const pain = k => D.pain[k] ? `<span class="pain" title="${esc(D.pain[k].where)}">${ICON.warn}${esc(D.pain[k].title)}</span>` : "";
const metric = (m, mode) => ((SUM[mode||"haiku"]||{})[m]) || null;
const signed = v => (v > 0 ? "+" : "") + num(v, Number.isInteger(+v)?0:1);
const fl = f => `${f.AIRLINE}${f.FLIGHT_NUMBER}`;
const briefFig = id => D.brief.find(b => b.id === id);
const verdictCls = v => v === "APPROVE" ? "ok" : v === "REJECT" ? "no" : "mid";

/* ---------- hand-drawn icons ---------- */
const ICON = {
  ATC:`<svg viewBox="0 0 40 40" fill="none" stroke="#2563EB" stroke-width="2"><path d="M14 38 L16 18 H24 L26 38"/><path d="M11 18 H29 L27 11 H13 Z"/><path d="M20 11 V5"/><circle cx="20" cy="4" r="1.6" fill="#2563EB"/><path d="M15 28 H25"/></svg>`,
  PILOT:`<svg viewBox="0 0 40 40" fill="none" stroke="#0D8577" stroke-width="2"><path d="M8 16 Q20 6 32 16 L30 19 H10 Z"/><path d="M17 12 L20 9 L23 12"/><circle cx="20" cy="26" r="7"/><path d="M4 22 L13 24 M36 22 L27 24"/></svg>`,
  GROUND:`<svg viewBox="0 0 40 40" fill="none" stroke="#15803D" stroke-width="2"><rect x="5" y="17" width="22" height="11" rx="2"/><path d="M27 21 H33 L36 25 V28 H27"/><circle cx="11" cy="31" r="3"/><circle cx="29" cy="31" r="3"/><path d="M9 17 V11 H19 V17"/></svg>`,
  REVIEW:`<svg viewBox="0 0 40 40" fill="none" stroke="#6D3FD6" stroke-width="2"><path d="M20 4 L34 9 V19 C34 28 27 34 20 36 C13 34 6 28 6 19 V9 Z"/><path d="M13 20 L18 25 L27 15"/></svg>`,
  HUMAN:`<svg viewBox="0 0 40 40" fill="none" stroke="#0D1A14" stroke-width="2"><circle cx="20" cy="12" r="6"/><path d="M8 36 C8 26 14 22 20 22 C26 22 32 26 32 36"/><path d="M27 6 L31 2 M31 8 L36 6"/></svg>`,
  PHONE:`<svg viewBox="0 0 40 40" fill="none" stroke="#B26A00" stroke-width="2"><path d="M10 6 L16 6 L18 14 L14 17 C16 22 18 24 23 26 L26 22 L34 24 L34 30 C34 33 31 35 28 34 C17 31 9 23 6 12 C5 9 7 6 10 6 Z"/></svg>`,
  CODE:`<svg viewBox="0 0 40 40" fill="none" stroke="#15803D" stroke-width="2"><rect x="4" y="7" width="32" height="26" rx="3"/><path d="M15 15 L10 20 L15 25 M25 15 L30 20 L25 25 M22 13 L18 27"/></svg>`,
  warn:`<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="#B26A00" stroke-width="1.6"><path d="M8 2 L15 14 H1 Z"/><path d="M8 6 V10 M8 12 V12.5"/></svg>`,
  slot_shift:`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#2563EB" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7 V12 L16 14"/></svg>`,
  hold:`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#B26A00" stroke-width="2"><rect x="3" y="8" width="18" height="8" rx="4"/><path d="M17 5 L20 8 L17 11"/></svg>`,
  divert:`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#C2362B" stroke-width="2"><path d="M4 20 V12 C4 8 8 6 12 6 H20"/><path d="M16 2 L20 6 L16 10"/></svg>`,
  gate_swap:`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#15803D" stroke-width="2"><path d="M4 8 H18 L15 5 M20 16 H6 L9 19"/></svg>`,
  ground_hold:`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#6D3FD6" stroke-width="2"><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></svg>`,
};
const kindLabel = {slot_shift:"Arrival slot shift", hold:"Airborne hold", divert:"Divert", gate_swap:"Gate swap", ground_hold:"Ground hold at origin"};
const roleView = {ATC:"runway, wake, taxi", PILOT:"fuel, duty, alternates", GROUND:"gates, next legs, connections"};

function ruleOf(run, cand, rule){ return run.rules.find(r => r.candidate_id===cand && r.rule_id===rule); }
function failsOf(run, cand){ return run.rules.filter(r => r.candidate_id===cand && !r.passed).map(r => r.rule_id); }
function candOf(run, id){ return run.candidates.find(c => c.candidate_id===id); }

/* ---------- chapter 1: cascade svg ---------- */
function cascadeSVG(legs){
  if (!legs.length) return "<p class='dim'>No legs found in flights.csv.</p>";
  const t0 = Math.floor((Math.min(...legs.map(l=>l.sched_dep))-60)/120)*120;
  const t1 = Math.ceil((Math.max(...legs.map(l=>l.act_arr))+60)/120)*120;
  const W=1200, left=210, right=110, rowH=62, top=36, Hh=top+legs.length*rowH+20;
  const x = m => left + (m-t0)/(t1-t0)*(W-left-right);
  let s = `<svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Timeline of the aircraft's legs">`;
  for (let m=t0; m<=t1; m+=120){ s += `<line x1="${x(m)}" y1="${top-10}" x2="${x(m)}" y2="${Hh-14}" stroke="#DCE3DD"/><text x="${x(m)}" y="${top-16}" fill="#66766D" font-size="15" text-anchor="middle" font-family="IBM Plex Mono,Cascadia Mono,Consolas,monospace">${hhmm(m)}</text>`; }
  legs.forEach((l,i)=>{
    const y = top + i*rowH + 8;
    const col = l.arr_delay >= 180 ? "#C2362B" : "#B26A00";
    s += `<text x="10" y="${y+17}" fill="#0D1A14" font-size="19" font-family="IBM Plex Mono,Cascadia Mono,Consolas,monospace" font-weight="700">${esc(l.flight)}</text>`;
    s += `<text x="10" y="${y+39}" fill="#66766D" font-size="15" font-family="IBM Plex Mono,Cascadia Mono,Consolas,monospace">${esc(l.origin)}→${esc(l.dest)}</text>`;
    s += `<rect x="${x(l.sched_dep)}" y="${y}" width="${Math.max(3,x(l.sched_arr)-x(l.sched_dep))}" height="16" fill="none" stroke="#66766D" stroke-dasharray="5 4" rx="3"/>`;
    s += `<rect x="${x(l.act_dep)}" y="${y+22}" width="${Math.max(3,x(l.act_arr)-x(l.act_dep))}" height="18" fill="${col}" opacity=".85" rx="3"/>`;
    s += `<line x1="${x(l.sched_arr)}" y1="${y+8}" x2="${x(l.act_arr)}" y2="${y+31}" stroke="${col}" stroke-width="1.5" stroke-dasharray="3 3"/>`;
    s += `<text x="${x(l.act_arr)+8}" y="${y+37}" fill="${col}" font-size="20" font-weight="700" font-family="IBM Plex Mono,Cascadia Mono,Consolas,monospace">+${l.arr_delay}</text>`;
  });
  return s + `</svg>`;
}

/* ---------- chapters ---------- */
const CH = [];
const briefChip = b => `<span class="chip src-brief" title="${esc(b.cite)}">reported in our industry brief</span>`;

CH.push({t:"The problem", r(){
  const legs = D.tail_day.legs, first = legs[0], last = legs[legs.length-1];
  const tot = legs.reduce((a,l)=>a+l.arr_delay,0);
  const figs = ["calls","lag","cost"].map(briefFig).filter(Boolean);
  return `
  <div class="kicker">Chapter 1 · the problem</div>
  <h1>A storm at the hub, three parties to agree, one phone</h1>
  <p class="lead">Today the airline's duty manager calls each party in turn until they agree.</p>
  <div class="flow">
    ${[["PHONE","TRACON","slots, holding"],["PILOT","Crew","fuel, duty time"],["GROUND","Ramp","gates, next departure"],["PHONE","TRACON again","if anyone says no"]]
      .map(([ic,a,b])=>`<div class="card step"><div class="agent">${ICON[ic]}<h3>${a}</h3></div><div class="dim small">${b}</div></div>`).join("")}
  </div>
  <div class="grid g3" style="margin-top:14px">
    ${figs.map(b=>`<div class="card"><div class="big mid">${esc(b.figure)}</div><div class="small">${esc(b.label)}</div><div style="margin-top:6px">${briefChip(b)}</div></div>`).join("")}
  </div>
  <h2>Meanwhile the delay rides the aircraft all day · ${esc(D.tail_day.tail)}</h2>
  <div class="card svgbox">${cascadeSVG(legs)}
    <div class="legend">dashed = scheduled · bar = actual · ${chip("data")} flights.csv</div></div>
  <p class="lead" style="margin-top:12px">${esc(first.flight)} landed <b class="mid">+${first.arr_delay} min</b>. By ${esc(last.flight)} the same aircraft was <b class="no">+${last.arr_delay} min</b>: ${num(tot)} min of delay in one day.</p>`;
}});

CH.push({t:"The disruption", r(){
  const f = S.flight;
  const labels = {dest_disruption:"Delayed arrivals that hour", taxi_congestion:"Taxi congestion", wake_category:"Wake category", fuel_reserve_min:"Spare fuel (min)", crew_duty_remaining_min:"Crew duty left (min)", nominal_aar:"Arrival rate / hour"};
  const card = (tag, big, src, sub) => `<div class="card"><div class="tag">${tag}</div><div class="big" style="font-size:30px">${big}</div>${src}${sub?`<div class="dim small">${sub}</div>`:""}</div>`;
  return `
  <div class="kicker">Chapter 2 · the disruption</div>
  <h1>${esc(fl(f))} ${esc(f.ORIGIN_AIRPORT)}→${esc(f.DESTINATION_AIRPORT)}, ${esc(f.date)}</h1>
  <p class="lead">One row of the US DOT 2015 data becomes a scenario. Every value is tagged with its source.</p>
  <div class="small">${chip("data")} real ${chip("estimated")} derived ${chip("assumed")} our constant ${chip("synthetic")} stand-in</div>
  <div class="grid g4" style="margin-top:12px">
    ${card("Aircraft", esc(f.TAIL_NUMBER), chip("data"))}
    ${card("Sched → actual arrival", `${hhmm(f.SCHEDULED_ARRIVAL)} → ${hhmm(f.ARRIVAL_TIME)}`, chip("data"))}
    ${card("Arrival delay", `<span class="mid">+${esc(f.ARRIVAL_DELAY)} min</span>`, chip("data"), `weather ${esc(f.WEATHER_DELAY)} · late aircraft ${esc(f.LATE_AIRCRAFT_DELAY)}`)}
    ${card("Later legs today", S.downstream.length, chip("data"))}
  </div>
  <div class="grid g3" style="margin-top:14px">
    ${S.facts.map(x=>card(esc(labels[x.key]||x.key), esc(x.value), chip(x.source))).join("")}
    ${card("Gate", esc(S.gates.assigned_gate), chip(S.gates.source), `turnaround ${esc(S.gates.min_turnaround_min)} min`)}
    ${card("Connections at risk", `${S.connections.n} · ${S.connections.pax} pax`, chip(S.connections.source))}
    ${card("Alternates", S.alternates.map(a=>esc(a.iata)).join(" · "), chip("data"), S.alternates.map(a=>`${esc(a.iata)} ${num(a.distance_nm)} nm`).join(" · "))}
  </div>`;
}});

CH.push({t:"The menu", r(){
  const maxK = Math.max(...S.candidates.map(c=>c.est_knock_on_min));
  return `
  <div class="kicker">Chapter 3 · the menu</div>
  <h1>${S.candidates.length} options, written by code</h1>
  <p class="lead">Agents can only rank or veto these. Delays are model estimates.</p>
  <div class="grid g4">${S.candidates.map(c=>`<div class="card cand">
    <div class="agent" style="margin:0">${ICON[c.kind]||""}<span style="font-size:19px;font-weight:700">${esc(c.candidate_id)}</span></div>
    <div class="dim small">${esc(kindLabel[c.kind]||c.kind)}</div>
    <div>delay <b class="${c.est_delay_min<0?"ok":"mid"}">${signed(c.est_delay_min)} min</b></div>
    <div class="small dim">knock-on ${num(c.est_knock_on_min)} min</div>
    <div class="bar"><i style="width:${(c.est_knock_on_min/maxK*100).toFixed(1)}%"></i></div></div>`).join("")}</div>
  <p class="legend">Knock-on = delay carried into the aircraft's later legs.</p>`;
}});

function agentCard(m, run){
  const [top, ...rest] = m.ranking;
  return `<div class="card comms" style="--ac:${AC[m.agent]}">
    <div class="agent">${ICON[m.agent]}<div><h3 style="margin:0">${esc(m.agent)}</h3><div class="dim small">${esc(roleView[m.agent]||"")}</div></div></div>
    <div class="small">Accepts <b>${m.acceptable.length}/${run.candidates.length}</b></div>
    ${top?`<div class="bubble"><b>${esc(top.candidate_id)}</b> <span class="score">${esc(top.score)}</span><br>${esc(top.rationale)}<br>${(top.cited_fields||[]).map(c=>`<span class="chip src-estimated">${esc(c)}</span>`).join("")}</div>`:""}
    ${rest.length?`<div class="small dim" style="margin-top:8px">then ${rest.slice(0,3).map(r=>`${esc(r.candidate_id)} <span class="ok">${esc(r.score)}</span>`).join(" · ")}</div>`:""}
    ${m.vetoes.length?`<div class="small" style="margin-top:8px">Vetoes ${m.vetoes.map(v=>`<span class="pencil strike" title="${esc(v.reason)}">${esc(v.candidate_id)}</span>`).join("")}</div>`:""}
  </div>`;
}

CH.push({t:"Agents negotiate", r(){
  const rounds = S.turns.map(t=>`
    <h2>Round ${t.round}${t.invalid?` · <span class="no">${t.invalid} invalid</span>`:""}</h2>
    <div class="grid g3">${t.messages.map(m=>agentCard(m,S)).join("")}</div>
    <div class="banner green" style="margin-top:12px">All three accept: ${t.intersection.map(esc).join(" · ")}</div>`).join("");
  const LC = L && L.recommendation.chosen;
  return `
  <div class="kicker">Chapter 4 · negotiation · ${esc(S.meta.model)}</div>
  <h1>Three agents, each seeing only its own data</h1>
  <p class="lead">They rank, accept and veto in structured JSON. None of them sees the rule results.</p>
  ${rounds}
  ${L?`<p class="small dim" style="margin-top:14px">Same flight with ${esc(L.meta.model)}: also picked <b class="ok">${esc(LC&&LC.candidate_id)}</b> (${esc(L.recommendation.decided_by)}, reviewer ${esc(L.recommendation.reviewer_verdict)}).</p>`:""}`;
}});

function matrix(run, opts){
  opts = opts || {};
  const chosen = run.recommendation.chosen && run.recommendation.chosen.candidate_id;
  const agreed = new Set((run.turns[run.turns.length-1]||{intersection:[]}).intersection);
  let h = `<table id="${opts.id||"mx"}"><tr><th>option</th>${run.rule_ids.map(r=>`<th class="c">${esc(r)}<br>${chip(run.rule_source[r])}</th>`).join("")}</tr>`;
  run.candidates.forEach(c=>{
    h += `<tr><td>${chosen===c.candidate_id?"★ ":""}${esc(c.candidate_id)} ${agreed.has(c.candidate_id)?'<span class="pencil ring" title="all three agents accept">agreed</span>':""}</td>`;
    run.rule_ids.forEach(r=>{ const x = ruleOf(run,c.candidate_id,r);
      h += x ? `<td tabindex="0" class="c cell ${x.passed?"pass":"fail"}" data-c="${esc(c.candidate_id)}" data-r="${esc(r)}">${x.passed?"PASS":"FAIL"}</td>` : `<td class="c dim">–</td>`; });
    h += `</tr>`;
  });
  return h + `</table>`;
}
function wireMatrix(run, id, detailId){
  const tbl = document.getElementById(id), det = document.getElementById(detailId);
  if (!tbl) return;
  const show = (c,r) => { const x = ruleOf(run,c,r); if(!x) return;
    tbl.querySelectorAll(".cell").forEach(e=>e.classList.toggle("sel", e.dataset.c===c && e.dataset.r===r));
    det.innerHTML = `<div><b>${esc(x.rule_id)}</b> × <b>${esc(x.candidate_id)}</b>: <b class="${x.passed?"ok":"no"}">${x.passed?"PASS":"FAIL"}</b></div><div class="small" style="margin-top:4px">observed ${esc(x.observed)} vs limit ${esc(x.threshold)} ${chip(x.source)}</div><div class="small dim" style="margin-top:6px">${esc(x.citation)}</div>`; };
  tbl.addEventListener("click", e=>{ const td = e.target.closest(".cell"); if (td) show(td.dataset.c, td.dataset.r); });
  tbl.addEventListener("keydown", e=>{ if (e.key!=="Enter" && e.key!==" ") return; const td = e.target.closest && e.target.closest(".cell"); if (td){ e.preventDefault(); show(td.dataset.c, td.dataset.r); } });
  const firstFail = run.rules.find(r=>!r.passed) || run.rules[0];
  if (firstFail) show(firstFail.candidate_id, firstFail.rule_id);
}

CH.push({t:"Code checks the rules", r(){
  const tf = metric("agent_top_pick_rule_fail_rate");
  const nFail = S.rules.filter(r=>!r.passed).length;
  return `
  <div class="kicker">Chapter 5 · rules engine · deterministic</div>
  <h1>${S.rules.length} checks, ${nFail} fail</h1>
  <p class="lead">Consensus = all three agents accept <b>and</b> it passes every rule. Click a cell for its source.</p>
  <div class="grid mx-wrap">
    <div class="card">${matrix(S,{id:"mx1"})}</div>
    <div><div class="card hl" id="mx1d"></div>
      <div class="card"><h3>Agents' top picks</h3>${S.top_picks.map(p=>`<div class="small">${esc(p.agent)} → <b>${esc(p.candidate_id)}</b> ${p.fails.length?`<span class="no">fails ${p.fails.map(esc).join(", ")}</span>`:`<span class="ok">passes</span>`}</div>`).join("")}</div>
      ${tf?`<div class="card warn" style="margin-top:12px"><div class="big mid">${pct(tf.value)}</div><div class="small">of agent top picks across 200 flights broke a rule they could not see. The engine caught every one.</div></div>`:""}
    </div></div>`;
}, after(){ wireMatrix(S,"mx1","mx1d"); }});

CH.push({t:"Independent reviewer", r(){
  const R = S.reviewer, cid = R.candidate_id;
  const cands = [...new Set(R.re_derived.map(x=>x.candidate_id))];
  const checks = [...new Set(R.re_derived.map(x=>x.check))];
  const cell = (c,k) => { const x = R.re_derived.find(y=>y.candidate_id===c && y.check===k); return x?`<td class="c ${x.passed?"ok":"no"}">${num(x.derived,1)} / ${num(x.threshold,1)}</td>`:"<td></td>"; };
  return `
  <div class="kicker">Chapter 6 · reviewer · written separately</div>
  <h1>A second check redoes the fuel, duty and wake maths</h1>
  <div class="agent" style="margin-top:6px">${ICON.REVIEW}<span class="stamp ${verdictCls(R.verdict)}">${esc(R.verdict)}</span><span style="margin-left:8px">${esc(cid)}</span></div>
  <div class="grid g3" style="margin-top:14px">
    <div class="card"><div class="big">${R.engine_disagreements.length}</div><div class="small">disagreements with the rules engine</div></div>
    <div class="card"><div class="big">${esc(R.citations_checked)}</div><div class="small">agent citations checked</div></div>
    <div class="card"><div class="big ${R.cited_mismatches.length?"no":"ok"}">${R.cited_mismatches.length}</div><div class="small">citations that did not match the data</div></div>
  </div>
  <h2>Re-derived per option · value / limit</h2>
  <div class="card"><table><tr><th>option</th>${checks.map(k=>`<th class="c">${esc(k)}</th>`).join("")}</tr>
    ${cands.map(c=>`<tr><td>${c===cid?"★ ":""}${esc(c)}</td>${checks.map(k=>cell(c,k)).join("")}</tr>`).join("")}</table>
    <div class="legend">FUEL min left · DUTY min left · WAKE seconds per runway</div></div>`;
}});

function timeline(run){
  return `<div class="tl">${run.timeline.map(e=>`<div class="ev e-${esc(e.event)} ${e.event==="reviewer_verdict"&&/REJECT/.test(e.text)?"rej":""}"><span class="tag">${esc((e.ts||"").slice(11,19))}</span> <b>${esc(e.event)}</b> <span class="small">${esc(e.text)}</span></div>`).join("")}</div>`;
}

CH.push({t:"The human decides", r(){
  const R = S.recommendation, c = R.chosen || {};
  return `
  <div class="kicker">Chapter 7 · human approval</div>
  <h1>One recommendation, two buttons</h1>
  <div class="grid" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr)">
    <div class="card hl">
      <div class="agent">${ICON.HUMAN}<h3 style="margin:0">${esc(fl(S.flight))} · recommended</h3></div>
      <div class="big ok" style="font-size:56px">${esc(c.candidate_id)}</div>
      <div>${esc(kindLabel[c.kind]||c.kind)} · delay ${signed(c.est_delay_min)} min</div>
      <div class="small dim" style="margin-top:8px">${esc(R.decided_by)} · reviewer <b class="${verdictCls(R.reviewer_verdict)}">${esc(R.reviewer_verdict)}</b> · ${S.rule_ids.length}/${S.rule_ids.length} rules · $${num(S.meta.cost_usd,4)} · ${num(S.meta.latency_s,0)} s</div>
      <div style="margin-top:16px;display:flex;gap:12px"><button class="btn primary" id="appr">✔ Approve</button><button class="btn" id="rej" style="border-color:var(--red);color:var(--red)">✖ Reject</button></div>
      <div class="toast" id="toast">human_decision: <b>${esc(R.human_decision)}</b></div>
      <div class="small dim">Demo only. The tool never executes anything.</div>
    </div>
    <div class="card"><h3>Consensus log</h3>${timeline(S)}<div class="legend">Append-only. ${S.rules.length} rule checks shown as one line.</div></div>
  </div>`;
}, after(){
  const t = document.getElementById("toast");
  const say = d => { t.innerHTML = `Would log <b>human_decision: ${d}</b>. Nothing is executed.`; };
  document.getElementById("appr").onclick = () => say("approve");
  document.getElementById("rej").onclick = () => say("reject");
}});

CH.push({t:"When nothing is safe", r(){
  const f = F.flight, fd = D.failure_doc;
  const duty = F.facts.find(x=>x.key==="crew_duty_remaining_min");
  const dutyRows = F.candidates.map(c=>({c, r: ruleOf(F,c.candidate_id,"R-DUTY-01")}));
  const agreed = (F.turns[F.turns.length-1]||{intersection:[]}).intersection.length;
  return `
  <div class="kicker">Chapter 8 · the honest failure</div>
  <h1>${esc(fl(f))} ${esc(f.ORIGIN_AIRPORT)}→${esc(f.DESTINATION_AIRPORT)}: every option times out the crew</h1>
  <div class="banner red">No legal option. Escalated to the duty manager.</div>
  <div class="grid g3" style="margin-top:14px">
    <div class="card"><div class="tag">Arrival delay</div><div class="big no">+${esc(f.ARRIVAL_DELAY)} min</div>${chip("data")}</div>
    <div class="card"><div class="tag">Crew duty left</div><div class="big mid">${esc(duty&&duty.value)} min</div>${chip(duty&&duty.source)}<span class="small dim">no real rosters</span></div>
    <div class="card"><div class="tag">Agents</div><div class="big">${agreed}</div><div class="small">options all three accepted · reviewer <b class="no">${esc(F.reviewer.verdict)}</b></div></div>
  </div>
  <div class="grid g2" style="margin-top:14px">
    <div class="card"><h3>R-DUTY-01 · duty left at arrival (min)</h3>
      <table><tr><th>option</th><th class="c">min</th></tr>
      ${dutyRows.map(x=>`<tr><td>${esc(x.c.candidate_id)}</td><td class="c ${x.r&&x.r.passed?"ok":"no"}">${x.r?num(x.r.observed,0):"–"}</td></tr>`).join("")}</table></div>
    <div class="card warn"><h3>It also caught a bug in our own reviewer</h3>
      <div class="small">The reviewer forgot delay already incurred, so its duty check passed.${fd.fix_commit?` Fixed in ${esc(fd.fix_commit)}.`:""} Reviewer-engine disagreement over 200 flights fell${fd.disagree_before_pct?` from ${esc(fd.disagree_before_pct)}%`:""} to ${pct(metric("reviewer_engine_disagreement_rate").value)}.</div></div>
  </div>`;
}});

CH.push({t:"The evidence", r(){
  const tiles = [];
  const add = (big, title, m, cls) => { if (m) tiles.push(`<div class="card tile"><div class="big ${cls||""}">${big}</div><div class="small">${title}</div><div class="def">n = ${esc(m.n)}</div></div>`); };
  const c = metric("consensus_rate"); add(c&&pct(c.value), "agents agree on a rule-passing option", c, "ok");
  const tf = metric("agent_top_pick_rule_fail_rate"); add(tf&&pct(tf.value), "agent top picks broke a rule, all caught", tf, "mid");
  const ph = PS.haiku;
  if (ph) tiles.push(`<div class="card tile"><div class="big no">${ph.escalated} / ${ph.n}</div><div class="small">escalated to a human: no legal option</div><div class="def">n = ${ph.n}</div></div>`);
  const a = metric("reviewer_APPROVE_rate"), mo = metric("reviewer_MODIFY_rate"), rj = metric("reviewer_REJECT_rate");
  if (a&&mo&&rj) tiles.push(`<div class="card tile"><div class="big"><span class="ok">${pct(a.value,0)}</span> <span class="mid">${pct(mo.value,0)}</span> <span class="no">${pct(rj.value,0)}</span></div><div class="small">reviewer approve / modify / reject</div><div class="def">n = ${esc(a.n)}</div></div>`);
  const si = metric("schema_invalid_rate"); add(si&&pct(si.value,1), "invalid agent replies, logged, never repaired", si);
  const cu = metric("cost_usd_mean"); add(cu&&("$"+num(cu.value,4)), "cost per decision", cu);
  const lm = metric("latency_s_mean"); add(lm&&(num(lm.value,0)+" s"), "time per decision", lm);
  const cm = metric("cited_value_mismatch_rate"); add(cm&&pct(cm.value,1), "agent citations that did not match the data", cm);
  return `
  <div class="kicker">Chapter 9 · the evidence</div>
  <h1>200 real delayed flights, same pipeline</h1>
  <p class="lead">Seeded sample from US DOT 2015, run with ${esc(S.meta.model)} agents.</p>
  <div class="grid g4">${tiles.join("")}</div>`;
}});

CH.push({t:"Real vs assumed", r(){
  const groups = {data:[],estimated:[],assumed:[],synthetic:[]};
  S.facts.forEach(x=>{ (groups[x.source]=groups[x.source]||[]).push(esc(x.key)); });
  groups.data.push("flight times and delays", "alternates");
  groups.synthetic.push("gates");
  groups.assumed.push("turnaround times");
  if (S.connections.source && groups[S.connections.source]) groups[S.connections.source].push("connecting passengers");
  return `
  <div class="kicker">Chapter 10 · honesty and next steps</div>
  <h1>What is real, what is assumed, what comes next</h1>
  <div class="grid g4">${Object.entries(groups).map(([k,v])=>`<div class="card"><h3>${chip(k)}</h3><ul class="tight small">${v.map(x=>`<li>${x}</li>`).join("")}</ul></div>`).join("")}</div>
  <div class="grid g2" style="margin-top:14px">
    <div class="card"><h3>To reach production</h3><ul class="tight">
      <li>Real crew rosters</li>
      <li>Crew and tail swaps as options</li>
      <li>Live gate and fuel feeds</li>
      <li>Shadow trial with a duty manager</li></ul></div>
    <div class="card"><h3>What never changes</h3><ul class="tight">
      <li>LLMs rank and explain, never judge legality</li>
      <li>Every result cites a rule and a source</li>
      <li>A fallback and a reviewer behind every pick</li>
      <li>A human approves; the tool never executes</li></ul></div>
  </div>
  <div class="thesis">LLMs negotiate, code decides, a human approves.</div>
  <div style="display:flex;justify-content:center"><div class="mandatory" role="img" aria-label="Mandatory sign: human approves">Hold short &middot; human approves</div></div>`;
}});

/* ---------- console chrome: agent status bar + radar scope ---------- */
const AC = {ATC:"var(--c-atc)", PILOT:"var(--c-pilot)", GROUND:"var(--c-ground)", RULES:"var(--c-rules)", REVIEWER:"var(--c-review)", HUMAN:"var(--c-human)"};
const FLASH = [["ATC","ATC"],["PILOT","PILOT"],["GROUND","GROUND"],["RULES","RULES ENGINE"],["REVIEWER","REVIEWER"],["HUMAN","DUTY MANAGER"]];
/* One entry per chapter, same order as CH: who acts, which run the scope shows, and its state. */
const PHASE = [
  {on:["HUMAN"], run:"S", mode:"idle", phase:"Phone coordination"},
  {on:[], run:"S", mode:"idle", phase:"Scenario built (code)"},
  {on:[], run:"S", mode:"menu", phase:"Menu generated (code)"},
  {on:["ATC","PILOT","GROUND"], run:"S", mode:"menu", phase:"Agents negotiate"},
  {on:["RULES"], run:"S", mode:"rules", phase:"Rules checked (code)"},
  {on:["REVIEWER"], run:"S", mode:"chosen", phase:"Independent review"},
  {on:["HUMAN"], run:"S", mode:"chosen", phase:"Awaiting approval"},
  {on:["RULES","REVIEWER","HUMAN"], run:"F", mode:"escalate", phase:"Escalated"},
  {on:["ATC","PILOT","GROUND","RULES","REVIEWER","HUMAN"], run:"S", mode:"chosen", phase:"200-flight evaluation"},
  {on:["HUMAN"], run:"S", mode:"chosen", phase:"Human approves"},
];
const PLANE = "M12 2 L14 8 L20 10 L14 12 L14 18 L17 20 L17 21 L12 19 L7 21 L7 20 L10 18 L10 12 L4 10 L10 8 Z";

function scopeSVG(run, mode){
  const g = run.scope, C = 140, R = 120;
  if (!g || !g.dest) return `<svg viewBox="0 0 280 280" role="img" aria-label="No coordinates for this airport"><circle cx="${C}" cy="${C}" r="${R}" fill="#040a04" stroke="#1a4a1a"/><text x="${C}" y="${C}" fill="#98bb98" font-size="12" text-anchor="middle">no coordinates</text></svg>`;
  const range = g.range_nm, f = run.flight;
  const P = (brg, nm) => { const r = Math.min(nm/range, 1)*R, a = (brg-90)*Math.PI/180; return [C + r*Math.cos(a), C + r*Math.sin(a)]; };
  const fx = v => v.toFixed(1);
  const chosen = run.recommendation.chosen;
  const blipCol = mode==="escalate" ? "#ff3333" : mode==="chosen" ? "#33ff33" : "#ffaa00";
  const ob = g.origin ? g.origin.brg : 270, heading = (ob + 180) % 360;
  const [bx, by] = P(ob, range*0.52);
  let s = `<svg viewBox="0 0 280 280" role="img" aria-label="Schematic scope centred on ${esc(g.dest.iata)}, ${esc(range)} nautical miles: alternates and origin by true bearing">`;
  s += `<circle cx="${C}" cy="${C}" r="${R}" fill="#040a04" stroke="#1f5a1f" stroke-width="1.2"/>`;
  for (let k = 1; k <= 4; k++){
    const r = R*k/4;
    s += `<circle cx="${C}" cy="${C}" r="${fx(r)}" fill="none" stroke="#1a4a1a" ${k<4?'stroke-dasharray="2 4"':""}/>`;
    s += `<text x="${C+3}" y="${fx(C-r+10)}" fill="#3f7a3f" font-size="8">${Math.round(range*k/4)}</text>`;
  }
  s += `<line x1="${C-R}" y1="${C}" x2="${C+R}" y2="${C}" stroke="#123012"/><line x1="${C}" y1="${C-R}" x2="${C}" y2="${C+R}" stroke="#123012"/>`;
  for (let d = 0; d < 360; d += 30){ const [x1,y1] = P(d, range*0.96), [x2,y2] = P(d, range); s += `<line x1="${fx(x1)}" y1="${fx(y1)}" x2="${fx(x2)}" y2="${fx(y2)}" stroke="#2a6a2a"/>`; }
  s += `<text x="${C}" y="${C-R-5}" fill="#6a8e6a" font-size="9" text-anchor="middle">N</text>`;
  if (Number(f.WEATHER_DELAY) > 0) s += `<circle class="wx" cx="${C}" cy="${C}" r="${fx(R*0.3)}" fill="rgba(255,170,0,.10)" stroke="rgba(255,170,0,.55)" stroke-dasharray="3 3"/><text x="${fx(C+R*0.3*0.72)}" y="${fx(C-R*0.3*0.72)}" fill="#ffaa00" font-size="9">WX</text>`;
  const altPos = {};
  (g.alternates||[]).forEach(a => { altPos[a.iata] = P(a.brg, a.nm); });
  const diverts = run.candidates.filter(c => c.kind === "divert").map(c => ({c, iata: c.candidate_id.replace(/^DIVERT_/, "")})).filter(d => altPos[d.iata]);
  const line = (x, y, col, dash, w) => `<line x1="${fx(bx)}" y1="${fx(by)}" x2="${fx(x)}" y2="${fx(y)}" stroke="${col}" stroke-width="${w||1.2}" ${dash?'stroke-dasharray="4 3"':""} opacity=".9"/>`;
  const racetrack = col => `<g transform="translate(${fx(bx)},${fx(by)}) rotate(${heading}) translate(10,-6)"><rect width="12" height="22" rx="6" fill="none" stroke="${col}" stroke-dasharray="3 2"/></g>`;
  if (mode === "menu" || mode === "rules"){
    diverts.forEach(d => { const ok = !failsOf(run, d.c.candidate_id).length; s += line(altPos[d.iata][0], altPos[d.iata][1], mode==="rules" ? (ok?"#33ff33":"#ff3333") : "#33ccff", true); });
    const holds = run.candidates.filter(c => c.kind === "hold");
    if (holds.length) s += racetrack(mode==="rules" ? (holds.every(h=>!failsOf(run,h.candidate_id).length) ? "#33ff33" : "#ff3333") : "#33ccff");
  }
  if (mode === "chosen" && chosen){
    if (chosen.kind === "divert"){ const p = altPos[chosen.candidate_id.replace(/^DIVERT_/, "")]; if (p) s += line(p[0], p[1], "#ff66ff", false, 2); }
    if (chosen.kind === "hold") s += racetrack("#ff66ff");
  }
  (g.alternates||[]).forEach(a => {
    const [x, y] = altPos[a.iata], right = x > C;
    s += `<path d="M${fx(x)} ${fx(y-4)} L${fx(x+4)} ${fx(y)} L${fx(x)} ${fx(y+4)} L${fx(x-4)} ${fx(y)} Z" fill="none" stroke="#98bb98"/>`;
    s += `<text x="${fx(right ? x-7 : x+7)}" y="${fx(y+3)}" fill="#98bb98" font-size="9" text-anchor="${right?"end":"start"}">${esc(a.iata)}</text>`;
  });
  /* Labels sit either side of the inbound track: the flight's on the upper side, the origin's opposite. */
  const ang = (ob-90)*Math.PI/180;
  let nx = -Math.sin(ang), ny = Math.cos(ang);
  if (ny > 0){ nx = -nx; ny = -ny; }
  const anchorFor = x => x < C-24 ? "start" : x > C+24 ? "end" : "middle";
  if (g.origin){
    const [ox, oy] = P(g.origin.brg, range);
    const lx = Math.min(Math.max(ox - nx*12, 22), 258), ly = oy - ny*12 + 3;
    s += `<circle cx="${fx(ox)}" cy="${fx(oy)}" r="2.5" fill="#33ccff"/>`;
    s += `<text x="${fx(lx)}" y="${fx(ly)}" fill="#33ccff" font-size="8.5" text-anchor="${anchorFor(lx)}">${esc(g.origin.iata)} ${num(g.origin.nm)}NM</text>`;
  }
  s += `<rect x="${C-3}" y="${C-3}" width="6" height="6" fill="#d0e8d0"/><text x="${C}" y="${C+15}" fill="#d0e8d0" font-size="10" font-weight="600" text-anchor="middle">${esc(g.dest.iata)}</text>`;
  for (let k = 1; k <= 3; k++){ const [tx, ty] = P(ob, range*(0.52 + k*0.05)); s += `<circle cx="${fx(tx)}" cy="${fx(ty)}" r="1.6" fill="${blipCol}" opacity="${(0.55 - k*0.15).toFixed(2)}"/>`; }
  s += `<g class="${mode==="escalate"?"blinking":""}"><g transform="translate(${fx(bx)},${fx(by)}) rotate(${heading}) scale(.75) translate(-12,-12)"><path d="${PLANE}" fill="${blipCol}"/></g></g>`;
  const tag = mode==="escalate" ? "ESCALATE" : (mode==="chosen" && chosen) ? chosen.candidate_id : `+${f.ARRIVAL_DELAY} MIN`;
  const tx = Math.min(Math.max(bx + nx*20, 26), 254), ty = by + ny*20;
  s += `<text x="${fx(tx)}" y="${fx(ty-5)}" fill="${blipCol}" font-size="9.5" font-weight="600" text-anchor="${anchorFor(tx)}">${esc(fl(f))}</text>`;
  s += `<text x="${fx(tx)}" y="${fx(ty+6)}" fill="${blipCol}" font-size="8.5" text-anchor="${anchorFor(tx)}">${esc(tag)}</text>`;
  return s + `</svg>`;
}

function readoutHTML(run, ph){
  const f = run.flight, R = run.recommendation, mode = ph.mode;
  const nFail = run.rules.filter(r => !r.passed).length;
  const status = mode==="idle" ? "inbound, delayed"
    : mode==="menu" ? `${run.candidates.length} options on the menu`
    : mode==="rules" ? `${nFail} of ${run.rules.length} checks FAIL`
    : mode==="escalate" ? "escalate to duty manager"
    : `${R.decided_by} · reviewer ${R.reviewer_verdict}`;
  const pick = mode==="escalate" ? `<b class="no">NONE</b>` : (mode==="chosen" && R.chosen) ? `<b class="ok">${esc(R.chosen.candidate_id)}</b>` : `<b class="dim">pending</b>`;
  const row = (k, v) => `<div><span>${k}</span>${v}</div>`;
  return row("FLT", `<b>${esc(fl(f))} ${esc(f.ORIGIN_AIRPORT)}→${esc(f.DESTINATION_AIRPORT)}</b>`)
    + row("TAIL", `<b>${esc(f.TAIL_NUMBER)}</b>`)
    + row("ARR DELAY", `<b class="mid">+${esc(f.ARRIVAL_DELAY)} min</b>`)
    + row("PHASE", `<b>${esc(ph.phase)}</b>`)
    + row("STATUS", `<b>${esc(status)}</b>`)
    + row("PICK", pick)
    + `<span class="note">Bearings and distances from airports.csv. The aircraft's position is schematic.</span>`;
}

function renderChrome(i){
  const ph = PHASE[i] || PHASE[0], run = ph.run === "F" ? F : S;
  document.getElementById("flash").innerHTML = FLASH.map(([k, label]) =>
    `<span role="listitem" class="fchip ${ph.on.indexOf(k) >= 0 ? "on" : ""}" style="--ac:${AC[k]}"><i></i>${label}</span>`).join("");
  document.getElementById("scope").innerHTML = scopeSVG(run, ph.mode);
  document.getElementById("readout").innerHTML = readoutHTML(run, ph);
  document.getElementById("scopeTitle").textContent = `Scope · ${run.scope && run.scope.dest ? run.scope.dest.iata : "?"}`;
  document.getElementById("scopeRange").textContent = run.scope ? `${run.scope.range_nm} NM` : "";
  document.getElementById("scn").textContent = run.scenario_id;
}

/* ---------- navigation: one continuous scroll ---------- */
const $ = id => document.getElementById(id);
const stage = $("stage"), nav = $("index"), rail = $("rail");
const pad = n => String(n).padStart(2, "0");
const reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
let cur = -1;

function heroHTML(){
  const f = S.flight;
  return `<section class="hero" id="sec-0"><span class="node" aria-hidden="true"></span>
    <div class="eyebrow">Autonomous SG 2026 · Airbus track · Challenge 2</div>
    <h1>One delayed arrival. Three agents. <em>One human decision.</em></h1>
    <p class="sub">LLMs negotiate, code decides, a human approves.</p>
    <div class="strip" role="group" aria-label="Flight strip">
      <div><span class="k">Flight</span><span class="v">${esc(fl(f))}</span></div>
      <div><span class="k">Route</span><div class="v">${esc(f.ORIGIN_AIRPORT)} → ${esc(f.DESTINATION_AIRPORT)}</div></div>
      <div><span class="k">Date</span><div class="v">${esc(f.date)}</div></div>
      <div><span class="k">Sched → actual</span><div class="v">${hhmm(f.SCHEDULED_ARRIVAL)} → ${hhmm(f.ARRIVAL_TIME)}</div></div>
      <div><span class="k">Arrival delay</span><div class="v mid">+${esc(f.ARRIVAL_DELAY)} min</div></div>
    </div>
    <div class="cue"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 4v16M5 13l7 7 7-7"/></svg>Scroll to follow it through ten phases</div>
  </section>`;
}

let html = heroHTML();
CH.forEach((c, i) => {
  let body;
  try { body = c.r(); }
  catch(err){ body = `<h1>Chapter ${i+1}</h1><p class="no">Could not render this chapter: ${esc(err.message)}</p>`; }
  html += `<section class="chap" id="sec-${i+1}" data-n="${pad(i+1)}" aria-label="${esc(c.t)}"><span class="node" aria-hidden="true"></span>${body}</section>`;
});
stage.innerHTML = html;
CH.forEach(c => { if (c.after) { try { c.after(); } catch(err){} } });
nav.innerHTML = CH.map((c,i)=>`<a data-i="${i}" tabindex="0" role="button"><span class="n">${pad(i+1)}</span><span>${esc(c.t)}</span><span class="d"></span></a>`).join("");
const links = () => nav.querySelectorAll("a");

function activate(i){
  i = Math.max(0, Math.min(CH.length-1, i));
  if (i === cur) return;
  cur = i;
  try { renderChrome(i); } catch(err){ const sc = $("scope"); if (sc) sc.innerHTML = ""; }
  $("counter").textContent = `${pad(i+1)} / ${pad(CH.length)}`;
  links().forEach((a,j) => { a.classList.toggle("on", j===i); a.classList.toggle("past", j<i); });
  for (let k = 1; k <= CH.length; k++){ const s = $("sec-"+k); if (s){ s.classList.toggle("on", k===i+1); s.classList.toggle("past", k<i+1); } }
}
function go(i){
  i = Math.max(0, Math.min(CH.length-1, i));
  activate(i);
  const s = $("sec-"+(i+1));
  if (s && s.scrollIntoView) s.scrollIntoView({behavior: reduceMotion ? "auto" : "smooth", block: "start"});
  if (window.history && history.replaceState) history.replaceState(null, "", "#"+(i+1));
}

nav.addEventListener("click", e=>{ const a = e.target.closest("a"); if (a) go(+a.dataset.i); });
nav.addEventListener("keydown", e=>{ if (e.key!=="Enter" && e.key!==" ") return; const a = e.target.closest && e.target.closest("a"); if (a){ e.preventDefault(); go(+a.dataset.i); } });
document.addEventListener("keydown", e=>{
  if (e.altKey || e.ctrlKey || e.metaKey) return;
  const tag = e.target && e.target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return;
  if (e.key==="ArrowRight") { e.preventDefault(); go(cur+1); }
  else if (e.key==="ArrowLeft") { e.preventDefault(); go(cur-1); }
  else if (e.key==="Home") { e.preventDefault(); go(0); }
  else if (e.key==="End") { e.preventDefault(); go(CH.length-1); }
  else if (e.key==="i"||e.key==="I") { if (rail) rail.classList.toggle("hidden"); }
});

/* Scroll spy: the phase crossing the middle of the screen is the active one; sections fade in as they arrive. */
if (typeof IntersectionObserver !== "undefined"){
  document.documentElement.classList.add("reveal");
  const spy = new IntersectionObserver(entries => {
    entries.forEach(en => { if (en.isIntersecting){ const n = +en.target.id.slice(4); activate(n === 0 ? 0 : n-1); } });
  }, {rootMargin: "-45% 0px -50% 0px"});
  const rev = new IntersectionObserver(entries => {
    entries.forEach(en => { if (en.isIntersecting){ en.target.classList.add("in"); rev.unobserve(en.target); } });
  }, {threshold: 0.08});
  for (let k = 0; k <= CH.length; k++){ const s = $("sec-"+k); if (s){ spy.observe(s); if (k) rev.observe(s); } }
}
if (window.addEventListener){
  const bar = $("bar");
  const onScroll = () => {
    const d = document.documentElement, max = d.scrollHeight - window.innerHeight;
    bar.style.height = (max > 0 ? Math.min(100, window.scrollY / max * 100) : 0) + "%";
  };
  window.addEventListener("scroll", onScroll, {passive: true});
  onScroll();
}

const h = parseInt((location.hash||"").slice(1), 10);
if (!isNaN(h) && h >= 1){ activate(h-1); const s = $("sec-"+h); if (s && s.scrollIntoView) s.scrollIntoView({block:"start"}); }
else activate(0);
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
