"""Generate the SAMPLE run files the UI tests and the UI's empty-state use. Owner: Reine (T2).

    python tests/fixtures/sample_run/make_sample.py

These are hand-authored fixtures in the documented runs/<scenario_id>.json layout
(docs/plan-rohan.md section 3.4) with matching consensus-log .jsonl files (section 3.1 event names).
They are NOT outputs of src/cli.py and NOT real model replies: flight rows follow
data/flights.csv for the N469AA tail on 24 Apr 2015 (docs/briefing.md section 4.5), every other number
(fuel, crew duty, gates, rule results, agent messages, reviewer output) is illustrative.

Three runs:
- 2015-04-24_AA334_N469AA.json : showcase. No consensus in round 1, consensus in round 2,
  reviewer MODIFY because one agent cited a value that does not match the scenario.
- failure_showcase.json         : AA1274 (same tail, last leg). All three agents accept a
  20-minute hold in round 1 and the rules engine passes it, but the independent reviewer
  re-derives the fuel reserve, REJECTs it, and the deterministic fallback takes over.
- 2015-04-24_AA1389_N469AA.json : the PILOT agent's reply fails schema validation twice;
  the message is logged with its raw text and the fallback decides after round 1.
Plus eval/summary.csv + eval/meta.json, a SAMPLE evaluation in the long format of section 3.6.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.schemas import AgentMessage, Candidate, RuleResult, Scenario, Tagged, Turn  # noqa: E402

OUT = Path(__file__).resolve().parent
SGT = timezone(timedelta(hours=8))
RULES = ["R-WAKE-01", "R-FUEL-01", "R-GATE-01", "R-DUTY-01", "R-TURN-01", "R-AAR-01"]
CITATIONS = {
    "R-WAKE-01": ("FAA JO 7110.65 para 5-5-4 (spacing behind assumed Heavy leader)", "assumed"),
    "R-FUEL-01": ("14 CFR 121.639 (engine: final reserve floor)", "estimated"),
    "R-GATE-01": ("synthetic gate model, seed 42", "synthetic"),
    "R-DUTY-01": ("14 CFR Part 117 (FDP remaining)", "synthetic"),
    "R-TURN-01": ("assumed: airline minimum turnaround, narrowbody 45 min", "assumed"),
    "R-AAR-01": ("assumed: FAA published arrival rate, disruption cap", "assumed"),
}


def hhmm(t: str) -> int:
    return int(t[:2]) * 60 + int(t[2:])


def flight_row(**kw) -> dict:
    base = {k: 0 for k in ("AIR_SYSTEM_DELAY", "SECURITY_DELAY", "AIRLINE_DELAY", "DIVERTED",
                           "CANCELLED")}
    base.update({"YEAR": 2015, "MONTH": 4, "DAY": 24, "DAY_OF_WEEK": 5, "AIRLINE": "AA",
                 "TAIL_NUMBER": "N469AA", "CANCELLATION_REASON": None})
    base.update(kw)
    return base


def cand(cid, kind, params, d, k) -> Candidate:
    return Candidate(candidate_id=cid, kind=kind, params=params, est_delay_min=d,
                     est_knock_on_min=k)


def rule_results(cands, table) -> list[RuleResult]:
    """table[rule][cid] = (passed, observed, threshold)"""
    out = []
    for rule in RULES:
        citation, source = CITATIONS[rule]
        for c in cands:
            passed, observed, threshold = table[rule][c.candidate_id]
            out.append(RuleResult(rule_id=rule, candidate_id=c.candidate_id, passed=passed,
                                  observed=observed, threshold=threshold, source=source,
                                  citation=citation))
    return out


def msg(agent, rnd, acceptable, ranking, vetoes) -> AgentMessage:
    return AgentMessage(
        agent=agent, round=rnd, acceptable=acceptable,
        ranking=[{"candidate_id": c, "score": s, "rationale": r, "cited_fields": f}
                 for c, s, r, f in ranking],
        vetoes=[{"candidate_id": c, "reason": r, "cited_field": f} for c, r, f in vetoes],
    )


class Log:
    def __init__(self, scenario_id: str, start: datetime):
        self.sid, self.t, self.events = scenario_id, start, []

    def add(self, event: str, **payload):
        self.t += timedelta(milliseconds=350)
        self.events.append({"ts": self.t.isoformat(timespec="milliseconds"), "event": event,
                            "scenario_id": self.sid, **payload})


def tag_counts(s: Scenario) -> dict:
    counts = {"data": 0, "estimated": 0, "assumed": 0, "synthetic": 0}
    for v in s.__dict__.values():
        if isinstance(v, Tagged):
            counts[v.source] += 1
    return counts


def write_run(fname, s, cands, rules, turns, rec, fallback, reviewer, meta_extra, start,
              calls_cost):
    sid = s.scenario_id
    log = Log(sid, start)
    agents_mode = meta_extra.get("agents", "haiku")
    log.add("run_start", row_index=s.row_index, agents_mode=agents_mode,
            model=meta_extra.get("model"), seed=42,
            flags={"force_deadlock": False, "tamper_rules": False}, git_sha="sample")
    log.add("scenario_built", source_tag_counts=tag_counts(s),
            n_downstream_legs=len(s.downstream_legs), n_alternates=len(s.alternates))
    log.add("candidates_generated", n=len(cands), candidate_ids=[c.candidate_id for c in cands])
    for r in rules:
        log.add("rule_check", **r.model_dump())
    passing = {c.candidate_id for c in cands} - {r.candidate_id for r in rules if not r.passed}
    for t in turns:
        log.add("round_start", round=t.round)
        for m in t.messages:
            tin, tout, cost, lat = calls_cost[(t.round, m.agent)]
            log.add("agent_message", round=t.round, agent=m.agent, acceptable=m.acceptable,
                    vetoes=m.vetoes, top_choice=m.ranking[0]["candidate_id"],
                    n_ranked=len(m.ranking), tokens_in=tin, tokens_out=tout, cost_usd=cost,
                    latency_s=lat)
        for inv in t.invalid_messages:
            log.add("message_invalid", **inv)
        if not t.invalid_messages:
            log.add("intersection", round=t.round, acceptable_intersection=t.intersection,
                    rules_pass_intersection=[c for c in t.intersection if c in passing])
    for ev in meta_extra.pop("_events", []):
        log.add(ev.pop("event"), **ev)
    log.add("recommendation", decided_by=rec["decided_by"],
            candidate_id=(rec["chosen"] or {}).get("candidate_id"),
            rounds_used=rec["rounds_used"], reviewer_verdict=rec["reviewer_verdict"])
    tokens_in = sum(v[0] for v in calls_cost.values())
    tokens_out = sum(v[1] for v in calls_cost.values())
    cost = round(sum(v[2] for v in calls_cost.values()), 6)
    latency = round(sum(v[3] for v in calls_cost.values()) + 0.4, 2)
    log.add("run_end", latency_s=latency, cost_usd=cost, tokens_in=tokens_in,
            tokens_out=tokens_out)

    meta = {"scenario_id": sid, "row_index": s.row_index, "agents": agents_mode,
            "model": meta_extra.get("model"), "seed": 42,
            "flags": {"force_deadlock": False, "tamper_rules": False},
            "started_at": start.isoformat(timespec="seconds"), "latency_s": latency,
            "cost_usd": cost, "tokens_in": tokens_in, "tokens_out": tokens_out,
            "git_sha": "sample", "sample_fixture": True}
    run = {"meta": meta, "scenario": s.model_dump(), "candidates": [c.model_dump() for c in cands],
           "rule_results": [r.model_dump() for r in rules],
           "turns": [t.model_dump() for t in turns], "recommendation": rec,
           "fallback": fallback, "reviewer": reviewer}
    (OUT / f"{fname}.json").write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n",
                                      encoding="utf-8", newline="\n")
    with open(OUT / f"{fname}.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for e in log.events:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")


def table_from(cands, spec, default):
    """spec[rule][cid] overrides; default(rule, cid) -> (passed, observed, threshold)."""
    return {rule: {c.candidate_id: spec.get(rule, {}).get(c.candidate_id) or default(rule, c)
                   for c in cands} for rule in RULES}


# ---------------------------------------------------------------------------------------------
# 1. Showcase: AA334 MFE -> DFW, consensus in round 2, reviewer MODIFY
# ---------------------------------------------------------------------------------------------


def showcase():
    s = Scenario(
        scenario_id="2015-04-24_AA334_N469AA", row_index=131072,
        flight=flight_row(FLIGHT_NUMBER=334, ORIGIN_AIRPORT="MFE", DESTINATION_AIRPORT="DFW",
                          SCHEDULED_DEPARTURE=hhmm("1116"), DEPARTURE_TIME=hhmm("1310"),
                          DEPARTURE_DELAY=114.0, TAXI_OUT=14.0, WHEELS_OFF=hhmm("1324"),
                          SCHEDULED_TIME=99.0, ELAPSED_TIME=86.0, AIR_TIME=64.0, DISTANCE=468,
                          WHEELS_ON=hhmm("1428"), TAXI_IN=8.0, SCHEDULED_ARRIVAL=hhmm("1255"),
                          ARRIVAL_TIME=hhmm("1436"), ARRIVAL_DELAY=101.0,
                          LATE_AIRCRAFT_DELAY=43.0, WEATHER_DELAY=58.0),
        dest_disruption=Tagged(value=14, source="data",
                               note="delayed arrivals at DFW, 12:00-13:00 local (proxy)"),
        taxi_congestion=Tagged(value=1.4, source="data", note="TAXI_IN / DFW median TAXI_IN"),
        downstream_legs=[
            {"AIRLINE": "AA", "FLIGHT_NUMBER": 1389, "ORIGIN_AIRPORT": "DFW",
             "DESTINATION_AIRPORT": "MEM", "SCHEDULED_DEPARTURE": hhmm("1348"),
             "SCHEDULED_ARRIVAL": hhmm("1522"), "DEPARTURE_DELAY": 111.0, "ARRIVAL_DELAY": 102.0},
            {"AIRLINE": "AA", "FLIGHT_NUMBER": 1389, "ORIGIN_AIRPORT": "MEM",
             "DESTINATION_AIRPORT": "DFW", "SCHEDULED_DEPARTURE": hhmm("1602"),
             "SCHEDULED_ARRIVAL": hhmm("1748"), "DEPARTURE_DELAY": 249.0, "ARRIVAL_DELAY": 264.0},
            {"AIRLINE": "AA", "FLIGHT_NUMBER": 1274, "ORIGIN_AIRPORT": "DFW",
             "DESTINATION_AIRPORT": "BWI", "SCHEDULED_DEPARTURE": hhmm("1835"),
             "SCHEDULED_ARRIVAL": hhmm("2245"), "DEPARTURE_DELAY": 288.0, "ARRIVAL_DELAY": 256.0},
        ],
        alternates=[{"iata": "DAL", "distance_nm": 10}, {"iata": "AUS", "distance_nm": 165},
                    {"iata": "IAH", "distance_nm": 196}],
        wake_category=Tagged(value="L", source="assumed",
                             note="FAA registry miss -> airline fleet default (MD-80/737)"),
        fuel_reserve_min=Tagged(value=78, source="estimated",
                                note="distance x typical burn; planned arrival + reserve"),
        crew_duty_remaining_min=Tagged(value=150, source="synthetic",
                                       note="seeded FDP model under Part 117"),
        gates={"assigned": "C21", "free": ["C14", "C30"], "occupied_until": {"C21": hhmm("1450")}},
        connections=[
            {"flight": "AA2211", "dest": "ORD", "pax": 14, "minutes_after_arrival": 70},
            {"flight": "AA1630", "dest": "LGA", "pax": 9, "minutes_after_arrival": 95},
            {"flight": "AA455", "dest": "MIA", "pax": 6, "minutes_after_arrival": 150},
        ],
        nominal_aar=Tagged(value=90, source="assumed", note="FAA published DFW rate, VMC"),
    )
    cands = [
        cand("SLOT-15", "slot_shift", {"shift_min": -15}, 0, 0),
        cand("SLOT+15", "slot_shift", {"shift_min": 15}, 15, 10),
        cand("SLOT+30", "slot_shift", {"shift_min": 30}, 30, 26),
        cand("HOLD20", "hold", {"minutes": 20}, 20, 16),
        cand("HOLD40", "hold", {"minutes": 40}, 40, 35),
        cand("DIVERT_DAL", "divert", {"iata": "DAL"}, 95, 140),
        cand("DIVERT_AUS", "divert", {"iata": "AUS"}, 150, 210),
        cand("GATE_C14", "gate_swap", {"gate": "C14", "extra_taxi_min": 4}, 4, 0),
        cand("GATE_C30", "gate_swap", {"gate": "C30", "extra_taxi_min": 6}, 6, 0),
        cand("GHOLD20", "ground_hold", {"minutes": 20}, 20, 14),
    ]
    extra = {"SLOT-15": 0, "SLOT+15": 15, "SLOT+30": 30, "HOLD20": 20, "HOLD40": 40,
             "DIVERT_DAL": 2, "DIVERT_AUS": 24, "GATE_C14": 0, "GATE_C30": 0, "GHOLD20": 0}
    duty = {"DIVERT_DAL": 62, "DIVERT_AUS": 84}

    def default(rule, c):
        cid = c.candidate_id
        if rule == "R-FUEL-01":
            obs = 78 - extra[cid]
            return (obs >= 45, obs, 45)
        if rule == "R-DUTY-01":
            obs = 150 - duty.get(cid, c.est_delay_min)
            return (obs >= 0, obs, 0)
        if rule == "R-WAKE-01":
            return (True, 5.0, 5.0)
        if rule == "R-GATE-01":
            return (True, "free", "free")
        if rule == "R-TURN-01":
            obs = 58 - c.est_knock_on_min * 0.5
            return (obs >= 45, round(obs, 1), 45)
        return (True, 13, 18)

    rules = rule_results(cands, table_from(cands, {
        "R-AAR-01": {"SLOT-15": (False, 21, 18)},
        "R-GATE-01": {"GATE_C30": (False, "occupied 14:40-15:25", "free")},
        "R-TURN-01": {"DIVERT_DAL": (False, "tail at DAL", "at DFW"),
                      "DIVERT_AUS": (False, "tail at AUS", "at DFW")},
        "R-WAKE-01": {"SLOT-15": (False, 4.1, 5.0)},
    }, default))

    atc1 = msg("ATC", 1, ["SLOT+15", "GHOLD20", "SLOT+30"], [
        ("SLOT+15", 0.9, "A 15-minute shift moves this arrival off the DFW peak with "
                         "dest_disruption=14 against nominal_aar=90.", ["dest_disruption=14",
                                                                        "nominal_aar=90"]),
        ("GHOLD20", 0.85, "Holding at MFE keeps the aircraft out of the DFW stream and off busy "
                          "taxiways.", ["taxi_congestion=1.4"]),
        ("SLOT+30", 0.75, "Regularises the stream but later than needed.", ["dest_disruption=14"]),
        ("GATE_C14", 0.55, "Neutral for the runway; adds a little taxi time when "
                           "taxi_congestion=1.4.", ["taxi_congestion=1.4"]),
        ("SLOT-15", 0.4, "Pulls the flight into the peak hour.", ["dest_disruption=14"]),
        ("GATE_C30", 0.5, "Neutral for the runway, longer taxi.", ["taxi_congestion=1.4"]),
        ("HOLD20", 0.35, "Airborne holding into a disrupted hour.", ["dest_disruption=14"]),
        ("DIVERT_DAL", 0.25, "Re-enters the sector later as a second arrival.", []),
        ("DIVERT_AUS", 0.2, "Removes the flight but adds a later re-entry.", []),
        ("HOLD40", 0.1, "Longest airborne hold during the disruption peak.",
         ["dest_disruption=14"]),
    ], [("HOLD40", "Adds 40 minutes of airborne holding into the disrupted hour.",
         "dest_disruption=14")])
    pilot1 = msg("PILOT", 1, ["GATE_C14", "SLOT+15", "SLOT-15"], [
        ("GATE_C14", 0.85, "No added airborne time and protects the AA2211 connection.",
         ["fuel_reserve_min=78", "connections[0].minutes_after_arrival=70"]),
        ("SLOT-15", 0.8, "Earliest arrival protects the three listed connections.",
         ["connections[0].pax=14"]),
        ("SLOT+15", 0.8, "Small shift; the fuel figure is an estimate so short is better.",
         ["fuel_reserve_min=78", "crew_duty_remaining_min=180"]),
        ("GHOLD20", 0.65, "Waits on the ground at MFE, no airborne burn.",
         ["fuel_reserve_min=78"]),
        ("GATE_C30", 0.6, "Neutral for the flight deck.", []),
        ("SLOT+30", 0.5, "Longer day for the crew.", ["crew_duty_remaining_min=150"]),
        ("HOLD20", 0.35, "Holding near weather with WEATHER_DELAY present.",
         ["flight.WEATHER_DELAY=58"]),
        ("DIVERT_DAL", 0.3, "Near alternate but all connections are lost.",
         ["alternates[0].distance_nm=10"]),
        ("DIVERT_AUS", 0.1, "Far alternate, connections lost.", ["alternates[1].distance_nm=165"]),
        ("HOLD40", 0.05, "Long hold draws on an estimated reserve.", ["fuel_reserve_min=78"]),
    ], [("HOLD40", "A 40-minute hold draws on fuel_reserve_min=78, an estimate.",
         "fuel_reserve_min=78"),
        ("DIVERT_AUS", "Far alternate and all three connections lost.",
         "alternates[1].distance_nm=165")])
    ground1 = msg("GROUND", 1, ["GATE_C14", "SLOT-15", "GHOLD20"], [
        ("GATE_C14", 0.95, "C14 is free (synthetic gate model) and keeps the AA1389 turn.",
         ["gates.free[0]=C14", "downstream_legs[0].FLIGHT_NUMBER=1389"]),
        ("SLOT-15", 0.8, "Earlier arrival protects the downstream turnaround.",
         ["downstream_legs[0].SCHEDULED_DEPARTURE=828"]),
        ("GHOLD20", 0.7, "Low knock-on for the ramp crew.", ["taxi_congestion=1.4"]),
        ("SLOT+15", 0.65, "Modest knock-on on the downstream legs.",
         ["downstream_legs[0].SCHEDULED_DEPARTURE=828"]),
        ("GATE_C30", 0.6, "Free in the gate model but further from the turn.",
         ["gates.free[1]=C30"]),
        ("SLOT+30", 0.45, "Pushes the turnaround towards the shift change.", []),
        ("HOLD20", 0.4, "Moderate knock-on.", []),
        ("HOLD40", 0.2, "High est_knock_on_min on a contested gate.", ["gates.assigned=C21"]),
        ("DIVERT_DAL", 0.15, "Strands the tail away from the hub.",
         ["downstream_legs[0].FLIGHT_NUMBER=1389"]),
        ("DIVERT_AUS", 0.05, "Strands the tail, gate plan and three downstream legs.",
         ["downstream_legs[0].FLIGHT_NUMBER=1389"]),
    ], [("DIVERT_AUS", "Strands the tail; three downstream legs depend on it.",
         "downstream_legs[0].FLIGHT_NUMBER=1389"),
        ("DIVERT_DAL", "Tail ends up off-hub before AA1389.",
         "downstream_legs[0].FLIGHT_NUMBER=1389")])

    def widen(m, add, notes):
        ranking = []
        for r in m.ranking:
            r = dict(r)
            if r["candidate_id"] in notes:
                r["rationale"], r["cited_fields"] = notes[r["candidate_id"]]
            ranking.append(r)
        return AgentMessage(agent=m.agent, round=2, acceptable=m.acceptable + add,
                            ranking=ranking, vetoes=m.vetoes)

    atc2 = widen(atc1, ["GATE_C14"], {"GATE_C14": (
        "Concession: tolerable for the runway; taxi pressure is moderate at "
        "taxi_congestion=1.4.", ["taxi_congestion=1.4"])})
    pilot2 = widen(pilot1, ["GHOLD20"], {"GHOLD20": (
        "Concession: waiting at MFE adds no airborne time against fuel_reserve_min=78.",
        ["fuel_reserve_min=78"])})
    ground2 = widen(ground1, ["SLOT+15"], {"SLOT+15": (
        "Concession: the AA1389 turn still works with a 15-minute shift.",
        ["downstream_legs[0].SCHEDULED_DEPARTURE=828"])})
    turns = [
        Turn(round=1, messages=[atc1, pilot1, ground1], invalid_messages=[], intersection=[]),
        Turn(round=2, messages=[atc2, pilot2, ground2], invalid_messages=[],
             intersection=["SLOT+15", "GHOLD20", "GATE_C14"]),
    ]
    chosen = next(c for c in cands if c.candidate_id == "SLOT+15")
    notes = [
        "FUEL re-derived: SLOT+15 adds 15 airborne min; 78-15=63 >= 45 min; "
        "fuel_reserve_min=78 (estimated) -> PASS [14 CFR 121.639]",
        "DUTY re-derived: SLOT+15 adds 15 min; 150-15=135 >= 0; crew_duty_remaining_min=150 "
        "(synthetic) -> PASS [14 CFR Part 117]",
        "WAKE re-derived: behind assumed Heavy leader, L needs 5 NM; available spacing at "
        "effective rate 76/h is above it -> PASS [FAA JO 7110.65 5-5-4]",
        "CITED: PILOT ranked SLOT+15 citing crew_duty_remaining_min=180; scenario has 150 "
        "(synthetic) -> mismatch",
    ]
    reviewer = {
        "verdict": "MODIFY", "notes": notes,
        "re_derived": [
            {"check": "FUEL", "candidate_id": "SLOT+15", "derived": 63, "threshold": 45,
             "passed": True, "citation": "14 CFR 121.639"},
            {"check": "DUTY", "candidate_id": "SLOT+15", "derived": 135, "threshold": 0,
             "passed": True, "citation": "14 CFR Part 117"},
            {"check": "WAKE", "candidate_id": "SLOT+15", "derived": 5.0, "threshold": 5.0,
             "passed": True, "citation": "FAA JO 7110.65 para 5-5-4"},
        ],
        "cited_mismatches": [
            {"agent": "PILOT", "round": 2, "candidate_id": "SLOT+15",
             "path": "crew_duty_remaining_min", "cited": "180", "actual": 150, "tolerance": 3.0},
        ],
        "engine_disagreements": [],
    }
    rec = {"scenario_id": s.scenario_id, "chosen": chosen.model_dump(),
           "decided_by": "consensus", "rounds_used": 2,
           "rule_results": [r.model_dump() for r in rules if r.candidate_id == "SLOT+15"],
           "reviewer_verdict": "MODIFY", "reviewer_notes": notes, "human_decision": "pending",
           "log_path": f"runs/{s.scenario_id}.jsonl", "fallback": None,
           "reviewer_detail": reviewer}
    fallback = {"fired": False, "reason": None, "objective": None, "n_eligible": None,
                "excluded": []}
    calls = {(1, "ATC"): (1890, 610, 0.000494, 2.9), (1, "PILOT"): (2050, 655, 0.000533, 3.2),
             (1, "GROUND"): (1980, 640, 0.000518, 3.0), (2, "ATC"): (2140, 630, 0.000529, 3.1),
             (2, "PILOT"): (2310, 668, 0.000565, 3.4), (2, "GROUND"): (2235, 652, 0.00055, 3.2)}
    write_run(s.scenario_id, s, cands, rules, turns, rec, fallback, reviewer,
              {"agents": "haiku", "model": "claude-haiku-5-5",
               "_events": [{"event": "consensus", "round": 2, "candidate_id": "SLOT+15",
                            "summed_score": 2.35,
                            "per_agent_scores": {"ATC": 0.9, "PILOT": 0.8, "GROUND": 0.65}},
                           {"event": "reviewer_verdict", **reviewer}]},
              datetime(2026, 10, 31, 13, 21, 4, tzinfo=SGT), calls)


# ---------------------------------------------------------------------------------------------
# 2. Failure showcase: AA1274 DFW -> BWI; consensus on HOLD20, reviewer REJECT, fallback
# ---------------------------------------------------------------------------------------------


def failure():
    s = Scenario(
        scenario_id="2015-04-24_AA1274_N469AA", row_index=131433,
        flight=flight_row(FLIGHT_NUMBER=1274, ORIGIN_AIRPORT="DFW", DESTINATION_AIRPORT="BWI",
                          SCHEDULED_DEPARTURE=hhmm("1835"), DEPARTURE_TIME=hhmm("2323"),
                          DEPARTURE_DELAY=288.0, TAXI_OUT=17.0, WHEELS_OFF=hhmm("2340"),
                          SCHEDULED_TIME=190.0, ELAPSED_TIME=158.0, AIR_TIME=133.0,
                          DISTANCE=1217, WHEELS_ON=hhmm("0253"), TAXI_IN=8.0,
                          SCHEDULED_ARRIVAL=hhmm("2245"), ARRIVAL_TIME=hhmm("0301"),
                          ARRIVAL_DELAY=256.0, LATE_AIRCRAFT_DELAY=233.0, WEATHER_DELAY=23.0),
        dest_disruption=Tagged(value=3, source="data",
                               note="delayed arrivals at BWI in the arrival hour (proxy)"),
        taxi_congestion=Tagged(value=0.9, source="data", note="TAXI_IN / BWI median TAXI_IN"),
        downstream_legs=[],
        alternates=[{"iata": "DCA", "distance_nm": 28}, {"iata": "IAD", "distance_nm": 41},
                    {"iata": "PHL", "distance_nm": 78}],
        wake_category=Tagged(value="L", source="assumed",
                             note="FAA registry miss -> airline fleet default"),
        fuel_reserve_min=Tagged(value=52, source="estimated",
                                note="distance x typical burn; long sector, late night"),
        crew_duty_remaining_min=Tagged(value=41, source="synthetic",
                                       note="seeded FDP model; crew on since morning"),
        gates={"assigned": "D8", "free": ["D4"], "night_crew_until": hhmm("0130")},
        connections=[],
        nominal_aar=Tagged(value=40, source="assumed", note="FAA published BWI rate, night"),
    )
    cands = [
        cand("SLOT+15", "slot_shift", {"shift_min": 15}, 15, 0),
        cand("SLOT+30", "slot_shift", {"shift_min": 30}, 30, 0),
        cand("HOLD20", "hold", {"minutes": 20}, 20, 0),
        cand("HOLD40", "hold", {"minutes": 40}, 40, 0),
        cand("DIVERT_DCA", "divert", {"iata": "DCA"}, 70, 0),
        cand("DIVERT_IAD", "divert", {"iata": "IAD"}, 75, 0),
        cand("GATE_D4", "gate_swap", {"gate": "D4", "extra_taxi_min": 3}, 3, 0),
        cand("GHOLD15", "ground_hold", {"minutes": 15}, 15, 0),
    ]
    extra = {"SLOT+15": 15, "SLOT+30": 30, "HOLD20": 20, "HOLD40": 40, "DIVERT_DCA": 4,
             "DIVERT_IAD": 6, "GATE_D4": 0, "GHOLD15": 0}
    duty = {"DIVERT_DCA": 64, "DIVERT_IAD": 66, "GATE_D4": 3}

    def default(rule, c):
        cid = c.candidate_id
        if rule == "R-FUEL-01":  # engine uses a 30-min final-reserve floor (reviewer uses 45)
            obs = 52 - extra[cid]
            return (obs >= 30, obs, 30)
        if rule == "R-DUTY-01":
            obs = 41 - duty.get(cid, c.est_delay_min)
            return (obs >= 0, obs, 0)
        if rule == "R-WAKE-01":
            return (True, 5.0, 5.0)
        if rule == "R-GATE-01":
            return (True, "free", "free")
        if rule == "R-TURN-01":
            return (True, "no downstream leg", "n/a")
        return (True, 3, 30)

    rules = rule_results(cands, table_from(cands, {}, default))
    atc = msg("ATC", 1, ["HOLD20", "SLOT+15", "GATE_D4", "GHOLD15"], [
        ("SLOT+15", 0.8, "Low disruption at BWI, dest_disruption=3, so a short shift is easy.",
         ["dest_disruption=3"]),
        ("HOLD20", 0.7, "A short hold is tolerable when dest_disruption=3 against "
                        "nominal_aar=40.", ["dest_disruption=3", "nominal_aar=40"]),
        ("GHOLD15", 0.65, "Neutral for the arrival stream.", []),
        ("SLOT+30", 0.6, "Later than needed but regular.", ["dest_disruption=3"]),
        ("GATE_D4", 0.5, "Neutral for the runway.", ["taxi_congestion=0.9"]),
        ("HOLD40", 0.3, "Long airborne hold.", []),
        ("DIVERT_DCA", 0.2, "Moves traffic into a neighbouring field.", []),
        ("DIVERT_IAD", 0.2, "Moves traffic into a neighbouring field.", []),
    ], [])
    pilot = msg("PILOT", 1, ["SLOT+15", "HOLD20", "GATE_D4"], [
        ("SLOT+15", 0.7, "Short and the fuel figure is an estimate.",
         ["fuel_reserve_min=52"]),
        ("GATE_D4", 0.65, "No added airborne time.", ["fuel_reserve_min=52"]),
        ("HOLD20", 0.6, "A 20-minute hold draws on fuel_reserve_min=52, an estimate, but keeps "
                        "the crew at BWI.", ["fuel_reserve_min=52", "crew_duty_remaining_min=41"]),
        ("GHOLD15", 0.55, "Ground time, no airborne burn.", []),
        ("SLOT+30", 0.4, "Long day for the crew.", ["crew_duty_remaining_min=41"]),
        ("DIVERT_DCA", 0.3, "Near alternate, but a second approach late at night.",
         ["alternates[0].distance_nm=28"]),
        ("HOLD40", 0.1, "Long hold against an estimated reserve.", ["fuel_reserve_min=52"]),
        ("DIVERT_IAD", 0.1, "Diversion late in a long duty day.", ["crew_duty_remaining_min=41"]),
    ], [("HOLD40", "A 40-minute hold draws on fuel_reserve_min=52, an estimate.",
         "fuel_reserve_min=52"),
        ("DIVERT_IAD", "Diversion plus ground time late in the duty day.",
         "crew_duty_remaining_min=41")])
    ground = msg("GROUND", 1, ["HOLD20", "GATE_D4", "SLOT+15", "GHOLD15"], [
        ("HOLD20", 0.9, "Lands while the night crew is still on and D8 is free.",
         ["gates.assigned=D8"]),
        ("GATE_D4", 0.7, "D4 is free in the synthetic gate model.", ["gates.free[0]=D4"]),
        ("SLOT+15", 0.6, "No downstream legs listed, so knock-on is low.",
         ["downstream_legs=[]"]),
        ("GHOLD15", 0.55, "Low ramp impact.", ["taxi_congestion=0.9"]),
        ("SLOT+30", 0.4, "Pushes towards the end of the night crew shift.", []),
        ("HOLD40", 0.3, "Late arrival for the night crew.", []),
        ("DIVERT_DCA", 0.1, "Gate plan and crew at the wrong airport.", []),
        ("DIVERT_IAD", 0.1, "Gate plan and crew at the wrong airport.", []),
    ], [("DIVERT_DCA", "Strands the aircraft and the night ramp plan.", "gates.assigned=D8"),
        ("DIVERT_IAD", "Strands the aircraft and the night ramp plan.", "gates.assigned=D8")])
    turns = [Turn(round=1, messages=[atc, pilot, ground], invalid_messages=[],
                  intersection=["SLOT+15", "HOLD20", "GATE_D4"])]
    gate = next(c for c in cands if c.candidate_id == "GATE_D4")
    reject_notes = [
        "FUEL re-derived: HOLD20 needs 20+45=65 min; fuel_reserve_min=52 (estimated) -> FAIL "
        "[14 CFR 121.639]",
        "ENGINE: R-FUEL-01 passed HOLD20 (engine floor 30 min), reviewer fails it (45 min "
        "reserve) -> disagreement",
        "ENGINE: R-FUEL-01 passed SLOT+15 (engine floor 30 min), reviewer fails it (needs 60, "
        "has 52) -> disagreement",
    ]
    final_notes = [
        "FUEL re-derived: GATE_D4 adds 0 airborne min; 52 >= 45; fuel_reserve_min=52 "
        "(estimated) -> PASS [14 CFR 121.639]",
        "DUTY re-derived: GATE_D4 adds 3 min taxi; 41-3=38 >= 0; crew_duty_remaining_min=41 "
        "(synthetic) -> PASS [14 CFR Part 117]",
        "WAKE re-derived: L behind assumed Heavy, spacing available at effective rate 37/h -> "
        "PASS [FAA JO 7110.65 5-5-4]",
        "ENGINE: R-FUEL-01 fuel floor differs from reviewer (30 vs 45 min) on HOLD20 and "
        "SLOT+15 -> reconcile against docs/regulatory_sources.md",
    ]
    disagreements = [
        {"rule_id": "R-FUEL-01", "candidate_id": "HOLD20", "engine_passed": True,
         "reviewer_passed": False},
        {"rule_id": "R-FUEL-01", "candidate_id": "SLOT+15", "engine_passed": True,
         "reviewer_passed": False},
    ]
    reviewer = {
        "verdict": "MODIFY",
        "notes": reject_notes + final_notes,
        "re_derived": [
            {"check": "FUEL", "candidate_id": "HOLD20", "derived": 32, "threshold": 45,
             "passed": False, "citation": "14 CFR 121.639"},
            {"check": "FUEL", "candidate_id": "GATE_D4", "derived": 52, "threshold": 45,
             "passed": True, "citation": "14 CFR 121.639"},
            {"check": "DUTY", "candidate_id": "GATE_D4", "derived": 38, "threshold": 0,
             "passed": True, "citation": "14 CFR Part 117"},
            {"check": "WAKE", "candidate_id": "GATE_D4", "derived": 5.0, "threshold": 5.0,
             "passed": True, "citation": "FAA JO 7110.65 para 5-5-4"},
        ],
        "cited_mismatches": [],
        "engine_disagreements": disagreements,
        "history": [
            {"candidate_id": "HOLD20", "verdict": "REJECT", "notes": reject_notes},
            {"candidate_id": "GATE_D4", "verdict": "MODIFY", "notes": final_notes},
        ],
    }
    fallback = {
        "fired": True, "reason": "reviewer_reject", "candidate_id": "GATE_D4",
        "objective": 3.0, "n_eligible": 2,
        "weights": {"delay": 1.0, "knock_on": 0.5},
        "excluded": [
            {"candidate_id": "HOLD20", "why": "reviewer REJECT (FUEL)"},
            {"candidate_id": "SLOT+15", "why": "reviewer fails FUEL"},
            {"candidate_id": "SLOT+30", "why": "engine R-FUEL-01"},
            {"candidate_id": "HOLD40", "why": "engine R-FUEL-01"},
            {"candidate_id": "DIVERT_DCA", "why": "engine R-DUTY-01"},
            {"candidate_id": "DIVERT_IAD", "why": "engine R-DUTY-01"},
        ],
    }
    rec = {"scenario_id": s.scenario_id, "chosen": gate.model_dump(), "decided_by": "fallback",
           "rounds_used": 1,
           "rule_results": [r.model_dump() for r in rules if r.candidate_id == "GATE_D4"],
           "reviewer_verdict": "MODIFY", "reviewer_notes": reject_notes + final_notes,
           "human_decision": "pending", "log_path": f"runs/{s.scenario_id}.jsonl",
           "fallback": fallback, "reviewer_detail": reviewer}
    calls = {(1, "ATC"): (1720, 520, 0.000432, 2.6), (1, "PILOT"): (1880, 560, 0.000468, 2.9),
             (1, "GROUND"): (1650, 515, 0.000423, 2.7)}
    write_run("failure_showcase", s, cands, rules, turns, rec, fallback, reviewer,
              {"agents": "haiku", "model": "claude-haiku-5-5", "_events": [
                  {"event": "consensus", "round": 1, "candidate_id": "HOLD20",
                   "summed_score": 2.2,
                   "per_agent_scores": {"ATC": 0.7, "PILOT": 0.6, "GROUND": 0.9}},
                  {"event": "reviewer_verdict", "verdict": "REJECT", "notes": reject_notes,
                   "re_derived": reviewer["re_derived"][:1], "cited_mismatches": [],
                   "engine_disagreements": disagreements},
                  {"event": "fallback_fired", **{k: v for k, v in fallback.items()
                                                 if k != "fired"}},
                  {"event": "reviewer_verdict", "verdict": "MODIFY", "notes": final_notes,
                   "re_derived": reviewer["re_derived"][1:], "cited_mismatches": [],
                   "engine_disagreements": disagreements},
              ]},
              datetime(2026, 10, 31, 13, 24, 40, tzinfo=SGT), calls)


# ---------------------------------------------------------------------------------------------
# 3. Invalid message: AA1389 MEM -> DFW, PILOT reply fails validation twice
# ---------------------------------------------------------------------------------------------


def invalid():
    s = Scenario(
        scenario_id="2015-04-24_AA1389_N469AA", row_index=131298,
        flight=flight_row(FLIGHT_NUMBER=1389, ORIGIN_AIRPORT="MEM", DESTINATION_AIRPORT="DFW",
                          SCHEDULED_DEPARTURE=hhmm("1602"), DEPARTURE_TIME=hhmm("2011"),
                          DEPARTURE_DELAY=249.0, TAXI_OUT=21.0, WHEELS_OFF=hhmm("2032"),
                          SCHEDULED_TIME=106.0, ELAPSED_TIME=121.0, AIR_TIME=88.0, DISTANCE=432,
                          WHEELS_ON=hhmm("2200"), TAXI_IN=12.0, SCHEDULED_ARRIVAL=hhmm("1748"),
                          ARRIVAL_TIME=hhmm("2212"), ARRIVAL_DELAY=264.0,
                          LATE_AIRCRAFT_DELAY=102.0, WEATHER_DELAY=147.0),
        dest_disruption=Tagged(value=11, source="data"),
        taxi_congestion=Tagged(value=1.8, source="data"),
        downstream_legs=[{"AIRLINE": "AA", "FLIGHT_NUMBER": 1274, "ORIGIN_AIRPORT": "DFW",
                          "DESTINATION_AIRPORT": "BWI", "SCHEDULED_DEPARTURE": hhmm("1835"),
                          "SCHEDULED_ARRIVAL": hhmm("2245"), "ARRIVAL_DELAY": 256.0}],
        alternates=[{"iata": "DAL", "distance_nm": 10}, {"iata": "SHV", "distance_nm": 160}],
        wake_category=Tagged(value="L", source="assumed"),
        fuel_reserve_min=Tagged(value=70, source="estimated"),
        crew_duty_remaining_min=Tagged(value=95, source="synthetic"),
        gates={"assigned": "C21", "free": ["C14"]},
        connections=[{"flight": "AA1274", "dest": "BWI", "pax": 21, "minutes_after_arrival": 47}],
        nominal_aar=Tagged(value=90, source="assumed"),
    )
    cands = [
        cand("SLOT+15", "slot_shift", {"shift_min": 15}, 15, 15),
        cand("SLOT+30", "slot_shift", {"shift_min": 30}, 30, 30),
        cand("HOLD20", "hold", {"minutes": 20}, 20, 20),
        cand("DIVERT_DAL", "divert", {"iata": "DAL"}, 90, 120),
        cand("GATE_C14", "gate_swap", {"gate": "C14", "extra_taxi_min": 5}, 5, 0),
        cand("GHOLD20", "ground_hold", {"minutes": 20}, 20, 18),
    ]

    def default(rule, c):
        if rule == "R-TURN-01" and c.kind == "divert":
            return (False, "tail at DAL", "at DFW")
        return {"R-FUEL-01": (True, 70, 45), "R-DUTY-01": (True, 95 - c.est_delay_min, 0),
                "R-WAKE-01": (True, 5.0, 5.0), "R-GATE-01": (True, "free", "free"),
                "R-TURN-01": (True, 50, 45), "R-AAR-01": (True, 11, 18)}[rule]

    rules = rule_results(cands, table_from(cands, {}, default))
    atc = msg("ATC", 1, ["SLOT+15", "GHOLD20"], [
        ("SLOT+15", 0.85, "Moves off the peak with dest_disruption=11.", ["dest_disruption=11"]),
        ("GHOLD20", 0.8, "Keeps the aircraft off busy taxiways at taxi_congestion=1.8.",
         ["taxi_congestion=1.8"]),
        ("GATE_C14", 0.5, "Adds taxi time when taxi_congestion=1.8.", ["taxi_congestion=1.8"]),
        ("SLOT+30", 0.6, "Later than needed.", []),
        ("HOLD20", 0.3, "Airborne hold into a disrupted hour.", ["dest_disruption=11"]),
        ("DIVERT_DAL", 0.2, "Second arrival later.", []),
    ], [])
    ground = msg("GROUND", 1, ["GATE_C14", "SLOT+15"], [
        ("GATE_C14", 0.9, "C14 free in the synthetic gate model.", ["gates.free[0]=C14"]),
        ("SLOT+15", 0.7, "Keeps the AA1274 turn workable.",
         ["downstream_legs[0].FLIGHT_NUMBER=1274"]),
        ("GHOLD20", 0.55, "Moderate knock-on.", []),
        ("SLOT+30", 0.4, "Pushes the AA1274 turn.", []),
        ("HOLD20", 0.35, "Moderate knock-on.", []),
        ("DIVERT_DAL", 0.05, "Strands the tail before AA1274.",
         ["downstream_legs[0].FLIGHT_NUMBER=1274"]),
    ], [("DIVERT_DAL", "Strands the tail before AA1274.", "downstream_legs[0].FLIGHT_NUMBER=1274")])
    long_rationale = ("Holding is undesirable because " + "the estimated reserve and the weather "
                      "and the crew day all point the same way, " * 5).strip()
    raw = json.dumps({"acceptable": ["SLOT+15", "GHOLD20"], "ranking": [
        {"candidate_id": "SLOT+15", "score": 0.8, "rationale": "Short shift.",
         "cited_fields": ["fuel_reserve_min=70"]},
        {"candidate_id": "HOLD20", "score": 0.2, "rationale": long_rationale,
         "cited_fields": ["flight.WEATHER_DELAY=147"]}], "vetoes": [],
        "confidence": "high"})
    error = ("attempt 1: 1 validation error for _Reply\nranking.1.rationale\n  String should have "
             "at most 240 characters [type=string_too_long]; attempt 2: 1 validation error for "
             "_Reply\nconfidence\n  Extra inputs are not permitted [type=extra_forbidden]")
    inv = {"agent": "PILOT", "round": 1, "reason": "schema", "raw_text": raw, "error": error}
    turns = [Turn(round=1, messages=[atc, ground], invalid_messages=[inv], intersection=[])]
    chosen = next(c for c in cands if c.candidate_id == "GATE_C14")
    notes = ["FUEL re-derived: GATE_C14 adds 0 airborne min; 70 >= 45 -> PASS [14 CFR 121.639]",
             "DUTY re-derived: GATE_C14 adds 5 min; 95-5=90 >= 0 -> PASS [14 CFR Part 117]",
             "WAKE re-derived: L behind assumed Heavy -> PASS [FAA JO 7110.65 5-5-4]"]
    reviewer = {"verdict": "APPROVE", "notes": notes, "re_derived": [], "cited_mismatches": [],
                "engine_disagreements": []}
    fallback = {"fired": True, "reason": "invalid_message", "candidate_id": "GATE_C14",
                "objective": 5.0, "n_eligible": 5, "weights": {"delay": 1.0, "knock_on": 0.5},
                "excluded": [{"candidate_id": "DIVERT_DAL", "why": "engine R-TURN-01"}]}
    rec = {"scenario_id": s.scenario_id, "chosen": chosen.model_dump(), "decided_by": "fallback",
           "rounds_used": 1,
           "rule_results": [r.model_dump() for r in rules if r.candidate_id == "GATE_C14"],
           "reviewer_verdict": "APPROVE", "reviewer_notes": notes, "human_decision": "pending",
           "log_path": f"runs/{s.scenario_id}.jsonl", "fallback": fallback}
    calls = {(1, "ATC"): (1760, 540, 0.000446, 2.8), (1, "GROUND"): (1700, 530, 0.000435, 2.7),
             (1, "PILOT"): (3900, 1350, 0.001065, 6.1)}
    write_run(s.scenario_id, s, cands, rules, turns, rec, fallback, reviewer,
              {"agents": "haiku", "model": "claude-haiku-5-5", "_events": [
                  {"event": "fallback_fired", **{k: v for k, v in fallback.items()
                                                 if k != "fired"}},
                  {"event": "reviewer_verdict", **reviewer}]},
              datetime(2026, 10, 31, 13, 27, 12, tzinfo=SGT), calls)


# ---------------------------------------------------------------------------------------------
# 4. Sample evaluation summary (long format) + meta
# ---------------------------------------------------------------------------------------------

SAMPLE_NOTE = "SAMPLE FIXTURE: illustrative value, not a real result"
MODEL_NOTE = "model estimate; not comparable like-for-like with actual"


def evaluation():
    rows = [
        ("n_rows", 200, "rows", 200, "sample size", SAMPLE_NOTE),
        ("n_completed", 40, "rows", 200, "scenarios finished", SAMPLE_NOTE),
        ("n_guard_stopped", 0, "rows", 200, "stopped by cost/time guard", SAMPLE_NOTE),
        ("consensus_rate", 0.55, "fraction", 40, 'decided_by=="consensus" / n_completed',
         SAMPLE_NOTE),
        ("consensus_round1_rate", 0.2, "fraction", 40, "consensus with rounds_used==1",
         SAMPLE_NOTE),
        ("consensus_round2_rate", 0.35, "fraction", 40, "consensus with rounds_used==2",
         SAMPLE_NOTE),
        ("mean_rounds", 1.7, "rounds", 40, "mean rounds_used over agent runs", SAMPLE_NOTE),
        ("fallback_rate_no_consensus", 0.3, "fraction", 40, "fallback no_consensus / n_completed",
         SAMPLE_NOTE),
        ("fallback_rate_invalid_message", 0.1, "fraction", 40,
         "fallback invalid_message / n_completed", SAMPLE_NOTE),
        ("fallback_rate_reviewer_reject", 0.05, "fraction", 40,
         "fallback reviewer_reject / n_completed", SAMPLE_NOTE),
        ("agent_top_pick_rule_fail_rate", 0.18, "fraction", 342,
         "valid messages whose ranking[0] fails >=1 engine rule / valid messages", SAMPLE_NOTE),
        ("consensus_excluded_by_rules_rate", 0.08, "fraction", 40,
         "runs where acceptable intersection is non-empty but none pass the rules", SAMPLE_NOTE),
        ("reviewer_APPROVE_rate", 0.6, "fraction", 40, "verdict counts / n_completed",
         SAMPLE_NOTE),
        ("reviewer_MODIFY_rate", 0.32, "fraction", 40, "verdict counts / n_completed",
         SAMPLE_NOTE),
        ("reviewer_REJECT_rate", 0.08, "fraction", 40, "verdict counts / n_completed",
         SAMPLE_NOTE),
        ("reviewer_engine_disagreement_rate", 0.04, "fraction", 360,
         "candidates with engine != reviewer pass / candidates checked", SAMPLE_NOTE),
        ("cited_value_mismatch_rate", 0.06, "fraction", 1210,
         "mismatched citations / citations with a value", SAMPLE_NOTE),
        ("schema_invalid_rate", 0.03, "fraction", 360, "invalid messages / total agent calls",
         SAMPLE_NOTE),
        ("modelled_delay_agents_mean", 17.5, "min", 40, "est_delay_min of chosen (agents)",
         MODEL_NOTE),
        ("modelled_delay_solver_mean", 15.2, "min", 40, "est_delay_min of chosen (solver only)",
         MODEL_NOTE),
        ("actual_delay_mean", 96.4, "min", 40, "ARRIVAL_DELAY of the row (data)", "data"),
        ("actual_chain_mean", 141.0, "min", 40, "sum of downstream ARRIVAL_DELAY (data, partial)",
         "data, partial: only delayed legs exist"),
        ("modelled_saving_vs_actual_mean", 78.9, "min", 40, "actual - modelled (agents)",
         MODEL_NOTE),
        ("agents_vs_solver_same_pick_rate", 0.62, "fraction", 40, "chosen ids equal",
         SAMPLE_NOTE),
        ("latency_s_mean", 19.4, "s", 40, "run latency", SAMPLE_NOTE),
        ("cost_usd_mean", 0.0031, "USD", 40, "run cost", SAMPLE_NOTE),
        ("cost_usd_total", 0.124, "USD", 40, "total cost", SAMPLE_NOTE),
        ("human_decision", "pending", "", 40, "always pending in eval: the tool never acts",
         SAMPLE_NOTE),
    ]
    ev = OUT / "eval"
    ev.mkdir(exist_ok=True)
    with open(ev / "summary.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["metric", "value", "unit", "n", "definition", "note"])
        w.writerows(rows)
    meta = {"model": "claude-haiku-5-5", "seed": 42, "n": 200, "n_completed": 40, "workers": 4,
            "budget": 15, "guard_stopped": False, "reason": None, "cost": 0.124,
            "start": "2026-10-31T14:30:00+08:00", "end": "2026-10-31T14:41:00+08:00",
            "git_sha": "sample", "sample_fixture": True}
    (ev / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8",
                                  newline="\n")


if __name__ == "__main__":
    showcase()
    failure()
    invalid()
    evaluation()
    print("wrote", sorted(p.name for p in OUT.rglob("*.json*")))
