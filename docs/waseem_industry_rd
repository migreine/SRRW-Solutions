# SRRW Solutions — Challenge #2 Build Plan (from 11:29 to judging)

**Hard numbers:** submissions close 16:15. It is 11:29. We have 4 h 46 min. First valid submission target **14:30**, final freeze **15:45**, nothing merges to `main` after that.

**One-line thesis for every decision:** *LLMs negotiate and explain; deterministic code decides; every decision traces to a rule ID and a data field; a human approves.*

---

## 1. Where the points are, and what that forces

| Rubric criterion | Weight | What we build to earn it | Owner of the evidence |
|---|---|---|---|
| Technical soundness | 25 | End-to-end run on *any* `flights.csv` row (not one scripted row). Three separate LLM calls. Rules engine does all legality/arithmetic. Hard 2-round cap + deterministic fallback. | L, T1, T2 |
| Problem realism | 20 | Named user: airline OCC duty manager coordinating TRACON traffic manager + hub ramp controller. Status quo: phone calls across 3 orgs. Cost: N469AA arrival delay +101 → +256 on 24 Apr 2015. | N |
| Honest evaluation | 20 | 200-row eval with fixed seed, three-way comparison (actual / solver-only / agents+solver), stated metrics, **one live failure case** (reviewer REJECT → fallback), real-vs-synthetic table. | L (harness), N (write-up) |
| Trust & traceability | 20 | Every rule result cites rule ID + source + data field; every synthetic value tagged; append-only JSONL log; approve/reject button; schema-invalid messages rejected and logged, never repaired. | T1 (rules), L (log), T2 (UI) |
| Impact | 10 | Estimated chain-delay saved vs actual, clearly labelled "model estimate"; decision latency in seconds vs phone-call baseline. | N + L |
| Time discipline | 5 | Submit at 14:30, pitch rehearsed to 2:45. | N |

**What the rubric does *not* reward:** UI polish, breadth of option menu, LLM explanation prose. Those are cut first.

---

## 2. Decisions frozen now (no re-litigating after 11:45)

1. **"Under 3 turns"** = max 2 negotiation rounds; turn 3 is always the deterministic fallback. Stated in README and pitch.
2. **Reviewer is deterministic code, not an LLM.** It re-runs the constraint checks with an *independently written* implementation (T1 writes rules engine, L's session writes reviewer — different Claude sessions, different prompts) and cross-checks every number an agent cites against the scenario's actual field value. An LLM legality check is explicitly "weak" in the rubric.
3. **Fallback = argmin over a finite candidate menu** subject to rules-pass. No MILP, no OR-Tools (Python 3.14 risk). The menu is finite, so a solver is unnecessary and the result is hand-verifiable.
4. **Models:** Haiku 5.5 for the 200-row eval (est. < $1 total), Sonnet 5.5 for the live demo and a 50-row comparison sweep if time permits. Measure on 10 rows before any sweep.
5. **Budget:** each technical member spends ≤ $30 of their own key on Claude Code, keeps $20 reserve. **N's key is the app key** (N's Claude Code usage is light): `.env` on the demo machine uses N's key; eval capped at $15, demo reserve $10.
6. **Organiser PDF stays out of the public repo.** Move `problem statement/` to `.gitignore` before going public at 15:45.
7. **Python:** T1 checks at 11:35 whether `pandas pydantic anthropic streamlit pytest` install cleanly on 3.14. If `pyarrow`/Streamlit fails, we standardise on 3.12 via `uv python install 3.12` immediately. Nobody else installs anything until T1 posts the verdict (≤ 11:45).
8. **Resubmission rule:** N asks organisers at 11:45 whether an updated submission changes the recorded time. If first time counts → submit 14:30, update at 15:45. If last time counts → single submission at 15:30 with a freeze at 15:20.

---

## 3. Team and ownership

Fill in names at kickoff. Everyone runs their own Claude Code session on their own branch, in their own directories only.

