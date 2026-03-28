# PitWall

> **Want your own Peter Bonnington? Your own GP Lambiase? Here's one — and it never sleeps.**

In F1, the voice in your ear makes the difference. Bono tells Lewis exactly where he's losing time. GP tells Max precisely where to push harder. That relationship — driver and race engineer, data and instinct — is what separates a good lap from a great one.

PitWall brings that to sim racing.

After every Assetto Corsa session, PitWall reads your telemetry, runs it through a pipeline of specialised AI agents, and delivers the kind of corner-by-corner coaching that usually only exists in a professional motorsport garage. Not generic advice — specific data. *"You're braking 12 metres earlier than your reference at T4. That's 263ms. Here's what to do about it."*

![Dashboard preview](docs/dashboard_preview.png)

### How the telemetry gets captured

On track, [Telemetrick](https://www.telemetrick.com/) runs inside Assetto Corsa and logs everything — speed, throttle, brake, steering, G-forces — at 30Hz into a MoTeC `.ld` file. The moment you finish a session, PitWall picks it up automatically (via file watcher), ingests it into SQLite, and has your coaching report ready before you've taken your helmet off.

No manual export steps. No copying files. Just drive, then read.

---

## What it does

After each session, PitWall:

1. **Captures** your `.ld` telemetry automatically via [Telemetrick](https://www.telemetrick.com/) — file watcher ingests it the moment AC writes it
2. **Compares** your laps corner-by-corner — brake points, minimum speed, throttle pickup
3. **Runs** specialist AI agents (braking efficiency, balance diagnosis, corner analysis) to identify exactly where time is lost
4. **Delivers** a prioritised coaching report: the biggest problem first, specific numbers, actionable fixes
5. **Renders** everything in a visual dashboard — speed traces, input overlays, corner delta tables

**Current setup:** Abarth 500 SS · Vallelunga Club · chasing 2 seconds

---

## Architecture

```
[Assetto Corsa + Telemetrick]
      ↓  exports .ld + .ldx after session
[ingest.py]  →  [SQLite]
                    ↓
              [MCP Server]        ←  6 tools, pure data retrieval, zero analysis
                    ↓
       [Data Gatherer Agent]      ←  only agent with MCP access
                    ↓ SessionPayload
         [Orchestrator Claude]    ←  coordinates, never analyses
          ├── Corner Analysis Agent
          ├── Braking Efficiency Agent
          ├── Balance Diagnosis Agent
          ├── Synthetic Lap Agent
          └── Coaching Writer Agent
                    ↓
         [dashboard.json]  →  [React Dashboard]
```

### Design principles

- **MCP is a data boundary.** MCP tools do zero calculation — pure SQL queries and file reads. All racing knowledge lives in agents.
- **One agent, one lens.** The Corner Analysis Agent doesn't know about braking physics. The Coaching Writer doesn't know about raw data. Responsibilities never bleed.
- **Context minimisation.** Each agent receives only the channels and distance range it needs. Small context = faster, cheaper, more accurate.
- **JSON contracts.** All inter-agent communication is typed JSON. No prose passes between agents.
- **Orchestrator coordinates, never analyses.** It decides which corners to focus on, which agents to spawn, and in what order. That's it.
- **Prompt files are the knowledge layer.** Swap coaching philosophy by editing a `.txt` file — no Python touched.
- **Graceful degradation.** Missing `AC_ROOT`? Skip synthetic laps. Missing channel? Store NULL and continue. The report is always produced.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- [Anthropic API key](https://console.anthropic.com)
- Assetto Corsa + [Telemetrick](https://www.telemetrick.com/) (to export `.ld` files)

### Install

```bash
git clone https://github.com/yuyangwu0325/Pitwall.git
cd Pitwall

# Python dependencies
pip install -r requirements.txt

# ldparser (MoTeC .ld file parser)
git clone https://github.com/gotzl/ldparser.git

# Dashboard dependencies
cd dashboard && npm install && cd ..
```

### Configure

```bash
cp .env.example .env
# Edit .env and set:
#   ANTHROPIC_API_KEY=your_key_here
#   AC_ROOT=C:\...\steamapps\common\assettocorsa   # optional, for synthetic laps
```

### Run

```bash
# Ingest a session and generate coaching report
python scripts/run_session.py data/sessions/your_session.ld

# Start the dashboard
cd dashboard && npm run dev
# Open http://localhost:5173
```

---

## Data Flow in Detail

### 1. Ingest (`.ld` → SQLite)

`ingest.py` uses [ldparser](https://github.com/gotzl/ldparser) to parse MoTeC binary files exported by Telemetrick. It extracts all laps, stores sample-by-sample telemetry at 30Hz, and computes sector times at the 580m mark.

Channels stored: `Ground Speed`, `Throttle Pos`, `Brake Pos`, `Steering Angle`, `Gear`, `Engine RPM`, `Lap Distance`, `CG Accel Lateral`, `CG Accel Longitudinal`.

Lap validity is determined by the `Lap Invalidated` channel if present, otherwise by a configurable time-range heuristic (30s–120s).

### 2. MCP Server (data layer)

`server.py` exposes 6 tools over the MCP protocol (stdio transport). None of these tools do analysis:

| Tool | Returns |
|------|---------|
| `list_sessions()` | All ingested sessions |
| `list_laps(session_id)` | Laps with metadata for a session |
| `get_lap_trace(lap_id, channels, start_m, end_m)` | Raw samples for a distance range |
| `get_session_metadata(session_id)` | Car specs, gear ratios, fastest lap |
| `get_ac_car_data(car_id)` | Physics parameters from AC installation |
| `get_ac_track_line(track_id)` | Track geometry + auto-detected corner map |

### 3. Agent pipeline

| Agent | Input | Output |
|-------|-------|--------|
| **Data Gatherer** | Session ID | SessionPayload — all traces needed for analysis |
| **Corner Analysis** | Target + reference trace for one corner | Brake point, min speed, throttle pickup, delta |
| **Braking Efficiency** | Brake zone trace | Deceleration rate, trail brake detection |
| **Balance Diagnosis** | Steering + lat G trace | Understeer/oversteer diagnosis, onset distance |
| **Synthetic Lap** | Car physics + track geometry | Theoretical fastest lap (point-mass model) |
| **Coaching Writer** | All agent outputs | Human coaching report (markdown + JSON) |

### 4. Dashboard

React + Vite + Recharts. Reads `dashboard.json` produced by `export.py`.

Five views:
- **Session overview** — lap time bar chart, best vs. target vs. reference
- **Speed trace overlay** — best lap vs. reference, corner zones shaded
- **Throttle / brake trace** — input overlay, shows early braking and late throttle
- **Corner summary table** — delta per corner, colour-coded, sorted by time loss
- **Coaching panel** — full report from Claude, priority corners highlighted

---

## Project Structure

```
PitWall/
├── config.py                    # Typed config loader (reads .env)
├── requirements.txt
├── .env.example
├── ldparser/                    # Cloned from github.com/gotzl/ldparser
├── data/
│   └── sessions/                # Drop .ld + .ldx files here
├── db/
│   └── pitwall.db               # SQLite (gitignored)
├── pitwall/
│   ├── ingest.py                # .ld → SQLite
│   ├── server.py                # FastMCP server — 6 data tools
│   ├── orchestrator.py          # Coordinates all agents via Claude Agent SDK
│   ├── export.py                # DB → dashboard.json
│   └── agents/
│       ├── data_gatherer.py     # MCP-connected data fetch agent
│       ├── corner_analysis.py
│       ├── braking_efficiency.py
│       ├── balance_diagnosis.py
│       ├── synthetic_lap.py
│       └── coaching_writer.py
├── prompts/                     # Agent system prompts — edit to tune coaching
│   ├── orchestrator.txt
│   ├── data_gatherer.txt
│   ├── corner_analysis.txt
│   ├── braking_efficiency.txt
│   ├── balance_diagnosis.txt
│   ├── synthetic_lap.txt
│   └── coaching_writer.txt
├── scripts/
│   ├── run_session.py           # CLI: ingest + analyse + export
│   └── set_reference_lap.py    # CLI: mark a lap as the reference
├── dashboard/
│   ├── public/
│   │   └── mock_session.json    # Static demo data
│   └── src/
│       ├── App.jsx
│       └── components/
│           ├── SessionHeader.jsx
│           ├── LapTimeBarChart.jsx
│           ├── SpeedTraceChart.jsx
│           ├── InputTraceChart.jsx
│           ├── CornerSummaryTable.jsx
│           └── CoachingPanel.jsx
└── tests/
    ├── test_ingest.py
    └── test_export.py
```

---

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Your Anthropic API key |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-6` | Model used for all agents |
| `AC_ROOT` | No | — | Path to AC installation. Required for synthetic reference laps |
| `PITWALL_DB_PATH` | No | `db/pitwall.db` | SQLite database path |
| `PITWALL_DATA_DIR` | No | `data/sessions` | Session files directory |
| `PITWALL_VALID_LAP_MIN_MS` | No | `30000` | Minimum valid lap time (ms) |
| `PITWALL_VALID_LAP_MAX_MS` | No | `120000` | Maximum valid lap time (ms) |

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Telemetry parsing | [ldparser](https://github.com/gotzl/ldparser) |
| Storage | SQLite |
| AI orchestration | [Claude Agent SDK](https://anthropic.com) |
| Agent interface | [FastMCP](https://github.com/jlowin/fastmcp) |
| Dashboard | React + Vite + Recharts |

---

## Security

- API keys are loaded from `.env` — never logged, never committed
- All SQL queries use parameterised statements (`?` placeholders)
- File paths from user-supplied IDs are validated against a safe base directory (path traversal blocked)
- Agent responses are parsed as JSON — never `eval()`'d
- `.ld` files are validated (exists, regular file, `.ld` extension, within `data_dir`, <500MB)

---

## Roadmap

- [ ] External reference lap (AC AI ghost → `.ld`)
- [ ] Multi-session progress tracking ("T4 improved 0.3s over 3 sessions")
- [ ] Voice coaching between laps (text-to-speech via Coaching Writer)
- [ ] Additional tracks and cars (corner map auto-generates from `fast_lane.ai`)
- [ ] Web UI with live MCP connection

---

## Contributing

Contributions welcome. Please open an issue before submitting a PR for new features.

If you're a sim racer who wants to add support for a different track or car — that's the best kind of issue to open.

---

## License

MIT

---

*Built with Claude, FastMCP, and the belief that every driver deserves a GP Lambiase in their corner.*
