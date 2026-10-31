"""Ask Claude Fable 5.1 for a plan, in planning mode (no code).

Sends a request plus context files and the Airbus track PDF to the model and writes the plan to
a Markdown file. Billed to ANTHROPIC_API_KEY (or .env).

    python scripts/make_timeline.py                          # the team timeline
    python scripts/make_timeline.py --request scripts/requests/rohan.md --out docs/plan-rohan.md \
        --context docs/briefing.md docs/timeline.md CLAUDE.md src/schemas.py
"""

import argparse
import base64
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent.parent
TRACK_PDF = ROOT / "problem statement" / "Autonomous SG 2026_Airbus Track.pdf"

MODEL = "claude-fable-5-1"
PRICE_IN, PRICE_OUT = 10.00, 50.00  # USD per million tokens, Fable 5.1 list price

SYSTEM = """You are the technical lead of a 4-person hackathon team, working in planning mode:
you produce a plan, not code. The team builds with parallel Claude Code sessions, so plan
around directing, reviewing and integrating AI-written code, not typing it by hand.

Your plan is the team's single source of truth for the rest of the day. Ground every
decision in the attached track brief and judging rubric and in the project files provided, and
spend effort where the rubric awards points. Be concrete: real clock times, named owners,
the files or modules each person's Claude Code session works on, the interfaces between
them, and integration checkpoints. Say explicitly what gets cut, and in what order, if the
team falls behind, and make sure a valid submission exists well before the deadline.

Write it in Markdown. No preamble."""


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--request", default="docs/timeline-request.md")
    parser.add_argument("--context", nargs="+", default=["docs/briefing.md"])
    parser.add_argument("--out", default="docs/timeline.md")
    parser.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")

    pdf_b64 = base64.standard_b64encode(TRACK_PDF.read_bytes()).decode()
    context = "\n\n".join(
        f'<file path="{p}">\n{(ROOT / p).read_text(encoding="utf-8")}\n</file>' for p in args.context
    )
    now = datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M (UTC%z)")
    request = (
        f"<project_files>\n{context}\n</project_files>\n\n"
        "The attached PDF is the official track brief and judging rubric; it wins if it "
        "conflicts with the project files.\n\n"
        f"Current time: {now}. Plan from now.\n\n"
        f"<request>\n{(ROOT / args.request).read_text(encoding='utf-8')}\n</request>"
    )

    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        # Re-run on another model if Fable's safety classifiers decline the request.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": args.effort},
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64},
                    },
                    {"type": "text", "text": request},
                ],
            }
        ],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
        message = stream.get_final_message()

    print()
    if message.stop_reason == "refusal":
        sys.exit(f"Request declined: {message.stop_details}")
    if message.stop_reason == "max_tokens":
        print("Warning: output hit max_tokens and is truncated.", file=sys.stderr)

    out = ROOT / args.out
    out.write_text("".join(b.text for b in message.content if b.type == "text"), encoding="utf-8")

    usage = message.usage
    cost = usage.input_tokens / 1e6 * PRICE_IN + usage.output_tokens / 1e6 * PRICE_OUT
    print(
        f"\nSaved {args.out} | model {message.model} | "
        f"{usage.input_tokens:,} in / {usage.output_tokens:,} out | ~${cost:.2f}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