| Tag | Person | Branch | Owns (directories) | Does not touch |
|---|---|---|---|---|
| **L** | Lead (you) | `lead/*` | `src/schemas.py`, `src/mediator/`, `src/reviewer/`, `src/fallback/`, `src/log/`, `src/cli.py`, `eval/`, `CLAUDE.md`, merges to `main` | agent prompts, rules internals, UI |
| **T1** | Technical | `t1/*` | `src/scenario/`, `src/options/`, `src/rules/`, `tests/test_rules.py`, `tests/test_scenario.py` | anything calling the API |
| **T2** | Technical | `t2/*` | `src/agents/`, `tests/test_agents.py`, then `app/streamlit_app.py` | rules, mediator |
| **N** | Non-technical | `n/*` | `README.md`, `docs/pitch.md`, `docs/data_limits.md`, `docs/regulatory_sources.md`, `docs/slides/`, submission form, budget tracker, timekeeping | `src/` |

**Git rules:** commit every 20 min; merge only at checkpoints; L resolves conflicts; `main` must always pass `pytest -q` and `python -m src.cli --row-id 0 --agents stub`. Ownership by directory means conflicts should be near zero.

---

## 4. Interfaces (frozen by 12:00 in `src/schemas.py`, owned by L)

Everyone's Claude Code session gets this file plus `CLAUDE.md` as context. Field names below are the contract; add fields freely, never rename or remove.

```python
# src/schemas.py  (Pydantic v2)
SourceTag = Literal["data", "estimated", "assumed", "synthetic"]

class Tagged(BaseModel):            # every non-raw value carries its provenance
    value: float | str | int
    source: SourceTag
    note: str = ""                  # e.g. "FAA registry miss -> airline fleet default"

class Scenario(BaseModel):
    scenario_id: str                # f"{date}_{airline}{flight}_{tail}"
    row_index: int
    flight: dict                    # raw flights.csv row, times normalised to minutes-since-midnight
    dest_disruption: Tagged         # delayed arrivals in dest hour (data, proxy)
    taxi_congestion: Tagged         # TAXI_IN vs airport median (data, proxy)
    downstream_legs: list[dict]     # same tail later that day (data, partial)
    alternates: list[dict]          # {iata, distance_nm} from airports.csv
    wake_category: Tagged           # "H"|"L"|"S", assumed unless looked up
    fuel_reserve_min: Tagged        # estimated
    crew_duty_remaining_min: Tagged # synthetic
    gates: dict                     # synthetic gate model, seeded
    connections: list[dict]         # estimated
    nominal_aar: Tagged             # assumed

class Candidate(BaseModel):
    candidate_id: str               # "SLOT+15", "HOLD30", "DIVERT_AUS", "GATE_B12", ...
    kind: Literal["slot_shift","hold","divert","gate_swap","ground_hold","tail_swap"]
    params: dict
    est_delay_min: float            # deterministic estimate
    est_knock_on_min: float

class RuleResult(BaseModel):
    rule_id: str                    # "R-FUEL-01"
    candidate_id: str
    passed: bool
    observed: float | str
    threshold: float | str
    source: SourceTag
    citation: str                   # "14 CFR 121.639" or "assumed: airline turnaround"

class AgentMessage(BaseModel):      # what every LLM call MUST return
    agent: Literal["ATC","PILOT","GROUND"]
    round: int
    acceptable: list[str]           # candidate_ids this agent can live with
    ranking: list[dict]             # [{candidate_id, score: 0-1, rationale, cited_fields: [str]}]
    vetoes: list[dict]              # [{candidate_id, reason, cited_field}]

class Turn(BaseModel):
    round: int
    messages: list[AgentMessage]
    invalid_messages: list[dict]    # raw text + validation error, never repaired
    intersection: list[str]

class Recommendation(BaseModel):
    scenario_id: str
    chosen: Candidate | None
    decided_by: Literal["consensus","fallback"]
    rounds_used: int
    rule_results: list[RuleResult]
    reviewer_verdict: Literal["APPROVE","REJECT","MODIFY"]
    reviewer_notes: list[str]
    human_decision: Literal["pending","approved","rejected"] = "pending"
    log_path: str
```

**Function contracts:**

