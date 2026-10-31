Plan only the work owned by Reine (role T2 in docs/timeline.md and docs/checklist.md). The team plan
is settled, and Rohan's plan (docs/plan-rohan.md) fixes the interfaces Reine's code must match; don't
re-plan either, only reference them where her code depends on them.

Reine's scope: src/agents/base.py (Agent, StubAgent, ClaudeAgent, InvalidMessage), the three system
prompts in src/agents/prompts/ (atc.txt, pilot.txt, ground.txt), tests/test_agents.py,
app/streamlit_app.py (including the evaluation panel and failure-case preset), the 60-second backup
screen recording, and answering the judges' agent questions. src/schemas.py and CLAUDE.md are
frozen and pushed, and her files exist as stubs (all shown in the project files).

Interfaces she must honour, from docs/plan-rohan.md §0 and §3: the optional `others=None` argument
to propose(), the "path=value" cited_fields format, the `calls` cost list and `MODEL_IDS` on
ClaudeAgent, round-2 `acceptable` ⊇ round-1 for StubAgent, the runs/<scenario_id>.json layout, the
consensus-log event names, and eval/results/summary.csv in long format. If anything there is
ambiguous for her, say what she should assume and that she should confirm it with Rohan.

Reine builds with Claude Code. Give her:
1. A minute-by-minute schedule for her own work from now until the 15:45 freeze, aligned with the
   team checkpoints (13:00, 14:15–14:30, 15:15–15:45).
2. For each of her deliverables, in build order: the design decisions she must make (with your
   recommendation), the behaviour and edge cases to get right, the tests that prove it works, and a
   ready-to-paste Claude Code prompt that builds it.
3. The three system prompts' design: what data each agent sees and must not see, how each agent's
   domain goals map to ranking and vetoes, how round 2 concession works, and how to keep the LLM
   from doing arithmetic or legality judgements. Include a full draft of each prompt.
4. The ClaudeAgent design: model IDs, prompt caching, structured output and validation, the single
   retry, InvalidMessage, cost and latency accounting, and how to test without spending credits.
5. The Streamlit UI design: each panel, what it reads, how source tags and failures are shown, how
   Approve / Reject writes to the log, and how it degrades if a file or field is missing.
6. What she hands to Rohan at each checkpoint and how she checks it before he merges.
7. Her own cut list if she falls behind, the risks specific to her modules, and her role in the
   demo and Q&A.

Keep sections other than 2 and 3 short.
