# Team checklist: Challenge #2

Drawn from [timeline.md](timeline.md). Section numbers like §2.7 refer to sections in that file.
Tick boxes as you go. The time in brackets is when each item must be done.

| Person | Role | Branch | Owns |
|---|---|---|---|
| **Rohan** | Technical (L) | `l/*` | `src/schemas.py`, `src/mediator/`, `src/reviewer/`, `src/fallback/`, `src/log/`, `src/cli.py`, `eval/run_eval.py`, `CLAUDE.md`, all merges to `main` |
| **Waseem** | Technical (T1) | `t1/*` | `src/scenario/`, `src/options/`, `src/rules/`, `eval/sample.py`, `tests/test_scenario.py`, `tests/test_rules.py`, `docs/failure_case.md` |
| **Reine** | Technical (T2) | `t2/*` | `src/agents/`, `tests/test_agents.py`, `app/streamlit_app.py`, the backup video |
| **Sydelle** | Non-technical (N) | `n/*` | `README.md`, `docs/pitch.md`, `docs/data_limits.md`, `docs/regulatory_sources.md`, `docs/slides/`, the submission, the budget, timekeeping, presenting |

**Rules for everyone:**
- Work only in your own folders.
- Commit every 20 minutes, starting the message with your tag (`L:`, `T1:`, `T2:`, `N:`).
- Merge to `main` only at checkpoints, and Rohan does the merging.
- Never commit `.env`.
- Start every Claude Code session with: *"Read CLAUDE.md, docs/briefing.md and docs/timeline.md, then do my task card."*

---

## Everyone (by 11:50)
- [ ] `git pull`, then create your branch.
- [ ] Create your own API key at platform.claude.com. Copy `.env.example` to `.env` and paste your key into `.env`. Never paste a key into chat or a commit.
- [ ] Find the "Decisions frozen now" section (§2) in `timeline.md` and read it. Don't reopen those decisions after 11:45.

---

## Rohan: Technical (L)

**Kickoff → schema freeze (11:45–12:00)**
- [ ] Commit and push `.gitignore` and `.env.example` so nobody commits a key.
- [ ] Write `CLAUDE.md` using the "Claude Code working rules" section (§7) of `timeline.md`.
- [ ] Write `src/schemas.py` (Pydantic v2): `Tagged`, `Scenario`, `Candidate`, `RuleResult`, `AgentMessage`, `Turn`, `Recommendation`, exactly as specified in the "Interfaces" section (§4) of `timeline.md`.
- [ ] Push both to `main` by **12:00** and tell the team to rebase.

**Build block 1 (12:00–13:00)**
- [ ] `src/log/consensus_log.py`: `ConsensusLog(path).append(event)`. Append-only JSONL with ISO timestamps.
- [ ] `src/fallback/solver.py`: `fallback_pick(candidates, rule_results, weights)`, a weighted minimum over options that pass the rules. Weights live in one dict.
- [ ] `src/mediator/protocol.py`: `negotiate(..., max_rounds=2)` using the Monotonic Concession Protocol:
  - [ ] Round 2's acceptable set must contain round 1's, otherwise the message is invalid and logged.
  - [ ] Consensus is the intersection of acceptable options that also pass the rules. If it's empty, go to round 2, then to the fallback.
  - [ ] Agents never see rule results.
- [ ] `src/cli.py`: `python -m src.cli --row-id N --agents stub|haiku|sonnet|none --out runs/`, plus a `--force-deadlock` flag.
- [ ] Done when `python -m src.cli --row-id 0 --agents stub` writes `runs/*.json` and `.jsonl`.

**Checkpoint 1 (13:00–13:15)**
- [ ] Merge the T1 and T2 branches. Run the AA334 row with `--agents stub`.
- [ ] Check that the run produces a recommendation and a log, records at least one rule failure, and that `--force-deadlock` triggers the fallback.

**Build block 2 (13:15–14:15)**
- [ ] Run AA334 live with `ClaudeAgent(haiku)`. Fix any prompt or schema mismatches with Reine.
- [ ] `src/reviewer/safety.py`, written separately from Waseem's rules code (your own Claude session and prompt). It must:
  - [ ] re-derive the fuel and wake checks
  - [ ] check every `cited_fields` value an agent quotes against the scenario
  - [ ] return APPROVE, REJECT or MODIFY
- [ ] Wire the reviewer into the CLI.
- [ ] Done when a live AA334 run makes 3 separate API calls per round and reaches consensus or the fallback, with a reviewer verdict.

**Checkpoint 2 (14:15–14:30)**
- [ ] Merge. Run live AA334 through the UI, and run `--force-deadlock`.
- [ ] Tell Sydelle to submit.
- [ ] Run a 10-row cost test: `eval/run_eval.py --n 10 --agents haiku`. Record the cost and time per scenario.

