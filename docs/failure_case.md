# Failure case: no legal option, escalate to the duty manager

**Status: final.** The showcase is a real run with Claude Haiku 5.5 agents under the organisers'
workbook limits ([constraints.md](constraints.md)), saved in `runs/failure_showcase.json` with its
consensus log `runs/failure_showcase.jsonl`. The earlier showcase, DL1501, is kept below: it is how
we found a bug in our own reviewer, and the workbook's crew rule later showed its escalation rested
on a synthetic value. Waseem's other draft candidates are further down as secondary examples.

## Showcase: F9782 LAS→DEN, 15 Dec 2015 (row 331503)

| Field | Value |
|---|---|
| Scenario | `2015-12-15_F9782_N218FR`, eval stratum `weather_DEN` |
| Schedule (local) | dep LAS 06:00, arr DEN 08:50 |
| What happened (data) | departed +367 min, `ARRIVAL_DELAY` **+390** (of which `WEATHER_DELAY` 367) |
| Later legs, same aircraft (data) | DEN→LAS +210, LAS→DEN +337, DEN→SFO +246 |
| Crew duty left at scheduled arrival | **183 min** (**synthetic**: seeded report time and duty limit) |

**What the agents did.** Three separate Haiku calls per round, 2 rounds, $0.0086, 63 s, no invalid
replies. All three agents' top pick was `SLOT-30` in both rounds. They agreed on 8 options in
round 1 and 9 in round 2 (sets only grow).

**Why every option fails.** `R-DUTY-01` checks `duty left − incurred delay − added delay ≥ 0`. The
crew is 207 min over before any option is applied (183 − 390), so every option fails, from −177 min
(`SLOT-30`) to −294 min (`DIVERT_PUB`). `R-TURN-01` and `R-GATE-01` also fail a few options.

**What the pipeline did.** The agents agreed, but `rules_pass_intersection` was empty in both rounds.
The deterministic fallback found 0 eligible options, the independent reviewer re-derived the duty
check itself and returned **REJECT**, and the recommendation is "no candidate passes engine and
reviewer; escalate to duty manager". The tool does not guess; a human decides (in operations: a
fresh crew, or a duty extension agreed with the captain).

**How the user knows.** In the UI and the story demo, the run shows `decided by: fallback`, a red
REJECT, every option failing `R-DUTY-01`, and the `synthetic` tag on the crew-duty input that drives
it.

**Reproduce:** `python -m src.cli --row-id 331503 --agents stub --pretty` (no API key needed; the
escalation does not depend on the agents).

## Earlier showcase: DL1501 BOS→ATL, 29 Dec 2015 (row 352317)

> Under the organisers' crew rule (13 h from report time) this flight now has legal options and is
> approved. That confirms the caution below: its escalation rested on a synthetic duty value. It is
> kept because it is how we found and fixed a bug in our own reviewer.

### The flight (data)

| Field | Value |
|---|---|
| Scenario | `2015-12-29_DL1501_N804DN`, eval stratum `weather_ATL` |
| Schedule (local) | dep BOS 07:15, arr ATL 10:28 |
| What happened | departed +247 min, gate-in at ATL 14:44, `ARRIVAL_DELAY` **+256** (of which `WEATHER_DELAY` 247) |
| ATL arrival hour | 6 delayed arrivals at ATL in the 14:00 hour (data, proxy) |
| Later legs | none for N804DN that day in the extract (rotations are partial) |

### What the agents agreed on

Three separate Haiku calls per round, 2 rounds, 6 calls in total. Cost $0.0077, 62 s, and no
invalid messages.

| Round | ATC top pick | PILOT top pick | GROUND top pick | Options all three accept |
|---|---|---|---|---|
| 1 | `SLOT-30` | `GROUND_HOLD_BOS` | `SLOT-15` | 7: `SLOT+15, SLOT-15, SLOT-30, HOLD20, GATE_A12, GATE_D6, GROUND_HOLD_BOS` |
| 2 | `SLOT-30` | `SLOT-30` | `SLOT-15` | 8: the same plus `SLOT+30` (monotonic concession: sets only grow) |

