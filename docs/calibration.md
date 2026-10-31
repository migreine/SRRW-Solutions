# Calibration of synthetic and assumed inputs (31 Oct 2026)

**Honesty note.** Every value changed here is a *synthetic*, *estimated* or *assumed* input. None
is measured. We have no airline crew rosters, dispatch releases, gate plans, ASPM runway
configurations or fleet registry. The new values are judgement calls based on typical public
real-world margins, so they are plausible, not validated. They keep their `source` tags, and the
pitch must keep calling them synthetic or assumed. Regulatory thresholds are unchanged: the 45 min
final reserve and the most-distant-alternate leg (14 CFR 121.639), the Part 117 FDP logic
(including `DUTY_EXTENSION_MIN = 0`), and the FAA JO 7110.65 5-5-4 wake distances by category.
Every rule's logic is unchanged.

## Why

The old generated state left almost no slack. On the stratified subset below, 30% of rows had
**no** candidate that passed every rule, and the end-to-end stub pipeline escalated 43 of 50 rows.
That makes the agents irrelevant and is not realistic: airlines plan crew duty buffers, dispatch
carries extra fuel on weather days, and hub gate plans follow the latest ETA. The goal was a
typical disrupted flight with roughly 3 to 6 of ~11 candidates passing every rule, with some
genuine zero-candidate (escalation) rows left in. The values were chosen as defensible values, not
tuned to hit a target number.

## Method

- **Subset (primary):** the first 10 rows of each stratum in `eval/sample_ids.csv`: `weather_ATL`,
  `weather_ORD`, `weather_DFW`, `weather_DEN`, `late_aircraft` (50 rows, 11 candidates each).
  The full 200-row sample is reported as a robustness check.
- **Pipeline:** `build_scenario(row)` -> `generate_candidates` -> `check_all`, seed 42. A candidate
  "passes" if all six rules pass. "Failures by rule" counts failed (candidate, rule) results.
- **"Before":** the old values were reproduced in-process by monkeypatching. This includes the old
  gate model: the gate plan was anchored on the scheduled arrival with the old gaps, which uses the
  identical RNG draw sequence. The reproduction matches the pre-change code exactly (15/50 zero
  rows on the subset; 74/200 on the full sample, as previously quoted in `src/rules/engine.py`).

## Before / after: stratified subset (50 rows)

Each cell is: rows with 0 passing / mean passing / median passing. Then failures by rule.

| Stratum | Before: 0-pass rows | Before: mean / median | After: 0-pass rows | After: mean / median |
|---|---|---|---|---|
| weather_ATL | 6/10 | 1.20 / 0.0 | 1/10 | 5.30 / 5.5 |
| weather_ORD | 1/10 | 2.30 / 2.0 | 1/10 | 6.20 / 7.5 |
| weather_DFW | 5/10 | 2.10 / 1.5 | 3/10 | 5.50 / 6.5 |
| weather_DEN | 2/10 | 2.30 / 2.0 | 0/10 | 6.00 / 6.0 |
| late_aircraft | 1/10 | 4.00 / 4.0 | 0/10 | 6.40 / 6.0 |
| **All** | **15/50 (30%)** | **2.38 / 2.0** | **5/50 (10%)** | **5.88 / 6.0** |

Failures by rule, before -> after:

| Stratum | WAKE | FUEL | DUTY | GATE | TURN | AAR |
|---|---|---|---|---|---|---|
| weather_ATL | 48 -> 0 | 33 -> 16 | 41 -> 13 | 37 -> 29 | 18 -> 18 | 33 -> 6 |
| weather_ORD | 12 -> 0 | 26 -> 11 | 31 -> 15 | 37 -> 31 | 11 -> 11 | 23 -> 0 |
| weather_DFW | 0 -> 0 | 26 -> 8 | 57 -> 38 | 27 -> 22 | 7 -> 7 | 20 -> 4 |
| weather_DEN | 0 -> 0 | 29 -> 11 | 32 -> 9 | 54 -> 28 | 15 -> 15 | 17 -> 0 |
| late_aircraft | 1 -> 0 | 28 -> 10 | 15 -> 9 | 45 -> 27 | 10 -> 10 | 0 -> 0 |
| **All** | **61 -> 0** | **142 -> 56** | **176 -> 84** | **200 -> 137** | **61 -> 61** | **93 -> 10** |

