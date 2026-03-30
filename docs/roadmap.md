# PitWall Roadmap

Living document for planned features, agent additions, and optimisation ideas.

---

## Agent Pipeline

### New Agents

**Track Strategy Agent** — Priority: HIGH
- Knows corner sequences, straight lengths, elevation changes
- Answers: "which corners matter most for lap time on this specific track?"
- Exit-speed weighting: a corner before a 1km straight matters more than one before a 100m link
- Corner-pair dependencies: "sacrifice T5 entry for T6 exit"
- Input: track geometry, all corner results, straight lengths
- Output: priority weighting per corner, corner-pair recommendations

**Consistency Agent** — Priority: HIGH
- Looks across all laps, not just best vs reference
- Answers: "where are you inconsistent?" and "which corners do you sometimes nail and sometimes blow?"
- Inconsistency (high variance) = confidence issue. Consistent but slow = technique issue. Different coaching for each.
- Input: all valid lap traces for each corner
- Output: variance per corner, consistency score, outlier lap identification

**Corner Flow Agent** — Priority: HIGH

The most common mistake fast-ish drivers make: entry speed feels fast, but it compromises the entire exit phase. No sim tool currently detects this tradeoff or explains why it happens.

*What it analyses:*

1. **Coasting detection** — distance where both brake_pct < 5% AND throttle_pct < 10%. Dead time. Every metre of coasting is ~20-30ms lost. Root causes: over-entry, early brake release without trail braking, car not rotated enough to get on throttle.
2. **Entry/exit tradeoff** — compare entry speed vs exit speed vs reference. Detect "net negative" corners: "You carry 5 kph more at entry but lose 8 kph at exit. Brake 10m earlier, roll more speed through the apex, get on throttle 15m sooner."
3. **Under-rotation detection** — high steering angle at apex relative to car baseline. Trail braking deeper would rotate the car before apex.
4. **Exit speed weighting** — weight each corner by the following straight length. 5 kph exit loss before a 1km straight = 300ms+. Before a 50m link = almost nothing. This changes which corners actually matter.
5. **Corner sequence analysis** — detect pairs where sacrificing one corner's entry benefits the next corner's exit. "Sacrifice T5 entry for T6 exit — T6 leads onto the main straight."
6. **Line analysis** (later) — use `car_pos_norm` channel to detect track width usage.

*Design principles:*

- **Deterministic first, AI second** — coasting distance, exit speed delta, straight length are pure calculations in export.py. The agent explains WHY and recommends WHAT TO CHANGE, not calculates.
- **One agent, one lens** — focuses on corner flow (entry → apex → exit → straight). Doesn't duplicate braking or balance analysis.
- **Car-aware** — uses car_context. AWD can get on throttle earlier. Heavy cars coast more on entry. Aero cars can carry more mid-corner.
- **Straight-length weighted** — always answer "how much does this cost on the following straight?" not just "how much time in this corner?"
- **Corner pairs, not just individual corners** — understand sequential dependencies. This is the differentiator vs every other sim tool.

*Input:* full corner traces + car_context + following straight length + corner sequence adjacency

*Output:*
```json
{
  "corner_name": "T4",
  "coasting_distance_m": 12.5,
  "coasting_pct": 8.2,
  "entry_exit_balance": "over_entry",
  "exit_speed_delta_kph": -8.3,
  "following_straight_m": 890,
  "estimated_straight_time_loss_ms": 340,
  "corner_pair": { "linked_to": "T5", "recommendation": "..." },
  "coaching_cues": ["..."]
}
```

*Implementation phases:*
1. Add deterministic metrics to export.py: coasting distance, exit speed, straight length per corner
2. Build Corner Flow Agent as new agent in pitwall/agents/
3. Add to orchestrator pipeline after corner_analysis
4. Dashboard: coasting column in corner summary, exit speed overlay

**Gear Selection Agent** — Priority: HIGH

Wrong gear = wrong part of the power band = slow exit. Detectable from gear + RPM + speed data, and AC car physics provide the power/torque curves to know what's optimal.

*What it analyses:*

1. **Upshift timing** — did the driver shift too early (below peak power RPM) or hold the gear too long (hitting the limiter)? With car_data power curve from AC, compute the optimal shift RPM and compare.
2. **Downshift pacing** — how quickly the driver drops through gears on entry. This is car-class dependent:
   - Formula / sequential with seamless shift: bang through gears as fast as you want
   - GT cars / paddle shift with rev match: fast but need to respect rev-match timing
   - Road cars / H-pattern or synchromesh: must pace downshifts — too fast causes rear lock-up or over-rev. Each downshift needs time for revs to settle.
   - Detect: rapid gear changes (< N samples between shifts) on a car class that can't handle it
3. **Gear choice at apex** — is the driver in the right gear for the corner's minimum speed? Too high a gear bogs the exit. Too low wastes time over-revving.
4. **Exit gear vs power band** — at throttle pickup, is RPM in the power band or below it? "You're at 4200 RPM in 4th but peak torque is at 6500 — stay in 3rd until the straight."

