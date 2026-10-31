# Reine (T2) — build plan, 12:18 → 15:45 freeze

Scope: `src/agents/` (base, views, prompts), `tests/test_agents.py`, `app/`, the backup video, agent Q&A. Rubric points these carry: **Technical soundness** (three genuinely separate LLM calls, schema-gated, no arithmetic in prompts), **Trust & traceability** (invalid messages rejected and shown, source tags visible, Approve/Reject in the human's hands), **Honest evaluation** (the eval panel and the failure preset are how judges see the numbers and the failure).

Everything below honours `docs/plan-rohan.md` §0 and §3; where it is ambiguous, the assumption is stated and marked **confirm with Rohan**.

---

## 1. Schedule

You are 35 minutes behind the checklist (prompts were due 11:45; `base.py` is a stub). Priority order is fixed by what Rohan needs when: **StubAgent for the 13:00 gate**, ClaudeAgent for the 13:15 live run, UI for 14:15, eval panel/preset/video for 15:15.

Two Claude Code sessions, both on `t2/*` branches: **Session 1** = `src/agents/`, `tests/test_agents.py`; **Session 2** = `app/`. Open each with: *"Read CLAUDE.md, docs/briefing.md, docs/timeline.md and docs/plan-rohan.md §0 and §3.4. You are Reine's session; edit only src/agents/, tests/test_agents.py and app/."* Commit every 20 min with `T2:`.

| Time | Session | Work | Done when |
|---|---|---|---|
| 12:18–12:25 | shell | `git pull && git checkout -b t2/agents`. Run `python -c "import anthropic;[print(m.id) for m in anthropic.Anthropic().models.list()]"` (free) and post the exact Haiku/Sonnet IDs in chat as `MODEL_IDS`. Read plan-rohan §0 notes 3–5. | IDs in chat |
| 12:25–12:50 | 1 | **D1**: refactor `base.py` (`others=None`, `MODEL_IDS`, `PRICES`, `InvalidMessage`), `views.py` domain views, `StubAgent`, stub tests | `pytest tests/test_agents.py -q` green for stub |
| 12:50–13:00 | shell | **D2**: paste the three prompts from §3 into `src/agents/prompts/*.txt`; run the grep gate; push `t2/agents`; post "T2 ready to merge: StubAgent + prompts; ClaudeAgent lands by 13:15" | push ≤ 12:58 |
| 13:00–13:15 | 1 | Checkpoint 1: run §6 self-checks on your branch, answer Rohan's merge questions. In parallel start **D3** ClaudeAgent with fake client (no API). Eat. | — |
| 13:15–13:35 | 1 + Rohan | Finish D3; `LIVE_AGENT_TEST=1 pytest -k live` once (≈ $0.002); Rohan runs AA334 `--agents haiku`; you fix prompts/view text, he fixes mediator. Note cost and latency per call. | live run reaches consensus or fallback; `calls` sums land in run meta |
| 13:35–14:10 | 2 | **D4**: Streamlit panels 1–4 against `runs/*.json` from `main` (`python -m src.cli --row-id 0 --agents stub` first if `runs/` is empty) | AA334 stub run renders; Approve appends `human_decision` to the `.jsonl` |
| 14:10–14:15 | shell | §6 checkpoint-2 self-checks, push `t2/ui` | pushed |
| 14:15–14:30 | — | Checkpoint 2: Rohan opens the live AA334 run in your UI; `--force-deadlock` run shows fallback. **14:25 cut decision** on UI (cut #7). Submission at 14:30. | Rohan confirms log line |
| 14:30–14:45 | 1 | Read the 10-row cost test with Rohan: `schema_invalid_rate`, `consensus_rate`, `cited_value_mismatch_rate`. Tune prompts only (§3.6 knobs); mediator doesn't change. | one tuning pass, max |
| 14:45–15:00 | 2 | **D5**: eval panel (reads `summary.csv` long format + `meta.json`) and failure-case preset button | panel renders against a hand-made `summary.csv`; preset loads `runs/failure_showcase.json` or any fallback run |
| 15:00–15:10 | screen | **D6**: backup video v1 (AA334 run + failure case + `--pretty` terminal), copy to two laptops | `docs/backup_demo_v1.mp4` on two machines |
| 15:10–15:15 | shell | Push `t2/ui`; hand §6 checkpoint-3 list to Rohan | pushed |
| 15:15–15:45 | — | Checkpoint 3: after `summary.csv` is merged (~15:20), reload eval panel; if it renders, record video v2 with real numbers (15:30–15:38). Give Sydelle the README "Run the UI" paragraph and video path. **15:45 freeze.** | v2 or v1 declared final |
| 15:45–16:15 | — | Rehearsals: you hold the video, run through §7 Q&A answers once aloud. | — |

---

## 2. Deliverables in build order

### D1 · `src/agents/base.py` refactor + `src/agents/views.py` + `StubAgent` (12:25–12:50)

**Design decisions (recommendation in bold):**
- **Signature:** `propose(self, s, candidates, round, prior, others=None)` on `Agent`, `StubAgent`, `ClaudeAgent`. `others` = list of the other two agents' most recent valid `AgentMessage`s (plan-rohan §0.3).
- **Module exports:** `Agent`, `StubAgent`, `ClaudeAgent`, `InvalidMessage`, `MODEL_IDS`, `PRICES`. `MODEL_IDS = {"haiku": os.getenv("HAIKU_MODEL", "<id from 12:20 check>"), "sonnet": os.getenv("SONNET_MODEL", "<id>")}`. `PRICES` (USD per Mtok in/out) from briefing §12 — `haiku 0.10/0.50`, `sonnet 2/10` — with a comment "from briefing; confirm in Console". Rohan's `eval/prices.py` recomputes independently, so a wrong price here is caught.
- **Domain views live in `views.py`, not in the prompts.** `domain_view(s, candidates, role, round, prior, others) -> str` builds the user message: a `DATA` block of `path=value (source)` lines (dotted paths that resolve against `Scenario`, `Tagged` shown as its `.value`), a `CANDIDATES` block (one JSON line each), and in round 2 a `ROUND 1` block. This is the single place that enforces "each agent sees only its domain" — testable, greppable, and the same text is shown in the UI turns panel on request. Field allocation per role is in §3.1. **Assume agents never see `flight.ARRIVAL_DELAY`, `ARRIVAL_TIME`, `WHEELS_ON`, `TAXI_IN`** (those are the outcome the eval compares against) — **confirm with Rohan**, since his reviewer example cites `flight.ARRIVAL_DELAY`.
- **`others` are shown as positions only**: candidate ids accepted, candidate ids vetoed with `reason`, `cited_field` stripped (it carries another domain's value). Keeps the domain separation honest.
- **StubAgent is preference-only, deterministic code.** Per-role kind weights × `est_delay_min`/`est_knock_on_min` normalisation; no thresholds, no reserve maths (CLAUDE.md forbids legality logic in agent modules, and the stub is in an agent module). Round 1 `acceptable` = top 3 by score; `vetoes` = the single worst id with a cited field from its own view; `ranking` covers every candidate. Round 2 `acceptable` = round-1 set ∪ every id any `other` accepted that this agent did not veto ∪ its 4th-ranked id — **superset guaranteed**, and three stubs converge by round 2 whenever any id is in two agents' top-3. `cited_fields` use real paths from the view (`dest_disruption=<v>`, `fuel_reserve_min=<v>`, `taxi_congestion=<v>`, `downstream_legs` existence-only).
- Role weights (kind → weight, higher = preferred): ATC `slot_shift 1.0, ground_hold .9, gate_swap .7, hold .4, divert .3, tail_swap .6`; PILOT `slot_shift 1.0, gate_swap .9, ground_hold .7, hold .5, tail_swap .4, divert .2`; GROUND `gate_swap 1.0, slot_shift .9, hold .6, ground_hold .5, tail_swap .4, divert .1`. Score = `0.6*weight + 0.4*(1 − delay_norm)` where delay uses `est_delay_min` (ATC/PILOT) or `est_delay_min+est_knock_on_min` (GROUND), min-max over the menu, clamped to [0,1].

**Behaviour and edge cases:** empty `candidates` → `ValueError` (never an empty message); one candidate → acceptable = that id, no vetoes; `others=None` in round 2 → behave as round 1 but still return superset of `prior.acceptable`; `prior=None` in round 2 → treat as round 1; all `est_delay_min` equal → `delay_norm = 0` for all (no divide-by-zero); `Tagged.value` may be a string (`wake_category`) → printed as-is; `gates` dict of unknown shape → flattened to dotted paths, capped at 15 lines; lists capped at 4 items with `…(n more)`; `None`/`NaN` values printed as `null`.

**Tests (`tests/test_agents.py`)** — own mini scenario built in the test file (Rohan's fixture isn't on `main` until 13:00): 6 candidates incl. `HOLD40`, `DIVERT_AUS`, `SLOT+15`, `GATE_B12`.
1. Stub returns a valid `AgentMessage` for all three roles, round 1; `ranking` covers every id; `acceptable ∩ vetoes = ∅`; every cited path resolves against the scenario (write a tiny resolver in the test).
2. Round 2 with `prior` and two `others` → `acceptable ⊇ prior.acceptable`; adds at least one id another agent accepted.
3. Three stubs, two rounds, computed intersection non-empty (proves the stub path won't always fall back).
4. `domain_view` for ATC contains no `fuel_reserve_min|crew_duty|gates|connections`; PILOT no `gates|nominal_aar|dest_disruption`; GROUND no `fuel_reserve_min|crew_duty|alternates`; none contain `ARRIVAL_DELAY`.
5. `domain_view` round 2 contains the other agents' ids and reasons but no other-domain `path=value` strings (assert `fuel_reserve_min=` absent from ATC's round-2 view even when PILOT's veto cited it).
6. Same inputs twice → identical message (determinism).

**Claude Code prompt (Session 1):**
```
Read CLAUDE.md, docs/briefing.md §2 and §5, docs/plan-rohan.md §0 (notes 3–5) and §3.3.
Edit only src/agents/ and tests/test_agents.py. Never edit src/schemas.py.

1. src/agents/base.py: keep Agent, StubAgent, ClaudeAgent, InvalidMessage. Change propose to
   propose(self, s, candidates, round, prior, others=None) on all three; others is a list of
   the other agents' most recent valid AgentMessage or None. Add module constants
   MODEL_IDS = {"haiku": os.getenv("HAIKU_MODEL", "<HAIKU_ID>"), "sonnet": os.getenv("SONNET_MODEL", "<SONNET_ID>")}
   and PRICES = {"haiku": {"in": 0.10, "out": 0.50}, "sonnet": {"in": 2.0, "out": 10.0}}  # USD/Mtok, from docs/briefing.md §12, confirm in Console
   Leave ClaudeAgent.propose raising NotImplementedError for now.

2. src/agents/views.py: domain_view(s, candidates, role, round, prior, others) -> str.
   - flatten(obj, prefix) yields "path=value (source)" lines: Tagged -> its .value with its
     source; raw numbers from s.flight -> "(data)"; dotted paths and [i] indexes exactly as a
     reviewer would resolve them (e.g. "alternates[0].distance_nm=190 (data)"). Lists capped at
     4 items + "...(n more)", dicts capped at 15 lines, None/NaN -> null.
   - Role field allow-lists (ONLY these appear in the DATA block):
     ATC: flight.{AIRLINE,FLIGHT_NUMBER,TAIL_NUMBER,ORIGIN_AIRPORT,DESTINATION_AIRPORT,
       SCHEDULED_DEPARTURE,SCHEDULED_ARRIVAL,DEPARTURE_DELAY,TAXI_OUT,WEATHER_DELAY},
       dest_disruption, taxi_congestion, nominal_aar, wake_category.
     PILOT: flight.{AIRLINE,FLIGHT_NUMBER,ORIGIN_AIRPORT,DESTINATION_AIRPORT,SCHEDULED_ARRIVAL,
       DEPARTURE_DELAY,DISTANCE,SCHEDULED_TIME,WEATHER_DELAY}, fuel_reserve_min,
       crew_duty_remaining_min, wake_category, alternates, connections.
     GROUND: flight.{AIRLINE,FLIGHT_NUMBER,TAIL_NUMBER,DESTINATION_AIRPORT,SCHEDULED_ARRIVAL,
       DEPARTURE_DELAY,LATE_AIRCRAFT_DELAY}, gates, downstream_legs, taxi_congestion,
       connections (count only, as "connections.count=N (estimated)").
     Never include flight.ARRIVAL_DELAY, ARRIVAL_TIME, WHEELS_ON, TAXI_IN for any role.
   - CANDIDATES block: one JSON line per candidate with candidate_id, kind, params,
     est_delay_min; add est_knock_on_min for PILOT and GROUND only.
   - Round 2 block (when round == 2): "YOUR ROUND-1 MESSAGE" = prior's acceptable, vetoes,
     top-3 ranking ids; "OTHER AGENTS' ROUND-1 POSITIONS" = for each message in others:
     agent, acceptable ids, vetoes as "id: reason" with cited_field REMOVED.
   - Final line: "Reply by calling submit_message exactly once."

3. StubAgent.propose: deterministic preference heuristics, no thresholds or compliance logic.
   Kind weights per role: ATC {slot_shift 1.0, ground_hold .9, gate_swap .7, tail_swap .6,
   hold .4, divert .3}; PILOT {slot_shift 1.0, gate_swap .9, ground_hold .7, hold .5,
   tail_swap .4, divert .2}; GROUND {gate_swap 1.0, slot_shift .9, hold .6, ground_hold .5,
   tail_swap .4, divert .1}. score = 0.6*weight + 0.4*(1 - delay_norm) where delay =
   est_delay_min (ATC, PILOT) or est_delay_min + est_knock_on_min (GROUND), min-max
   normalised over the menu (all equal -> 0), clamp to [0,1], round to 3 dp.
   ranking = every candidate sorted by score desc, rationale one sentence, cited_fields =
   one real "path=value" line from this role's own DATA block (ATC dest_disruption,
   PILOT fuel_reserve_min, GROUND taxi_congestion). vetoes = the single lowest-scored id with
   that same cited_field. Round 1 acceptable = top 3 ids (minus vetoed). Round 2 acceptable =
   set(prior.acceptable) | {ids accepted by any other that this agent did not veto} | {4th
   ranked id}, order preserved; if prior is None treat as round 1. Raise ValueError on empty
   candidates. No randomness.

4. tests/test_agents.py: build a small Scenario inline (fuel_reserve_min Tagged(78,
   "estimated"), crew_duty_remaining_min Tagged(150,"synthetic"), wake_category Tagged("L",
   "assumed"), nominal_aar Tagged(90,"assumed"), dest_disruption Tagged(14,"data"),
   taxi_congestion Tagged(1.4,"data"), alternates [{iata:"AUS",distance_nm:190}], gates
   {"assigned":"B12","free":["B14","C3"]}, two downstream_legs, three connections) and six
   candidates SLOT+15, SLOT+30, HOLD20, HOLD40, DIVERT_AUS, GATE_B12 with est values.
   Tests: (a) valid message all roles round 1, ranking covers all ids, acceptable and vetoes
   disjoint, every cited path resolves (write resolve(s, path) in the test); (b) round-2
   superset and adds an id another agent accepted; (c) three stubs over two rounds have a
   non-empty intersection; (d) ATC view has no fuel/crew/gates/connections text, PILOT no
   gates/nominal_aar/dest_disruption, GROUND no fuel/crew/alternates, none has ARRIVAL_DELAY;
   (e) round-2 view never contains another domain's "path=value" even when a veto cited it;
   (f) determinism. No API calls anywhere in this file. Run pytest tests/test_agents.py -q.
```

### D2 · System prompts `src/agents/prompts/{atc,pilot,ground}.txt` (12:50–13:00)

Paste the drafts from §3 verbatim. Then run Rohan's merge gate yourself:
```
grep -niE 'legal|safe to|compute|calculate|minus|subtract' src/agents/prompts/*.txt   # must print nothing
```
No Claude Code prompt needed. Commit `T2: prompts v1`, push.

### D3 · `ClaudeAgent` + fake-client tests (13:00–13:35)

Design is in §4. Decisions to lock here: **forced tool use** for structured output; **code sets `agent` and `round`** (the LLM returns only `acceptable`, `ranking`, `vetoes`); **one content retry**, with the validation error quoted back; **`calls` appended per API attempt**, each with `attempt` and `valid`; **client injectable** for tests.

**Edge cases:** response has no `tool_use` block (model answered in prose) → attempt invalid, `raw_text` = concatenated text blocks; tool input fails `_Reply.model_validate` (extra keys forbidden, score out of range, rationale > 240 chars, missing cited_fields) → invalid; both attempts invalid → `raise InvalidMessage(role, raw_text=<attempt-2 raw>, error="attempt 1: …; attempt 2: …")`; `anthropic.APIError` after the SDK's own transport retries → re-raised as-is (Rohan's mediator logs it as `exception`; it is *not* a content retry); `usage` missing `cache_read_input_tokens` → 0; `max_tokens` hit (`stop_reason == "max_tokens"`) → invalid attempt (truncated JSON). The SDK's `max_retries=2` is transport-level (429/5xx) and distinct from the single content retry — write that sentence in the module docstring so a judge reading the code doesn't count it as "two retries".

**Tests:** `FakeClient` with a scripted queue of fake responses (`content` blocks, `usage`, `stop_reason`):
1. Valid tool call first time → one entry in `calls`, `valid=True`, `cost_usd` equals hand-computed `(in*0.10 + out*0.50)/1e6`, `cache_read_tokens` recorded.
2. Invalid then valid → two `calls` entries `[False, True]`, second request's last user turn contains the Pydantic error text, returned message validates.
3. Invalid twice → `InvalidMessage` with `raw_text` non-empty and `error` naming both attempts; `calls` has two `valid=False` entries.
4. Prose reply with no tool block → counts as invalid attempt.
5. System prompt file for each role loads and contains the role name; the request's `system` carries `cache_control: {"type": "ephemeral"}`; `tool_choice` forces `submit_message`.
6. `test_live_haiku_one_call` — `@pytest.mark.skipif(not os.getenv("LIVE_AGENT_TEST"))`: one real PILOT call on the mini scenario, asserts a valid `AgentMessage`, prints tokens, `cost_usd`, `latency_s`, `cache_read_tokens`.

**Claude Code prompt (Session 1):**
```
Read CLAUDE.md and docs/plan-rohan.md §0 notes 3–5. Edit only src/agents/base.py and
tests/test_agents.py. Implement ClaudeAgent.

Constructor: ClaudeAgent(role, model, client=None, max_tokens=1200, temperature=0).
client defaults to anthropic.Anthropic(max_retries=2, timeout=60). Load the system prompt
from src/agents/prompts/{atc|pilot|ground}.txt once; keep self.calls: list[dict] = [].

Define private Pydantic models with extra="forbid": _RankingItem(candidate_id: str,
score: float ge=0 le=1, rationale: str max_length=240, cited_fields: list[str]),
_Veto(candidate_id: str, reason: str max_length=240, cited_field: str),
_Reply(acceptable: list[str], ranking: list[_RankingItem], vetoes: list[_Veto]).
Tool: {"name": "submit_message", "description": "Submit your negotiation position",
"input_schema": _Reply.model_json_schema()}; tool_choice {"type":"tool","name":"submit_message"}.

propose(s, candidates, round, prior, others=None):
  user = src.agents.views.domain_view(s, candidates, self.role, round, prior, others).
  messages = [{"role":"user","content": user}].
  For attempt in (1, 2):
    t0 = perf_counter(); resp = client.messages.create(model, system=[{"type":"text",
    "text": system_prompt, "cache_control": {"type":"ephemeral"}}], messages=messages,
    tools=[tool], tool_choice=..., max_tokens, temperature). latency = perf_counter()-t0.
    raw_text = json.dumps(tool_use.input) if a tool_use block exists else the joined text
    blocks. Validate: tool_use block present, stop_reason != "max_tokens",
    _Reply.model_validate(tool_use.input). Record a dict in self.calls: {round, attempt,
    tokens_in, tokens_out, cache_read_tokens, cache_write_tokens, cost_usd, latency_s, valid}
    with cost_usd = (tokens_in*in + cache_write*1.25*in + cache_read*0.10*in +
    tokens_out*out)/1e6 using PRICES keyed by the MODEL_IDS alias (fall back to "haiku"
    prices with a warning if the model id is not in MODEL_IDS.values()). Missing usage
    fields -> 0.
    If valid: return AgentMessage(agent=self.role, round=round, acceptable=reply.acceptable,
    ranking=[i.model_dump() for i in reply.ranking], vetoes=[v.model_dump() for v in reply.vetoes]).
    If invalid and attempt == 1: append the assistant content and a user turn "Your reply
    failed validation: <error>. Call submit_message once more with a payload that satisfies
    the schema. Do not change your position." and continue.
  After attempt 2: raise InvalidMessage(self.role, raw_text, "attempt 1: ...; attempt 2: ...").
  anthropic.APIError propagates unchanged. Docstring must state: the SDK max_retries=2 is
  transport-level (429/5xx); content validation gets exactly one retry; nothing is repaired.

Tests (append to tests/test_agents.py): a FakeClient whose .messages.create pops scripted
responses (SimpleNamespace with content, usage, stop_reason) and records requests. Cover:
valid first try with exact cost; invalid then valid (second request includes the error text);
invalid twice -> InvalidMessage with raw_text and both attempts in error, calls has two
False entries; prose reply without tool_use -> invalid; the request's system has
cache_control ephemeral and tool_choice forces submit_message; each role's prompt file loads.
Add test_live_haiku_one_call skipped unless env LIVE_AGENT_TEST=1: one real PILOT call on the
mini scenario with model MODEL_IDS["haiku"], assert valid, print the calls entry.
Run pytest tests/test_agents.py -q (must pass with no network).
```

### D4 · Streamlit UI panels 1–4 (13:35–14:10)

Design in §5. Lock these decisions: **two files** `app/streamlit_app.py` (layout) and `app/loaders.py` (file IO, `safe_get`, source-tag colours, log append) so the logic is unit-testable without Streamlit; **run JSON is read-only** — Approve/Reject appends a `human_decision` event to `recommendation.log_path` via `src.log.consensus_log.ConsensusLog` and the UI derives current state from the last `human_decision` event in the `.jsonl` (**confirm with Rohan** that he does not also want `recommendation.human_decision` rewritten in the `.json`; assume append-only). Dropdown globs `runs/*.json` and `runs/live/*.json` sorted by mtime.

**Edge cases:** `runs/` empty → `st.info` with the exact CLI command; a JSON missing `reviewer` → "reviewer not run"; missing `fallback` → treated as not fired; `turns == []` with `meta.agents == "none"` → "solver-only baseline, no negotiation"; `chosen is None` → red "No option passes engine and reviewer — escalate", Approve disabled; verdict `REJECT` → Approve requires a non-empty justification; unknown source tag → grey; `Turn.invalid_messages` dict shape unknown → render whatever keys exist, always show `raw_text`/`error` if present (**assume keys `agent, round, reason, raw_text, error`** — confirm); a round absent → "round 2 not needed (consensus in round 1)" or "fallback fired after round N"; `.jsonl` unreadable → state "unknown", buttons still work.

**Tests (`tests/test_app_loaders.py`, no Streamlit import):** `safe_get` on nested paths with defaults; `source_colour("synthetic")` and unknown tag; `list_runs(tmp)` ordering; `human_state(jsonl)` returns last decision; `append_human_decision(...)` writes one JSONL line with `event == "human_decision"`, `decision`, `by`, `note`, `scenario_id`, `ts`. Manual: `streamlit run app/streamlit_app.py` shows the row-0 stub run and the AA334 run; press Approve; `tail -1 runs/<id>.jsonl` shows the event.

**Claude Code prompt (Session 2):**
```
Read CLAUDE.md, docs/plan-rohan.md §3.1 (event vocabulary) and §3.4 (runs/<scenario_id>.json
layout: meta, scenario, candidates, rule_results, turns, recommendation, fallback, reviewer),
src/schemas.py and src/log/consensus_log.py. Edit only app/ and tests/test_app_loaders.py.
If runs/ is empty, first run: python -m src.cli --row-id 0 --agents stub --out runs/

app/loaders.py (pure functions, no streamlit import): list_runs(dirs=("runs","runs/live"))
-> [(label, path)] newest first; load_run(path) -> dict via json (st.cache_data applied in
the app, keyed on path+mtime); safe_get(d, "a.b[0].c", default=None); SOURCE_COLOURS =
{"data":"#2e7d32","estimated":"#1565c0","assumed":"#ef6c00","synthetic":"#6a1b9a"},
unknown -> "#616161"; tagged_rows(scenario) -> list of (field, value, source, note) for every
dict with keys value/source; human_state(log_path) -> last human_decision event or None;
append_human_decision(log_path, scenario_id, decision, by, note) using ConsensusLog.append
with event "human_decision" (do not modify the run .json).

app/streamlit_app.py, wide layout, sidebar: run dropdown from list_runs; buttons "Showcase
AA334" (first path containing 'aa334'), "Failure case" (runs/failure_showcase.json, else
runs/aa334_forced_deadlock.json, else first run with fallback.fired true), "Evaluation" tab
placeholder (I add it later). Header: scenario_id, meta.agents/model, badge for
recommendation.decided_by, badge for reviewer.verdict (APPROVE green, MODIFY amber, REJECT
red, missing grey "reviewer not run"), red banner if fallback.fired with its reason.
Panel 1 "Scenario": flight basics (airline, flight, tail, origin->dest, scheduled times,
departure delay, delay causes) from scenario.flight; a table of tagged_rows with the source
cell coloured via a pandas Styler; counts per source tag as four st.metric cards; expanders
for downstream_legs and alternates.
Panel 2 "Negotiation": for each turn, three columns ATC/PILOT/GROUND: acceptable ids as
chips, vetoes as "id — reason (cited_field)", top-3 ranking with score bar, rationale and
cited_fields; invalid messages count in red with an expander listing each one (reason,
raw_text, error) — never hidden; the turn.intersection line. If turns is empty and
meta.agents == "none" show "solver-only baseline: no negotiation". If fewer rounds than
2, explain why using recommendation.decided_by and fallback.reason.
Panel 3 "Checks": pivot of rule_results (rows candidate_id, columns rule_id, cell PASS/FAIL
coloured, tooltip-ish second table with observed/threshold/citation/source on selection via
a selectbox); reviewer block: verdict, notes list, tables for reviewer.re_derived,
cited_mismatches, engine_disagreements when present; fallback block with reason, objective,
n_eligible, excluded.
Panel 4 "Recommendation": chosen candidate card (id, kind, params, est_delay_min,
est_knock_on_min) or red "No option passes engine and reviewer — escalate to duty manager"
if chosen is null; a line "rests on N synthetic, M assumed, K estimated values"; current
human state from human_state(recommendation.log_path); inputs "Your name", "Note"; buttons
Approve / Reject calling append_human_decision then st.rerun. Approve disabled when chosen
is null; when verdict is REJECT, Approve requires a non-empty note and shows a warning.
Every panel wrapped in try/except that renders st.warning(f"{panel}: {exc}") instead of
crashing. Use safe_get everywhere; never assume a key exists.
tests/test_app_loaders.py: safe_get, SOURCE_COLOURS unknown tag, list_runs order,
human_state, append_human_decision writes exactly one JSONL line with the right keys.
Run pytest tests/test_app_loaders.py -q, then streamlit run app/streamlit_app.py and
confirm the row-0 run renders.
```

### D5 · Eval panel + failure preset (14:45–15:00)

**Decisions:** reads `eval/results/summary.csv` (long format `metric,value,unit,n,definition,note`) and `eval/results/meta.json`; shows headline `st.metric` cards for `n_completed`, `consensus_rate`, `fallback_rate_*` (summed), `agent_top_pick_rule_fail_rate`, `schema_invalid_rate`, `reviewer_REJECT_rate`, `cited_value_mismatch_rate`; a full table of all metrics with `definition` and `note`; modelled-vs-actual metrics in their own section captioned with their `note` column verbatim ("model estimate; not comparable like-for-like with actual"); a red banner if `meta.guard_stopped` with reason and `n_completed`. Failure preset: already in sidebar from D4; make it also auto-scroll by opening Panel 3 expander and showing a one-line "How the user knows: …" caption built from `fallback.reason` and `reviewer.verdict`.

**Edge cases:** file missing → `st.info("Evaluation not run. python -m eval.run_eval ...")`; a metric missing → card shows "—"; `value` non-numeric → shown as text; `n` blank → omitted.

**Tests:** `tests/test_app_loaders.py`: `load_summary(path)` on a hand-made 6-row CSV returns a dict keyed by metric; missing file returns `None`. Manual: panel renders against the hand-made CSV at `/tmp/evaltest/summary.csv` from Rohan's `--n 3` stub run.

**Claude Code prompt (Session 2):**
```
Read docs/plan-rohan.md §3.6 (summary.csv long format metric,value,unit,n,definition,note;
meta.json keys model, seed, n, n_completed, guard_stopped, reason, cost). Edit only app/ and
tests/test_app_loaders.py. Add to app/loaders.py: load_summary(path) -> dict[metric ->
{value, unit, n, definition, note}] or None if missing; load_meta(path) -> dict or {}.
Add an "Evaluation" tab to app/streamlit_app.py reading eval/results/summary.csv and
meta.json (path overridable via env EVAL_RESULTS_DIR): red banner if guard_stopped;
st.metric cards for n_completed, consensus_rate, total fallback rate (sum of
fallback_rate_* metrics), agent_top_pick_rule_fail_rate, schema_invalid_rate,
reviewer_REJECT_rate, cited_value_mismatch_rate (show "—" when absent); a section
"Modelled vs actual delay" listing every metric whose name starts with modelled_ or actual_,
with the note column shown verbatim as a caption; then the full table (metric, value, unit,
n, definition, note). If the file is missing show st.info with the run_eval command.
Failure preset: when the sidebar "Failure case" button was pressed, show above Panel 3 a
caption "How the user knows: reviewer {verdict}; fallback fired because {reason}; decided
by {decided_by}" and expand the fallback block. Add load_summary tests (6-row CSV, missing
file). Run pytest tests/test_app_loaders.py -q and streamlit run with
EVAL_RESULTS_DIR=/tmp/evaltest to confirm it renders.
```

### D6 · Backup video (15:00–15:10, v2 at 15:30 if eval panel merged)

Not a Claude Code task. macOS: QuickTime → New Screen Recording (or OBS). One take, 60 s, no audio (Sydelle narrates live): 0–25 s UI on the AA334 live-Haiku run — Scenario tags, Negotiation three columns, Checks with verdict; 25–45 s sidebar "Failure case" → fallback banner, reason, fallback block; 45–55 s Evaluation tab (v1: whatever renders, even `--n 3` stub results, labelled on screen); 55–60 s terminal `python -m src.cli --row-id <AA334> --agents stub --force-deadlock --pretty`. Save as `docs/backup_demo_v1.mp4`; AirDrop/USB to Rohan's laptop; also to your phone. v2 replaces v1 only if it finishes by 15:40. Do not commit the MP4 if > 25 MB; note its location in the README paragraph you give Sydelle.

---

## 3. System prompt design

### 3.1 What each agent sees and must not see

The prompt text is static per role; all scenario data arrives in the user message built by `views.py` (D1). The allow-lists are the enforcement; the prompt just tells the agent the boundary exists.

| Role | Sees (dotted paths) | Must not see | Why |
|---|---|---|---|
| ATC | `flight.{SCHEDULED_*,DEPARTURE_DELAY,TAXI_OUT,WEATHER_DELAY,…}`, `dest_disruption`, `taxi_congestion`, `nominal_aar`, `wake_category`; candidates with `est_delay_min` | fuel, crew, gates, connections, alternates' distances | Brief: wake separation, taxiway blockage, throughput |
| PILOT | `flight.{DISTANCE,SCHEDULED_TIME,WEATHER_DELAY,…}`, `fuel_reserve_min`, `crew_duty_remaining_min`, `wake_category`, `alternates[i].{iata,distance_nm}`, `connections[i].*`; candidates with `est_delay_min`, `est_knock_on_min` | `gates`, `nominal_aar`, `dest_disruption` | Brief: fuel, safety, turbulence, connections |
| GROUND | `flight.{TAIL_NUMBER,LATE_AIRCRAFT_DELAY,…}`, `gates.*`, `downstream_legs[i].*`, `taxi_congestion`, `connections.count`; candidates with `est_delay_min`, `est_knock_on_min` | fuel, crew duty, alternates, `nominal_aar` | Brief: gates, crew overtime, turnaround |
| all | `candidate_id, kind, params` for every option; in round 2 the others' acceptable ids and veto *reasons* | **rule results, ever**; the outcome fields `ARRIVAL_DELAY/ARRIVAL_TIME/WHEELS_ON/TAXI_IN`; other agents' `cited_field` values | How the rules engine "catches" agent picks is measured; cross-domain leakage would blur the three-domain claim |

Every DATA line carries its source tag — `fuel_reserve_min=78 (estimated)` — so the agent can voice uncertainty in rationale ("the fuel figure is an estimate") without doing anything with it.

### 3.2 Domain goals → ranking and vetoes

| Role | Prefers (high score) | Dislikes (low score) | Veto trigger (preference-based, cited) |
|---|---|---|---|
| ATC | small slot shifts, ground hold at origin when `dest_disruption` is high relative to `nominal_aar`; options that regularise the stream | airborne holds at the peak, diversions that re-enter the sector; anything adding taxi pressure when `taxi_congestion` is high | holding during heavy disruption (`dest_disruption=…`); taxi-heavy options when `taxi_congestion=…` is high |
| PILOT | earliest arrival at destination (connections), least added airborne time; gate swaps | long holds (fuel, turbulence in weather — `WEATHER_DELAY` present), diversions (connections lost, long alternate distance) | the longest hold when `fuel_reserve_min=…` is low or estimated; divert to a far alternate (`alternates[i].distance_nm=…`) when connections are many |
| GROUND | gate swaps, small slot shifts that keep the downstream leg's departure | diversions (gate and crew at a different airport, turnaround lost), long holds pushing `downstream_legs[0].SCHEDULED_DEPARTURE` | divert when downstream legs exist (`downstream_legs[0].FLIGHT_NUMBER=…`); options with high `est_knock_on_min` when the gate is already contested (`gates.*`) |

Scores are 0–1 preferences for *this domain*, not predictions. Acceptable = "can live with"; the mediator intersects. Rationale ≤ 240 chars (tool schema), one sentence.

### 3.3 Round-2 concession (Monotonic Concession Protocol, plan-rohan §3.3)

The user message gains the agent's own round-1 message and the others' positions. The prompt requires: (1) `acceptable` ⊇ round-1 `acceptable` — Rohan's mediator marks a shrink as `monotonic_violation` → fallback; (2) add at least one id another agent accepted, picking the least harmful to own goals, unless it's a standing veto (then say so in that candidate's rationale); (3) vetoes may be withdrawn, never added on a round-1 accepted id. If the 14:30 cost test shows `consensus_rate ≈ 0`, the only knob you turn is (2) → "add every id another agent accepted that you did not veto"; the mediator does not change.

### 3.4 Keeping the LLM out of arithmetic and legality

Four mechanisms, in order of strength: (a) **structural** — rule results never reach the agent; the DATA block contains only quotable values, so there is nothing to "check against"; (b) **tool schema** — only `acceptable/ranking/vetoes` can be returned; `cited_fields` must be `path=value` strings, and Rohan's reviewer cross-checks every value, so an invented number becomes a visible `cited_value_mismatch`; (c) **prompt** — explicit "quote, never derive" and "never say an option is permitted or compliant" rules, plus "the rules engine owns thresholds"; (d) **wording discipline** — the prompts avoid the tokens in Rohan's gate grep (`legal`, `safe to`, `compute`, `calculate`, `minus`, `subtract`), so prohibition sentences don't trip it. Keep it that way when you tune.

### 3.5 The prompts

**`src/agents/prompts/atc.txt`**
```
You are the ATC AGENT in a three-party negotiation about one disrupted arriving flight. The
other parties are a PILOT agent and a GROUND agent. A human duty manager makes the final
decision, and a separate deterministic rules engine checks every option against operational
limits. You do neither of those jobs: you state the air-traffic position.

YOUR DOMAIN, and only this: the destination airport's runway, final approach and taxiways.
Goals in priority order:
1. Wake-turbulence spacing on final. When the destination hour is already disrupted
   (dest_disruption high relative to nominal_aar) prefer options that move this flight away
   from the peak over options that add airborne holding into it. A heavier wake_category
   deserves more spacing margin.
2. Taxiway flow. When taxi_congestion is high, prefer options that keep aircraft off the
   taxiways at the peak (slot shifts, a ground hold at origin) over options that add them.
3. Sector throughput. Prefer options that keep the arrival stream regular. Small slot shifts
   disturb it least; airborne holds and diversions disturb it most.

WHAT YOU RECEIVE: a DATA block of "path=value (source)" lines for your domain only, a
CANDIDATES block listing every option, and in round 2 your own round-1 message plus the other
agents' round-1 positions. You do not receive fuel, crew-duty, gate or passenger data; do not
speculate about them. The PILOT and GROUND agents own those.

HOW TO ANSWER: call the submit_message tool exactly once.
- ranking: every candidate_id from the CANDIDATES block, each with a score from 0.0 (worst for
  your domain) to 1.0 (best), a one-sentence rationale, and cited_fields.
- acceptable: the candidate_ids you can live with from the air-traffic point of view. List at
  least one unless every option is intolerable; if so, say why in the rationales.
- vetoes: candidate_ids you refuse, each with a reason and exactly one cited_field. An id must
  never appear in both acceptable and vetoes.
- cited_fields entries are copied verbatim from the DATA block, for example
  "dest_disruption=14". Never invent a path or a value. Use an empty list if nothing applies.

LIMITS ON YOUR BEHAVIOUR:
- Quote values; never derive new numbers. No sums, differences, rates, conversions or numeric
  comparisons between fields. "dest_disruption=14 is high for this hour" is fine; producing a
  figure that is not in the DATA block is not.
- Never state that an option is permitted, compliant, within limits or meets a regulation, and
  never state a threshold. The rules engine owns all of that.
- Note the source tag when it matters: a value marked assumed or synthetic deserves less weight
  in your rationale than one marked data.
- State your position; do not address or persuade the other agents.

ROUND 2 (only when round-1 positions are present): this is a concession round.
- Your acceptable list must include every id from your round-1 acceptable list; you may only
  widen it.
- Add at least one id that another agent listed as acceptable, choosing the one least harmful
  to your goals. If the only such ids are ones you vetoed in round 1 and the veto still stands,
  keep the veto and explain in that candidate's rationale.
- You may withdraw a round-1 veto. You may not add a veto on an id you accepted in round 1.
- Give each concession a rationale naming the cited field that makes it tolerable.
```

**`src/agents/prompts/pilot.txt`**
```
You are the PILOT AGENT, representing the flight crew of one disrupted arriving flight in a
three-party negotiation with an ATC agent and a GROUND agent. A human duty manager makes the
final decision, and a separate deterministic rules engine checks every option against
operational limits. You do neither of those jobs: you state the flight-deck position.

YOUR DOMAIN, and only this: the aircraft, its fuel and crew state, its passengers.
Goals in priority order:
1. Preserve fuel reserves. Options that add airborne time (holds, long diversions) draw on
   fuel_reserve_min; prefer options that add little or none, and treat a low or estimated
   fuel figure as a reason for caution.
2. Flight safety and crew state. A long delay erodes crew_duty_remaining_min; prefer options
   that keep the day short. If WEATHER_DELAY is present, holding near the destination is the
   most exposed place to be.
3. Minimise turbulence and passenger discomfort. Extended holding in weather is worse than a
   slot shift or a ground hold; a diversion avoids the weather but adds a second approach.
4. Protect passengers' connections. Earlier arrival at the destination protects the
   connections listed; a diversion loses all of them.
Alternates are listed with their distance; a nearer alternate is less costly in fuel and time
than a far one, but any diversion ranks below arriving at the destination unless the hold
options look intolerable.

WHAT YOU RECEIVE: a DATA block of "path=value (source)" lines for your domain only, a
CANDIDATES block listing every option, and in round 2 your own round-1 message plus the other
agents' round-1 positions. You do not receive runway rates, taxiway congestion or gate data;
do not speculate about them. The ATC and GROUND agents own those.

HOW TO ANSWER: call the submit_message tool exactly once.
- ranking: every candidate_id from the CANDIDATES block with a score from 0.0 (worst for the
  flight deck) to 1.0 (best), a one-sentence rationale, and cited_fields.
- acceptable: the candidate_ids the crew can live with. List at least one unless every option
  is intolerable; if so, say why in the rationales.
- vetoes: candidate_ids you refuse, each with a reason and exactly one cited_field. An id must
  never appear in both acceptable and vetoes.
- cited_fields entries are copied verbatim from the DATA block, for example
  "fuel_reserve_min=78" or "alternates[0].distance_nm=190". Never invent a path or a value.

LIMITS ON YOUR BEHAVIOUR:
- Quote values; never derive new numbers. No sums, differences, burn rates, conversions or
  numeric comparisons between fields. "fuel_reserve_min=78 is an estimate and a 40-minute
  hold draws on it" is fine; producing a remaining-fuel figure is not.
- Never state that an option is permitted, compliant, within limits or meets a regulation, and
  never state a reserve or duty threshold. The rules engine owns all of that.
- Note the source tag when it matters: estimated and synthetic values deserve explicit caution.
- State your position; do not address or persuade the other agents.

ROUND 2 (only when round-1 positions are present): this is a concession round.
- Your acceptable list must include every id from your round-1 acceptable list; you may only
  widen it.
- Add at least one id that another agent listed as acceptable, choosing the one least harmful
  to your goals. If the only such ids are ones you vetoed in round 1 and the veto still stands,
  keep the veto and explain in that candidate's rationale.
- You may withdraw a round-1 veto. You may not add a veto on an id you accepted in round 1.
- Give each concession a rationale naming the cited field that makes it tolerable.
```

**`src/agents/prompts/ground.txt`**
```
You are the GROUND AGENT, representing hub ramp and gate operations for one disrupted arriving
flight in a three-party negotiation with an ATC agent and a PILOT agent. A human duty manager
makes the final decision, and a separate deterministic rules engine checks every option
against operational limits. You do neither of those jobs: you state the ground-operations
position.

YOUR DOMAIN, and only this: gates, ground crew and the aircraft's turnaround.
Goals in priority order:
1. Gate utilisation. The assigned and free gates are in the gates lines. Prefer options whose
   arrival timing fits a free gate; a gate swap is a tool you own, not a cost.
2. Avoid ground-crew overtime. Long delays push the turnaround into the next shift; prefer
   options with low est_knock_on_min.
3. Minimise turnaround delay for the downstream legs listed. The same tail flies on; an option
   that lands this aircraft at the hub, even later, usually beats a diversion, which strands
   the tail, the gate plan and the downstream legs. If no downstream legs are listed, say so
   and weigh diversion less harshly.
taxi_congestion tells you how slow the ramp is right now; when it is high, prefer options that
do not add aircraft to the ramp at the peak.

WHAT YOU RECEIVE: a DATA block of "path=value (source)" lines for your domain only, a
CANDIDATES block listing every option, and in round 2 your own round-1 message plus the other
agents' round-1 positions. You do not receive fuel, crew-duty, runway-rate or alternate data;
do not speculate about them. The PILOT and ATC agents own those.

HOW TO ANSWER: call the submit_message tool exactly once.
- ranking: every candidate_id from the CANDIDATES block with a score from 0.0 (worst for
  ground operations) to 1.0 (best), a one-sentence rationale, and cited_fields.
- acceptable: the candidate_ids ground operations can live with. List at least one unless
  every option is intolerable; if so, say why in the rationales.
- vetoes: candidate_ids you refuse, each with a reason and exactly one cited_field. An id must
  never appear in both acceptable and vetoes.
- cited_fields entries are copied verbatim from the DATA block, for example
  "downstream_legs[0].SCHEDULED_DEPARTURE=828" or "taxi_congestion=1.4". Never invent a path
  or a value.

LIMITS ON YOUR BEHAVIOUR:
- Quote values; never derive new numbers. No sums, differences, durations, conversions or
  numeric comparisons between fields. "est_knock_on_min=95 is the highest on the menu" is
  fine if it is visibly the highest; producing a new turnaround figure is not.
- Never state that an option is permitted, compliant, within limits or meets a regulation, and
  never state a turnaround or shift threshold. The rules engine owns all of that.
- Note the source tag when it matters: the gate model is synthetic, so say so when you rely
  on it.
- State your position; do not address or persuade the other agents.

ROUND 2 (only when round-1 positions are present): this is a concession round.
- Your acceptable list must include every id from your round-1 acceptable list; you may only
  widen it.
- Add at least one id that another agent listed as acceptable, choosing the one least harmful
  to your goals. If the only such ids are ones you vetoed in round 1 and the veto still stands,
  keep the veto and explain in that candidate's rationale.
- You may withdraw a round-1 veto. You may not add a veto on an id you accepted in round 1.
- Give each concession a rationale naming the cited field that makes it tolerable.
```

### 3.6 Tuning knobs (14:30–14:45 only, prompts only)

| Symptom from the 10-row test | Change |
|---|---|
| `schema_invalid_rate` > 10%, mostly `unknown_candidate` | Add to all three: "candidate_id values are exact strings from the CANDIDATES block; copy them character for character." |
| `consensus_rate` ≈ 0, round 2 adds nothing | Round-2 bullet 2 → "add every id another agent listed as acceptable that you did not veto in round 1." |
| `cited_value_mismatch_rate` > 20% | Add: "Each cited_fields entry is one whole DATA line up to and excluding the source tag." and shorten DATA block (cap lists at 3). |
| rationales exceed 240 chars → invalid | Add "under 25 words" to the ranking bullet. |
| An agent "declares compliance" in rationales | Strengthen the LIMITS bullet; it costs nothing, the reviewer already ignores prose. |

---

## 4. ClaudeAgent design (short)

- **Model IDs:** from the 12:20 `models.list()` check; stored in `MODEL_IDS` with env overrides `HAIKU_MODEL`/`SONNET_MODEL`. Haiku for eval, Sonnet for the live demo (Rohan's CLI passes `MODEL_IDS[mode]`).
- **Prompt caching:** the per-role system prompt is the static part and carries `cache_control: ephemeral`; the scenario goes in the user turn. The system prompt is ~700 tokens; if `cache_read_tokens` stays 0 after the second call in the live test, the model's minimum cacheable length is above that. **Do not pad** — note it in README ("system prompt below cache threshold; caching inactive, cost negligible") and move on (cut #1).
- **Structured output:** forced tool use (`tool_choice` → `submit_message`) with `input_schema` generated from `_Reply`; the SDK hands back a dict, which is still validated with Pydantic (`extra="forbid"`, score bounds, rationale length). `agent`/`round` are set by code, not the model. Validation only; no repair.
- **Single retry:** one further `messages.create` with the Pydantic error quoted. Both attempts recorded in `calls`. Second failure → `InvalidMessage(role, raw_text, error)`; Rohan's mediator logs `message_invalid` reason `schema` and falls back. The SDK's transport `max_retries=2` is documented as distinct.
- **Accounting:** `calls` entries `{round, attempt, tokens_in, tokens_out, cache_read_tokens, cache_write_tokens, cost_usd, latency_s, valid}` — superset of what plan-rohan §0.5 asks for (**confirm with Rohan** that per-attempt rows are fine for his sums; they are additive).
- **Testing without credits:** injected `FakeClient` with scripted responses; the only live test is behind `LIVE_AGENT_TEST=1` and makes one Haiku call (~$0.002). Run it exactly once at 13:20.

---

## 5. Streamlit UI design (short)

| Panel | Reads | Shows | Degrades to |
|---|---|---|---|
| Sidebar | `runs/*.json`, `runs/live/*.json` | run dropdown (newest first), **Showcase AA334**, **Failure case**, Evaluation tab | `st.info` with the CLI command if no runs |
| Header | `meta`, `recommendation`, `reviewer`, `fallback` | `decided_by` badge; verdict badge green/amber/red; red fallback banner with reason | grey "reviewer not run"; no banner if `fallback` absent |
| 1 Scenario | `scenario` | flight card; table of every `Tagged` field with coloured source cell (data green, estimated blue, assumed amber, synthetic purple, unknown grey); four tag-count metrics; downstream legs, alternates | missing fields skipped silently, counts still render |
| 2 Negotiation | `turns` | per round, three columns; acceptable chips; vetoes with reason + cited field; top-3 with score bar; **invalid-message count in red + expander with raw text and error**; intersection line; explanation of missing round 2 | "solver-only baseline" when `turns == []` |
| 3 Checks | `rule_results`, `reviewer`, `fallback` | candidate × rule PASS/FAIL pivot; selected cell's observed/threshold/citation/source; reviewer notes, re-derived, cited mismatches, engine disagreements; fallback reason/objective/eligible/excluded | tables omitted when keys missing; verdict line always present |
| 4 Recommendation | `recommendation`, `.jsonl` | chosen card; "rests on N synthetic, M assumed, K estimated values"; current human state from last `human_decision` event; name + note; **Approve / Reject** → `ConsensusLog(log_path).append({"event":"human_decision","scenario_id":…,"decision":…,"by":…,"note":…})` then rerun | `chosen is None` → escalation banner, Approve disabled; verdict REJECT → Approve needs a note |
| Evaluation | `eval/results/summary.csv`, `meta.json` | guard banner; headline metric cards; modelled-vs-actual with `note` verbatim; full long-format table | `st.info` with run command if files missing; "—" for absent metrics |

Every panel is wrapped so an exception renders as a warning naming the panel, not a crash. All reads via `safe_get`. The run `.json` is never written; the `.jsonl` is append-only — the UI respects the log's contract.

---

## 6. Checkpoint handoffs

**Checkpoint 1 (push ≤ 12:58, Rohan merges 13:00).** Branch `t2/agents` with: `base.py` (`others=None`, `MODEL_IDS`, `PRICES`, `InvalidMessage`, `StubAgent` done, `ClaudeAgent` raising `NotImplementedError` if D3 isn't finished), `views.py`, three prompt files, `tests/test_agents.py`. Self-check before posting "ready": `pytest tests/test_agents.py -q` green with network off; `python -c "from src.agents.base import Agent, StubAgent, ClaudeAgent, InvalidMessage, MODEL_IDS, PRICES"`; grep gate prints nothing; stub round-2 superset test present (Rohan's gate item 2 depends on it). Tell Rohan the `calls` rows are per attempt and that agents don't see `ARRIVAL_DELAY` (his §0.2/§3.5 ambiguities).

**Checkpoint 2 (push ≤ 14:12).** Branch `t2/ui` (rebased on `main` after CP1, containing finished `ClaudeAgent`). Self-check: `pytest -q` all green; `streamlit run` shows the row-0 stub run and the AA334 live Haiku run Rohan produced at 13:20; press Approve → `tail -1 runs/<aa334>.jsonl` is a `human_decision` event with `ts`, `scenario_id`, `decision`, `by`, `note`; load the `--force-deadlock` run → red banner reads `forced_deadlock`; `LIVE_AGENT_TEST` cost line pasted in chat for Sydelle's budget sheet. If panels 1–4 don't render the AA334 run by 14:25, tell Rohan "cut #7" yourself — don't let him discover it.

**Checkpoint 3 (push ≤ 15:12).** Eval tab, failure preset, `tests/test_app_loaders.py`, README paragraph (how to run the UI, where the video is) handed to Sydelle, video v1 on two laptops. Self-check: eval tab renders `/tmp/evaltest/summary.csv`; after Rohan merges `eval/results/` (~15:20), reload and confirm the real `summary.csv` renders and `n_completed` matches what Sydelle quotes; "Failure case" button loads `runs/failure_showcase.json` once Waseem's is merged (fallback to the forced-deadlock run until then).

---

## 7. Cut list, risks, demo role

**Cut order (announce the number in chat):**
1. Prompt caching effort — if `cache_read_tokens` is 0 at 13:25, stop; README notes it.
2. Panel 2 ranking detail → acceptable/vetoes/invalid count only (trigger: panels not rendering by 13:55).
3. Approve/Reject name + note inputs → bare buttons with `by="demo"` (trigger: 14:05).
4. Eval panel charts/cards → the raw long-format table only (trigger: 14:55).
5. Failure preset button → judges select `failure_showcase.json` from the dropdown (trigger: 15:00).
6. Video v2 → v1 stands (trigger: eval not merged by 15:28).
7. Streamlit entirely → Rohan's `cli --pretty` (trigger: AA334 not rendering at 14:25, team cut #7). You then spend 14:30–15:00 on prompt tuning and record the video from the terminal.

**Never cut:** three separate `ClaudeAgent` calls per round; forced tool schema + Pydantic validation; `InvalidMessage` carrying raw text, one retry, no repair; `calls` accounting; `others=None` kwarg; stub round-2 superset; `views.py` domain allow-lists; the `human_decision` log write; video v1.

**Risks specific to your modules:**

| Risk | Mitigation |
|---|---|
| Forced `tool_choice` or `cache_control` unsupported by the exact model id | `FakeClient` tests pass regardless; at 13:20 live test fails fast → drop `tool_choice` to `{"type":"any"}`, then to text-JSON parsing with a `{` prefill as last resort |
| Model returns prose or truncated JSON → high `schema_invalid_rate` | Honest result; it is logged and shown; §3.6 knob row 1 and `max_tokens` 1200 → 2000 |
| Agents converge 0% under the superset rule | Honest result, fallback does its job; one prompt knob (§3.6 row 2), mediator untouched |
| Cross-domain leakage via `others` reasons | `cited_field` stripped; test (e) proves no `path=value` from another domain appears |
| Prompt words trip Rohan's grep | Run the grep before every push; keep prohibition wording as drafted |
| Streamlit on Python 3.14 | Waseem's verdict stands; if Streamlit breaks on your machine, run the UI from Rohan's laptop (demo machine) and develop with `pytest` on `loaders.py` |
| Run JSON shape drifts from plan-rohan §3.4 | `safe_get` everywhere; panels degrade to warnings, never crash |
| Approve writes to the wrong file | Always `recommendation.log_path`; test asserts one appended line; Rohan checks the file at CP2 |
| Parallel eval 429s blamed on ClaudeAgent | Transport retries are the SDK's (`max_retries=2`); content retry is one; both documented in the docstring and `calls` |

**Demo and Q&A role.** You hold the backup video on your laptop (open, paused at 0:00) and start it only if Rohan says "video". In Q&A you answer agent questions; keep each under 20 s:

- *Why three calls, not one prompt?* "Each agent gets only its domain's data — `views.py` allow-lists — and returns a schema-checked position. The mediator intersects; neither the agents nor the mediator decide legality, the rules engine does."
- *How do you stop the LLM doing maths or declaring something legal?* "Structurally: it never sees rule results, its only output channel is a tool schema of ids, scores and quoted `path=value` citations; the reviewer cross-checks every cited value against the scenario, so an invented number shows up as a mismatch in the eval."
- *What happens when an agent returns garbage?* "One retry with the validation error. Second failure raises `InvalidMessage` with the raw text; it's logged, counted in `schema_invalid_rate`, and the deterministic fallback decides. Nothing is repaired."
- *How does it converge in under 3 turns?* "Monotonic concession: round-2 acceptable sets can only widen, and each agent must add an id another agent accepted. Two rounds max; turn 3 is the fallback. A shrinking set is itself an invalid message."
- *Cost and latency?* Quote the `calls` numbers from the live test and `summary.csv` (`cost_usd_mean`, `latency_s_mean`); Haiku for the 200-row eval, Sonnet live.
- *Where does the agent layer fail?* "When agents never agree the fallback rate goes to 100% — that's visible in the eval and the log, and the human sees `decided_by: fallback`. When they agree on something unsafe, the rules engine excludes it and the consensus is void — `consensus_excluded_by_rules_rate`." Point at the failure preset on screen.