| Module | Signature | Owner |
|---|---|---|
| `scenario/builder.py` | `build_scenario(row_index:int, seed:int=42) -> Scenario` | T1 |
| `options/menu.py` | `generate_candidates(s: Scenario) -> list[Candidate]` (≥ 5, ≤ 12) | T1 |
| `rules/engine.py` | `check_all(s, candidates) -> list[RuleResult]` | T1 |
| `agents/base.py` | `Agent.propose(s, candidates, round, prior: AgentMessage|None) -> AgentMessage` ; `StubAgent`, `ClaudeAgent(model)` | T2 |
| `mediator/protocol.py` | `negotiate(s, candidates, agents, rules, max_rounds=2) -> (Recommendation, list[Turn])` | L |
| `reviewer/safety.py` | `review(s, rec, turns) -> (verdict, notes)` | L |
| `fallback/solver.py` | `fallback_pick(candidates, rule_results, weights) -> Candidate|None` | L |
| `log/consensus_log.py` | `ConsensusLog(path).append(event: dict)` → JSONL with ISO timestamps | L |
| `cli.py` | `python -m src.cli --row-id N --agents stub|haiku|sonnet --out runs/` | L |
| `eval/run_eval.py` | `--n 200 --seed 42 --agents haiku --out eval/results/` | L |
| `app/streamlit_app.py` | reads `runs/*.json` + `eval/results/summary.csv` | T2 |

**Monotonic Concession Protocol (L implements):** round 2 `acceptable` must be a superset of round 1 `acceptable` — a message that shrinks it is invalid and logged. Consensus = `∩ acceptable ∩ rules_pass ≠ ∅`, pick max summed score. Else round 2. Else fallback. Agents see the candidate menu **without** rule results (they only know their own domain) — that is how we measure "agent-proposed violations caught by rules engine".

**Rule IDs (T1):** `R-WAKE-01` (FAA JO 7110.65 §5-5-4, assumed approach speed), `R-FUEL-01` (14 CFR 121.639, estimated fuel), `R-DUTY-01` (14 CFR 117, synthetic duty state), `R-GATE-01` (synthetic), `R-TURN-01` (assumed per class), `R-AAR-01` (assumed nominal rate). Each result carries the source tag so the UI can show "this check rests on synthetic data".

---

## 5. Timeline

### 11:29 – 11:45 · Kickoff (all four, 15 min, standing)
- Read §2 decisions aloud; assign names to L/T1/T2/N.
- **L:** write `CLAUDE.md` (conventions: Pydantic everywhere, no silent repair, seed=42, rule IDs cite sources, no LLM arithmetic) and start `src/schemas.py` with Claude Code.
- **T1:** environment check (§2.7). Post verdict in group chat by 11:45. Create `requirements.txt`.
- **T2:** draft the three system prompts in `src/agents/prompts/` as plain text (domain-only data, strict JSON output, no legality claims).
- **N:** ask organisers §2.8 and submission format (repo link? video? form fields?). Start `docs/pitch.md` from briefing §10.

### 11:45 – 12:00 · Schema freeze
- **L** pushes `schemas.py` + `CLAUDE.md` to `main`. Everyone rebases. From here, Claude Code sessions run in parallel with the task cards below.

### 12:00 – 13:00 · Build block 1 (deterministic slice)

| Owner | Claude Code task card | Done when |
|---|---|---|
| **T1** | `build_scenario`: load `flights.csv`, normalise hhmm (incl. 2400 wrap), dest-hour disruption count, same-tail downstream legs, 3 nearest alternates by haversine (skip ECP/PBG/UST), seeded synthetic gates/crew/fuel with tags. Then `generate_candidates` (slot ±15/±30, hold 20/40, divert ×2 alternates, gate swap ×2, ground hold at origin). Then `check_all` with the 6 rules. Tests on row 0 and the N469AA row. | `pytest tests/test_scenario.py tests/test_rules.py` green; AA334 row yields ≥ 8 candidates with ≥ 1 rule failure among them |
| **T2** | `StubAgent` (deterministic domain heuristics returning valid `AgentMessage`); `ClaudeAgent` with anthropic SDK, prompt caching on the system prompt, 1 retry on invalid JSON, then raise `InvalidMessage` carrying raw text; token + cost accounting per call. Test against a hand-built `Scenario`. | Stub returns valid messages for all 3 roles; one real Haiku call validates against schema; cost per call printed |
| **L** | `negotiate` (MCP, 2 rounds), `ConsensusLog`, `fallback_pick` (weighted argmin, weights in one dict), `cli.py` wiring everything with `--agents stub`. | `python -m src.cli --row-id 0 --agents stub` writes `runs/*.json` + `.jsonl` end to end |
| **N** | `docs/data_limits.md` (briefing §4.1 limitations, §5 table verbatim). `docs/regulatory_sources.md`: verify the four values in briefing §9 against primary sources; anything unverified is written as "assumed". README skeleton: Problem → User → Architecture → Run → Limits → Results (empty). | Docs pushed; verified/assumed status for every regulatory number |

