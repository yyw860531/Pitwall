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

**Works with any car and any track in Assetto Corsa** — no per-track configuration needed. Just drive, export, and analyse.

---

## Architecture

```
[Assetto Corsa + Telemetrick]
      ↓  exports .ld + .ldx after session
[ingest.py]  →  [SQLite]
                    ↓
              [server.py]              ←  6 data functions + HTTP API, zero analysis
            ↙       ↓              ↘
  [Data Gatherer] [Tool Registry]    [React Dashboard]
  (direct import) (_base.py)         (REST /api/*)
         ↓              ↓
  [Orchestrator Agent]  ←  planner: zero tools, returns dispatch plan
         ↓ dispatch plan (JSON)
  [Python Dispatcher]   ←  ThreadPoolExecutor, parallel execution
   ├── Corner Analysis Agent  ⚡ tools: get_lap_trace, get_session_metadata
   ├── Braking Efficiency Agent  ⚡ tools: get_lap_trace
   ├── Balance Diagnosis Agent  ⚡ tools: get_lap_trace
   ├── Synthetic Lap Agent  ⚡ tools: get_ac_car_data, get_ac_track_line
   └── Coaching Writer Agent  (no tools — always runs last)
         ↓
  [dashboard.json]  →  [React Dashboard]
```

> **Orchestrator is a planner.** Data gathering runs first (Python, guaranteed). The orchestrator agent receives a session summary with zero tools and returns a structured dispatch plan — which corners to analyse, which analysis types each needs. Python reads the plan and dispatches sub-agents in parallel via `ThreadPoolExecutor`. Each sub-agent runs in a multi-turn tool-use loop with restricted tool visibility (Option B). The coaching writer always runs last.

### Design principles

- **Server is a data boundary.** Server functions do zero calculation — pure SQL queries and file reads. All racing knowledge lives in agents. The data gatherer imports these directly; the dashboard uses REST endpoints on the same server.
- **One agent, one lens.** The Corner Analysis Agent doesn't know about braking physics. The Coaching Writer doesn't know about raw data. Responsibilities never bleed.
- **Context minimisation.** Each agent receives only the channels and distance range it needs. Small context = faster, cheaper, more accurate.
- **JSON contracts.** All inter-agent communication is typed JSON. No prose passes between agents.
- **Orchestrator plans, never executes.** It decides which corners to focus on and which agents to run. Python handles the actual dispatch and parallel execution.
- **Prompt files are the knowledge layer.** Swap coaching philosophy by editing a `.txt` file — no Python touched.
- **Graceful degradation.** Missing `AC_ROOT`? Skip synthetic laps. Missing channel? Store NULL and continue. The report is always produced.