**Build block 3 (14:30–15:15)**
- [ ] Run the full `eval/run_eval.py` on 200 rows, comparing what actually happened, the solver alone, and agents plus solver.
- [ ] Record these metrics:
  - [ ] consensus rate within the turn cap
  - [ ] mean rounds
  - [ ] fallback rate
  - [ ] agent top picks that failed a rule
  - [ ] reviewer rejections
  - [ ] cited-value mismatches
  - [ ] schema-invalid message rate
  - [ ] estimated delay vs the real `ARRIVAL_DELAY`
  - [ ] latency and cost
- [ ] Hard cap of $15. Stop at 150 rows if the cost projects over.
- [ ] Commit `eval/results/summary.csv` and `per_scenario.csv` by **15:10**.

**Freeze (15:15–15:45)**
- [ ] Put the evaluation numbers into the README and the impact slide.
- [ ] Hide the organisers' PDF before going public: run `git rm --cached -r "problem statement"` and add the folder to `.gitignore`.
- [ ] Add an Apache-2.0 `LICENSE`, make the repo public and tag `v1.0-submission`.
- [ ] **Code freeze at 15:45.**

**Pitch (16:30):** drive the live demo.

---

## Waseem: Technical (T1)

**Kickoff (by 11:45)**
- [ ] Environment check: `pip install pandas pydantic anthropic streamlit pytest` on Python 3.14. Post the verdict in the group chat.
- [ ] If anything fails to install, everyone switches to Python 3.12: run `uv python install 3.12` and say so in the chat.
- [ ] Commit `requirements.txt`.
- [ ] Re-upload your real industry R&D file. `docs/waseem_industry_rd` is currently a copy of `timeline.md`. Save it as `docs/waseem_industry_rd.md` and delete the copy.

**Build block 1 (12:00–13:00)**
- [ ] `src/scenario/builder.py`: `build_scenario(row_index, seed=42) -> Scenario`. It must handle:
  - [ ] converting `hhmm` times to minutes, including `2400` and midnight wrap-around
  - [ ] delayed arrivals in the destination hour, tagged `data`
  - [ ] taxi time compared with the airport median
  - [ ] the same tail's later legs that day
  - [ ] the 3 nearest alternates by great-circle distance, skipping ECP, PBG and UST
  - [ ] seeded synthetic gates, crew and fuel, each with a source tag
- [ ] `src/options/menu.py`: `generate_candidates(s)` with slot ±15/±30, hold 20/40, divert to 2 alternates, 2 gate swaps and a ground hold at origin.
- [ ] `src/rules/engine.py`: `check_all(s, candidates)` with 6 rules, each citing its source:
  - [ ] `R-WAKE-01`
  - [ ] `R-FUEL-01`
  - [ ] `R-DUTY-01`
  - [ ] `R-GATE-01`
  - [ ] `R-TURN-01`
  - [ ] `R-AAR-01`
- [ ] Tests on row 0 and the N469AA row.
- [ ] Done when `pytest tests/test_scenario.py tests/test_rules.py` passes, and AA334 yields at least 8 candidates with at least 1 rule failure.

**Build block 2 (13:15–14:15)**
- [ ] Add edge-case tests:
  - [ ] midnight wrap
  - [ ] missing coordinates
  - [ ] no downstream legs
  - [ ] unmatched tail number
- [ ] `eval/sample.py`: a seeded sample of 200 rows (150 with `WEATHER_DELAY > 15` across ORD/ATL/DFW/DEN, 50 with `LATE_AIRCRAFT_DELAY > 20`). Commit `eval/sample_ids.csv`.
- [ ] Solver-only baseline: `--agents none` goes straight to the fallback.

**Build block 3 (14:30–15:15)**
- [ ] From the evaluation output, choose the **showcase failure case** (a reviewer REJECT or a deadlock that falls back). Save it as `runs/failure_showcase.json`, reproducible with one command.
- [ ] Write `docs/failure_case.md`: what happened, why, and what would fix it.
- [ ] Review Rohan's reviewer maths as a second pair of eyes.

**Pitch (16:30):** keep the failure case open in a terminal and answer the judges' rules questions.

---

## Reine: Technical (T2)

**Kickoff (by 11:45)**
- [ ] Draft the three system prompts in `src/agents/prompts/` as `atc.txt`, `pilot.txt` and `ground.txt`. Each prompt:
  - [ ] sees only its own domain's data
  - [ ] must reply in strict JSON matching `AgentMessage`
  - [ ] never claims something is legal, and never does arithmetic

