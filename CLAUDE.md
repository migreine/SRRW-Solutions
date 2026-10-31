# CLAUDE.md

Multi-agent air-traffic disruption negotiation for Autonomous SG 2026, Airbus track, Challenge #2.
Read `docs/briefing.md` (project context, data, rubric) and `docs/timeline.md` (plan, interfaces,
task cards) before starting. `docs/checklist.md` lists each member's tasks.

**Principle: LLMs negotiate and explain; deterministic code decides; every decision traces to a rule
ID and a data field; a human approves.**

## Layout and owners

| Path | Owner | What |
|---|---|---|
| `src/schemas.py` | Rohan (L) | Shared Pydantic types. The contract: add fields freely, never rename or remove. |
| `src/scenario/` | Waseem (T1) | `flights.csv` row -> `Scenario` |
| `src/options/` | Waseem (T1) | Fixed candidate menu |
| `src/rules/` | Waseem (T1) | Deterministic rules engine, one rule ID per check |
| `src/agents/` | Reine (T2) | ATC / Pilot / Ground agents, stub and Claude |
| `src/mediator/` | Rohan (L) | Monotonic concession protocol, max 2 rounds |
| `src/reviewer/` | Rohan (L) | Independent safety re-check: APPROVE / REJECT / MODIFY |
| `src/fallback/` | Rohan (L) | Deterministic pick when there is no consensus |
| `src/log/` | Rohan (L) | Append-only JSONL consensus log |
| `src/cli.py` | Rohan (L) | Runs one scenario end to end |
| `eval/run_eval.py` | Rohan (L) | Evaluation harness |
| `eval/sample.py` | Waseem (T1) | Seeded evaluation sample |
| `app/` | Reine (T2) | Streamlit UI |
| `tests/` | Each module's owner | pytest |
| `docs/`, `README.md` | Sydelle (N) | Pitch, data limits, regulatory sources, slides |
| `data/` | - | Read-only inputs. Never modify. |
| `runs/`, `eval/results/` | - | Generated outputs |

## Rules for every session

- Import every shared type from `src/schemas.py`; never redefine one. Never rename a field.
- No LLM output is trusted: parse it with Pydantic. On failure, log the raw text and the error to the
  consensus log and raise. No auto-repair, and no more than one retry for invalid JSON.
- No arithmetic, scheduling or legality logic in any prompt or agent module. If a check is needed, it
  belongs in `src/rules/`.
- Every estimated, synthetic or assumed number is a `Tagged` value. Every `RuleResult` cites a source.
- Seed all randomness with 42 (`random.seed(42)`, `np.random.default_rng(42)`). Gate assignments are
  locked per scenario.
- Edit only your own directories. Write a test alongside each module.
- Commit every 20 minutes with a message starting with your tag (`L:`, `T1:`, `T2:`, `N:`). Merges to
  `main` happen only at checkpoints, done by Rohan.
- Never commit `.env` or print API keys.
- Prefer boring code: pandas, Pydantic, anthropic SDK, Streamlit, pytest. No new frameworks.

## Commands

```
pip install -r requirements.txt
pytest -q
python -m src.cli --row-id 0 --agents stub          # must always work on main
python -m src.cli --row-id <N> --agents haiku --out runs/
python -m eval.run_eval --n 200 --seed 42 --agents haiku --out eval/results/
streamlit run app/streamlit_app.py
```