Only `HOLD40` and the two diverts stayed outside the agreement. ATC vetoed both diverts. The agents
agreed broadly. The problem is that **none of the options they agreed on is legal**, and they could
not know that, because agents never see rule results. All six top picks fail a rule.

### Why every option fails

`R-DUTY-01` (14 CFR Part 117 FDP) checks
`crew_duty_remaining_min − incurred ARRIVAL_DELAY − added delay ≥ 0`. For this flight:

- `crew_duty_remaining_min` = **103 min** at the scheduled arrival (**synthetic**).
- The incurred delay is **256 min** (**data**).
- The crew is already 153 min past the limit before any option is applied, so every option fails:

| Candidate | R-DUTY-01 observed (min) | Other failures |
|---|---|---|
| `SLOT-30` | −123 | `R-GATE-01` (15 min overlap at gate A6, synthetic) |
| `SLOT-15` | −138 | |
| `GATE_A12` | −155 | |
| `GATE_D6` | −158 | |
| `SLOT+15` | −168 | |
| `HOLD20` | −173 | |
| `GROUND_HOLD_BOS` | −178 | |
| `SLOT+30` | −183 | |
| `HOLD40` | −193 | |
| `DIVERT_CSG` | −233.6 | |
| `DIVERT_CHA` | −239.3 | |

Every other rule passes on every option. Fuel is not the problem: the tightest case is `HOLD40`,
with 63.8 min left against 61.6 min needed (16.6 min to the BHM alternate + 45 min final reserve,
fuel estimated).

**The deciding input is synthetic.** The scenario note says the seeded crew reported at −49 min,
which is 23:11 the evening before a 07:15 departure. It sets the FDP limit at 780 min (an assumed
Part 117 Table B value). That leaves 103 min at the scheduled arrival.

A crew that reported 60 min before departure (an assumed, typical report) would have used about
8.5 h of FDP by the actual 14:44 gate-in. That is well under the assumed 13 h limit, even with
`HOLD40`. Earlier legs that crew may have flown are not in the extract, so we cannot tell which
picture is true. The only data-backed input to this escalation is the 256 min delay. **The system
may be escalating a crew shortage that does not exist.** It says so through the `synthetic` tag on
the deciding value, not through its verdict.

### What the pipeline did (from `runs/failure_showcase.jsonl`)

1. `rule_check` × 66 (11 options × 6 rules), before any agent is called.
2. Round 1 `intersection`: 7 options agreed, `rules_pass_intersection: []`. No consensus.
3. Round 2 `intersection`: 8 options agreed, `rules_pass_intersection: []`. No consensus, and the
   2-round cap is reached.
4. `fallback_fired` with reason `no_consensus`, `n_eligible: 0`, `candidate_id: null`. The
   deterministic fallback has nothing legal to pick.
5. `reviewer_verdict` **REJECT**: "no candidate was chosen (chosen=None), so there is nothing to
   execute". The fallback re-runs (`reviewer_reject`) and still finds 0 eligible.
6. `recommendation`: `decided_by: fallback`, `candidate_id: null`, reviewer REJECT, with the note
   "no candidate passes engine and reviewer; escalate to duty manager". `human_decision` stays
   `pending`.

In the 200-row eval, the same scenario is counted under `consensus_excluded_by_rules`: the agents
agreed on something, and the rules excluded all of it.

### A fault we found in this case: the reviewer's duty check was not independent (fixed)

When this scenario was first run (commit `ee2d30d`), the reviewer's own DUTY re-derivation
**passed all 11 options**. For example, for `SLOT+15` it computed 103 − 15 = 88 ≥ 0, subtracting
only the option's added delay, not the 256 min already incurred. The run listed 11 `R-DUTY-01`
engine disagreements. The outcome was still safe: the REJECT came from there being no pick, and the
reviewer rejects any pick the engine failed. But the independent check did not catch the duty
problem on its own.