## Before / after: full 200-row sample (robustness)

| Stratum | Before: 0-pass rows | Before: mean / median | After: 0-pass rows | After: mean / median |
|---|---|---|---|---|
| weather_ATL (38) | 19 | 1.58 / 0.5 | 4 | 5.11 / 5.5 |
| weather_ORD (37) | 15 | 1.73 / 2.0 | 7 | 5.05 / 6.0 |
| weather_DFW (37) | 17 | 1.76 / 2.0 | 8 | 4.86 / 6.0 |
| weather_DEN (38) | 13 | 2.05 / 2.0 | 4 | 5.97 / 7.0 |
| late_aircraft (50) | 10 | 2.92 / 3.0 | 4 | 6.00 / 6.0 |
| **All (200)** | **74 (37%)** | **2.06 / 2.0** | **27 (13.5%)** | **5.44 / 6.0** |

Failures by rule, all 200 rows, before -> after: WAKE 194 -> 0, FUEL 592 -> 240, DUTY 750 -> 448,
GATE 846 -> 515, TURN 297 -> 297, AAR 313 -> 26.

Distribution of passing candidates per row (200 rows), before -> after:
0: 74 -> 27, 1: 9 -> 4, 2: 42 -> 4, 3: 22 -> 9, 4: 27 -> 24, 5: 15 -> 20, 6: 9 -> 25, 7: 1 -> 30,
8: 0 -> 31, 9: 0 -> 17, 10: 1 -> 7, 11: 0 -> 2.

The result sits at the upper end of the 3 to 6 target (mean 5.4 to 5.9, median 6). The zero-pass
rate is 10% on the subset and 13.5% on the full sample. Of the zero-pass rows, 4 of 5 on the
subset and 22 of 27 on the full sample fail R-DUTY-01 on *every* candidate: a crew-duty timeout
after a long incurred delay (up to 916 min). The other 5 are mixed. In 4 of them duty rules out 9
or 10 options and fuel, gate or turnaround rule out the rest. One (row 196533, ATL, +120 min)
combines a weather-reduced AAR, gate conflicts, turnaround and fuel. These are genuine escalations:
a reserve crew or a 117.19 extension is a human decision.

End to end with stub agents on the 50-row subset (`src.cli.run_one`, same old/new switch):
before, 43 escalated, 5 consensus+APPROVE, 2 consensus+MODIFY. After, 5 escalated, 35
consensus+APPROVE, 10 consensus+MODIFY. All 10 MODIFYs come from one R-DUTY-01 engine/reviewer
disagreement on a non-chosen candidate (see "Open issues").

## Marginal effect of each change (subset, one change reverted at a time)

| Configuration | 0-pass rows | Mean | Median |
|---|---|---|---|
| All new values | 5/50 | 5.88 | 6.0 |
| ...but old discretionary fuel (5-20) | 5/50 | 4.72 | 5.0 |
| ...but old crew duty range (30-300) | 11/50 | 4.92 | 6.0 |
| ...but old gate model (scheduled-arrival anchored) | 6/50 | 4.24 | 4.5 |
| ...but old wake leader (Heavy) | 8/50 | 4.98 | 6.0 |
| ...but old weather AAR cut (0.4) | 7/50 | 4.86 | 6.0 |
| ...but old per-airport runway table | 5/50 | 5.88 | 6.0 |
| All old values | 15/50 | 2.38 | 2.0 |

The runway table change makes no difference on this subset: the four hubs already had 3 to 4
runways, and no late-aircraft row was near the limit. It is there for consistency with the
reviewer (below).

## Parameters changed

