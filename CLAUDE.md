# CLAUDE.md — PitWall

## What This Is
AI race engineer for Assetto Corsa sim racing. Reads MoTeC .ld telemetry, runs 6 AI agents, produces corner-by-corner coaching reports with a React dashboard.

## Architecture
- **pitwall/server.py** — 6 data functions (FastMCP decorated) + REST `/api/*` endpoints. Zero analysis logic.
- **pitwall/agents/data_gatherer.py** — Imports server functions directly as Python (NOT via MCP protocol). Only file that touches server.py.
- **pitwall/agents/_base.py** — Shared `call_claude_json()` helper. All agents are single-turn: JSON in, JSON out via `anthropic.Anthropic().messages.create()`.
- **pitwall/orchestrator.py** — Plain Python function coordinating agents sequentially. No framework.
- **pitwall/export.py** — Builds dashboard.json from SQLite. Corner metrics computed here (no AI).
- **pitwall/ingest.py** — Parses .ld files via ldparser, writes to SQLite at 30Hz.
- **pitwall/track.py** — Corner detection from lateral-G + AC track data parsing.
- **prompts/*.txt** — Agent system prompts. Edit these to change coaching behaviour.
- **dashboard/** — React + Vite + Recharts. Reads dashboard.json or hits REST API.

## Key Design Rules
- Server functions do zero analysis — pure SQL + file reads
- One agent, one lens — agents never see data outside their scope
- JSON contracts between all agents — no prose
- Orchestrator coordinates, never analyses
- `from __future__ import annotations` required in files using `Path | None` (Python 3.10 compat)

## Running
```bash
python scripts/run_session.py path/to/session.ld   # ingest + analyse + export
python scripts/run_session.py --no-agents path.ld  # data-only, skip AI
cd dashboard && npm run dev                         # localhost:5173
```

## Testing
```bash
python3 -m pytest tests/ -v
```
- test_ingest.py requires ldparser (skips if not installed)
- test_export.py and test_track.py run standalone

## Code Style
- Tabs for indentation, not spaces
- Type hints on function signatures
- f-strings over .format()
- pathlib.Path over os.path
- Comments explain WHY, not WHAT

## Common Pitfalls
- Adding `from __future__ import annotations` is required if using `X | None` union syntax — Python 3.10 needs it
- Never import from pitwall.server outside of data_gatherer.py — that's the architectural boundary
- Agent prompt files in prompts/*.txt are the knowledge layer — change coaching behaviour there, not in Python
- SQLite column names in get_lap_trace are allowlisted — adding a new channel requires updating the ALLOWED set in server.py
- Corner detection thresholds (lat_g 0.5g, min 30m, 50m gap merge) are tuned for typical circuits — Nordschleife may need different values

## Git Conventions
- Commit messages: imperative mood, concise ("Add braking agent", not "Added braking agent")
- Branch naming: feature/, fix/, chore/
- Never commit .env, db/*.db, or dashboard/public/dashboard.json

## Current State
- MCP stdio transport is available but nothing consumes it — agents use direct imports
- `feature/agent-sdk` branch exists for future Claude Agent SDK migration
- See docs/roadmap.md for planned features and docs/eval-plan.md for eval strategy
