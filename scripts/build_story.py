"""Build the judges' story demo: demo/story.html.

Reads the saved runs, eval results and flights.csv at build time, extracts what each chapter
needs, and writes one self-contained HTML file (inline CSS + JS, data embedded as a JSON blob,
no network requests). Re-run after any new results:

    python scripts/build_story.py
"""

from __future__ import annotations

import csv
import json
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
:root{
  --bg:#03100c; --bg2:#071a14; --panel:#0a2019; --line:#15402f; --grid:#0f3226;
  --fg:#d8f5e6; --dim:#86b3a0; --green:#3cf08e; --amber:#ffb53d; --red:#ff5b4f;
  --cyan:#5fd4ff; --violet:#c79bff;
  --mono:Consolas,"Cascadia Mono","Lucida Console","DejaVu Sans Mono",monospace;
  --sans:"Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);font-family:var(--sans);font-size:20px;line-height:1.45}
body{background:
  radial-gradient(ellipse at 85% -10%,rgba(60,240,142,.10),transparent 55%),
  repeating-linear-gradient(0deg,transparent 0 39px,rgba(60,240,142,.035) 39px 40px),
  repeating-linear-gradient(90deg,transparent 0 39px,rgba(60,240,142,.035) 39px 40px),var(--bg)}
.mono{font-family:var(--mono)}
header{display:flex;align-items:center;gap:18px;padding:12px 26px;border-bottom:1px solid var(--line);background:rgba(3,16,12,.92);position:sticky;top:0;z-index:5}
.brand{font-family:var(--mono);letter-spacing:.12em;color:var(--green);font-size:15px}
.brand b{display:block;color:var(--fg);font-size:21px;letter-spacing:.04em;font-family:var(--sans)}
.spacer{flex:1}
.counter{font-family:var(--mono);color:var(--dim);font-size:17px}
.btn{font:inherit;font-size:18px;background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:9px 18px;cursor:pointer}
.btn:hover,.btn:focus-visible{border-color:var(--green);outline:none;box-shadow:0 0 0 2px rgba(60,240,142,.25)}
.btn[disabled]{opacity:.35;cursor:default}
.btn.primary{background:#0f3a26;border-color:var(--green);color:var(--green)}
.progress{height:5px;background:var(--grid)}
.progress i{display:block;height:100%;background:linear-gradient(90deg,var(--green),var(--amber));width:0;transition:width .35s}
/* radar */
.radar{position:relative;width:52px;height:52px;border-radius:50%;flex:none;
  background:repeating-radial-gradient(circle,transparent 0 9px,rgba(60,240,142,.45) 9px 10px),#04140e;
  border:1px solid var(--green);overflow:hidden}
.radar::before{content:"";position:absolute;inset:0;background:linear-gradient(var(--green),var(--green)) center/1px 100% no-repeat,linear-gradient(var(--green),var(--green)) center/100% 1px no-repeat;opacity:.35}
.radar::after{content:"";position:absolute;inset:0;border-radius:50%;background:conic-gradient(from 0deg,rgba(60,240,142,.75),rgba(60,240,142,0) 70deg,transparent 360deg);animation:sweep 3.2s linear infinite}
.radar.big{width:330px;height:330px;background:repeating-radial-gradient(circle,transparent 0 40px,rgba(60,240,142,.28) 40px 41px),#04140e}
.blip{position:absolute;width:9px;height:9px;border-radius:50%;background:var(--amber);box-shadow:0 0 12px var(--amber);animation:blink 3.2s infinite}
@keyframes sweep{to{transform:rotate(360deg)}}
@keyframes blink{0%,100%{opacity:.25}10%{opacity:1}}
@media (prefers-reduced-motion:reduce){.radar::after,.blip{animation:none}}
/* layout */
.wrap{display:flex;min-height:calc(100vh - 140px)}
nav#index{width:300px;flex:none;border-right:1px solid var(--line);padding:14px 10px;background:rgba(7,26,20,.75);font-size:16px}
nav#index.hidden{display:none}
nav#index a{display:flex;gap:10px;padding:8px 10px;border-radius:6px;color:var(--dim);text-decoration:none;cursor:pointer}
nav#index a .n{font-family:var(--mono);color:var(--green);min-width:24px}
nav#index a.on{background:var(--panel);color:var(--fg);border-left:3px solid var(--amber)}
nav#index a:hover{color:var(--fg)}
main{flex:1;padding:26px 40px 30px;max-width:1500px}
footer{display:flex;align-items:center;gap:14px;padding:12px 26px;border-top:1px solid var(--line);background:rgba(3,16,12,.92);position:sticky;bottom:0}
.keys{color:var(--dim);font-size:15px;font-family:var(--mono)}
/* type */
.kicker{font-family:var(--mono);color:var(--amber);letter-spacing:.14em;font-size:16px;text-transform:uppercase}
h1{font-size:44px;line-height:1.12;margin:6px 0 10px}
h2{font-size:26px;margin:22px 0 10px;color:var(--green);font-weight:600}
h3{font-size:21px;margin:0 0 8px}
p.lead{font-size:23px;color:var(--fg);max-width:1100px;margin:6px 0 14px}
.dim{color:var(--dim)}
.small{font-size:16px}
.grid{display:grid;gap:16px}
.g2{grid-template-columns:repeat(2,minmax(0,1fr))}.g3{grid-template-columns:repeat(3,minmax(0,1fr))}.g4{grid-template-columns:repeat(4,minmax(0,1fr))}
@media (max-width:1100px){.g3,.g4{grid-template-columns:repeat(2,minmax(0,1fr))}nav#index{display:none}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card.hl{border-color:var(--green);box-shadow:0 0 0 1px rgba(60,240,142,.25) inset}
.card.warn{border-color:var(--amber)}
.card.bad{border-color:var(--red)}
.big{font-family:var(--mono);font-size:42px;font-weight:700;line-height:1.05}
.chip{display:inline-block;font-family:var(--mono);font-size:14px;padding:1px 8px;border-radius:999px;border:1px solid;margin:2px 4px 2px 0;white-space:nowrap}
.src-data{color:var(--green);border-color:var(--green);background:rgba(60,240,142,.08)}
.src-estimated{color:var(--cyan);border-color:var(--cyan);background:rgba(95,212,255,.08)}
.src-assumed{color:var(--amber);border-color:var(--amber);background:rgba(255,181,61,.08)}
.src-synthetic{color:var(--violet);border-color:var(--violet);background:rgba(199,155,255,.08)}
.src-brief{color:#ffd9a0;border-color:#a8763a;background:rgba(168,118,58,.15)}
.ok{color:var(--green)}.no{color:var(--red)}.mid{color:var(--amber)}
.tag{font-family:var(--mono);font-size:14px;color:var(--dim)}
.pain{display:inline-flex;align-items:center;gap:6px;font-size:15px;color:#ffd9a0;border:1px dashed #a8763a;border-radius:6px;padding:2px 8px;margin:2px 6px 2px 0}
.cite{font-family:var(--mono);font-size:14px;color:var(--dim)}
.brief-note{font-size:15px;color:#ffd9a0}
table{border-collapse:collapse;width:100%;font-size:17px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--dim);font-weight:500;font-family:var(--mono);font-size:15px}
td.c{text-align:center}
.cell{cursor:pointer;font-family:var(--mono);font-weight:700;border-radius:4px}
.cell.pass{color:var(--green)}.cell.fail{color:#fff;background:rgba(255,91,79,.35)}
.cell.sel{outline:2px solid var(--amber)}
.agent{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.agent svg{width:38px;height:38px;flex:none}
.bubble{background:var(--bg2);border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin:6px 0;font-size:17px}
.bubble.veto{border-color:rgba(255,91,79,.6)}
.score{font-family:var(--mono);color:var(--amber)}
.tl{border-left:2px solid var(--line);margin-left:10px;padding-left:18px}
.tl .ev{position:relative;padding:4px 0;font-size:16px}
.tl .ev::before{content:"";position:absolute;left:-25px;top:12px;width:10px;height:10px;border-radius:50%;background:var(--green)}
.tl .ev.e-fallback_fired::before,.tl .ev.e-reviewer_verdict.rej::before{background:var(--red)}
.tl .ev.e-agent_message::before{background:var(--cyan)}
.tl .ev.e-rule_check::before{background:var(--amber)}
.stamp{display:inline-block;font-family:var(--mono);font-weight:800;font-size:34px;letter-spacing:.1em;padding:4px 18px;border:4px solid;border-radius:8px;transform:rotate(-3deg)}
.banner{border-radius:10px;padding:14px 18px;font-size:22px;font-weight:600}
.banner.red{background:rgba(255,91,79,.15);border:2px solid var(--red);color:#ffd2ce}
.banner.green{background:rgba(60,240,142,.1);border:2px solid var(--green)}
.tile .big{font-size:52px}
.tile .def{font-size:15px;color:var(--dim);margin-top:6px}
.thesis{font-size:30px;line-height:1.3;font-weight:600;border-left:5px solid var(--green);padding:10px 20px;margin:24px 0;background:rgba(60,240,142,.06)}
.toast{margin-top:10px;font-size:17px;min-height:26px}
.svgbox svg{width:100%;height:auto;display:block}
.legend{font-size:15px;color:var(--dim)}
ul.tight{margin:6px 0;padding-left:22px}ul.tight li{margin:4px 0}
.cand{display:flex;flex-direction:column;gap:4px}
.bar{height:8px;background:var(--grid);border-radius:4px;overflow:hidden}.bar i{display:block;height:100%;background:var(--amber)}
.flow{display:flex;align-items:stretch;gap:10px;flex-wrap:wrap}
.flow .step{flex:1;min-width:150px}
</style>
</head>
<body>
<noscript><p style="padding:30px">This story needs JavaScript enabled (no network access required).</p></noscript>
<header>
  <div class="radar" aria-hidden="true"><span class="blip" style="left:32px;top:14px"></span></div>
  <div class="brand">SRRW SOLUTIONS · DISRUPTION DESK<b>One disrupted arrival, start to finish</b></div>
  <div class="spacer"></div>
  <button class="btn" id="toggleIndex" title="Chapter index (I)">☰ Chapters</button>
  <div class="counter" id="counter"></div>
</header>
<div class="progress"><i id="bar"></i></div>
<div class="wrap">
  <nav id="index" aria-label="Chapter index"></nav>
  <main id="stage" tabindex="-1" aria-live="polite"></main>
</div>
<footer>
  <button class="btn" id="prev">◀ Back</button>
  <button class="btn primary" id="next">Next ▶</button>
  <span class="keys">← → arrow keys · Home/End · I = index</span>
  <div class="spacer"></div>
  <span class="keys" id="foot"></span>
</footer>
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
  ATC:`<svg viewBox="0 0 40 40" fill="none" stroke="#5fd4ff" stroke-width="2"><path d="M14 38 L16 18 H24 L26 38"/><path d="M11 18 H29 L27 11 H13 Z"/><path d="M20 11 V5"/><circle cx="20" cy="4" r="1.6" fill="#5fd4ff"/><path d="M15 28 H25"/></svg>`,
  PILOT:`<svg viewBox="0 0 40 40" fill="none" stroke="#3cf08e" stroke-width="2"><path d="M8 16 Q20 6 32 16 L30 19 H10 Z"/><path d="M17 12 L20 9 L23 12"/><circle cx="20" cy="26" r="7"/><path d="M4 22 L13 24 M36 22 L27 24"/></svg>`,
  GROUND:`<svg viewBox="0 0 40 40" fill="none" stroke="#ffb53d" stroke-width="2"><rect x="5" y="17" width="22" height="11" rx="2"/><path d="M27 21 H33 L36 25 V28 H27"/><circle cx="11" cy="31" r="3"/><circle cx="29" cy="31" r="3"/><path d="M9 17 V11 H19 V17"/></svg>`,
  REVIEW:`<svg viewBox="0 0 40 40" fill="none" stroke="#c79bff" stroke-width="2"><path d="M20 4 L34 9 V19 C34 28 27 34 20 36 C13 34 6 28 6 19 V9 Z"/><path d="M13 20 L18 25 L27 15"/></svg>`,
  HUMAN:`<svg viewBox="0 0 40 40" fill="none" stroke="#d8f5e6" stroke-width="2"><circle cx="20" cy="12" r="6"/><path d="M8 36 C8 26 14 22 20 22 C26 22 32 26 32 36"/><path d="M27 6 L31 2 M31 8 L36 6"/></svg>`,
  PHONE:`<svg viewBox="0 0 40 40" fill="none" stroke="#ffb53d" stroke-width="2"><path d="M10 6 L16 6 L18 14 L14 17 C16 22 18 24 23 26 L26 22 L34 24 L34 30 C34 33 31 35 28 34 C17 31 9 23 6 12 C5 9 7 6 10 6 Z"/></svg>`,
  CODE:`<svg viewBox="0 0 40 40" fill="none" stroke="#3cf08e" stroke-width="2"><rect x="4" y="7" width="32" height="26" rx="3"/><path d="M15 15 L10 20 L15 25 M25 15 L30 20 L25 25 M22 13 L18 27"/></svg>`,
  warn:`<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="#ffb53d" stroke-width="1.6"><path d="M8 2 L15 14 H1 Z"/><path d="M8 6 V10 M8 12 V12.5"/></svg>`,
  slot_shift:`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#5fd4ff" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7 V12 L16 14"/></svg>`,
  hold:`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#ffb53d" stroke-width="2"><rect x="3" y="8" width="18" height="8" rx="4"/><path d="M17 5 L20 8 L17 11"/></svg>`,
  divert:`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#ff5b4f" stroke-width="2"><path d="M4 20 V12 C4 8 8 6 12 6 H20"/><path d="M16 2 L20 6 L16 10"/></svg>`,
  gate_swap:`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#3cf08e" stroke-width="2"><path d="M4 8 H18 L15 5 M20 16 H6 L9 19"/></svg>`,
  ground_hold:`<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#c79bff" stroke-width="2"><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></svg>`,
};
const kindLabel = {slot_shift:"Arrival slot shift", hold:"Airborne hold", divert:"Divert", gate_swap:"Gate swap", ground_hold:"Ground hold at origin"};
const roleView = {ATC:"TRACON traffic manager · sees arrival rate, wake, taxi", PILOT:"Flight crew + dispatch · sees fuel, duty, alternates", GROUND:"Ramp / gate control · sees gates, next legs, connections"};

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
  for (let m=t0; m<=t1; m+=120){ s += `<line x1="${x(m)}" y1="${top-10}" x2="${x(m)}" y2="${Hh-14}" stroke="#15402f"/><text x="${x(m)}" y="${top-16}" fill="#86b3a0" font-size="15" text-anchor="middle" font-family="Consolas,monospace">${hhmm(m)}</text>`; }
  legs.forEach((l,i)=>{
    const y = top + i*rowH + 8;
    const col = l.arr_delay >= 180 ? "#ff5b4f" : "#ffb53d";
    s += `<text x="10" y="${y+17}" fill="#d8f5e6" font-size="19" font-family="Consolas,monospace" font-weight="700">${esc(l.flight)}</text>`;
    s += `<text x="10" y="${y+39}" fill="#86b3a0" font-size="15" font-family="Consolas,monospace">${esc(l.origin)}→${esc(l.dest)}</text>`;
    s += `<rect x="${x(l.sched_dep)}" y="${y}" width="${Math.max(3,x(l.sched_arr)-x(l.sched_dep))}" height="16" fill="none" stroke="#86b3a0" stroke-dasharray="5 4" rx="3"/>`;
    s += `<rect x="${x(l.act_dep)}" y="${y+22}" width="${Math.max(3,x(l.act_arr)-x(l.act_dep))}" height="18" fill="${col}" opacity=".85" rx="3"/>`;
    s += `<line x1="${x(l.sched_arr)}" y1="${y+8}" x2="${x(l.act_arr)}" y2="${y+31}" stroke="${col}" stroke-width="1.5" stroke-dasharray="3 3"/>`;
    s += `<text x="${x(l.act_arr)+8}" y="${y+37}" fill="${col}" font-size="20" font-weight="700" font-family="Consolas,monospace">+${l.arr_delay}</text>`;
  });
  return s + `</svg>`;
}

/* ---------- chapters ---------- */
const CH = [];

CH.push({t:"The duty manager's problem", r(){
  const legs = D.tail_day.legs, first = legs[0], last = legs[legs.length-1];
  const tot = legs.reduce((a,l)=>a+l.arr_delay,0);
  const calls = briefFig("calls"), lag = briefFig("lag"), cost = briefFig("cost"), casc = briefFig("cascade");
  return `
  <div class="kicker">Chapter 1 · the user</div>
  <h1>An ops-control duty manager, a storm at the hub, and a phone</h1>
  <p class="lead">When weather cuts a hub's arrival rate, the airline's duty manager has to get three parties who each own one piece of the answer to agree on one plan, today by calling them one after another.</p>
  <div class="flow">
    ${[["PHONE","Call 1 · TRACON / TMU","arrival slot, holding, arrival-rate cap"],["PILOT","Call 2 · Crew via dispatch","fuel, alternates, duty time (VHF / ACARS)"],["GROUND","Call 3 · Ramp / gate control","gate, ground crew, next departure"],["PHONE","Call 4… · back to TRACON","when crew or ramp says no, start again"]]
      .map(([ic,a,b])=>`<div class="card step"><div class="agent">${ICON[ic]}<h3>${a}</h3></div><div class="dim small">${b}</div></div>`).join("")}
  </div>
  <p class="small">${pain("phone")}${pain("ramp")}${pain("atc")}</p>
  <div class="grid g3" style="margin-top:8px">
    ${[calls,lag,cost].filter(Boolean).map(b=>`<div class="card"><div class="big mid">${esc(b.figure)}</div><div>${esc(b.label)}</div><div style="margin-top:6px">${brief()}</div><div class="cite">${esc(b.cite)}</div></div>`).join("")}
  </div>
  <h2>While the calls go on, the delay rides the aircraft all day: ${esc(D.tail_day.tail)}, ${esc(D.tail_day.date)}</h2>
  <div class="card svgbox">${cascadeSVG(legs)}
    <div class="legend">dashed outline = scheduled · filled bar = actual (scheduled + reported delay) · local times · source: data/flights.csv ${chip("data")}</div></div>
  <p class="lead" style="margin-top:12px">${esc(first.flight)} ${esc(first.origin)}→${esc(first.dest)} arrived <b class="mid mono">+${first.arr_delay} min</b> (${first.weather_delay} weather, ${first.late_aircraft_delay} late aircraft). By the last leg, ${esc(last.flight)} ${esc(last.origin)}→${esc(last.dest)}, the same aircraft was <b class="no mono">+${last.arr_delay} min</b>. Arrival delays across its ${legs.length} legs: <span class="mono">${legs.map(l=>l.arr_delay).join(" → ")}</span> (${num(tot)} min in total). ${pain("cascade")}</p>
  ${casc?`<p class="brief-note">${brief()} ${esc(casc.figure)} ${esc(casc.label)}. <span class="cite">${esc(casc.cite)}</span></p>`:""}`;
}});

CH.push({t:"The disruption", r(){
  const f = S.flight;
  const painFor = {fuel_reserve_min:"fuel", crew_duty_remaining_min:"duty", nominal_aar:"atc", dest_disruption:"atc"};
  const labels = {dest_disruption:"Delayed arrivals at destination, that hour", taxi_congestion:"Taxi congestion index", wake_category:"Wake category", fuel_reserve_min:"Fuel beyond planned arrival (min)", crew_duty_remaining_min:"Crew duty left at sched. arrival (min)", nominal_aar:"Nominal arrival rate (per hour)"};
  const facts = S.facts.map(x=>`<div class="card"><div class="tag">${esc(x.key)}</div><div class="big" style="font-size:34px">${esc(x.value)}</div><div>${esc(labels[x.key]||x.key)} ${chip(x.source)}</div><div class="dim small">${esc(x.note)}</div>${painFor[x.key]?`<div>${pain(painFor[x.key])}</div>`:""}</div>`).join("");
  return `
  <div class="kicker">Chapter 2 · the disruption</div>
  <h1>${esc(fl(f))} ${esc(f.ORIGIN_AIRPORT)}→${esc(f.DESTINATION_AIRPORT)}, ${esc(f.date)}: flying into the storm</h1>
  <p class="lead">One row of the US DOT 2015 file (row ${esc(S.row_index)}) becomes a scenario. Every value carries a source tag, so the duty manager can see what is real and what we had to fill in.</p>
  <div>${chip("data")} from flights.csv / airports.csv ${chip("estimated")} derived from data ${chip("assumed")} our constant, unverified ${chip("synthetic")} seeded stand-in, no real source</div>
  <div class="grid g4" style="margin-top:12px">
    <div class="card"><div class="tag">TAIL_NUMBER</div><div class="big" style="font-size:34px">${esc(f.TAIL_NUMBER)}</div>${chip("data")}</div>
    <div class="card"><div class="tag">SCHEDULED → ACTUAL ARRIVAL</div><div class="big" style="font-size:34px">${hhmmInt(f.SCHEDULED_ARRIVAL)} → ${hhmmInt(f.ARRIVAL_TIME)}</div>${chip("data")}</div>
    <div class="card"><div class="tag">ARRIVAL_DELAY</div><div class="big mid" style="font-size:34px">+${esc(f.ARRIVAL_DELAY)} min</div>${chip("data")}<div class="dim small">WEATHER ${esc(f.WEATHER_DELAY)} · LATE_AIRCRAFT ${esc(f.LATE_AIRCRAFT_DELAY)}</div></div>
    <div class="card"><div class="tag">NEXT LEGS SAME TAIL</div><div class="big" style="font-size:34px">${S.downstream.length}</div>${chip("data")}<div class="dim small">${S.downstream.length?`next: ${esc(S.downstream[0].airline)}${esc(S.downstream[0].flight_number)} ${esc(S.downstream[0].origin)}→${esc(S.downstream[0].destination)}, turn gap ${esc(S.downstream[0].gap_after_actual_arrival_min)} min`:""}</div>${pain("cascade")}</div>
  </div>
  <div class="grid g3" style="margin-top:14px">${facts}
    <div class="card"><div class="tag">gates</div><div class="big" style="font-size:34px">${esc(S.gates.assigned_gate)}</div><div>Assigned gate at ${esc(S.gates.airport)} ${chip(S.gates.source)}</div><div class="dim small">min turnaround ${esc(S.gates.min_turnaround_min)} min ${chip(S.gates.turnaround_source)}</div>${pain("ramp")}</div>
    <div class="card"><div class="tag">connections</div><div class="big" style="font-size:34px">${S.connections.n} flights · ${S.connections.pax} pax</div><div>Onward connections at risk ${chip(S.connections.source)}</div><div class="dim small">tightest leaves ${esc(S.connections.first_min_after)} min after arrival</div></div>
    <div class="card"><div class="tag">alternates</div><div class="big" style="font-size:30px">${S.alternates.map(a=>esc(a.iata)).join(" · ")}</div><div>Nearest alternates ${chip("data")}</div><div class="dim small">${S.alternates.map(a=>`${esc(a.iata)} ${num(a.distance_nm,1)} nm`).join(" · ")} (airports.csv lat/long)</div></div>
  </div>`;
}});

CH.push({t:"The menu", r(){
  const maxK = Math.max(...S.candidates.map(c=>c.est_knock_on_min));
  return `
  <div class="kicker">Chapter 3 · the menu</div>
  <h1>Code writes the menu: ${S.candidates.length} options, no free-text plans</h1>
  <p class="lead">The agents may only rank, accept or veto options from this fixed list. Every delay and knock-on number below is a deterministic model estimate, not an LLM guess and not a measured outcome.</p>
  <div class="grid g4">${S.candidates.map(c=>`<div class="card cand">
    <div class="agent" style="margin:0">${ICON[c.kind]||""}<span class="mono" style="font-size:22px;font-weight:700">${esc(c.candidate_id)}</span></div>
    <div class="dim small">${esc(kindLabel[c.kind]||c.kind)}</div>
    <div class="mono">delay <b class="${c.est_delay_min<0?"ok":"mid"}">${signed(c.est_delay_min)} min</b></div>
    <div class="mono small">knock-on ${num(c.est_knock_on_min,1)} min</div>
    <div class="bar"><i style="width:${(c.est_knock_on_min/maxK*100).toFixed(1)}%"></i></div></div>`).join("")}</div>
  <p class="small dim" style="margin-top:12px">Knock-on = estimated added delay carried into the aircraft's later legs that day (model estimate). ${pain("cascade")}</p>`;
}});

function agentCard(m, run){
  const top = m.ranking.slice(0,3);
  return `<div class="card">
    <div class="agent">${ICON[m.agent]}<div><h3 style="margin:0">${esc(m.agent)}</h3><div class="dim small">${esc(roleView[m.agent]||"")}</div></div></div>
    <div class="small">Accepts <b class="mono">${m.acceptable.length}/${run.candidates.length}</b>: ${m.acceptable.map(a=>`<span class="chip src-data">${esc(a)}</span>`).join("")}</div>
    ${top.map((r,i)=>`<div class="bubble"><span class="mono">#${i+1} <b>${esc(r.candidate_id)}</b></span> <span class="score">${esc(r.score)}</span><br>${esc(r.rationale)}<br>${(r.cited_fields||[]).map(c=>`<span class="chip src-estimated">${esc(c)}</span>`).join("")}</div>`).join("")}
    ${m.vetoes.map(v=>`<div class="bubble veto"><span class="no mono">VETO ${esc(v.candidate_id)}</span><br>${esc(v.reason)}<br><span class="chip src-estimated">${esc(v.cited_field)}</span></div>`).join("")}
  </div>`;
}

CH.push({t:"Three agents negotiate", r(){
  const rounds = S.turns.map(t=>`
    <h2>Round ${t.round}${t.invalid?` · <span class="no">${t.invalid} invalid message(s)</span>`:""}</h2>
    <div class="grid g3">${t.messages.map(m=>agentCard(m,S)).join("")}</div>
    <div class="banner green" style="margin-top:12px">All three accept (${t.intersection.length}): <span class="mono">${t.intersection.map(esc).join(" · ")}</span></div>`).join("");
  const liveBlock = L ? `<h2>Same flight, Sonnet agents (${esc(L.meta.model)})</h2>
    <div class="card small">${L.turns.map(t=>`Round ${t.round}: top picks ${t.messages.map(m=>`<b>${esc(m.agent)}</b> <span class="mono">${esc(m.ranking[0]&&m.ranking[0].candidate_id)}</span>`).join(" · ")}; all accept <span class="mono">${t.intersection.map(esc).join(", ")}</span>`).join("<br>")}
    <br>Decision: <b class="mono">${esc(L.recommendation.chosen&&L.recommendation.chosen.candidate_id)}</b> by ${esc(L.recommendation.decided_by)}, reviewer <b class="${verdictCls(L.recommendation.reviewer_verdict)}">${esc(L.recommendation.reviewer_verdict)}</b> · $${num(L.meta.cost_usd,4)} · ${num(L.meta.latency_s,1)} s. A different model, a narrower agreement, the same final pick.</div>` : "";
  return `
  <div class="kicker">Chapter 4 · negotiation (${esc(S.meta.model)})</div>
  <h1>Three separate agents, each seeing only its own domain</h1>
  <p class="lead">Instead of sequential calls, ATC, PILOT and GROUND answer in structured JSON: what they accept, their ranking with the data fields they relied on, and what they veto and why. None of them sees the rule results.</p>
  <p class="small">${pain("phone")}${pain("ramp")}</p>
  ${rounds}${liveBlock}`;
}});

function matrix(run, opts){
  opts = opts || {};
  const chosen = run.recommendation.chosen && run.recommendation.chosen.candidate_id;
  const agreed = new Set((run.turns[run.turns.length-1]||{intersection:[]}).intersection);
  let h = `<table class="mono" id="${opts.id||"mx"}"><tr><th>candidate</th>${run.rule_ids.map(r=>`<th class="c">${esc(r)}<br>${chip(run.rule_source[r])}</th>`).join("")}</tr>`;
  run.candidates.forEach(c=>{
    h += `<tr><td>${chosen===c.candidate_id?"★ ":""}${esc(c.candidate_id)} ${agreed.has(c.candidate_id)?'<span class="chip src-data" title="all three agents accept">∩</span>':""}</td>`;
    run.rule_ids.forEach(r=>{ const x = ruleOf(run,c.candidate_id,r);
      h += x ? `<td class="c cell ${x.passed?"pass":"fail"}" data-c="${esc(c.candidate_id)}" data-r="${esc(r)}">${x.passed?"PASS":"FAIL"}</td>` : `<td class="c dim">–</td>`; });
    h += `</tr>`;
  });
  return h + `</table>`;
}
function topPickList(run, label){
  return `<div class="card"><h3>${esc(label)}</h3>${run.top_picks.map(p=>`<div class="small mono">r${p.round} ${esc(p.agent)} → <b>${esc(p.candidate_id)}</b> ${p.fails.length?`<span class="no">FAIL ${p.fails.map(esc).join(", ")}</span>`:`<span class="ok">passes all</span>`}</div>`).join("")}</div>`;
}
function wireMatrix(run, id, detailId){
  const tbl = document.getElementById(id), det = document.getElementById(detailId);
  if (!tbl) return;
  const show = (c,r) => { const x = ruleOf(run,c,r); if(!x) return;
    tbl.querySelectorAll(".cell").forEach(e=>e.classList.toggle("sel", e.dataset.c===c && e.dataset.r===r));
    det.innerHTML = `<div class="mono"><b>${esc(x.rule_id)}</b> × <b>${esc(x.candidate_id)}</b>: <b class="${x.passed?"ok":"no"}">${x.passed?"PASS":"FAIL"}</b> · observed ${esc(x.observed)} vs threshold ${esc(x.threshold)} ${chip(x.source)}</div><div class="small" style="margin-top:6px">${esc(x.citation)}</div>`; };
  tbl.addEventListener("click", e=>{ const td = e.target.closest(".cell"); if (td) show(td.dataset.c, td.dataset.r); });
  const firstFail = run.rules.find(r=>!r.passed) || run.rules[0];
  if (firstFail) show(firstFail.candidate_id, firstFail.rule_id);
}

CH.push({t:"Code checks the rules", r(){
  const tf = metric("agent_top_pick_rule_fail_rate");
  const byA = ["ATC","PILOT","GROUND"].map(a=>metric("agent_top_pick_rule_fail_rate_"+a)).map((m,i)=>m?`${["ATC","PILOT","GROUND"][i]} ${pct(m.value)} (n=${m.n})`:"").filter(Boolean).join(" · ");
  const nFail = S.rules.filter(r=>!r.passed).length;
  return `
  <div class="kicker">Chapter 5 · the rules engine (deterministic)</div>
  <h1>${S.candidates.length} options × ${S.rule_ids.length} rules = ${S.rules.length} checks, ${nFail} FAIL</h1>
  <p class="lead">Consensus means all three agents accept an option <b>and</b> it passes every rule. Click any cell for the rule's citation and the data it used. ★ = recommended · ∩ = all three agents accept.</p>
  <p class="small">${pain("fuel")}${pain("duty")}${pain("ramp")}${pain("atc")}</p>
  <div class="grid" style="grid-template-columns:minmax(0,1.6fr) minmax(0,1fr)">
    <div class="card">${matrix(S,{id:"mx1"})}</div>
    <div><div class="card hl" id="mx1d"></div>
      <h2>Top picks vs rules they could not see</h2>
      ${topPickList(S, `${fl(S.flight)} · ${S.meta.model}`)}
      ${L?topPickList(L, `${fl(L.flight)} · ${L.meta.model}`):""}
      ${topPickList(F, `${fl(F.flight)} (Chapter 8) · ${F.meta.model}`)}
      ${tf?`<div class="card warn" style="margin-top:10px"><div class="big mid">${pct(tf.value)}</div><div>of ${num(tf.n)} valid agent messages across 200 flights had a top pick that breaks ≥1 rule; every one was caught by the engine.</div><div class="dim small">${esc(byA)}</div></div>`:""}
    </div></div>`;
}, after(){ wireMatrix(S,"mx1","mx1d"); }});

CH.push({t:"The independent reviewer", r(){
  const R = S.reviewer, cid = R.candidate_id;
  const mine = R.re_derived.filter(x=>x.candidate_id===cid);
  const cands = [...new Set(R.re_derived.map(x=>x.candidate_id))];
  const checks = [...new Set(R.re_derived.map(x=>x.check))];
  const cell = (c,k) => { const x = R.re_derived.find(y=>y.candidate_id===c && y.check===k); return x?`<td class="c ${x.passed?"ok":"no"}">${num(x.derived,1)} / ${num(x.threshold,1)}</td>`:"<td></td>"; };
  return `
  <div class="kicker">Chapter 6 · second pair of eyes (deterministic, written separately)</div>
  <h1>The reviewer redoes the fuel, duty and wake arithmetic from the raw scenario</h1>
  <div class="grid" style="grid-template-columns:auto 1fr;align-items:center">
    <div class="agent">${ICON.REVIEW}</div>
    <div><span class="stamp ${verdictCls(R.verdict)}">${esc(R.verdict)}</span> <span class="mono" style="margin-left:16px">on ${esc(cid)}</span></div></div>
  <div class="grid g3" style="margin-top:14px">
    <div class="card"><div class="big">${R.engine_disagreements.length}</div>engine disagreements</div>
    <div class="card"><div class="big">${esc(R.citations_checked)}</div>agent citations checked against the scenario</div>
    <div class="card"><div class="big ${R.cited_mismatches.length?"no":"ok"}">${R.cited_mismatches.length}</div>cited values that did not match the data</div>
  </div>
  <h2>Reviewer notes for ${esc(cid)}</h2>
  ${R.notes.map(n=>`<div class="bubble mono small">${esc(n).replace(/PASS/g,'<b class="ok">PASS</b>').replace(/FAIL/g,'<b class="no">FAIL</b>')}</div>`).join("")}
  <p class="small">${pain("fuel")}${pain("duty")}${pain("atc")}</p>
  <h2>Re-derived for every option (derived / threshold)</h2>
  <div class="card"><table class="mono"><tr><th>candidate</th>${checks.map(k=>`<th class="c">${esc(k)}</th>`).join("")}</tr>
    ${cands.map(c=>`<tr><td>${c===cid?"★ ":""}${esc(c)}</td>${checks.map(k=>cell(c,k)).join("")}</tr>`).join("")}</table>
    <div class="legend">FUEL: minutes of fuel left vs alternate + 45-min reserve · DUTY: minutes of duty left at arrival vs 0 · WAKE: seconds per runway vs wake spacing needed</div></div>`;
}});

function timeline(run){
  return `<div class="tl">${run.timeline.map(e=>`<div class="ev e-${esc(e.event)} ${e.event==="reviewer_verdict"&&/REJECT/.test(e.text)?"rej":""}"><span class="tag">${esc((e.ts||"").slice(11,23))}</span> <b class="mono">${esc(e.event)}</b> <span class="small">${esc(e.text)}</span></div>`).join("")}</div>`;
}

CH.push({t:"The human decides", r(){
  const R = S.recommendation, c = R.chosen || {};
  return `
  <div class="kicker">Chapter 7 · management by exception</div>
  <h1>One recommendation, its reasons, and two buttons</h1>
  <div class="grid" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr)">
    <div class="card hl">
      <div class="agent">${ICON.HUMAN}<h3 style="margin:0">Recommendation for ${esc(fl(S.flight))} · ${esc(S.scenario_id)}</h3></div>
      <div class="big ok" style="font-size:58px">${esc(c.candidate_id)}</div>
      <div class="mono">${esc(kindLabel[c.kind]||c.kind)} · delay ${signed(c.est_delay_min)} min · knock-on ${num(c.est_knock_on_min,1)} min <span class="dim">(model estimates)</span></div>
      <div style="margin-top:10px" class="mono small">decided by <b>${esc(R.decided_by)}</b> in round ${esc(R.rounds_used)} · reviewer <b class="${verdictCls(R.reviewer_verdict)}">${esc(R.reviewer_verdict)}</b> · passes ${S.rule_ids.length}/${S.rule_ids.length} rules · ${esc(S.meta.n_agent_calls)} agent calls · $${num(S.meta.cost_usd,4)} · ${num(S.meta.latency_s,1)} s</div>
      <div class="small" style="margin-top:8px">Ramp gets the revised plan at the same moment as ATC and the crew. ${pain("ramp")}</div>
      <div style="margin-top:16px;display:flex;gap:12px"><button class="btn primary" id="appr">✔ Approve</button><button class="btn" id="rej" style="border-color:var(--red);color:var(--red)">✖ Reject</button></div>
      <div class="toast" id="toast">human_decision: <b class="mono">${esc(R.human_decision)}</b></div>
      <div class="dim small">Illustrative only: these buttons are not wired. In the Streamlit app the click is appended to the log as a <span class="mono">human_decision</span> event. The tool never executes anything.</div>
    </div>
    <div class="card"><h3>Consensus log: ${esc(S.scenario_id)}.jsonl</h3>${timeline(S)}<div class="legend">Append-only, timestamped. ${S.rules.length} rule_check events are collapsed into one line.</div></div>
  </div>`;
}, after(){
  const t = document.getElementById("toast");
  const say = d => { t.innerHTML = `<span class="mid">Illustrative:</span> would append <span class="mono">{"event":"human_decision","decision":"${d}"}</span> to the log. Nothing is executed.`; };
  document.getElementById("appr").onclick = () => say("approve");
  document.getElementById("rej").onclick = () => say("reject");
}});

CH.push({t:"When nothing is safe", r(){
  const f = F.flight, fd = D.failure_doc;
  const duty = F.facts.find(x=>x.key==="crew_duty_remaining_min");
  const dutyRows = F.candidates.map(c=>({c, r: ruleOf(F,c.candidate_id,"R-DUTY-01"), other: failsOf(F,c.candidate_id).filter(x=>x!=="R-DUTY-01")}));
  const allFailDuty = dutyRows.every(x=>x.r && !x.r.passed);
  return `
  <div class="kicker">Chapter 8 · the honest failure</div>
  <h1>${esc(fl(f))} ${esc(f.ORIGIN_AIRPORT)}→${esc(f.DESTINATION_AIRPORT)}, ${esc(f.date)}: every option times out the crew</h1>
  <div class="banner red">No option passes engine and reviewer: escalate to the duty manager. Reviewer <b>${esc(F.reviewer.verdict)}</b> · fallback reason <span class="mono">${esc(F.fallback.reason)}</span> · eligible ${esc(F.fallback.n_eligible)} · decided by ${esc(F.recommendation.decided_by)}</div>
  <div class="grid g3" style="margin-top:14px">
    <div class="card"><div class="tag">ARRIVAL_DELAY</div><div class="big no">+${esc(f.ARRIVAL_DELAY)}</div>${chip("data")} <span class="dim small">weather ${esc(f.WEATHER_DELAY)}</span></div>
    <div class="card"><div class="tag">crew_duty_remaining_min</div><div class="big mid">${esc(duty&&duty.value)}</div>${chip(duty&&duty.source)}<div class="dim small">${esc(duty&&duty.note)}</div></div>
    <div class="card"><div class="tag">AGENTS</div>${F.turns.map(t=>`<div class="small">Round ${t.round}: ${t.intersection.length} options all three accept; top picks ${t.messages.map(m=>`${esc(m.agent)} <span class="mono">${esc(m.ranking[0]&&m.ranking[0].candidate_id)}</span>`).join(", ")}</div>`).join("")}<div class="dim small">${F.meta.n_agent_calls} calls · $${num(F.meta.cost_usd,4)} · ${num(F.meta.latency_s,1)} s</div></div>
  </div>
  <div class="grid g2" style="margin-top:6px">
    <div class="card"><h3>R-DUTY-01 on every option ${allFailDuty?'<span class="no">(all FAIL)</span>':""} ${pain("duty")}</h3>
      <table class="mono small"><tr><th>candidate</th><th>duty left at arrival (min)</th><th>other fails</th></tr>
      ${dutyRows.map(x=>`<tr><td>${esc(x.c.candidate_id)}</td><td class="${x.r&&x.r.passed?"ok":"no"}">${x.r?num(x.r.observed,1):"–"}</td><td>${x.other.map(esc).join(", ")}</td></tr>`).join("")}</table>
      <div class="small" style="margin-top:6px">${esc((dutyRows[0]&&dutyRows[0].r||{}).citation||"")}</div></div>
    <div>
      <div class="card"><h3>Reviewer</h3>${F.reviewer.notes.map(n=>`<div class="bubble mono small">${esc(n)}</div>`).join("")}</div>
      <div class="card warn" style="margin-top:12px"><h3>The bug this case exposed in our own reviewer (fixed)</h3>
        <div class="small">On the first run${fd.bug_commit?` (commit <span class="mono">${esc(fd.bug_commit)}</span>)`:""}, the reviewer's own duty check passed every option: it computed <span class="mono">${esc(fd.bug_example||"duty − added")}</span>, subtracting only the option's added delay and forgetting the delay already incurred${fd.bug_disagreements?`, which showed up as ${esc(fd.bug_disagreements)} engine disagreements`:""}. The outcome was still safe because nothing could be picked, but the "independent" check had not caught it on its own.
        ${fd.fix_commit?`Commit <span class="mono">${esc(fd.fix_commit)}</span>`:"The fix"} applies duty − incurred − added${fd.fix_example?` (<span class="mono">${esc(fd.fix_example)}</span>)`:""}. Reviewer-engine disagreement over 200 flights fell${fd.disagree_before_pct?` from ${esc(fd.disagree_before_pct)}%`:""} to ${pct(metric("reviewer_engine_disagreement_rate").value)}.</div>
        <div class="cite">source: docs/failure_case.md; current rate: eval/results/summary.csv</div></div>
      <div class="card" style="margin-top:12px"><h3>Honest caveat</h3><div class="small">The deciding value is ${chip(duty&&duty.source)}: we have no real crew rosters, so this may be a crew shortage that does not exist. The source tag says so, and the human makes the call.</div></div>
    </div>
  </div>
  <h2>Its consensus log</h2><div class="card">${timeline(F)}</div>`;
}});

CH.push({t:"The evidence", r(){
  const tiles = [];
  const add = (big, title, m, extra, cls) => { if (!m) return; tiles.push(`<div class="card tile"><div class="big ${cls||""}">${big}</div><div><b>${title}</b></div><div class="def">n = ${esc(m.n)} · ${esc(m.definition)}${m.note?` · ${esc(m.note)}`:""}${extra?`<br>${extra}`:""}</div></div>`); };
  const c = metric("consensus_rate"); add(c&&pct(c.value), "Consensus rate (agents agree on a rule-passing option)", c, null, "ok");
  const tf = metric("agent_top_pick_rule_fail_rate"); add(tf&&pct(tf.value), "Agent top picks breaking a rule they could not see", tf, "every one caught by the rules engine", "mid");
  const ex = metric("consensus_excluded_by_rules_rate"); add(ex&&pct(ex.value), "Agreed options all excluded by the rules", ex);
  const ph = PS.haiku, pn = PS.none;
  if (ph) tiles.push(`<div class="card tile"><div class="big no">${ph.escalated} / ${ph.n}</div><div><b>Escalated to a human: no legal option</b></div><div class="def">n = ${ph.n} · rows with no recommended candidate (per_scenario.csv, agents)${pn?` · solver-only: ${pn.escalated} / ${pn.n}`:""}</div></div>`);
  const a = metric("reviewer_APPROVE_rate"), mo = metric("reviewer_MODIFY_rate"), rj = metric("reviewer_REJECT_rate");
  if (a&&mo&&rj) tiles.push(`<div class="card tile"><div class="big"><span class="ok">${pct(a.value,1)}</span> <span class="mid">${pct(mo.value,1)}</span> <span class="no">${pct(rj.value,1)}</span></div><div><b>Reviewer APPROVE / MODIFY / REJECT</b></div><div class="def">n = ${esc(a.n)} · ${esc(a.definition)}</div></div>`);
  const si = metric("schema_invalid_rate"); add(si&&pct(si.value,2), "Invalid agent replies (rejected, logged, never repaired)", si);
  const fi = metric("fallback_rate_invalid_message"); add(fi&&pct(fi.value), "Fallback after an invalid reply", fi);
  const rd = metric("reviewer_engine_disagreement_rate"); add(rd&&pct(rd.value,2), "Reviewer-engine disagreement", rd);
  const cm = metric("cited_value_mismatch_rate"); add(cm&&pct(cm.value,2), "Agent cited a value that does not match the data", cm);
  const sp = metric("agents_vs_solver_same_pick_rate"); add(sp&&pct(sp.value), "Agents + rules vs solver-only: same pick", sp);
  const cu = metric("cost_usd_mean"), ct = metric("cost_usd_total"); add(cu&&("$"+num(cu.value,4)), "Cost per decision", cu, ct?`whole run $${num(ct.value,2)}`:null);
  const lm = metric("latency_s_mean"), lp = metric("latency_s_p95"); add(lm&&(num(lm.value,0)+" s"), "Latency per decision (mean)", lm, lp?`p95 ${num(lp.value,0)} s (three sequential agent calls)`:null);
  const ad = DATA.actual_delay_mean, ac = DATA.actual_chain_mean;
  return `
  <div class="kicker">Chapter 9 · the evidence</div>
  <h1>200 real delayed flights, the same pipeline, every number with its n</h1>
  <p class="lead">Seeded sample of US DOT 2015 delayed arrivals, run with ${esc(S.meta.model)} agents and again solver-only. Values read from eval/results/summary.csv and per_scenario.csv at build time.</p>
  <div class="grid g3">${tiles.join("")}</div>
  ${ad?`<p class="small dim" style="margin-top:12px">For context (data): mean real arrival delay in the sample ${num(ad.value,1)} min${ac?`; mean ${num(ac.value,1)} min of delay on the same aircraft's later delayed legs that day (${esc(ac.note)})`:""}. Our modelled delays are estimates and are not compared like-for-like with these; no saving is claimed as measured.</p>`:""}`;
}});

CH.push({t:"Real vs assumed, and what's next", r(){
  const groups = {data:[],estimated:[],assumed:[],synthetic:[]};
  S.facts.forEach(x=>{ (groups[x.source]=groups[x.source]||[]).push(`<span class="mono">${esc(x.key)}</span>`); });
  groups.data.push("flight times &amp; delays, later legs, delayed arrivals per hour (flights.csv)", "alternates (airports.csv)");
  groups.synthetic.push(`gates at ${esc(S.gates.airport)}`);
  groups.assumed.push(`turnaround ${esc(S.gates.min_turnaround_min)} min`);
  Object.entries(S.rule_source).forEach(([r,src])=>{ if (groups[src]) groups[src].push(`rule basis <span class="mono">${esc(r)}</span>`); });
  if (S.connections.source && groups[S.connections.source]) groups[S.connections.source].push("connecting passengers");
  return `
  <div class="kicker">Chapter 10 · honesty and the road to production</div>
  <h1>What is real, what is assumed, and what would make it production-ready</h1>
  <div class="grid g4">${Object.entries(groups).map(([k,v])=>`<div class="card"><h3>${chip(k)}</h3><ul class="tight small">${v.map(x=>`<li>${x}</li>`).join("")}</ul></div>`).join("")}</div>
  <div class="grid g2" style="margin-top:14px">
    <div class="card"><h3>To be production-ready</h3><ul class="tight">
      <li>Real crew tracking (report time, legs flown, rest) instead of synthetic duty state: the main driver of escalations. ${pain("duty")}</li>
      <li>Crew-swap and tail-swap options; the Part 117.19 extension as an explicit "requires PIC agreement" choice.</li>
      <li>Aircraft type from the FAA registry for wake class; verified runway configurations and arrival rates.</li>
      <li>A live, read-only feed from the airline's gate system, so the ramp sees the same plan as ATC and crew. ${pain("ramp")}</li>
      <li>Fuel on board from dispatch instead of an estimate from distance and air time. ${pain("fuel")}</li>
      <li>Shadow-mode trial alongside a real duty manager before any reliance.</li></ul></div>
    <div class="card"><h3>What does not change</h3><ul class="tight">
      <li>LLMs only rank, veto and explain; they never compute legality.</li>
      <li>Every rule result cites its rule ID, the data field and its source tag.</li>
      <li>A deterministic fallback and an independent reviewer sit behind every pick.</li>
      <li>The tool recommends; a human approves. It never executes.</li></ul>
      <div class="brief-note small" style="margin-top:8px">Industry figures in this story (${D.brief.map(b=>esc(b.figure)).join(", ")}) are ${brief()}, not our measurements.</div></div>
  </div>
  <div class="thesis">LLMs negotiate, code decides, every decision traces to a rule and a data field, and a human approves.</div>
  <div style="display:flex;justify-content:center"><div class="radar big" aria-hidden="true"><span class="blip" style="left:210px;top:90px"></span><span class="blip" style="left:90px;top:200px;animation-delay:1.1s"></span><span class="blip" style="left:240px;top:230px;animation-delay:2s"></span></div></div>`;
}});

/* ---------- navigation ---------- */
let cur = 0;
const stage = document.getElementById("stage"), nav = document.getElementById("index");
nav.innerHTML = CH.map((c,i)=>`<a data-i="${i}"><span class="n">${String(i+1).padStart(2,"0")}</span><span>${esc(c.t)}</span></a>`).join("");
nav.addEventListener("click", e=>{ const a = e.target.closest("a"); if (a) go(+a.dataset.i); });
function go(i){
  cur = Math.max(0, Math.min(CH.length-1, i));
  try { stage.innerHTML = CH[cur].r(); if (CH[cur].after) CH[cur].after(); }
  catch(err){ stage.innerHTML = `<h1>Chapter ${cur+1}</h1><p class="no">Could not render this chapter: ${esc(err.message)}</p>`; }
  document.getElementById("counter").textContent = `${String(cur+1).padStart(2,"0")} / ${String(CH.length).padStart(2,"0")}`;
  document.getElementById("bar").style.width = ((cur+1)/CH.length*100) + "%";
  document.getElementById("prev").disabled = cur===0;
  document.getElementById("next").disabled = cur===CH.length-1;
  document.getElementById("foot").textContent = CH[cur].t;
  nav.querySelectorAll("a").forEach((a,j)=>a.classList.toggle("on", j===cur));
  if (location.hash !== "#"+(cur+1)) history.replaceState(null, "", "#"+(cur+1));
  window.scrollTo(0,0);
}
document.getElementById("prev").onclick = () => go(cur-1);
document.getElementById("next").onclick = () => go(cur+1);
document.getElementById("toggleIndex").onclick = () => nav.classList.toggle("hidden");
document.addEventListener("keydown", e=>{
  if (e.altKey || e.ctrlKey || e.metaKey) return;
  if (e.key==="ArrowRight"||e.key==="PageDown") { e.preventDefault(); go(cur+1); }
  else if (e.key==="ArrowLeft"||e.key==="PageUp") { e.preventDefault(); go(cur-1); }
  else if (e.key==="Home") go(0);
  else if (e.key==="End") go(CH.length-1);
  else if (e.key==="i"||e.key==="I") nav.classList.toggle("hidden");
});
const h = parseInt((location.hash||"").slice(1),10);
go(isNaN(h) ? 0 : h-1);
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