| Parameter (file) | Old | New | Source tag | Rationale |
|---|---|---|---|---|
| `DISCRETIONARY_RANGE` (`src/scenario/builder.py`) | U[5, 20] min | U[15, 40] min | `fuel_reserve_min` stays **estimated** | Every eval row is weather- or late-aircraft-delayed. Dispatchers add holding/extra fuel when destination weather or ATC flow delays are forecast, typically ~15 to 45 min. Assumed, not from dispatch releases. Effect: margin above alternate + 45 min is now ~20 to 45 min. On the 200 rows, R-FUEL-01 passes SLOT+15 200/200, HOLD20 193/200, SLOT+30 117/200 and HOLD40 50/200. |
| `DUTY_REMAINING_RANGE` (`src/scenario/builder.py`) | U[30, 300] min | U[60, 420] min (cap at report >= 45 min before departure unchanged) | `crew_duty_remaining_min` stays **synthetic** | The leg can be anywhere in the duty day. The ~1 h floor is the delay buffer schedulers keep on the last leg of a long day (pairings are not built to the limit because a 117.19 extension needs PIC concurrence). The ~7 h ceiling is the first leg of a typical 8 to 10 h, 3 to 4 leg duty day against 12 to 13 h Table B limits. Assumed. FDP limits and the rule are unchanged. |
| Gate plan anchor (`_gates`, `src/scenario/builder.py`) | Scheduled arrival `sched_arr_abs` | Projected gate-in `actual_arr_abs` | `gates.source` stays **synthetic** | Airline gate plans are re-flowed to the latest ETA once a delay is known, and the scenario already plans against `actual_arr_abs`. Before, a 60 to 120 min late flight met the *next* aircraft at its own gate on almost every slot/hold candidate. |
| `ASSIGNED_GATE_PREV_GAP` (new constant, `builder.py`) | U[10, 29] min (hard-coded) | U[10, 40] min | **synthetic** | Idle time between the previous occupant leaving and our gate-in. Assumed: hub gate plans keep a 10 to 15 min minimum buffer and up to ~1 h between banks. |
| `ASSIGNED_GATE_NEXT_GAP` (new constant, `builder.py`) | U[5, 25] min (hard-coded) | U[15, 60] min | **synthetic** | Idle time after our planned turn before the next occupant. Same basis. A 5 min floor was below any planned gate buffer. |
| `OTHER_GATE_BUSY` / `OTHER_GATE_IDLE` (`builder.py`) | U[40, 90] / U[20, 149] (hard-coded) | unchanged, now named constants | **synthetic** | ~43% utilisation of the other gates; left as is. |
| Engine wake leader `LEADER_CATEGORY` (`src/rules/engine.py`) | Heavy (always) | Large | rule source stays **assumed** | The typical leader at ATL/ORD/DFW/DEN is a Large narrowbody, and Heavies are a small share of hub arrivals. Assuming every leader is a Heavy made ATL fail WAKE on almost every row. It also contradicted the reviewer, which already assumed Large. Distances are unchanged and retained: behind Heavy H 4 / L 5 / S 6 nm; behind Large H 3 / L 3 / S 4 nm (FAA JO 7110.65 5-5-4, verify). |
| Engine arrival runways `ARRIVAL_RUNWAYS_ASSUMED` (`engine.py`) | Per-airport table (ATL/ORD/DEN/CLT 3, DFW 4, others 1 to 2, default 1) | 3 for every airport | **assumed** | Must equal the reviewer's single assumed count (it cannot take a table without a logic change). 3 is the typical hub figure (ATL 26R/27L/28; ORD, DFW, DEN 3 to 4). It is also the smallest count for which the assumed ATL nominal AAR of 126/h fits 3 nm at 140 kt (46.7/h per runway). Cost: it overstates single-runway airports (EWR, LGA, DCA), where nominal rates are low enough that WAKE would not bind anyway. |
| `WX_CAP_REDUCTION` (`engine.py`) | 0.40 | 0.25 | **assumed** | AAR cut when every delayed arrival in the hour is weather-related. VMC-to-IMC called rates at the large hubs drop by roughly 15 to 30% (FAA airport capacity profiles, not verified). 0.4 meant a single weather-delayed arrival in an hour cut ATL's cap below its own base load, failing every candidate. |
| `ASSUMED_ARRIVAL_RUNWAYS` (`src/reviewer/safety.py`, constants block only) | 2 | 3 | **assumed** | Reconciliation with the engine (below). With 2, the reviewer could not pass WAKE at ATL/ORD/DFW/DEN on any normal hour (126/h over 2 runways = 57 s < 77 s). |
| `CIT_WAKE_RUNWAYS` (`safety.py`, constants block only) | "2 arrival runways ..." | "3 arrival runways ..." | **assumed** | Citation text follows the constant. |