Commit `9dcb86a` fixed it: the reviewer now applies `duty − incurred − added ≥ 0`, derived
independently of the rules engine. The saved `runs/failure_showcase.json` was regenerated on the
fixed code: the reviewer now fails DUTY on every option itself (`SLOT+15`: 103 − 256 − 15 = −168),
with **0 engine disagreements**. Over the 200-row solver-only pass, reviewer-engine disagreement fell
from 20.1% to 0.8% of candidate checks. The evaluation in `eval/results/` was re-run on the fixed
code.

### How the user sees it

`streamlit run app/streamlit_app.py`, then click **Failure case** in the sidebar. It loads
`runs/failure_showcase.json`. No API key is needed.

- **Header:** a **decided by: fallback** badge (orange, not the green consensus badge), a
  **reviewer: REJECT** badge and **human decision: pending**. A **red banner** reads "Deterministic
  fallback fired: reviewer_reject — the recommendation was not decided by agent consensus."
- **Negotiation panel:** both rounds, with each agent's acceptable set, ranking, rationales and
  cited fields.
- **Checks panel:**
  - A red "How the user knows" line names the REJECT, the fallback reason and "decided by
    fallback".
  - The rules matrix shows `R-DUTY-01` as FAIL on every row.
  - The rule detail shows the citation "103 min left at scheduled arrival (synthetic) − 256
    incurred ARRIVAL_DELAY (data) − 15.0 added", with each source tag colour-coded.
  - The fallback block is expanded and shows 0 eligible options.
- **Recommendation panel:** a red box reads "No option passes engine and reviewer — escalate to
  duty manager." There is nothing to approve. The duty manager can still record a decision, which
  is written to the log as a `human_decision` event.

### What would fix it

1. **Real crew-tracking data** (report time, legs already flown, rest) in place of the synthetic
   `crew_duty_remaining_min`. This is the main fix, because the deciding value is synthetic and the
   shortage may not be real.
2. **A crew-swap option.** In operations the normal answer is a reserve crew at ATL. That needs a
   `crew_swap` candidate kind and reserve-crew availability as an input, with `R-DUTY-01` checking
   the new crew. Neither is on the menu today, and `tail_swap` was cut too.
3. **The 14 CFR 117.19 extension, with the pilot in command's agreement.** It exists as
   `DUTY_EXTENSION_MIN` in `src/rules/engine.py` (up to 120 min). It is 0 by default, because the
   PIC's concurrence is a human decision, not something the tool can assume. It should be an
   explicitly labelled "requires PIC agreement" option the duty manager can choose, not a constant.
   **On this row it would not be enough on its own:** the best option, `SLOT-30`, is at −123 min
   against a −120 floor, and it also fails `R-GATE-01`. It would help on other rows where duty is
   the only failure.

### Reproduce

```bash
# Saved run: open it in the UI (Failure case button), or read runs/failure_showcase.json

# Re-run without an API key. The escalation does not depend on the agents,
# because every option fails R-DUTY-01; only the agents' rankings differ.
python -m src.cli --row-id 352317 --agents stub --pretty
python -m src.cli --row-id 352317 --agents none --pretty     # solver-only

# Live Haiku agents (needs ANTHROPIC_API_KEY; rankings vary from run to run)
python -m src.cli --row-id 352317 --agents haiku --pretty
```

Re-runs write `runs/2015-12-29_DL1501_N804DN.json` and do not overwrite
`runs/failure_showcase.json`.

---

## Secondary examples (Waseem's draft, updated after the recalibration)

**These came from the deterministic pipeline only, before the recalibration in
[calibration.md](calibration.md) and before any agent run, so the draft's figures are stale.** The
corrected figures are:

- Rows where every option fails: 74 of 200 → **27 of 200**.
- Rows where every option fails on duty: 38 → **22**.
- The draft's per-rule failure rates and its "57 of 200 obvious picks fail" are pre-calibration.
  The measured agent top-pick failure rate is in `eval/results/summary.md`.
- The draft's "117.19 extension → 35 of 200" was measured on the old values.

Two of the draft candidates no longer fail the way the draft described. They are kept because they
show how much outcomes depend on assumed constants.

Their current outcomes are taken from `eval/results/per_scenario.csv`, from the 200-row evaluation
re-run on the final code (after the reviewer fixes in `9dcb86a`).