### 13:00 – 13:15 · **Checkpoint 1: deterministic end-to-end**
- L merges T1, T2, L branches. Run `cli --row-id <AA334> --agents stub`. Fix only blocking issues.
- Pass criterion: Recommendation produced, log written, at least one rule failure recorded, fallback path exercised by forcing an empty intersection (`--force-deadlock` flag).
- Eat at desks during this slot.

### 13:15 – 14:15 · Build block 2 (live agents, reviewer, UI)

| Owner | Task card | Done when |
|---|---|---|
| **L** | Swap in `ClaudeAgent(haiku)`, run AA334 live; fix prompt/schema mismatches with T2. Write `reviewer/safety.py`: independent re-derivation of fuel and wake checks + cross-check of every `cited_fields` value against `Scenario`; REJECT if mismatch > tolerance or any rule fails. Wire into `cli`. | AA334 live run: 3 distinct API calls per round, consensus or fallback, reviewer verdict in output |
| **T1** | Harden: `tests/test_rules.py` edge cases (midnight wrap, missing alternate coords, zero downstream legs, tail with no registry match). Add `eval/sample.py`: seeded sample of 200 rows (150 `WEATHER_DELAY>15` across ORD/ATL/DFW/DEN, 50 `LATE_AIRCRAFT_DELAY>20`), save `eval/sample_ids.csv`. Add a "solver-only" baseline mode (`--agents none` → fallback directly). | Sample file committed; `cli --agents none` works |
| **T2** | `app/streamlit_app.py`: 4 panels — (1) scenario card with source tags colour-coded, (2) turns table showing each agent's acceptable/vetoes/rationale and invalid-message count, (3) rule results + reviewer verdict + "decided by", (4) recommendation with **Approve / Reject** buttons that append to the log. Reads `runs/*.json`. Dropdown to pick any run. | UI shows the AA334 run; approve button writes a log line |
| **N** | Slides (≤ 6): user & status quo · architecture diagram (one box per §6 component) · live demo placeholder · eval table placeholder · real-vs-synthetic table · limitations & fixes. Impact slide: actual chain +101→+256 vs "model-estimated" chain under recommendation (number to be filled by L at 15:15). | Deck v1 in `docs/slides/` |

### 14:15 – 14:30 · **Checkpoint 2: live demo works → first submission**
- Merge. Run live AA334 through the UI. Run `cli --force-deadlock` to confirm the failure case displays correctly.
- **N submits** (per §2.8 outcome): repo link, description, README state. This is the **valid submission**. Everything after is improvement.
- L starts the 10-row cost measurement (`eval/run_eval.py --n 10 --agents haiku`). Record $/scenario and seconds/scenario.

### 14:30 – 15:15 · Build block 3 (evaluation and honesty)

| Owner | Task | Done when |
|---|---|---|
| **L** | `run_eval.py` full: 200 rows × {actual, solver-only, agents+solver}. Metrics: consensus rate within cap, mean rounds, fallback rate, agent top-choice failing a rule (count), reviewer rejects, cited-value mismatches, schema-invalid rate, est. delay vs actual `ARRIVAL_DELAY`, latency, cost. Writes `eval/results/summary.csv` + `per_scenario.csv`. Budget cap $15 — abort at 150 rows if cost projects over. | Summary CSV committed by 15:10 |
| **T1** | Pick the **showcase failure case** from eval output: a reviewer REJECT or a deadlock → fallback. Save it as `runs/failure_showcase.json`. Write `docs/failure_case.md`: what happened, why, what would fix it. Then review L's reviewer code for a second independent pair of eyes on the maths. | Failure case reproducible with one CLI command |
| **T2** | UI: add eval panel reading `summary.csv`; add failure-case preset button. Record a 60-second backup screen capture of the AA334 run + failure case (in case live demo or Wi-Fi fails). | Backup video on two laptops |
| **N** | README results section, limitations section, "how the user knows it failed" paragraph. Rehearse pitch alone twice with a timer. | README complete except numbers |

### 15:15 – 15:45 · **Checkpoint 3: final integration and freeze**
- L drops eval numbers into README and slide; N proofreads claims against `summary.csv` (every number in the pitch must exist in a committed file).
- `.gitignore` the PDF, add LICENSE (Apache-2.0), make repo public, tag `v1.0-submission`.
- **15:45 code freeze.** Final submission update if §2.8 allows. Nothing merges after this.

