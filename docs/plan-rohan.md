# Rohan (L) — build plan, 11:54 → 15:45 freeze

Scope: `src/log/`, `src/fallback/`, `src/mediator/`, `src/cli.py`, `src/reviewer/`, `eval/run_eval.py`, merges, live demo. Everything else is settled; this plan references other people's interfaces only where my code depends on them.

Rubric points my modules carry: **Technical soundness** (turn cap, deterministic fallback, end-to-end on any row), **Trust & traceability** (log, reviewer, invalid messages rejected not repaired), **Honest evaluation** (harness, metrics, failure case), **Impact** (the before/after numbers come out of my harness).

---

## 0. Five interface notes to post in chat before 12:00 (do this first, 5 minutes)

My modules depend on four things that are not pinned down in `schemas.py`. Post these now so Waseem and Reine build to them; all are additive, nothing frozen changes.

1. **`row_index` definition (Waseem):** `row_index` = 0-based positional index of `data/flights.csv` read with `pd.read_csv(..., keep_default_na=True)` in file order. No sorting, no dropping rows. I will post the AA334 row index at 12:15 (see §1).
2. **Field semantics I re-derive from (Waseem):** `fuel_reserve_min.value` = minutes of flying time available beyond the planned arrival at destination (before any reserve is eaten). `crew_duty_remaining_min.value` = minutes of FDP remaining at *scheduled* arrival. `alternates[i]` = `{"iata", "distance_nm"}`. `nominal_aar.value` = arrivals/hour. `check_all` returns one `RuleResult` for **every (rule, candidate) pair**, including passes. If you can't give me these, tell me what you give me instead.
3. **Agent kwarg (Reine):** `Agent.propose(s, candidates, round, prior, others=None)` — `others` is the other two agents' most recent valid `AgentMessage`s. Default `None`, so nothing of yours breaks. Round 2 needs it: an agent can't concede toward anything if it doesn't know what the others accept. My mediator calls with `others=` inside a `try/except TypeError` and falls back to the 4-arg call, so I'm not blocked either way.
4. **Cited-field format (Reine, into the prompts she's drafting now):** `cited_fields` entries are `"<dotted.path>=<value>"`, e.g. `"fuel_reserve_min=78"`, `"flight.ARRIVAL_DELAY=101"`, `"alternates[0].distance_nm=190"`. The reviewer cross-checks the value against the Scenario; an entry without `=` gets an existence check only.
5. **Cost accounting + model IDs (Reine):** `ClaudeAgent` keeps `self.calls: list[dict]` with `{round, tokens_in, tokens_out, cache_read_tokens, cost_usd, latency_s, valid: bool}`; `src/agents/base.py` exposes `MODEL_IDS = {"haiku": "...", "sonnet": "..."}`. My CLI sums `calls` for the run meta and imports `MODEL_IDS`. Also: **`StubAgent` round 2 must return a superset of its round-1 `acceptable`** (monotonic concession), otherwise the stub path always falls back.

Also tell Waseem: `--agents none` (solver-only baseline) lives in `src/cli.py`, so I own it; his checklist item for it is done by me.

---

## 1. Schedule (my sessions only)

I run **two Claude Code sessions** on `l/*` branches: **Session A** (core: log → fixtures → fallback → mediator), **Session B** (cli → eval harness). The reviewer gets a **fresh Session C** with no rules code in context (see §3.5). Commit every 20 min with `L:` prefix.

| Time | Session | Work | Done when |
|---|---|---|---|
| 11:54–12:00 | — | Post §0 notes. `git checkout -b l/core`. Open Session A with: *"Read CLAUDE.md, docs/briefing.md, docs/timeline.md. You are Rohan's session; edit only src/log, src/fallback, src/mediator, src/cli.py, src/reviewer, eval/run_eval.py, tests/test_log.py, tests/test_fallback.py, tests/test_mediator.py, tests/test_cli.py, tests/test_reviewer.py, tests/fixtures/."* | |
| 12:00–12:10 | A | `src/log/consensus_log.py` + `tests/test_log.py` (§3.1) | test green |
| 12:10–12:15 | shell | Find AA334 row index, post it: `python -c "import pandas as pd; d=pd.read_csv('data/flights.csv'); print(d.index[(d.AIRLINE=='AA')&(d.FLIGHT_NUMBER==334)&(d.MONTH==4)&(d.DAY==24)&(d.TAIL_NUMBER=='N469AA')].tolist())"`. Write it into `eval/showcase.json` `{"row_index": N, "label": "AA334 MFE->DFW 2015-04-24 N469AA"}` and commit. | index in chat |
| 12:15–12:30 | A | `tests/fixtures/aa334_fixture.py` + `tests/fixtures/fixture_agents.py` (§2) | fixtures import, validate against schemas |
| 12:30–12:40 | A | `src/fallback/solver.py` + `tests/test_fallback.py` (§3.2) | test green |
| 12:40–13:00 | A | `src/mediator/protocol.py` + `tests/test_mediator.py` (§3.3) | 7 tests green |
| 12:40–13:00 | B (parallel, `l/cli`) | `src/cli.py` with `run_one()` and `--agents fixture` (§3.4); `python -m src.cli --row-id 0 --agents fixture` writes `runs/*.json` + `.jsonl` | runs end to end on fixtures |
| 12:55 | — | Announce checkpoint in 5 min; `pytest -q` on my branch; push. | |
| **13:00–13:15** | — | **Checkpoint 1 merge** (§4.1). Eat at desk. | `main`: `pytest -q`, `cli --row-id <AA334> --agents stub`, `--force-deadlock` all pass |
| 13:15–13:35 | shell + Reine | Live AA334 with `--agents haiku` on my own key. Fix prompt/schema mismatches with Reine (she edits prompts, I edit mediator). Inspect the `.jsonl` by hand: 3 `agent_message` events per round, no silent repair. | live run reaches consensus or fallback; cost per scenario noted |
| 13:35–14:05 | **C (fresh)** | `src/reviewer/safety.py` + `tests/test_reviewer.py` (§3.5). Session C never sees `src/rules/`. | tests green incl. injected unsafe candidate → REJECT |
| 13:35–14:05 | B | `eval/run_eval.py` skeleton over `run_one()` (§3.6): sample loading, solver-only pass, agents pass, per-row append, cost/time guard, summary writer. Test with `--n 3 --agents stub`. | `eval/results/` written for n=3 stub |
| 14:05–14:15 | A | Wire reviewer into `run_one()`: REJECT → fallback with exclusion; `--tamper-rules` fault-injection flag only if reviewer is done by 14:05 (else cut). Push. | `cli --agents stub --tamper-rules` shows REJECT → fallback |
| **14:15–14:30** | — | **Checkpoint 2 merge** (§4.2). Live AA334 through Reine's UI. `--force-deadlock` through UI. Tell Sydelle **submit at 14:30**. Swap `.env` to Sydelle's key for eval. | submission recorded |
| 14:30–14:45 | B | `python -m eval.run_eval --n 10 --agents haiku`. Read `$`/scenario, s/scenario, reviewer disagreement rate, invalid rate. Set `--workers`. If reviewer–engine disagreement > 30% on wake: diff the two assumption sets against `docs/regulatory_sources.md` with Waseem, fix the wrong one (10 min max), note the finding for the write-up. | go/no-go for 200 rows |
| 14:45–15:05 | B | Full run: solver-only pass (free, ~1 min) then `--n 200 --agents haiku --workers 6 --budget-usd 15 --deadline 15:05`. Meanwhile Session A writes `eval/make_summary.py` → `summary.md`. | per_scenario.csv complete or guard-stopped with `n_completed` recorded |
| 15:05–15:15 | — | Commit `eval/results/{summary.csv,per_scenario.csv,summary.md,meta.json}`. Hand Sydelle the numbers. Hand Waseem `per_scenario.csv` so he picks the showcase failure case. If Haiku finished by 15:00 and spend < $8: start Sonnet 50-row sweep in background (cut candidate #2). | summary committed by **15:10** |
| **15:15–15:45** | — | **Checkpoint 3** (§4.3): merge, numbers into README/impact slide, `git rm --cached -r "problem statement"`, `.gitignore`, `LICENSE` (Apache-2.0), repo public, tag `v1.0-submission`. **15:45 freeze.** | tag pushed |
| 15:45–16:15 | — | Demo prep (§6). Three rehearsals with Sydelle. | |

---

## 2. Unblocking myself before Waseem's and Reine's code exists

Everything I own is downstream of `build_scenario`, `generate_candidates`, `check_all` and the agents. Until 13:00 those raise `NotImplementedError`. I own `tests/`, so fixtures live there and stay as unit-test inputs after the merge.

**`tests/fixtures/aa334_fixture.py`** — hand-built, validated against `schemas.py`:
- `fixture_scenario()` → an AA334-shaped `Scenario` (DFW, dep delay 114, arr delay 101, `fuel_reserve_min=Tagged(78,"estimated")`, `crew_duty_remaining_min=Tagged(150,"synthetic")`, `wake_category=Tagged("L","assumed")`, 3 alternates incl. AUS 190 NM, 3 downstream legs, `nominal_aar=Tagged(90,"assumed")`, `dest_disruption=Tagged(14,"data")`).
- `fixture_candidates()` → 8 candidates: `SLOT+15, SLOT+30, SLOT-15, HOLD20, HOLD40, DIVERT_AUS, GATE_B12, GROUND_HOLD_MFE` with plausible `est_delay_min`/`est_knock_on_min`.
- `fixture_rule_results()` → 6 rules × 8 candidates = 48 `RuleResult`s; `HOLD40` fails `R-FUEL-01`, `DIVERT_AUS` fails `R-DUTY-01`, everything else passes. Each carries a source tag and citation.

**`tests/fixtures/fixture_agents.py`** — `FixtureAgent(Agent)` subclassing Reine's existing `Agent` base (the class exists, only `propose` is unimplemented). Accepts `others=None`. Modes drive mediator tests:

| mode | round 1 | round 2 | mediator outcome |
|---|---|---|---|
| `converge` | pairwise overlap but empty 3-way intersection (ATC {SLOT+15,SLOT+30}, PILOT {SLOT+30,HOLD20}, GROUND {HOLD20,GATE_B12}) | each adds one id so `SLOT+30` is common | consensus, round 2 |
| `converge_r1` | all three include `SLOT+15` | n/a | consensus, round 1 |
| `unsafe_consensus` | all three include only `HOLD40` | superset incl. `HOLD40` only | ∩ non-empty but fails rules → fallback `no_consensus` |
| `deadlock` | disjoint | still disjoint | fallback `no_consensus` |
| `shrink` | as converge | drops an id | fallback `monotonic_violation` |
| `invalid` | raises `InvalidMessage` for PILOT | — | fallback `invalid_message` |
| `unknown_id` | acceptable includes `"BOGUS"` | — | fallback `invalid_message` (reason `unknown_candidate`) |
| `veto_conflict` | same id in `acceptable` and `vetoes` | — | fallback `invalid_message` (reason `veto_acceptable_conflict`) |

**`src/cli.py --agents fixture`**: dev mode that uses the fixture scenario/candidates/rules and `FixtureAgent(mode="converge")`, bypassing Waseem's modules. Kept after merge (it's how `tests/test_cli.py` runs without `flights.csv` loaded), documented as test-only.

---

## 3. Modules in build order

### 3.1 `src/log/consensus_log.py` (12:00–12:10)

**Decisions.** One JSON object per line; every event has `ts` (ISO 8601 with `+08:00`), `event`, `scenario_id`, plus payload. Open-append-close on every call (crash-safe; a killed eval run still leaves complete lines). Pydantic objects serialised via `model_dump()`; `NaN`/`inf` → `null`; `ensure_ascii=False`. Parent dir created on first append. No in-memory buffering, no rotation.

**Canonical event vocabulary** (the UI and harness read these names; freeze them now):

| event | payload |
|---|---|
| `run_start` | row_index, agents_mode, model, seed, flags `{force_deadlock, tamper_rules}`, git_sha |
| `scenario_built` | source_tag_counts `{data,estimated,assumed,synthetic}`, n_downstream_legs, n_alternates |
| `candidates_generated` | n, candidate_ids |
| `rule_check` | one per `RuleResult`: rule_id, candidate_id, passed, observed, threshold, source, citation |
| `round_start` | round |
| `agent_message` | round, agent, acceptable, vetoes, top_choice, n_ranked, tokens_in, tokens_out, cost_usd, latency_s |
| `message_invalid` | round, agent, reason ∈ {schema, unknown_candidate, veto_acceptable_conflict, monotonic_violation, exception}, raw_text, error |
| `intersection` | round, acceptable_intersection, rules_pass_intersection |
| `consensus` | round, candidate_id, summed_score, per_agent_scores |
| `fallback_fired` | reason ∈ {no_consensus, invalid_message, monotonic_violation, forced_deadlock, solver_only, reviewer_reject}, candidate_id or null, objective, n_eligible, weights, excluded |
| `reviewer_verdict` | verdict, notes, re_derived (list), cited_mismatches (list), engine_disagreements (list) |
| `recommendation` | decided_by, candidate_id, rounds_used, reviewer_verdict |
| `human_decision` | decision, by, note — written by Reine's UI |
| `run_end` | latency_s, cost_usd, tokens_in, tokens_out |

**Tests (`tests/test_log.py`).** (1) two appends → two parseable lines, timestamps monotonic, tz present; (2) a dict containing a `Tagged` model and a `float("nan")` round-trips as JSON with `null`; (3) appending after process restart appends, doesn't truncate.

**Claude Code prompt (Session A):**
```
Read CLAUDE.md, docs/briefing.md, docs/timeline.md. Implement src/log/consensus_log.py.
ConsensusLog(path).append(event: dict) writes one JSON object per line. Rules:
- add "ts" (ISO 8601 with +08:00 offset) if absent; require "event" and "scenario_id" keys,
  raise ValueError otherwise.
- open in append mode and close on every call; mkdir parents on first write.
- serialise pydantic BaseModel values with model_dump(); convert NaN/inf to None recursively;
  json.dumps(ensure_ascii=False, default=str).
- No buffering, no rotation, no other methods except `read_all() -> list[dict]` for tests/UI.
Put the event-name vocabulary from the module docstring (I will paste it) as a
frozenset EVENTS and warn (not raise) on an unknown event name.
Write tests/test_log.py covering: two appends parse and are ordered; NaN and a Tagged value
round-trip; append after re-instantiating the class does not truncate. Run pytest -q.
```

### 3.2 `src/fallback/solver.py` (12:30–12:40)

**Decisions.** Pure, no agent input — "deterministic non-AI fallback" means the agents' opinions are not consulted at all. Eligible = candidates where *every* `RuleResult` for that id has `passed=True` **and** at least one `RuleResult` exists (unchecked candidate = ineligible; logged by caller as a warning). Objective = `weights["delay"]*est_delay_min + weights["knock_on"]*est_knock_on_min`. Ties → lowest `candidate_id` lexicographically (deterministic). Additive kwarg `exclude: set[str] = frozenset()` for reviewer rejections. Returns `None` if nothing is eligible — this is the "escalate to human, no safe option" state and must stay representable. Also return the objective and eligible count via a second function `fallback_explain(...) -> dict` so the log has `objective` and `n_eligible` without recomputing.

**Edge cases.** Empty candidates; all fail; candidate with missing `RuleResult`s; negative `est_delay_min` (an early slot) is allowed; weights missing a key → `KeyError` on purpose (weights live in one dict, `DEFAULT_WEIGHTS`, and are logged).

**Tests.** (1) fixture rules → picks the lowest-objective passing candidate, never `HOLD40`/`DIVERT_AUS`; (2) `exclude` of the winner → next best; (3) all failing → `None`; (4) unchecked candidate ignored; (5) tie-break deterministic; (6) changing weights changes the pick.

**Prompt (Session A):**
```
Implement src/fallback/solver.py per its docstring and CLAUDE.md. Keep the frozen signature
and add an optional kwarg exclude: set[str] = frozenset(). Eligibility: a candidate is
eligible only if it has >=1 RuleResult and all of them passed, and it is not excluded.
Objective: weights["delay"]*est_delay_min + weights["knock_on"]*est_knock_on_min, argmin,
ties broken by candidate_id ascending. Return None if nothing eligible.
Also add fallback_explain(candidates, rule_results, weights, exclude) -> dict with keys
{"chosen": id|None, "objective": float|None, "n_eligible": int, "eligible_ids": [...],
"excluded": [...], "unchecked": [...]} so the caller can log it. No randomness, no LLM.
Use tests/fixtures/aa334_fixture.py for tests/test_fallback.py: six tests (best pick,
exclude, none eligible, unchecked ignored, tie-break, weights change pick). Run pytest -q.
```

### 3.3 `src/mediator/protocol.py` (12:40–13:00)

**Decisions (recommendations in bold).**
- **"Under 3 turns" = `max_rounds=2`; the fallback is turn 3.** Hard-coded default, logged.
- **Consensus** = (∩ of all valid agents' `acceptable`) ∩ (candidates passing all rules) ≠ ∅. Pick the candidate with the highest **summed ranking score** across agents (score clamped to [0,1], missing entry = 0); tie → lower `est_delay_min+est_knock_on_min`, then `candidate_id`.
- **Agents never receive rule results.** `negotiate` takes `rules` only to compute consensus; the call to `propose` passes `s, candidates, round, prior, others`. This is how the harness measures "agent top picks that fail a rule".
- **Invalid message ⇒ fallback immediately** (spec: fallback fires on "a malformed message"). Reasons: `schema` (Reine's `InvalidMessage`, after her one retry), `unknown_candidate`, `veto_acceptable_conflict`, `monotonic_violation`, `exception` (any other error from the agent call — network, timeout — captured as text, never swallowed). The raw text and error go into `Turn.invalid_messages` and a `message_invalid` log event. The remaining agents in that round are still called (their messages are logged) so the schema-invalid rate is measured over all calls, but the decision goes to the fallback. **No repair ever.**
- **Monotonic concession**: round-2 `acceptable` ⊇ round-1 `acceptable` for the same agent, else `monotonic_violation`. Vetoes may be withdrawn in round 2 but a round-1 acceptable id cannot gain a veto.
- **`force_deadlock=True`**: after each valid message, overwrite `acceptable` with a disjoint slice (`candidates[i::3]` for agent i) so the real MCP path runs and the fallback fires with reason `forced_deadlock`. Logged; the harness refuses to count forced runs.
- Return `Recommendation` with `reviewer_verdict="APPROVE"` and empty notes as a placeholder; the CLI replaces it after `review()`. `decided_by` and `rounds_used` are set here. `log_path` set by caller.
- Signature stays frozen; `log: ConsensusLog | None = None`, `force_deadlock=False` and `weights=DEFAULT_WEIGHTS` are additive kwargs.

**Edge cases.** Agent list of length ≠ 3 or duplicate roles → `ValueError`. Round 1 consensus → return after 1 round (don't call round 2). An agent's `acceptable` empty but valid → allowed (it's a legitimate "nothing acceptable yet"). `others` passed as the other two agents' most recent valid messages. `TypeError` on `others=` → retry without it, log `agent_interface: legacy`.

**Tests (`tests/test_mediator.py`)**, one per fixture mode: converge→consensus round 2; converge_r1→consensus round 1 with 3 messages, round 2 not called; unsafe_consensus→fallback `no_consensus` and chosen ≠ HOLD40; deadlock→fallback; shrink→`monotonic_violation` recorded in `Turn.invalid_messages` and log; invalid→fallback with raw text in log; unknown_id→invalid; force_deadlock→`forced_deadlock` reason. Plus: log contains exactly 3 `agent_message` events per round and the `intersection` event per round.

**Prompt (Session A):**
```
Read CLAUDE.md and the docstring of src/mediator/protocol.py. Implement negotiate() with the
frozen signature plus additive kwargs: log: ConsensusLog | None = None,
force_deadlock: bool = False, weights=DEFAULT_WEIGHTS from src/fallback/solver.py.
Protocol (max_rounds=2, Monotonic Concession):
1. For each round: call agent.propose(s, candidates, round, prior=own previous valid message
   or None, others=[other agents' most recent valid messages]) inside try/except TypeError
   -> retry without others and log event agent_interface. Any other exception, or
   src.agents.base.InvalidMessage, becomes an invalid message (reason "schema" or
   "exception") with raw text; never repair, never retry here.
2. Validate each message: agent role matches; round matches; every id in acceptable, ranking,
   vetoes exists in candidates (else "unknown_candidate"); no id in both acceptable and
   vetoes ("veto_acceptable_conflict"); in round 2 acceptable must be a superset of the
   agent's round-1 acceptable ("monotonic_violation").
3. If force_deadlock, replace each valid message's acceptable with candidates[i::3] ids.
4. Always call all three agents in the round and log agent_message / message_invalid for
   each. Then: if any invalid -> stop and fall back (reason = the first invalid reason, or
   "forced_deadlock"). Else compute intersection of acceptable sets, then intersect with
   the set of candidates whose every RuleResult passed. Log event intersection. Non-empty ->
   consensus: choose max summed clamped ranking score, tie-break lower
   est_delay_min+est_knock_on_min then candidate_id; log consensus; return.
5. After max_rounds with no consensus -> fallback_pick(..., weights) and fallback_explain;
   log fallback_fired with reason "no_consensus". Agents NEVER receive rule results.
Return (Recommendation, turns). Recommendation.reviewer_verdict="APPROVE", reviewer_notes=[]
as placeholders (the CLI sets them), log_path="" (CLI sets). Record the fallback reason and
explain dict on the Recommendation via an additive field: edit src/schemas.py ONLY to add
`fallback: dict | None = None` to Recommendation (additive, allowed).
Write tests/test_mediator.py using tests/fixtures/fixture_agents.py modes converge,
converge_r1, unsafe_consensus, deadlock, shrink, invalid, unknown_id, veto_conflict, plus a
force_deadlock test; assert on log events too. Run pytest -q.
```
(Adding `fallback: dict | None = None` to `Recommendation` is additive and mine to make; announce it in chat when pushed.)

### 3.4 `src/cli.py` (Session B, 12:40–13:00; reviewer wiring 14:05–14:15)

**Decisions.** The core is a reusable `run_one(row_index, agents_mode, out_dir, seed=42, force_deadlock=False, tamper_rules=False, max_rounds=2, weights=None, fixture=False) -> dict`; `main()` only parses args and prints. `eval/run_eval.py` imports `run_one` so the harness and the demo share one code path (no "polished UI over a different pipeline"). Agent factory: `stub` → `StubAgent×3`; `haiku`/`sonnet` → `ClaudeAgent(role, MODEL_IDS[mode])`; `none` → skip `negotiate`, call `fallback_pick` directly, log `fallback_fired reason=solver_only`, `rounds_used=0`; `fixture` → `FixtureAgent`. `--pretty` prints a compact table (candidate, rule pass/fail per rule, each agent's acceptable set, decided_by, verdict). Cheap, and it's the cut-#7 replacement if the UI dies.

**Output `runs/<scenario_id>.json`** (Reine's UI reads this — post the layout at 12:50):
```
meta: {scenario_id,row_index,agents,model,seed,flags,started_at,latency_s,cost_usd,tokens_in,tokens_out,git_sha}
scenario, candidates, rule_results, turns, recommendation   (model_dump of each)
fallback: {fired,reason,objective,n_eligible,excluded}
reviewer: {verdict,notes,re_derived,cited_mismatches,engine_disagreements}
```
`recommendation.log_path` = `runs/<scenario_id>.jsonl`. Same `scenario_id` run twice overwrites `.json` and **appends** to `.jsonl` (append-only log; the UI shows the latest run but the history survives). For eval runs, `out_dir=eval/results/runs/` to keep demo `runs/` clean.

**Reviewer wiring (14:05).** After `negotiate`: `verdict, notes = review(s, rec, turns)`. On `REJECT`: `fallback_pick(exclude={rejected id} ∪ reviewer-failed ids)`, re-run `review` once on the new pick, set `decided_by="fallback"`, log `fallback_fired reason=reviewer_reject`. If still REJECT or `None` → `chosen=None`, verdict REJECT, note `"no candidate passes engine and reviewer; escalate to duty manager"`. `MODIFY` → recommendation stands, notes attached, nothing else changes. `--tamper-rules` (fault injection, only if time): flips the first failing `RuleResult` of the lowest-objective failing candidate to `passed=True` before negotiation and logs `tamper: true` — demonstrates the reviewer catching an upstream fault end-to-end; the harness refuses tampered runs.

**Edge cases.** `row_index` out of range → clear error. Missing `.env`/key with `haiku` → fail fast before building the scenario. `KeyboardInterrupt` mid-run still writes `run_end` with `aborted: true`.

**Tests (`tests/test_cli.py`).** `run_one(fixture=True, agents_mode="fixture")` writes both files, JSON validates by reloading into the schemas; `agents_mode="none"` gives `rounds_used=0` and `fallback.reason=="solver_only"`; `force_deadlock` gives `fallback.reason=="forced_deadlock"`.

**Prompt (Session B):**
```
Read CLAUDE.md, docs/timeline.md §4 and src/cli.py's docstring. Implement src/cli.py.
Core function run_one(row_index, agents_mode, out_dir="runs/", seed=42, force_deadlock=False,
tamper_rules=False, max_rounds=2, weights=None, fixture=False) -> dict. Pipeline:
build_scenario -> generate_candidates -> check_all -> (negotiate | solver-only) -> review ->
write <out_dir>/<scenario_id>.json and append <scenario_id>.jsonl via ConsensusLog.
- fixture=True or agents_mode=="fixture": use tests/fixtures/aa334_fixture.py data and
  tests/fixtures/fixture_agents.FixtureAgent(mode="converge") instead of src.scenario/
  options/rules and src.agents. This is a dev/test path; keep it.
- agents_mode "stub" -> three StubAgent; "haiku"/"sonnet" -> ClaudeAgent(role,
  MODEL_IDS[mode]) from src.agents.base (if MODEL_IDS is missing, read env HAIKU_MODEL /
  SONNET_MODEL); "none" -> skip negotiate, call fallback_pick + fallback_explain, log
  fallback_fired reason="solver_only", rounds_used=0, turns=[].
- Reviewer: for now call src.reviewer.safety.review inside try/except NotImplementedError
  -> verdict "APPROVE", notes ["reviewer not implemented"]. I will wire REJECT handling later.
- Log run_start, scenario_built (count Tagged fields by source), candidates_generated,
  one rule_check per RuleResult, recommendation, run_end. Sum cost/tokens/latency from each
  agent's `calls` list if present.
- Write the JSON layout exactly: meta, scenario, candidates, rule_results, turns,
  recommendation, fallback, reviewer. meta includes git_sha (subprocess, "unknown" on error).
- main(): add --agents choice "fixture", --seed, --max-rounds, --tamper-rules (stored, no-op
  for now), --pretty (tabular summary to stdout). Fail fast with a clear message if --agents
  haiku/sonnet and ANTHROPIC_API_KEY is unset. Load .env with python-dotenv if available.
Write tests/test_cli.py (fixture mode end-to-end, none mode, force_deadlock) and run pytest -q.
Then run: python -m src.cli --row-id 0 --agents fixture --pretty
```

### 3.5 `src/reviewer/safety.py` (Session C, fresh context, 13:35–14:05)

**What "independent" means, concretely.**
1. A new Claude Code session whose context contains `CLAUDE.md`, `src/schemas.py`, `docs/regulatory_sources.md`, the §0 field semantics and this spec — and **not** `src/rules/engine.py`, not Waseem's tests, not the fixture rule results. I don't open the rules code myself before this session ends.
2. The reviewer derives pass/fail **from `Scenario` and `Candidate.params` only**. It never reads `rule_results` to decide; it reads them afterwards only to report where it disagrees with the engine.
3. It recomputes the delay a candidate causes from `params`, not from `est_delay_min`.
4. Constants come from `docs/regulatory_sources.md` (Sydelle, verified/assumed status). If the two implementations disagree, the fix is to reconcile against that doc, never to copy code. Disagreement is itself reported in the eval as `reviewer_engine_disagreement_rate` — it is evidence of the check working.

**What it re-derives (three safety checks; nothing else blocks).**

| check | derived quantity | pass if | constants |
|---|---|---|---|
| FUEL (14 CFR 121.639) | `airborne_extra_min`: hold → `params.minutes`; slot_shift → `max(shift,0)`; divert → `alternates[iata].distance_nm / 7.0` (420 kt ≈ 7 NM/min, assumed); gate_swap / ground_hold → 0 | `fuel_reserve_min.value − airborne_extra_min ≥ 45` | 45 min reserve (verify status from Sydelle's doc) |
| DUTY (14 CFR 117) | `delay_min`: hold → minutes; slot → shift; divert → divert time + 60 min assumed ground time at alternate; ground_hold → minutes; gate_swap → `params.get("extra_taxi_min", 0)` | `crew_duty_remaining_min.value − delay_min ≥ 0` | — |
| WAKE (FAA JO 7110.65 §5-5-4) | required spacing: leader assumed Heavy (conservative); `sep_nm` = {H:4, L:5, S:6}[`wake_category`]; `required_s = sep_nm / (140 kt / 3600)`; available spacing `avail_s = 3600 / effective_aar` with `effective_aar = max(nominal_aar − dest_disruption, 1)` for the candidate's arrival hour | `avail_s ≥ required_s` | approach 140 kt assumed |

Also recomputes `delay_min` and compares to `Candidate.est_delay_min`: disagreement > 20% relative (and > 5 min absolute) → a note, not a verdict change.

**Cited-value cross-check.** For every agent in `turns` whose round-final `acceptable` contains the chosen candidate, parse each `ranking`/`vetoes` `cited_fields` entry `"path=value"`; resolve `path` against `Scenario` (dotted, `[i]` indexing, `Tagged` resolves to `.value`). Tolerance: numeric |Δ| ≤ max(1.0, 2% of scenario value); strings case-insensitive exact. Unresolvable path → mismatch `unknown_field`. Entries without `=` → existence check only.

**Verdict.**
- **REJECT**: any of FUEL/DUTY/WAKE fails for the chosen candidate, **or** the engine marked the chosen candidate as failing any rule (consensus should already exclude this; if it happens it's a mediator bug and must surface), **or** `chosen is None` already. Safety-conservative: if either implementation says fail, it's a fail.
- **MODIFY**: all three pass, but ≥ 1 cited-value mismatch among the supporting agents, or the delay re-derivation disagrees > 20%, or the engine and reviewer disagree on a *non-chosen* candidate (reported, since it affects the fallback's eligibility). Recommendation stands; UI shows amber; human decides with the notes visible.
- **APPROVE**: everything agrees within tolerance.
- For `--agents none` runs there are no citations; verdict is APPROVE/REJECT on the re-derivation alone.

**Notes format** (human-readable, every one cites a rule/source): `"FUEL re-derived: HOLD40 needs 40+45=85 min; fuel_reserve_min=78 (estimated) → FAIL [14 CFR 121.639]"`, `"CITED: PILOT ranked SLOT+30 citing fuel_reserve_min=95; scenario has 78 (estimated) → mismatch"`, `"ENGINE: R-WAKE-01 passed SLOT+15, reviewer fails it (required 128 s, available 90 s) → disagreement"`.

**Return** `(verdict, notes)` as frozen; store the structured detail on the Recommendation's additive `reviewer_detail: dict | None = None` field (another additive schema change, mine to make) so the UI and harness don't parse strings.

**Tests (`tests/test_reviewer.py`)** — built in Session C against the fixture scenario but with its *own* expected numbers (worked by hand in the prompt): (1) `SLOT+15` consensus with correct citations → APPROVE; (2) injected `Recommendation` choosing `HOLD40` (fuel 78 − 40 = 38 < 45) → REJECT with the FUEL note; (3) `DIVERT_AUS` with duty 150 and derived delay 190/7+60 ≈ 87 min → passes duty, so fixture rule result disagreement shows up as MODIFY/notes (this exercises the engine-disagreement path honestly); (4) a message citing `fuel_reserve_min=95` → MODIFY with a `CITED` note; (5) unknown path `foo.bar=1` → mismatch; (6) `chosen=None` → REJECT.

**Prompt (Session C — paste only this, plus the files it names):**
```
You are implementing an independent safety reviewer. Read CLAUDE.md, src/schemas.py and
docs/regulatory_sources.md ONLY. Do NOT open or read anything under src/rules/, src/options/,
src/scenario/, tests/test_rules.py or tests/fixtures/aa334_fixture.py's rule results; this
module must be an independent re-derivation of the safety checks, so it may only use the
Scenario, the Candidate.params and the turns. Field semantics:
fuel_reserve_min.value = minutes of fuel beyond planned destination arrival;
crew_duty_remaining_min.value = FDP minutes left at scheduled arrival; alternates =
[{iata, distance_nm}]; nominal_aar.value arrivals/hour; dest_disruption.value delayed
arrivals in the destination hour; wake_category.value in {"H","L","S"}.
Candidate.params conventions: hold -> {"minutes"}; slot_shift -> {"shift_min"} (may be
negative); divert -> {"iata"}; ground_hold -> {"minutes"}; gate_swap -> {"gate",
"extra_taxi_min"?}; tail_swap -> {}. Use .get with safe defaults and record a note when a
param is missing.
Implement src/reviewer/safety.py: review(s, rec, turns) -> (verdict, notes), and also
review_detail(s, rec, turns) -> dict {"verdict","notes","re_derived":[{check, candidate_id,
derived, threshold, passed, citation}], "cited_mismatches":[{agent, round, candidate_id,
path, cited, actual, tolerance}], "engine_disagreements":[{rule_id, candidate_id,
engine_passed, reviewer_passed}], "derived_delay_min": float|None}.
Checks for the CHOSEN candidate (constants from docs/regulatory_sources.md; mark assumed):
FUEL: airborne_extra = hold minutes | max(shift,0) | divert distance_nm/7.0 | 0; pass iff
fuel_reserve_min - airborne_extra >= 45 (14 CFR 121.639).
DUTY: delay = hold minutes | shift | divert time + 60 | ground_hold minutes | extra_taxi_min
or 0; pass iff crew_duty_remaining_min - delay >= 0 (14 CFR 117).
WAKE: sep_nm {H:4,L:5,S:6}[wake_category] behind an assumed Heavy leader; required_s =
sep_nm / (140/3600) kt-assumed; available_s = 3600 / max(nominal_aar - dest_disruption, 1);
pass iff available_s >= required_s (FAA JO 7110.65 5-5-4).
Run the same three checks on every candidate too, and compare each with rec.rule_results
(match on rule_id prefixes R-FUEL, R-DUTY, R-WAKE) to fill engine_disagreements; never use
rule_results to decide the verdict.
Cited values: for each AgentMessage in turns whose final acceptable set contains the chosen
id, parse every cited_fields entry "path=value" (dotted paths, [i] indexes, Tagged -> .value);
numeric tolerance max(1.0, 2% of actual); strings case-insensitive; no "=" -> existence
only; unresolvable -> mismatch "unknown_field".
Verdict: REJECT if chosen is None, or any of FUEL/DUTY/WAKE fails for chosen, or any
rec.rule_results entry for chosen has passed=False. Else MODIFY if any cited mismatch, or
derived delay differs from est_delay_min by >20% and >5 min, or any engine disagreement on
any candidate. Else APPROVE. Every note is one sentence that names the check, the numbers,
the source tag of the inputs and the citation.
Write tests/test_reviewer.py with a small hand-built Scenario (fuel 78 estimated, duty 150
synthetic, wake L assumed, nominal_aar 90, dest_disruption 14, alternate AUS 190 NM) and
candidates SLOT+15, HOLD40, DIVERT_AUS, covering APPROVE, REJECT on HOLD40 (fuel 38 < 45),
MODIFY on a cited fuel_reserve_min=95, unknown_field, chosen=None, and an engine
disagreement. Run pytest tests/test_reviewer.py.
```

### 3.6 `eval/run_eval.py` (Session B, 13:35–14:05 skeleton; runs 14:30–15:05)

**Inputs.** `eval/sample_ids.csv` (Waseem, 200 row indices, seed 42). If absent at 14:30, `--sample-ids` points at a file I generate with the same spec inline (150 `WEATHER_DELAY>15` at ORD/ATL/DFW/DEN, 50 `LATE_AIRCRAFT_DELAY>20`, seed 42) — same recipe, temporary.

**Three-way comparison, per row.**
1. **Actual** (data): `ARRIVAL_DELAY` of the row; `actual_chain_delay` = sum of `ARRIVAL_DELAY` over `scenario.downstream_legs` (data, partial — only delayed legs exist).
2. **Solver-only**: `run_one(row, "none")` → chosen id, `est_delay_min`, `est_knock_on_min`, verdict. Free; run first for all rows.
3. **Agents + solver**: `run_one(row, "haiku")` → everything above plus negotiation metrics.
The honest framing: 2 and 3 are **model estimates of the delay the recommendation would induce**; 1 is what happened. They are not the same quantity. The summary reports them side by side with the label `modelled`, and reports `agents_vs_solver_same_pick_rate` — the one like-for-like comparison (does negotiation change the decision, and when it does, is the pick still rule-compliant?).

**Metric definitions (each has a `definition` column in `summary.csv`).**

| metric | definition |
|---|---|
| `n_rows`, `n_completed`, `n_guard_stopped` | sample size, finished, stopped by cost/time guard |
| `consensus_rate` | `decided_by=="consensus"` / n_completed |
| `consensus_round1_rate`, `consensus_round2_rate` | split by `rounds_used` |
| `mean_rounds` | mean `rounds_used` over agent runs |
| `fallback_rate_<reason>` | fallback count by reason / n_completed |
| `agent_top_pick_rule_fail_rate` (overall and per role) | valid messages whose `ranking[0]` candidate fails ≥1 engine rule / valid messages — the "violations caught by the rules engine" number |
| `consensus_excluded_by_rules_rate` | runs where ∩acceptable ≠ ∅ but ∩acceptable∩rules_pass = ∅ |
| `reviewer_<verdict>_rate` | verdict counts / n_completed |
| `reviewer_engine_disagreement_rate` | candidates with engine≠reviewer pass / candidates checked |
| `cited_value_mismatch_rate` | mismatched citations / citations with a value |
| `schema_invalid_rate` | invalid messages / total agent calls (invalid includes schema, unknown_candidate, conflict, monotonic) |
| `modelled_delay_agents_mean/median`, `modelled_delay_solver_mean/median`, `actual_delay_mean/median`, `actual_chain_mean` | labelled `modelled` vs `data` |
| `modelled_saving_vs_actual_mean` | actual − modelled (agents); labelled **estimate**, with the caveat string in the `note` column |
| `agents_vs_solver_same_pick_rate` | chosen ids equal |
| `latency_s_mean/p95`, `cost_usd_mean`, `cost_usd_total`, `tokens_total` | from run meta |
| `human_decision` | always `pending` in eval — reported to show the tool never acts |

**Cost and time guard.** After each agent run: `cum_cost += meta.cost_usd`; after ≥10 rows, `projected = cum_cost / i * n`; stop if `cum_cost > budget` or `projected > 1.1*budget`; also stop if `now + (elapsed/i)*(n−i) > --deadline` (default 15:05). On stop: write `meta.json` with `guard_stopped: true, reason, n_completed`. Rows are appended to `per_scenario.csv` immediately (under a lock), so a crash or stop loses nothing and `--resume` skips done rows. Parallelism: `ThreadPoolExecutor(max_workers=--workers)`, default 4; each `run_one` writes its own log files so there's no contention. Refuse to run with `force_deadlock` or `tamper_rules`.

**Outputs** (`eval/results/`): `per_scenario.csv` (one row per scenario per mode: row_index, scenario_id, mode, chosen_id, kind, decided_by, rounds_used, fallback_reason, verdict, n_cited_mismatch, n_invalid, top_pick_fail_ATC/PILOT/GROUND, est_delay, est_knock_on, actual_delay, actual_chain, latency_s, cost_usd), `summary.csv` (long format: metric, value, unit, n, definition, note — Reine's UI panel and Sydelle's slide read this), `summary.md` (the table for the README), `meta.json` (model, seed, n, workers, budget, start/end, cost, git_sha, guard info), `runs/` (all per-row JSON/JSONL, so any eval row is reproducible with `python -m src.cli --row-id N --agents haiku`).

**Prompt (Session B):**
```
Read CLAUDE.md and eval/run_eval.py's docstring. Implement the harness on top of
src.cli.run_one (do not duplicate the pipeline). Args: --n, --seed, --agents, --out,
--budget-usd 15, --workers 4, --sample-ids eval/sample_ids.csv, --deadline "15:05",
--resume, --modes "none,haiku" (comma list; "none" is the solver-only baseline).
Flow: load sample ids (if the file is missing, build them inline: 150 rows WEATHER_DELAY>15
with DESTINATION_AIRPORT in ORD/ATL/DFW/DEN + 50 rows LATE_AIRCRAFT_DELAY>20, seed 42, and
warn). Run mode "none" for all rows first (sequential, no API). Then the agent mode with a
ThreadPoolExecutor(max_workers). For each completed run append one row to
<out>/per_scenario.csv under a threading.Lock with the columns I list in the module
docstring (paste them). Pull actual_delay from the flights row and actual_chain from
scenario.downstream_legs ARRIVAL_DELAY sum. Cost/time guard: after >=10 agent runs stop if
cumulative cost > budget or projected > 1.1*budget, or projected finish > --deadline (today,
Asia/Singapore); record in meta.json guard_stopped, reason, n_completed. Never run with
force_deadlock or tamper_rules. --resume skips scenario_ids already in per_scenario.csv.
At the end write summary.csv (long format: metric,value,unit,n,definition,note) with every
metric in the module docstring (paste the table), summary.md with the same as a markdown
table, and meta.json. Modelled-delay metrics must carry note="model estimate; not
comparable like-for-like with actual". Write tests/test_run_eval.py that runs --n 3
--modes none,fixture on fixture data and checks the files exist and parse.
Run: python -m eval.run_eval --n 3 --agents stub --modes none,stub --out /tmp/evaltest
```

---

## 4. Checkpoint merge procedure and checks

Merge order every time: **T1 → T2 → L**, each as `git merge --no-ff` into `main` on my machine, run the gate, push. Nobody else pushes to `main`.

**Gate on `main` (run after every merge, not just at the end):**
1. `pytest -q` green.
2. `python -m src.cli --row-id 0 --agents stub --out /tmp/gate/` writes `<scenario_id>.json` and `.jsonl`; the JSON reloads into `Scenario`, `Candidate`, `RuleResult`, `Recommendation` without error.
3. `python -m src.cli --row-id <AA334> --agents stub --force-deadlock --out /tmp/gate/` ends with `fallback.reason == "forced_deadlock"`.
4. `python -m src.cli --row-id 0 --agents fixture` still works (fixtures not broken by the merge).
5. `git ls-files | grep -Ei '(^|/)\.env$|problem statement'` returns nothing; `git diff main~1 main | grep -i 'sk-ant'` returns nothing.

**Handling a branch that fails the gate.** Never merge red. If the failure is a one-line integration mismatch (import name, kwarg name, signature) I fix it on `main` and tell the owner in chat. Anything else goes back to the owner on their branch with the failing command pasted; I merge the other branches meanwhile. If a dependency is still red at the end of the checkpoint window, `main` keeps working through the `--agents fixture` path and I move on — a missing module never stalls the merge, it becomes a cut (§5) or a 10-minute pair-fix at the owner's desk, not mine.

### 4.1 Checkpoint 1 (13:00–13:15): deterministic end-to-end

**Waseem's branch (`t1/*`), before merging:**
- `build_scenario(0)` and `build_scenario(<AA334>)` validate; run each twice and `model_dump()` compares equal (seeded).
- `flight["SCHEDULED_ARRIVAL"]` for AA334 is `775` (12:55 in minutes) — hhmm normalisation proof. A row with `2400` doesn't crash.
- Field semantics match §0 note 2: `fuel_reserve_min`, `crew_duty_remaining_min`, `alternates[i]["distance_nm"]`, `nominal_aar` present and tagged; `check_all` returns `len(rules) × len(candidates)` results including passes.
- AA334: ≥ 8 candidates, ≥ 1 `passed=False`, every `RuleResult` has a non-empty `citation` and a `source`.
- `Candidate.params` follow the conventions the reviewer expects (`hold → minutes`, `slot_shift → shift_min`, `divert → iata`). If not, I post the diff; he fixes, I don't.

**Reine's branch (`t2/*`), before merging:**
- `StubAgent` returns a valid `AgentMessage` for all three roles on the fixture scenario; round-2 `acceptable` ⊇ round-1 (else the stub path always falls back — gate item 2 would show it).
- `src.agents.base` exposes `Agent`, `StubAgent`, `ClaudeAgent`, `InvalidMessage`, `MODEL_IDS`; `propose` accepts `others=` or the mediator's `TypeError` retry logs `agent_interface: legacy` exactly once per call.
- `grep -niE 'legal|safe to|compute|calculate|minus|subtract' src/agents/prompts/*.txt` — any hit is a prompt doing arithmetic or legality; she rewrites it before merge.
- Her `tests/test_agents.py` makes no live API call (CI-safe); the one real Haiku call is behind an env flag.

**After all three are in:** gate, then the *real* (non-fixture) AA334 run with `--agents stub` — this is the check that the fixtures haven't hidden a semantics gap. Pass criterion as timeline §5: recommendation, log, ≥ 1 rule failure, `--force-deadlock` → fallback. Push, announce `main` sha, everyone rebases. Eat.

### 4.2 Checkpoint 2 (14:15–14:30): live demo, then submit

Merge order as above. Gate, plus:
- Live AA334 with `--agents haiku` on my key: `.jsonl` has exactly 3 `agent_message` (or `message_invalid`) events per round, a `reviewer_verdict` event, `meta.cost_usd > 0`.
- Reine's UI opens that run from the dropdown, shows source tags, turns, rule results, verdict, `decided_by`; **Approve** appends a `human_decision` event to the `.jsonl` (I check the file, not the screen).
- `--force-deadlock` run appears in the UI with "fallback" as decider.
- `eval/sample_ids.csv` exists with 200 rows (else my inline recipe runs at 14:30 and I say so).
- `python -m eval.run_eval --n 3 --agents stub --modes none,stub --out /tmp/evaltest` writes all four output files.
- Commit `runs/aa334_live_haiku.json` + `.jsonl` as the pre-warmed demo run (allowlisted in `.gitignore`).

If the UI fails any of its checks at 14:25, cut #7 from the timeline applies: `--pretty` is the demo surface and the submission goes in with that. **Sydelle submits at 14:30 from the `main` sha that passed the gate, no exceptions.** Then swap `.env` to Sydelle's key and start the 10-row cost test.

### 4.3 Checkpoint 3 (15:15–15:45): freeze

Merge Waseem (`docs/failure_case.md`, `runs/failure_showcase.json`), Reine (eval panel, failure preset, video path noted in README), Sydelle (README, slides). Gate, plus:
- `runs/failure_showcase.json` reproduces with the single command in `docs/failure_case.md`; its verdict/fallback reason matches the doc.
- Every number in `README.md` and `docs/slides/` exists in `eval/results/summary.csv` or `meta.json` (`grep` each one). `meta.json` `n_completed` is the n quoted everywhere; if `guard_stopped`, the README says so.
- `eval/results/summary.csv`, `per_scenario.csv`, `meta.json` committed; `eval/results/runs/` committed only if < 50 MB, else `.gitignore` it and keep a zip on two laptops.
- `git rm --cached -r "problem statement"`, add to `.gitignore`, add `LICENSE` (Apache-2.0), `requirements.txt` pinned.
- **Fresh-clone test** (15:30): `git clone` into `/tmp`, new venv, `pip install -r requirements.txt`, gate items 1–4. Judges may do exactly this.
- Repo public, `git tag v1.0-submission`, push tag, Sydelle re-submits if §2.8 allows.

**15:45 freeze.** After that `main` takes nothing; a typo in a slide is fixed in the slide file on Sydelle's laptop, not in the repo.

---

## 5. Cut list for Rohan's modules

Applied top-down; announce each cut in chat with its number.

| # | Cut | Trigger | Replacement |
|---|---|---|---|
| 1 | `--tamper-rules` fault injection | Default — only build if reviewer tests are green by 14:05 | Reviewer REJECT is shown via `tests/test_reviewer.py` (injected HOLD40) or a natural REJECT from the eval; `--force-deadlock` is the live failure case |
| 2 | Sonnet 50-row comparison sweep | Haiku run not finished by 15:00, or spend > $8 | Single-model eval; README says "Haiku only, Sonnet used for the live demo" |
| 3 | `eval/make_summary.py` / `summary.md` | Session A not free at 14:45 | Sydelle builds the README table from `summary.csv` by hand |
| 4 | `--workers` parallelism and `--resume` | Threading bugs or 429s in the 14:30 cost test | `--workers 1`, and the n reduction in #5 |
| 5 | Eval 200 rows → 50 rows | > 20 s/scenario sequential, or full run not started by 14:45 | `--n 50`, same seed, same sample file truncated in order; every metric reported with n=50 |
| 6 | Independent reviewer (Session C) | Session C not green by 14:05 | `review()` re-runs `check_all` on the chosen candidate + cited-value cross-check only; `engine_disagreements` always empty; README states "reviewer is not an independent implementation" |
| 7 | `MODIFY` verdict tier | Reviewer still red at 14:10 after #6 | APPROVE/REJECT only; cited mismatches become notes on an APPROVE and the UI shows them |
| 8 | Three-way comparison → two-way | `downstream_legs` semantics wrong at 15:00 | Drop `actual_chain_*` metrics; keep actual `ARRIVAL_DELAY` vs modelled, and `agents_vs_solver_same_pick_rate` |

**Never cut:** append-only JSONL log, `fallback_pick` with `None` representable, `max_rounds=2`, invalid messages rejected and logged (no repair), `--force-deadlock`, `run_one` as the single pipeline for CLI/UI/eval, an eval of n ≥ 50 with the guard metadata, the 14:30 submission.

---

## 6. Demo prep and risks

### 6.1 Setup (15:45–16:15, my laptop is the demo machine)
- `main` at `v1.0-submission`; `.env` = Sydelle's key with ≥ $10 unspent (checked in Console at 15:50); `.env.backup` = my key.
- Pre-warmed, committed runs in `runs/`: `aa334_live_sonnet.json` (made at 15:50, one Sonnet call, ~$0.05), `aa334_live_haiku.json`, `failure_showcase.json`, `aa334_forced_deadlock.json`.
- `streamlit run app/streamlit_app.py` started at 16:10 and left open on the AA334 pre-warmed run; a second terminal with the live command typed and not yet run; a third with `python -m src.cli --row-id <AA334> --agents sonnet --pretty` ready. Phone hotspot paired; Wi-Fi tested at 16:05.
- Reine: backup video on her laptop, open. Waseem: `cat runs/failure_showcase.json | python -m json.tool | less` ready.

### 6.2 Run order (I drive, Sydelle speaks; timings from timeline §5)
1. **0:00** Sydelle: user and status quo. I press Enter on the live Sonnet run (`--out runs/live/`). It takes 20–45 s; nobody waits for it.
2. **0:45** UI, pre-warmed AA334 run: scenario card (point at the `synthetic` / `assumed` tags), turns table (three separate agents, three messages per round, invalid-message counter), rule results with rule IDs and citations, reviewer verdict, **Approve / Reject** — I click nothing; "the duty manager clicks".
3. **1:35** If the live run finished, switch the dropdown to it: "same code, just now, different model" — one sentence, then move on.
4. **1:45** Failure preset: reviewer REJECT (or forced deadlock) → `fallback_fired` with reason → fallback pick or `chosen=None` escalation. "This is how the user knows."
5. **2:15** Eval panel: n, consensus rate, fallback rate, `agent_top_pick_rule_fail_rate`, `schema_invalid_rate`, modelled-vs-actual with the "estimate" label.
6. **2:40** Sydelle closes on limitations. Done by 2:45.

### 6.3 Fallbacks at the podium
| Failure | Do |
|---|---|
| Live run > 45 s or 429/5xx | Stay on pre-warmed run; say "pre-computed at 15:50, identical pipeline"; don't retry live |
| API key exhausted | `cp .env.backup .env`; otherwise as above |
| Streamlit crashes | Third terminal: `--pretty` on the pre-warmed JSON, then `--agents stub --force-deadlock --pretty` for the failure case |
| My laptop dies | Reine's video; Waseem's terminal for the failure JSON; Sydelle keeps talking |
| Wi-Fi down | Hotspot; if that's down too, no live run — stub + pre-warmed only, said out loud |

### 6.4 Risks specific to my modules
| Risk | Mitigation | When |
|---|---|---|
| MCP superset rule means agents deadlock ~100% and consensus rate is ~0 | Honest result: report it, show the fallback doing its job. Reine may widen the round-2 prompt ("you must add at least one id the others accept") between 14:30 and 14:45; the mediator does not change | 14:30 cost test |
| Reviewer REJECTs nearly everything (e.g. WAKE fails at every disrupted hour because `nominal_aar − dest_disruption` is too low) | At the cost test, compare reviewer and engine constants against `docs/regulatory_sources.md` with Waseem; fix whichever is wrong **in constants only**; report `reviewer_engine_disagreement_rate` as found | 14:30–14:45 |
| Engine never catches an agent top pick (`agent_top_pick_rule_fail_rate = 0`) | Report 0 honestly; the `unsafe_consensus` fixture test still proves the path works | 15:05 |
| Fixtures pass but the real path breaks (field semantics drift) | Checkpoint 1 runs the real AA334 path explicitly, never only fixtures | 13:00 |
| Rate limits / cost blow-up in the parallel eval | SDK retries, `--workers 4 → 2`, hard `--budget-usd 15` and `--deadline 15:05` guard; `per_scenario.csv` appended per row so nothing is lost | 14:45 |
| Missing or wrong cost accounting from `ClaudeAgent.calls` | Harness recomputes cost from token counts with a price table in `eval/prices.py`; both numbers in `meta.json` | 14:30 |
| `scenario_id` collision overwrites a run | `.json` is overwritten but `.jsonl` appends; harness keys on `row_index` as well | built in |
| Schema conflicts from my additive fields (`fallback`, `reviewer_detail`) | Only I edit `schemas.py`; announce each push; others rebase before their next commit | 12:40, 13:50 |
| Session C contaminated by rules code (independence claim false) | Session C's first message is the §3.5 prompt only; if it reads `src/rules/`, I kill it and restart; if no time, cut #6 and say so in README | 13:35 |
| Freeze slips because numbers aren't in by 15:10 | Guard deadline 15:05 is absolute; whatever `n_completed` is at 15:05 is the n we report | 15:05 |