---

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- [Anthropic API key](https://console.anthropic.com)
- Assetto Corsa + [Telemetrick](https://www.telemetrick.com/) (to export `.ld` files)

### Install

```bash
git clone https://github.com/yyw860531/Pitwall.git
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
```

Then edit `.env` — here's what each variable does:

```bash
# ── Required ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=your_key_here

# ── Model selection ───────────────────────────────────────────────────────────
# Sonnet for reasoning/language agents (coaching_writer, synthetic_lap)
CLAUDE_MODEL=claude-sonnet-4-6

# Haiku for structured JSON agents (corner_analysis, braking_efficiency, balance_diagnosis, orchestrator)
# Haiku is faster and ~20× cheaper for rule-based planning and calculation tasks.
CLAUDE_MODEL_FAST=claude-haiku-4-5

# ── Assetto Corsa installation ─────────────────────────────────────────────────
# Required for synthetic reference laps. Leave blank to skip that agent.
# Example (Windows): C:\Program Files (x86)\Steam\steamapps\common\assettocorsa
AC_ROOT=

# ── Storage paths (defaults shown — only change if you need to) ────────────────
PITWALL_DB_PATH=db/pitwall.db
PITWALL_DATA_DIR=data/sessions

# ── Telemetrick auto-discovery ─────────────────────────────────────────────────
# Root folder of your Telemetrick exports. If set, run_session.py can find
# sessions without you specifying the full file path.
# Example: C:\Users\YourName\Documents\Assetto Corsa\apps\telemetrick\exported\YourDriver
TELEMETRY_EXPORT_DIR=

# ── Lap validity filter ────────────────────────────────────────────────────────
# Laps outside this window are marked invalid when the 'Lap Invalidated'
# channel is absent from the .ld file.
PITWALL_VALID_LAP_MIN_MS=30000
PITWALL_VALID_LAP_MAX_MS=120000
```

### Run

```bash
python scripts/run_session.py path/to/your_session.ld
cd dashboard && npm run dev
# Open http://localhost:5173
```

This ingests the telemetry, runs the AI agent pipeline, and writes the dashboard. Add `--no-agents` to skip AI analysis and get a data-only dashboard instantly.

> **Tip:** Drive at least 3–4 clean laps per session. Corner detection and theoretical best need multiple laps to work.

---

## Data Flow in Detail

### 1. Ingest (`.ld` → SQLite)

`ingest.py` uses [ldparser](https://github.com/gotzl/ldparser) to parse MoTeC binary files exported by Telemetrick. It extracts all laps, stores sample-by-sample telemetry at 30Hz, and computes sector times using real sector boundaries from AC's `sections.ini` (supporting 2 or 3 sectors depending on the track).

Channels stored: `Ground Speed`, `Throttle Pos`, `Brake Pos`, `Steering Angle`, `Gear`, `Engine RPM`, `Lap Distance`, `CG Accel Lateral`, `CG Accel Longitudinal`, `Car Pos Norm`.

Track length is derived from telemetry data (maximum lap distance), so no per-track configuration is needed.

Lap validity is determined by the `Lap Invalidated` channel if present, otherwise by a dynamic heuristic based on venue length (minimum speed floor of 30 kph). Falls back to configurable time-range (30s–120s) if venue length is unknown.

### 2. Server (data layer)

`server.py` defines 6 data functions decorated with FastMCP, plus REST endpoints (`/api/*`) for the dashboard. The data gatherer imports the functions directly as Python; the dashboard hits the REST API. MCP stdio transport is available but not yet consumed. None of the data functions do analysis:

| Tool | Returns |
|------|---------|
| `list_sessions()` | All ingested sessions |
| `list_laps(session_id)` | Laps with metadata for a session |
| `get_lap_trace(lap_id, channels, start_m, end_m, stride)` | Raw samples for a distance range (stride for downsampling) |
| `get_session_metadata(session_id)` | Car specs, gear ratios, fastest lap |
| `get_ac_car_data(car_id)` | Physics parameters from AC installation (tyre grip, aero, drivetrain) |
| `get_ac_track_line(track_id)` | Track geometry + auto-detected corner map (handles multi-layout tracks) |

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

Features:
- **Session overview** — lap time bar chart with theoretical best reference line, sector splits (S1/S2/S3)
- **Lap comparison selector** — compare any two laps head-to-head, or compare against the theoretical best (stitched from best sector times)
- **Speed trace overlay** — best lap vs. reference with aligned X-axis
- **Throttle / brake trace** — input overlay, shows early braking and late throttle
- **Track map** — auto-detected from AC installation (supports multi-layout tracks like Red Bull Ring)
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
│   ├── ingest.py                # .ld → SQLite (N-sector support)
│   ├── server.py                # 6 data functions + REST API (FastMCP)
│   ├── orchestrator.py          # Planner agent + parallel dispatcher
│   ├── export.py                # DB → dashboard.json
│   ├── track.py                 # Corner detection + AC track/sector parsing
│   └── agents/
│       ├── _base.py             # Agentic loop, tool registry, per-agent allowlists
│       ├── data_gatherer.py     # Data fetch (direct server imports)
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
│   ├── watch_telemetry.py       # File watcher: auto-ingest on .ld drop
│   └── set_reference_lap.py    # CLI: mark a lap as the reference
└── dashboard/
    ├── public/                  # Created at runtime by export.py
    │   └── dashboard.json       # Generated session data
    └── src/
        ├── App.jsx
        └── components/
            ├── SessionHeader.jsx
            ├── SessionPicker.jsx
            ├── LapTimeBarChart.jsx
            ├── SpeedTraceChart.jsx
            ├── InputTraceChart.jsx
            ├── CornerSummaryTable.jsx
            ├── CoachingPanel.jsx
            ├── TrackMap.jsx
            └── LapCompareSelector.jsx
```

---

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | **Yes** | — | Your Anthropic API key |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-6` | Model for reasoning/language agents (coaching writer, synthetic lap) |
| `CLAUDE_MODEL_FAST` | No | `claude-haiku-4-5` | Model for structured JSON agents (corner analysis, braking, balance, orchestrator). Haiku is ~20× cheaper |
| `AC_ROOT` | No | — | Path to your AC installation. Enables track map, real sector boundaries, synthetic reference laps |
| `TELEMETRY_EXPORT_DIR` | No | — | Root of your Telemetrick export folder. Enables session auto-discovery |
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
| AI orchestration | [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python) |
| Data layer / API | [FastMCP](https://github.com/jlowin/fastmcp) |
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

Full roadmap with design notes: [docs/roadmap.md](docs/roadmap.md) · Eval plan: [docs/eval-plan.md](docs/eval-plan.md)

**Next up:**
- [ ] MCP client/server separation — agents consume data via MCP protocol, not direct imports
- [ ] Corner Flow Agent — coasting detection, entry/exit tradeoff, exit speed weighted by straight length
- [ ] Gear Selection Agent — shift timing, downshift pacing per car class, power band utilisation
- [ ] Track Strategy Agent — weight corner priority by straight length and corner sequences
- [ ] Consistency Agent — identify high-variance corners across laps
- [ ] Optimal braking point calculation from deceleration profiles
- [ ] Agent eval framework with golden session fixtures

**Done:**
- [x] Agentic loop with tool-use — multi-turn agents with restricted tool visibility per agent
- [x] Orchestrator as planner — zero tools, returns dispatch plan, Python dispatches in parallel
- [x] Prompt caching — 90% input token savings on repeated agent calls
- [x] Any car, any track support — no per-track hardcoding
- [x] Real sector boundaries from AC `sections.ini` (2 or 3 sectors)
- [x] Corner detection from lateral-G telemetry (no AI file needed)
- [x] Lap comparison selector with theoretical best trace
- [x] Track map auto-detection (multi-layout tracks supported)
- [x] Session management — re-import and delete from dashboard UI

---

## Contributing

Contributions welcome. Please open an issue before submitting a PR for new features.

If you're a sim racer who wants to add support for a different track or car — that's the best kind of issue to open.

---

## License

MIT

---

*Built with Claude, FastMCP, and the belief that every driver deserves a GP Lambiase in their corner.*