**Not changed (on purpose):** `FINAL_RESERVE_MIN` 45, `CONTINGENCY_FRACTION` 5%,
`DEFAULT_ALTERNATE_MIN`, FDP limits (13 h / 17 h), `REPORT_BEFORE_DEP_MIN`, `DUTY_EXTENSION_MIN` 0,
`TURNAROUND_MIN` (H 90 / L 45 / S 30), `TURN_ADDED_MAX_MIN` 30, `BASE_LOAD` 0.6, `NOMINAL_AAR`,
`APPROACH_KT` 140, the candidate menu, and every rule's logic. R-TURN-01 failures (61 on the subset)
are unchanged: they come from HOLD40, long ground holds and diverts, which genuinely add more than
30 min to the next leg.

## Wake reconciliation (engine R-WAKE-01 vs reviewer WAKE)

| Assumed input | Engine before | Reviewer before | Both now |
|---|---|---|---|
| Leader category | Heavy | Large | **Large** |
| Separation (H / L follower; builder emits only H or L) | 4 / 5 nm | 3 nm (every follower) | **3 nm** |
| Separation (S follower) | 6 nm | 3 nm | engine **4 nm** (7110.65 small behind large), reviewer 3 nm (see below) |
| Approach speed | 140 kt | 140 kt | **140 kt** |
| Arrival runways | per-airport table | 2 | **3** |
| Required spacing for H/L followers | 102.9 / 128.6 s | 77.1 s | **77.1 s** |

On the full 200-row sample (2,200 candidate checks), the reviewer failed WAKE on 1,606 checks
before and disagreed with the engine on 1,527. In practice it would have REJECTed nearly every hub
recommendation on WAKE. Now both pass all 2,200, with 0 disagreements.
`tests/test_rules.py::test_wake_inputs_match_reviewer_and_distances_unchanged` guards the match and
the unchanged distances.

Residual differences (logic, deliberately not changed):
- **Demand.** Engine demand = 0.6 x AAR + delayed arrivals in the candidate's hour + 1. Reviewer
  flow = AAR - `dest_disruption`, floored at 1. They agree on these inputs but are different models.
- **Small follower.** The reviewer applies 3 nm to every follower, so for a Small follower it
  would be 1 nm less strict than the engine. The builder never emits "S" today. If it ever does,
  the engine stays the stricter check, and the reviewer rejects anything the engine failed.
- **WAKE no longer binds on the eval sample.** With a Large leader and 3 runways, the engine fails
  only above 140 arrivals/h (ATL: more than ~63 delayed arrivals in one hour). The reviewer fails
  only if AAR - disruption > 140, which no airport in the table reaches. R-AAR-01 is now the
  binding capacity rule. That is realistic: nominal AARs are already set so that the separation
  can be met. WAKE remains a backstop, and the test fixtures still exercise its failure path.

## Open issues found while measuring (not fixed: outside this task's remit)

- **R-DUTY-01 vs reviewer DUTY.** The engine subtracts the incurred `ARRIVAL_DELAY` from
  `crew_duty_remaining_min` (which is defined at the scheduled arrival). The reviewer subtracts
  only the candidate's added delay. This causes all 10 MODIFY verdicts in the end-to-end subset run.
  It is a reviewer logic question for the reviewer's owner (L), not a calibration value.
- The reviewer header says to reconcile its constants "never against src/rules/". The runway count
  was reconciled against the engine on explicit instruction for this calibration. Only constants
  changed, never the logic.