*Design principles:*
- **Car-aware is mandatory** — this agent is useless without car_context. Downshift pacing advice for a Miata vs an F1 car is completely different.
- **Deterministic first** — compute shift points, time between downshifts, RPM at apex/exit in export.py. Agent explains the impact and coaching.
- **Channels needed:** gear, rpm, speed_kph (all already captured at 30Hz)
- **AC data needed:** power curve from car physics files (extend `get_ac_car_data` to read `power.lut`)

*Input:* corner traces with gear + RPM + speed, car_context with power curve, car class indicator

*Output:*
```json
{
  "corner_name": "T4",
  "apex_gear": 3,
  "optimal_apex_gear": 2,
  "exit_rpm": 4200,
  "power_band_rpm": [6000, 7500],
  "downshift_pace": "too_fast",
  "downshift_interval_ms": [80, 95],
  "recommended_interval_ms": 200,
  "coaching_cues": ["Drop to 2nd for T4 apex — you're bogging at 4200 RPM in 3rd",
                     "Pace your downshifts — 80ms between shifts is too fast for this gearbox"]
}
```

**Progression Agent** — Priority: MEDIUM (needs multi-session comparison)
- Cross-session tracking: "T4 improved 0.3s over 3 sessions, T7 regressed by 0.1s"
- Answers: "am I actually getting better, and where?"
- Needs DB queries across sessions for the same car/track combo
- Motivation layer — quantifies improvement over time

**Tyre/Grip Agent** — Priority: MEDIUM
- Friction circle analysis (lat_g vs long_g)
- Answers: "are you using the available grip?" and "where are you coasting?"
- Grip utilisation %, transition quality (brake-to-turn, turn-to-throttle)
- Needs calibration per car class — more complex to get right
- Input: lat_g, long_g traces per corner
- Output: grip utilisation %, transition scores, coast-zone identification

### Agent Improvements

**Corner Analysis** — add awareness of corner type (hairpin, fast sweeper, chicane) to tailor advice

**Braking Efficiency** — compute theoretical latest braking point from decel profile + entry/apex speed, not just "later than reference"

**Coaching Writer** — incorporate track strategy weighting so priority ranking reflects lap time impact, not just raw delta

**Orchestrator** — make Claude orchestrator opt-in. Default to deterministic `_fallback_plan()` (faster, zero API cost). Add `--smart-plan` flag to enable Claude-driven dispatch for complex sessions where heuristic selection isn't enough.

---

## Lap Optimisation Logic

**Optimal braking point calculation**
- Use deceleration profile (long_g) and entry speed to compute theoretical latest braking point for a target apex speed
- Gap between theoretical and actual = true braking inefficiency

**Improved per-corner time loss estimate**
- Current `estimated_time_loss_ms` in `export.py` only uses apex min speed difference
- Incorporate brake point delta (metres early/late) and throttle pickup delay (metres late to throttle)
- More accurate priority ranking = better orchestrator decisions and more useful corner summary table

**Exit speed → straight length weighting**
- Weight each corner's priority by the length of the following straight
- Simple to implement, immediately makes priority ranking more accurate

**Fine-grained theoretical best**
- Stitch best speed at each 10m segment across all laps (not just per-sector)
- Shows exactly where best lap deviates from driver's own optimal

**Momentum / corner-pair analysis**
- Detect sequences where sacrificing entry speed yields better exit speed
- Coaching should understand corner pairs, not just individual corners

**Friction circle visualisation**
- Plot lat_g vs long_g per corner on the dashboard
- Visual indicator of grip utilisation and transition quality

---

## Agent SDK Migration — Priority: HIGH

The current agent pipeline is single-turn: each agent receives pre-packaged data, makes one `messages.create()` call, and returns JSON. The orchestrator is a plain Python function with no framework. This works but limits what agents can do.

**Why migrate to Claude Agent SDK:**

The complexity of race performance analysis demands more than single-turn Q&A. Real engineering insight requires agents that can reason iteratively — request more data when something looks anomalous, cross-reference findings from other agents, and adjust analysis depth based on what they discover. A braking agent that spots a weird decel profile should be able to pull the throttle trace for that corner without the orchestrator anticipating that need upfront.

**What the Agent SDK enables:**

- **Tool use in agent loops** — agents call MCP tools on demand, fetching exactly the data they need instead of receiving a pre-packaged payload. A corner analysis agent could start with speed/brake, notice a gear-related issue, and autonomously request the RPM trace.
- **Multi-turn reasoning** — agent asks for data, analyses, identifies an anomaly, requests additional context, then concludes. Current single-turn design forces the data gatherer to predict what every agent might need.
- **Agent handoffs** — orchestrator delegates to sub-agents with proper context. Coaching writer could query the corner analysis agent for clarification instead of working from static JSON.
- **Guardrails** — input/output schema validation built into the framework. Currently hand-rolled with JSON parse + retry.

**What happens to data_gatherer:**

data_gatherer is not really an agent today — it's a Python function that fetches and packages data with zero LLM involvement. In the Agent SDK world, it disappears entirely:

- The server functions it wraps (`get_lap_trace`, `get_session_metadata`, etc.) become MCP tools that any agent can call directly
- Each analysis agent requests what it needs on demand — "I see a weird braking profile at T4, let me also pull the throttle trace"
- The packaging logic (which corners need braking analysis, balance baseline) moves into the orchestrator agent's reasoning
- No more pre-built payloads. Agents pull data, reason, pull more data, conclude.

```
Current:  orchestrator → data_gatherer.gather() → pre-packages everything
              ↓
          agents get fixed payloads, can't ask for more

Future:   orchestrator agent → spawns corner_analysis agent with MCP tools
              ↓
          corner_analysis calls get_lap_trace(T4, [speed, brake])
          spots anomaly → calls get_lap_trace(T4, [throttle, steering])
          reasons over combined data → returns analysis
```

**Migration path:**

1. **Phase 1: Tool registry + agentic loop** ✅ DONE — `_base.py` now has `run_agent()` with an agentic loop (multi-turn tool-use). Tool registry maps MCP tool names to server functions. Per-agent tool allowlists (Option B: restricted visibility). Agents still receive pre-packaged data from orchestrator but can fetch additional data on demand.
2. **Phase 2: Analysis agents on agentic loop** ✅ DONE — corner_analysis, braking_efficiency, balance_diagnosis, synthetic_lap all use `run_agent()` with their allowed tools. Coaching writer uses `run_agent()` with no tools. data_gatherer unchanged (still pre-packages data for performance).
3. **Phase 3: Orchestrator as planner** ✅ DONE — orchestrator is a planner agent with zero tools. Data gathering runs first in Python (guaranteed). Claude receives a lightweight session summary and returns a structured dispatch plan (which corners, which analysis types). Python dispatcher reads the plan and runs sub-agents in parallel via ThreadPoolExecutor. Coaching writer always runs last (unconditional). Deterministic fallback plan if the agent fails. Future: dissolve data_gatherer, let agents fetch data via MCP tools directly.
4. **Phase 4: Coaching writer with agent queries** — coaching writer can query individual analysis agents for clarification or request re-analysis with different parameters, producing richer reports.

**Design decisions to make:**

- **Transport:** stdio — single-process, local only. Keeps things simple and avoids network overhead for a tool that runs on the driver's own machine.
- **Tool granularity:** Current 6 tools may be too coarse for agent-driven analysis. Consider splitting `get_lap_trace` into channel-specific tools, or adding a `compare_traces` tool that returns delta directly.
- **Cost control:** Multi-turn agents consume more tokens. Need per-agent token budgets and circuit breakers. Haiku for data-fetching turns, Sonnet/Opus for reasoning turns.
- **Eval impact:** Multi-turn agents are harder to eval than single-turn. Layer 2 eval (LLM-as-judge) needs to assess conversation quality, not just final output.

**What stays the same:**

- Server functions remain the single data boundary — no agent touches SQLite directly
- Prompt files remain the knowledge layer — agent system prompts still live in `prompts/*.txt`
- JSON contracts between agents — structured output, not prose
- Graceful degradation — agent failure produces partial report, never crashes

---

## MCP Architecture

**Resources** — expose current session as an MCP resource (subscription-based, no session_id on every call)

**Tool granularity** — evaluate whether current 6 tools are the right split, or if some should be broken up / merged

**Auth model** — OAuth 2.0 support for demo/multi-user scenarios

---

## Eval Framework

See [eval-plan.md](eval-plan.md) for the three-layer eval strategy.

- Layer 1: Deterministic data accuracy (pytest)
- Layer 2: Agent output quality (LLM-as-judge with golden sessions)
- Layer 3: Coaching usefulness (multi-session before/after tracking)

---

## Dashboard & UX

**Empty states** — show meaningful messages when no corners detected, no valid laps, no coaching report

**Responsive layout** — support viewports below 1200px (currently hard-coded 520px coaching panel)

**Friction circle chart** — new visualisation component for grip utilisation

**Consistency heatmap** — per-corner variance across laps, colour-coded

**Session comparison view** — overlay two sessions to show progress over time

---

## Data & Tracks

**External reference lap** — import a faster driver's .ld file as a cross-session benchmark

**Multi-session progress tracking** — "T4 improved 0.3s over 3 sessions"

**Long track support** — scale SPEED_TRACE_POINTS with track length for Nordschleife-class tracks (20km+)

**Start/finish corner handling** — detect and merge corners that wrap the lap boundary

---

## Infrastructure

**Voice coaching** — text-to-speech from coaching writer output, playable between sessions

**Web UI with live MCP connection** — real-time data streaming instead of static dashboard.json

**CI eval runner** — run agent eval on PR to catch quality regressions (expensive, consider cost)

---

## Not Planned (and why)

**Setup recommendation agent** — no before/after setup data available from Telemetrick. Without A/B comparison, outputs would be guesswork.

**Weather / tyre degradation agent** — Telemetrick doesn't export tyre temp/wear channels. No data, no agent.

**Racecraft agent** — needs multi-car position data. Single-player hotlapping doesn't have this. Revisit if multiplayer replay data becomes available.
