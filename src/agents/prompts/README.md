# Agent system prompts (owner: Reine, T2)

One plain-text file per agent: `atc.txt`, `pilot.txt`, `ground.txt`.

Each prompt must:
- give the agent only its own domain's data and goals (see the agent table in `docs/briefing.md` §2)
- require strict JSON matching `AgentMessage` in `src/schemas.py`
- forbid legality claims and arithmetic; the rules engine owns those
- ask the agent to cite the scenario fields it relies on in `cited_fields`
