# scripts

`make_timeline.py` sends a planning request to Claude Fable 5.1, with project files and the track
PDF as context, and saves the plan as Markdown. It runs on the API key in your own `.env`, so it
bills your own credits.

## Setup (once)

1. `git pull`
2. `pip install anthropic`
3. Copy `.env.example` to `.env` and paste your own API key from platform.claude.com.

## Reine's plan

Run from the repo root (about $2–4; the plan streams to the terminal and is saved to
`docs/plan-reine.md`):

```
python scripts/make_timeline.py --request scripts/requests/reine.md --out docs/plan-reine.md --context docs/briefing.md docs/timeline.md docs/checklist.md CLAUDE.md src/schemas.py docs/plan-rohan.md src/agents/base.py src/agents/prompts/README.md app/streamlit_app.py
```

On Windows, if the terminal shows garbled characters, run `$env:PYTHONIOENCODING = "utf-8"` first.
It takes a few minutes. When it finishes, commit `docs/plan-reine.md` on your branch.

## Other plans

`scripts/requests/` holds the request each plan was made from. To make a new one, copy a request
file, edit its scope, and run the same command with your own `--request`, `--out` and `--context`.
