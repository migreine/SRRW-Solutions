# scripts

`make_timeline.py` asks **Claude Fable 5.1** (`claude-fable-5-1`) for a plan in planning mode (no
code). It sends your request file, the context files you list, and the track PDF
(`problem statement/Autonomous SG 2026_Airbus Track.pdf`) to the model, streams the answer to the
terminal and saves it as Markdown. It reads `ANTHROPIC_API_KEY` from your environment or the repo
`.env`, so **each run bills the caller's own credits**.

## Setup (once)

1. `git pull`
2. `pip install -r requirements.txt` (or just `pip install anthropic` for this script)
3. Copy `.env.example` to `.env` and paste your own key from platform.claude.com.

Never commit `.env` and never paste a key into chat or an issue.

## Usage

Run from the repo root. All paths are relative to the repo root.

| Flag | Default | Meaning |
|---|---|---|
| `--request` | `docs/timeline-request.md` | Markdown file with the request (what to plan) |
| `--context` | `docs/briefing.md` | One or more project files sent as context |
| `--out` | `docs/timeline.md` | Where the plan is written |
| `--effort` | `high` | Model effort: `low`, `medium`, `high`, `xhigh`, `max` |

With no flags it generates the team timeline (`docs/timeline-request.md` → `docs/timeline.md`).
The track PDF is always attached and wins over project files if they conflict.

## Existing requests

| Request | Output | Owner | Status |
|---|---|---|---|
| `scripts/requests/rohan.md` | `docs/plan-rohan.md` | Rohan (L) | already generated |
| `scripts/requests/rohan-part2.md` | appended to `docs/plan-rohan.md` (§4–6) | Rohan (L) | already generated |
| `scripts/requests/reine.md` | `docs/plan-reine.md` | Reine (T2) | not yet run |

**Rohan** (already generated, for reference):

```
python scripts/make_timeline.py --request scripts/requests/rohan.md --out docs/plan-rohan.md --context docs/briefing.md docs/timeline.md CLAUDE.md src/schemas.py
```

**Rohan part 2** (already generated and appended): `docs/plan-rohan.md` was cut off in section 4, so
this wrote sections 4–6 only. The pattern for a truncated plan: keep the cut-off plan in the context,
write to a separate file, then append it by hand:

```
python scripts/make_timeline.py --request scripts/requests/rohan-part2.md --out docs/plan-rohan-part2.md --context docs/briefing.md docs/timeline.md docs/checklist.md CLAUDE.md src/schemas.py docs/plan-rohan.md
```

**Reine** (plan streams to the terminal and is saved to `docs/plan-reine.md`):

```
python scripts/make_timeline.py --request scripts/requests/reine.md --out docs/plan-reine.md --context docs/briefing.md docs/timeline.md docs/checklist.md CLAUDE.md src/schemas.py docs/plan-rohan.md src/agents/base.py src/agents/prompts/README.md app/streamlit_app.py
```

When a run finishes, commit the output file on your branch.

## Making a new plan

1. Copy a file in `scripts/requests/` and edit its scope (owner, files, what to include).
2. Pick `--context`: the team docs (`docs/briefing.md`, `docs/timeline.md`, `docs/checklist.md`,
   `CLAUDE.md`, `src/schemas.py`), any plan your work depends on, and the stubs you own.
3. Run the command with your `--request`, `--out` and `--context`.

## Cost and time

- Prices in the script: **$10 / M input tokens, $50 / M output tokens** (Fable 5.1 list price).
- A plan run costs a few dollars (Reine's is about $2–4) and takes a few minutes.
- Output is capped at 32,000 tokens.
- When done, the script prints to stderr: `Saved <out> | model <model> | <in> in / <out> out | ~$<cost>`.
  Check `model`: the run uses a server-side fallback, so if Fable's safety classifiers decline,
  another model may have answered.
- **Refusal:** the script exits with `Request declined: ...` and writes nothing.
- **max_tokens:** the file is still saved, with a `Warning: output hit max_tokens and is truncated.`
  message on stderr. Re-run with a narrower request (see `rohan-part2.md` for the pattern).

## Troubleshooting

- `ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.` – your `.env` is
  missing or has no `ANTHROPIC_API_KEY=` line. The script looks for `.env` in the repo root, wherever
  you run it from.
- Windows terminal shows garbled characters: run `$env:PYTHONIOENCODING = "utf-8"` first.
- File-not-found on the PDF: the script expects
  `problem statement/Autonomous SG 2026_Airbus Track.pdf` at the repo root; `git pull` to get it.
