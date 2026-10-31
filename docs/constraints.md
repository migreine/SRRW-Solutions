# Organiser constraints workbook: where each limit is used (31 Oct 2026)

Source: `data/challenge2_operational_constraints.xlsx`. Its `rules_of_play` sheet says: *"Use the
limits in this workbook. Any limit you change must be stated in your demo."* This page is that
statement.

The workbook is read once by `src/constraints.py` (cached). The scenario builder, the rules engine
and the independent reviewer all read the same values from it. The reviewer reads only the shared
data, never rule logic from `src/rules/`. Every workbook value is tagged `source="assumed"` with the
note "organiser workbook (synthetic planning limit)". The organisers label the airport limits
SYNTHETIC: they are scaled from `flights.csv` traffic and are not real airport data.

## Workbook limit -> where it is used

| Sheet / limit | Value | Used in (file) | Rule ID |
|---|---|---|---|
| airport_capacity `active_runways` | 1 / 2 / 3 / 4 by size class | `src/rules/engine.py` `wake` (at the arrival airport, so the alternate's for a divert); `src/reviewer/safety.py` `_check_wake` (destination) | R-WAKE-01, reviewer WAKE |
| airport_capacity `max_runway_ops_per_hour` | 20 / 36 / 60 / 90 | `src/scenario/builder.py` `nominal_aar()` and `Scenario.nominal_aar` = ops/h x **0.5** arrival share (`constraints.ARRIVAL_SHARE`, assumed) | R-AAR-01, R-WAKE-01 demand, reviewer WAKE |
| airport_capacity `min_turnaround_min` | 35 (45 at large hubs) | `builder.py` -> `gates.min_turnaround_min` (destination); `src/options/menu.py` knock-on | R-GATE-01, R-TURN-01 |
| airport_capacity `spare_gates_at_any_time` | 2 or 3 | `menu.py` `_gate_choices`: number of gate-swap options = min(2, spare gates) | (menu) |
| airport_capacity `gates` | 8 to 150 | Loaded, not used (see below) | - |
| airport_capacity, airport not listed | default = first "Non-hub" row: 1 runway, 20 ops/h, 35 min, 2 spare | `constraints.airport()` (`listed=False`). All 322 airports in the data are listed, so this never fires on real rows | - |
| wake_separation table | Super->H/L/S 6/7/8, Heavy->H/L/S 4/5/6, Large->Small 4, any other pair 3 NM | `constraints.wake_sep_nm(leader, follower)` used by engine `wake` and reviewer `_check_wake` | R-WAKE-01, reviewer WAKE |
| fuel_and_crew final reserve | 30 min holding | `builder.FINAL_RESERVE_MIN`, engine `fuel`, reviewer `FUEL_FINAL_RESERVE_MIN` | R-FUEL-01, reviewer FUEL |
| fuel_and_crew contingency | 5% of trip fuel | `builder.CONTINGENCY_FRACTION`, shown in the fuel note as part of the spare fuel | R-FUEL-01 (input) |
| fuel_and_crew spare fuel on arrival | 45 min holding | `builder.SPARE_FUEL_ON_ARRIVAL_MIN`: `fuel_reserve_min` = 30 + alternate + 45 | R-FUEL-01, reviewer FUEL (input) |
| fuel_and_crew holding burn kg/h | 2,400 / 6,500 | Loaded, not used: fuel is modelled in minutes, not kg | - |
| fuel_and_crew crew max duty | 13 h from report | `builder.FDP_LIMIT_MIN` (seeds report time and `crew_duty_remaining_min`); engine `duty` citation; reviewer `CREW_MAX_DUTY_MIN` citation | R-DUTY-01, reviewer DUTY |
| fuel_and_crew ground crew shift | 8 h, 1.5x overtime after | Documented only (see below) | - |
| fuel_and_crew gate change notice | >= 20 min before arrival | engine `gate_notice` | **R-GATE-02** (new, citation "organiser workbook") |
| rules_of_play consensus within 3 turns | 3 | `src/mediator/` cap of 2 negotiation rounds (<= 3), unchanged | - |
| rules_of_play no consensus -> deterministic fallback | - | `src/fallback/` (unchanged) | - |

## Limits we changed or added (state these in the demo)

1. **Arrival share of runway ops = 0.5 (added, assumed).** The workbook gives total runway
   operations per hour. We read that as an airport-wide total of arrivals plus departures (90/h
   over 4 runways at a large hub) and take half as arrivals. DFW/ATL/ORD/DEN therefore accept 45
   arrivals/h. Our old unverified FAA-like rates were 112 to 126/h.
2. **Alternate fuel kept on top of the workbook reserve (added, stricter).** The workbook has a 30
   min final reserve and no alternate. We keep the 14 CFR 121.639 leg to the most distant listed
   alternate, so a non-divert must keep alternate + 30 min. The 45 min spare fuel on arrival is
   read as fuel above final reserve + alternate. A minute of holding fuel is treated as a minute of
   airborne extra. The 5% contingency is assumed to be part of the 45 min spare, not added on top.
3. **Wake leader is assumed Large (kept).** The workbook has no data on the leader. Distances are
   taken from the workbook table. Behind a Large, H/L followers need 3 NM and S needs 4 NM. The
   reviewer now also applies 4 NM to a Small follower (before, it used 3 NM for all). The 140 kt
   approach speed is ours (assumed). The workbook's `min_time_s` column (same-runway departures)
   is not used, because we only model arrivals.
4. **Gate-change decision time (added, assumed).** `GATE_DECISION_LEAD_MIN = 30` in
   `src/rules/engine.py`. A swap is decided 30 min before the projected gate-in, around top of
   descent while the negotiation runs. R-GATE-02 checks notice = new gate-in - decision time
   >= 20 min. With 30 plus 2 or 5 min of taxi, every menu swap passes. The rule binds only if the
   decision is taken later (the test sets the lead to 10 and gets a failure).
5. **Turnaround per airport, not per aircraft class (changed).** The old values were Heavy 90 /
   Large 45 / Small 30. Workbook values replace them, so a widebody now turns in 35 to 45 min, which
   is optimistic for a widebody.
6. **Crew duty is 13 h for every flight (changed).** We dropped our 17 h augmented-crew case for
   block times over 9 h to follow the workbook. The 45 min report before departure and the seeded
   remainder range (60 to 420 min) stay ours (synthetic).
7. **Spare gates is only a cap on the menu.** Our gate model is a synthetic 12-gate window with
   about 43% utilisation, so it usually has more than 2 or 3 free gates. We do not force the gate
   occupancy down to the workbook's spare count. The workbook's `gates` total is not used.
8. **Ground-crew shift and overtime: documented only.** There are no ground-crew shift times in
   the data, so we cannot tell when overtime starts. It is not a hard rule and not a cost in the
   menu.
9. **Unchanged assumed inputs that sit next to the workbook values.** `BASE_LOAD` 0.6 (share of
   capacity filled by on-time traffic), `WX_CAP_REDUCTION` 0.25, `TURN_ADDED_MAX_MIN` 30,
   `DUTY_EXTENSION_MIN` 0 and the 420 kt cruise. `BASE_LOAD` was calibrated against the old, higher
   AARs (docs/calibration.md) and now leaves 0.4 x 45 = 18 arrivals/h of headroom at the big
   hubs.

## Effect on the 200-row evaluation sample (`eval/sample_ids.csv`, seed 42, no API)

| Metric | Before | After |
|---|---|---|
| Rows with no candidate passing every rule | 27 / 200 | 29 / 200 |
| Mean candidates passing per row | 5.44 | 5.41 |
| Failures by rule (all candidates) | GATE 515, DUTY 448, TURN 297, FUEL 240, AAR 26 | GATE 510, DUTY 419, AAR 230, TURN 297, FUEL 0, GATE-02 0 |
| Reviewer-engine disagreement (R-FUEL/R-DUTY/R-WAKE checks) | 18 / 2200 (0.82%) | 20 / 2200 (0.91%) |
| Reviewer verdicts (APPROVE / REJECT / MODIFY) | 82.0% / 13.5% / 4.5% | 81.0% / 14.5% / 4.5% |

The count of rows with no legal option barely moves, but the reason changes. FUEL no longer binds:
with 45 min spare, the longest menu hold (40 min) passes. R-AAR-01 becomes the main capacity limit
at the weather-hit hubs, because their workbook arrival capacity is 45/h. **The AA334 showcase row
(DFW, 14:00) now has no legal option.** Every non-divert option fails R-AAR-01 (demand 54/h vs
cap 38.1/h after the weather cut) and both diverts fail R-TURN-01. The case escalates to a human.
`tests/test_rules.py::test_aa334_escalates_under_workbook_capacity` pins this. If we want a
different showcase, the levers are our own assumptions (arrival share, `BASE_LOAD`), and any change
to them must be stated here.