### 15:45 – 16:15 · Rehearse and de-risk
- Three timed run-throughs of the 3-minute pitch (target 2:45). N speaks; L drives the demo; T2 holds the backup video; T1 holds the failure-case terminal.
- Demo machine: `.env` with N's key, Sonnet for live run, pre-warmed run already in `runs/` in case API is slow. Phone hotspot tested.
- 16:00: confirm submission appears as received.

### 16:15 – 16:30 · Set up at judging station; nothing changes.

### 16:30 – 17:30 · Judging (3 min + Q&A)
Script order: user & status quo (25 s) → architecture line (20 s) → live AA334 negotiation (50 s) → reviewer REJECT + fallback (30 s) → eval table (30 s) → real-vs-synthetic + limitations (25 s). Expected judge question is "where does it fail and how does the user know?" — the answer is the failure case, the invalid-message counter and the source tags; T1 answers rules questions, T2 answers agent questions.

---

## 6. Cut order if behind (apply top-down, announce in chat when cut)

| # | Cut | Trigger | Replacement |
|---|---|---|---|
| 1 | LLM explanation/briefing layer | Default — don't start unless Checkpoint 3 is reached early | Log and rule results are already human-readable |
| 2 | FAA registry wake lookup | Default — don't start | Airline-fleet default, tagged `assumed` |
| 3 | Sonnet 50-row comparison sweep | Haiku sweep not done by 15:00 | Single-model eval |
| 4 | `tail_swap` and `ground_hold` candidates | T1 behind at 13:00 | Menu of slot/hold/divert/gate only |
| 5 | Eval 200 rows → 50 rows | Cost run shows > 20 s/scenario or eval not started by 14:45 | Report n=50, say so |
| 6 | Independent reviewer re-implementation | L behind at 14:15 | Reviewer re-runs the rules engine + cited-value cross-check only; README states it is not independently implemented |
| 7 | Streamlit UI | T2 not showing AA334 in UI by 14:30 | `cli --pretty` renders the Recommendation and log as a terminal table; approve/reject via `--approve` flag |
| 8 | Synthetic crew duty and connections | T1 behind at 12:45 | Drop `R-DUTY-01`, keep 5 rules |

**Never cut:** three separate LLM calls per round, schema validation with rejection logging, rules engine with citations, 2-round cap, deterministic fallback, JSONL consensus log, the AA334 live run, the failure case, data-limits section, submission at 14:30.

---

## 7. Claude Code working rules (paste into `CLAUDE.md`)

- Import every shared type from `src/schemas.py`; never redefine. Never rename a field.
- No LLM output is trusted: parse with Pydantic, on failure log raw text + error to the consensus log and raise. No auto-repair, no "fix the JSON" retry beyond one.
- No arithmetic, scheduling or legality logic in any prompt or agent module. If a check is needed, it belongs in `src/rules/`.
- Every estimated/synthetic/assumed number is a `Tagged` value. Every `RuleResult` cites a source.
- `random.seed(42)` / `np.random.default_rng(42)` everywhere; gate assignments locked per scenario.
- Each session edits only its owner's directories. Write a test alongside each module. Commit every 20 min with a message starting with the owner tag.
- Prefer boring code: pandas, Pydantic, anthropic SDK, Streamlit, pytest. No new frameworks.

---

## 8. Risk register

| Risk | Mitigation | Owner |
|---|---|---|
| Python 3.14 wheel failures | Verdict by 11:45; fallback to 3.12 via uv | T1 |
| API outage / slow at demo | Pre-computed run in `runs/`, backup video, `--agents stub` shows the deterministic core still works | T2 |
| Agents never reach consensus (fallback rate ~100%) | That is a valid, honest result — report it and show the fallback doing its job; tune prompts only if time at 14:30 | L |
| Agents always agree (rules engine never catches anything) | Agents see no rule results, so some top picks will fail; if count is still 0, report it honestly rather than rig it | L |
| Merge conflicts | Directory ownership + checkpoint-only merges | L |
| Budget overrun | Cost measured on 10 rows before sweep; hard $15 cap in harness; N tracks console usage at each checkpoint | N |
| Pitch over 3 minutes | Three timed rehearsals, cut slides not words | N |