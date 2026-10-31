# Failure case: DRAFT

> **Status: DRAFT, waiting on the agents and reviewer eval run.** Everything below comes from the
> deterministic pipeline only (`build_scenario` → `generate_candidates` → `check_all`) on the 200-row
> sample in `eval/sample_ids.csv` (seed 42). The agents, mediator, fallback and reviewer have not
> run on these rows yet. Once `eval/results/per_scenario.csv` exists, the final showcase is chosen
> from it (a reviewer REJECT, or a deadlock that falls back), saved as `runs/failure_showcase.json`,
> and this file is rewritten. Reproduce any row with `python -m src.cli --row-id <N> --agents stub`.

## What the deterministic pipeline shows on the sample

- **74 of 200 rows (37%)**: every candidate fails at least one rule, so the fallback has nothing
  eligible and returns `None` ("escalate to a human, no safe option").
  - On 38 of those 74, **R-DUTY-01 fails every candidate**. The cause is the incurred delay plus the
    synthetic duty state: the remaining FDP at scheduled arrival (seeded, 30–300 min) is smaller than
    the `ARRIVAL_DELAY` the flight already has. The sample leans toward large delays (median +80 min,
    max +916).
  - If we allowed the 14 CFR 117.19 extension of up to 2 h (`DUTY_EXTENSION_MIN = 120` in
    `src/rules/engine.py`), the all-fail count would drop to **35 of 200**. It is off by default,
    because using an extension needs the pilot in command to agree, and that is a human decision.
- **57 of 200 rows**: the obvious agent pick, the candidate with the smallest `est_delay_min + est_knock_on_min`
  (almost always `SLOT-30`), fails a safety rule (WAKE, FUEL or DUTY). Agents never see rule
  results, so this is where the engine and reviewer should catch a top pick.
- Rule fail rates on the sample: WAKE 8.8%, FUEL 26.9%, DUTY 34.1%, GATE 38.5%, TURN 13.5%,
  AAR 14.2%.

## Candidate 1: crew out of hours, nothing is safe (row 352317)

- **Scenario** `2015-12-29_DL1501_N804DN`, BOS→ATL, stratum `weather_ATL`. `ARRIVAL_DELAY` +256 (data),
  of which `WEATHER_DELAY` 247.
- **What fails.** R-DUTY-01 fails all 11 candidates. `crew_duty_remaining_min` = 62 at scheduled
  arrival (**synthetic**). After the 256 min incurred delay it is already −194, and each option makes
  it worse, from −164 (`SLOT-30`) down to −280 (`DIVERT_CHA`). `HOLD40` and `SLOT+30` also fail
  R-FUEL-01: 45.8 and 55.8 min left vs 61.6 needed (16.6 min to the BHM alternate + 45 final
  reserve; fuel is **estimated**).
- **Source tags.** The deciding input is synthetic (seeded duty state). The delay is data.
- **What the user would see.** No recommendation. Fallback `None`, the reviewer REJECTs because
  `chosen is None`, and the panel shows "fails on synthetic duty data" for every option.
- **What would fix it.** In operations, the answer is a crew swap at ATL or a 117.19 extension
  with PIC concurrence. Neither is on the menu. In the product: real crew-tracking data in place of
  the synthetic duty state, plus a `crew_swap` candidate kind.

## Candidate 2: the only rule-clean options are blocked by an assumed threshold (row 145563)

- **Scenario** `2015-05-18_WN2940_N259WN`, PBI→ATL, stratum `weather_ATL`. `ARRIVAL_DELAY` +55,
  `WEATHER_DELAY` 54 (data). There are 45 delayed arrivals in the ATL arrival hour (data, proxy).
- **What fails.**
  - Every option that lands at ATL in that hour or the next fails R-WAKE-01: 88.8 s available per
    runway (110.7 s an hour later) vs 128.6 s needed for a Large behind an assumed Heavy at 140 kt.
    The inputs are 3 assumed arrival runways and demand of 0.6 × AAR 126 (assumed) + 45 + 1.
  - Both gate swaps fail only on wake.
  - Both diverts (`DIVERT_CSG`, `DIVERT_CHA`) pass every rule except R-TURN-01. They add 80.6 and
    86.3 min to the next leg, against an **assumed** 30 min limit.
- **Source tags.** Wake: assumed (runway count, approach speed, base load). Turn: assumed threshold.
  Neither rests on regulation-backed data.
- **What the user would see.** No recommendation. The block comes from two assumed constants, and
  the honest message is "no option passes, and the block rests on assumed values".
- **What would fix it.** Verified runway configurations and AARs (FAA ASPM) in place of the
  assumed table, and a TURN threshold set by the airline rather than by us. It also exposes a
  design question: should an operational (non-safety) rule like TURN make a divert ineligible, or
  only lower its score?

## Candidate 3: the least-delay pick fails wake by 5 s (row 198749)

- **Scenario** `2015-06-26_DL525_N6711M`, LAS→ATL, stratum `weather_ATL`. `ARRIVAL_DELAY` +26 (data).
- **What fails.** `SLOT-30` has the least delay (−30 min, knock-on 0), but it fails R-WAKE-01:
  123.3 s available vs 128.6 s needed, with 11 delayed arrivals in the hour. `SLOT-15` and both gate
  swaps fail the same check. Only `DIVERT_CSG` and `DIVERT_CHA` pass every rule (+80.6 and
  +86.3 min).
- **Source tags.** Wake is assumed. The margin (5.3 s) is far smaller than the uncertainty in the
  assumed approach speed or base load.
- **What the user would see.** If the agents converge on `SLOT-30`, the consensus is excluded by
  the rules and the fallback picks an 80 min divert to avoid a 5 s wake shortfall. This is a good
  showcase for "rules beat agents", and also for "a hard threshold on an assumed input is brittle".
- **What would fix it.** A margin band: within ±10% of the threshold on an assumed input, mark the
  result MODIFY or human review instead of a hard fail. Real fleet-mix data would also let the
  leader category be modelled instead of always assumed Heavy.