### Row 145563: WN2940 PBI→ATL, 18 May 2015 (stale: no longer a no-option row)

- **Scenario.** `2015-05-18_WN2940_N259WN`, stratum `weather_ATL`. `ARRIVAL_DELAY` +55, of which
  `WEATHER_DELAY` 54 (data). 45 delayed arrivals in the ATL arrival hour (data, proxy).
- **What the draft found (before recalibration).**
  - Every option landing at ATL in that hour or the next failed R-WAKE-01: 88.8 s available per
    runway vs 128.6 s needed for a Large behind an assumed Heavy.
  - The two diverts passed everything except R-TURN-01. They added 80.6 and 86.3 min to the next
    leg, against an assumed 30 min limit.
  - Result: no recommendation, and the block rested entirely on assumed constants.
- **What happens now.**
  - The assumed wake leader is now a Large (77.1 s needed), so R-WAKE-01 no longer fails anywhere
    on the sample.
  - Solver-only picks `GATE_B12` (reviewer APPROVE).
  - The Haiku agents agreed on `GATE_B12` in round 1 (reviewer APPROVE, no cited-value
    mismatches).
  - All three agents' top picks failed at least one rule; the consensus landed on a legal option.
- **What it still shows.** Recalibrating assumed constants (chiefly the wake leader, Heavy →
  Large) turned "no option" into a routine recommendation. An answer that rests on assumed values must say so, and the source tags in the
  citations do.
- **What would fix it.** Verified runway configurations and arrival rates (FAA ASPM) and real fleet
  mix, in place of the assumed values. A TURN threshold set by the airline rather than by us.
- **Open design question.** Should an operational (non-safety) rule like R-TURN-01 make an option
  ineligible, or only lower its score?
- **Reproduce:**
  - `python -m src.cli --row-id 145563 --agents stub --pretty`
  - `python -m src.cli --row-id 145563 --agents none --pretty`

### Row 198749: DL525 LAS→ATL, 26 Jun 2015 (stale: the 5 s wake shortfall is gone)

- **Scenario.** `2015-06-26_DL525_N6711M`, stratum `weather_ATL`. `ARRIVAL_DELAY` +26 (data).
- **What the draft found (before recalibration).**
  - `SLOT-30` (least delay) failed R-WAKE-01 by 5.3 s: 123.3 s available vs 128.6 s needed.
  - `SLOT-15` and both gate swaps failed the same check.
  - Only the two diverts passed, so the fallback would have picked an 80 min divert to avoid a 5 s
    shortfall on an assumed input.
- **What happens now.**
  - The required spacing is 77.1 s and R-WAKE-01 passes.
  - Solver-only picks `SLOT-15` (reviewer APPROVE).
  - The Haiku agents agreed on `SLOT-15` in round 1 (reviewer APPROVE, no cited-value mismatches).
  - The PILOT top pick failed at least one rule. `per_scenario.csv` records only that it failed,
    not which rule.
- **What it still shows.** A hard threshold on an assumed input is brittle. Recalibrating assumed
  constants (chiefly the wake leader) moved this row from "80 min divert" to "15 min earlier slot".
- **What would fix it.** A margin band: within ±10% of a threshold on an assumed input, return
  MODIFY / human review instead of a hard pass or fail. Real fleet-mix data would let the leader
  category be modelled instead of assumed.
- **Reproduce:**
  - `python -m src.cli --row-id 198749 --agents stub --pretty`
  - `python -m src.cli --row-id 198749 --agents none --pretty`

### Related: forced deadlock on AA334 (constructed, not a real failure)

`python -m src.cli --row-id 123017 --agents stub --force-deadlock --out runs/deadlock/ --pretty`
gives each agent a disjoint third of the menu, so both rounds have an empty agreement. The
deterministic fallback then decides: in the saved `runs/deadlock/2015-04-24_AA334_N469AA.json` it
picks `SLOT-30` from 8 rule-passing options (objective 167), and the reviewer APPROVEs. This shows
the fallback path when a legal option exists. The DL1501 showcase above shows the path when none
does.