**Build block 1 (12:00–13:00)**
- [ ] `src/agents/base.py`: `Agent.propose(s, candidates, round, prior) -> AgentMessage`.
- [ ] `StubAgent`: fixed, rule-of-thumb logic for each role that always returns a valid message.
- [ ] `ClaudeAgent(model)` using the anthropic SDK. It must:
  - [ ] cache the system prompt
  - [ ] retry once on invalid JSON, then raise `InvalidMessage` with the raw text (never silently repair it)
  - [ ] record tokens and cost for each call
- [ ] `tests/test_agents.py` against a hand-built `Scenario`.
- [ ] Done when the stub returns valid messages for all 3 roles, one real Haiku call passes the schema, and the cost per call is printed.

**Build block 2 (13:15–14:15)**
- [ ] `app/streamlit_app.py` with 4 panels:
  - [ ] **Scenario card:** source tags colour-coded.
  - [ ] **Turns table:** each agent's acceptable options, vetoes and rationale, plus an invalid-message count.
  - [ ] **Checks:** rule results, the reviewer verdict and what made the decision (consensus or fallback).
  - [ ] **Recommendation:** with **Approve / Reject** buttons that write to the log.
- [ ] A dropdown to pick any file in `runs/*.json`.
- [ ] Done when the UI shows the AA334 run and Approve writes a log line.
- [ ] If the UI isn't showing AA334 by **14:30**, cut it and use `cli --pretty` instead.

**Build block 3 (14:30–15:15)**
- [ ] Add an evaluation panel that reads `eval/results/summary.csv`.
- [ ] Add a failure-case preset button.
- [ ] Record a 60-second backup screen capture of the AA334 run and the failure case. Put copies on two laptops.

**Pitch (16:30):** hold the backup video and answer the judges' agent questions.

---

## Sydelle: Non-technical (N)

You can use Claude (claude.ai or Claude Code) to draft every document below. Point it at `docs/briefing.md`.

**Kickoff (by 11:45)**
- [ ] Ask the organisers:
  - [ ] Does resubmitting change our recorded submission time?
  - [ ] What does a submission need: a repo link, a video, form fields?
- [ ] Post the answers in the chat. They decide whether we submit at 14:30 and update at 15:45, or submit once at 15:30.
- [ ] Your API key is the app's key for the demo. Keep your own Claude Code use light, and give Rohan your key in person, not in chat.
- [ ] Start `docs/pitch.md` from the "Pitch framing" section (§10) of `briefing.md`.

**Build block 1 (12:00–13:00)**
- [ ] `docs/data_limits.md`: the 4 data limitations (briefing §4.1) and the real-vs-synthetic table (briefing §5).
- [ ] `docs/regulatory_sources.md`: check each value in briefing §9 against its primary source (FAA JO 7110.65 §5-5-4, 14 CFR 121.639, 14 CFR Part 117). Mark each one "verified" with a link, or "assumed".
- [ ] README skeleton with these sections: Problem → User → Architecture → How to run → Limitations → Results (left empty for now).

**Build block 2 (13:15–14:15)**
- [ ] Slides, version 1 in `docs/slides/`, at most 6:
  1. [ ] The user and today's process (the duty manager and the phone calls), with N469AA going from +101 to +256 minutes.
  2. [ ] Architecture diagram, with one box per component.
  3. [ ] Live demo placeholder.
  4. [ ] Evaluation table placeholder.
  5. [ ] Real vs synthetic data.
  6. [ ] Limitations and what would fix them.
- [ ] Impact slide: the real delay chain vs the chain under our recommendation, labelled "model estimate". Rohan fills in the number at 15:15.

**Checkpoint 2 (14:15–14:30)**
- [ ] **Submit at 14:30**: repo link, description, and the README as it stands. This is our valid submission.

**Build block 3 (14:30–15:15)**
- [ ] README sections:
  - [ ] Results
  - [ ] Limitations
  - [ ] "How the user knows it failed"
- [ ] Rehearse the pitch alone twice, with a timer.
- [ ] Check spend in the Console for all 4 keys at each checkpoint, and warn anyone over $30.

**Freeze (15:15–15:45)**
- [ ] Check every number in the pitch and README against a committed file (`eval/results/summary.csv`). Remove any number you can't trace.
- [ ] Submit the final update if the organisers allow it.

**Rehearse (15:45–16:15)**
- [ ] Run three timed run-throughs, aiming for 2:45. Order and timing:
  - [ ] user and status quo, 25 s
  - [ ] architecture, 20 s
  - [ ] live demo, 50 s
  - [ ] rejection and fallback, 30 s
  - [ ] evaluation table, 30 s
  - [ ] limitations, 25 s
- [ ] At **16:00**, confirm the submission shows as received.

**Pitch (16:30):** you present.

**All day:** keep time, announcing each checkpoint 5 minutes before it starts.
