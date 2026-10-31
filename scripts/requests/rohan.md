Plan only the work owned by Rohan (role L in docs/timeline.md and docs/checklist.md). The team plan
and the other members' work are settled; don't re-plan them, only reference their interfaces where
Rohan's code depends on them.

Rohan's scope: src/log/consensus_log.py, src/fallback/solver.py, src/mediator/protocol.py,
src/cli.py, src/reviewer/safety.py, eval/run_eval.py, merging to main at each checkpoint, and
driving the live demo. src/schemas.py and CLAUDE.md are already written, frozen and pushed (shown
in the project files), along with stubs for every module.

Rohan builds with Claude Code. Give him:
1. A minute-by-minute schedule for his own work from now until the 15:45 freeze, aligned with the
   team checkpoints (13:00, 14:15–14:30, 15:15–15:45).
2. For each of his modules, in build order: the design decisions he must make (with your
   recommendation), the behaviour and edge cases to get right, the log events it must write, the
   tests that prove it works, and a ready-to-paste Claude Code prompt that builds it.
3. How he unblocks himself before Waseem's and Reine's modules exist (temporary fixtures or
   stubs), and exactly what to check when merging their branches at each checkpoint.
4. The evaluation harness design: how the three-way comparison is computed, how each metric is
   defined so it is honest, the cost guard, and the output files the UI and slides read.
5. The reviewer design: what "independent" means concretely, which numbers it re-derives, the
   tolerances, and how APPROVE / REJECT / MODIFY are decided.
6. His own cut list if he falls behind, and the risks specific to his modules.
