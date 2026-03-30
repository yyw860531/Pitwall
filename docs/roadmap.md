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

---

## Lap Optimisation Logic

**Optimal braking point calculation**
- Use deceleration profile (long_g) and entry speed to compute theoretical latest braking point for a target apex speed
- Gap between theoretical and actual = true braking inefficiency

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

**Migration path:**

1. **Phase 1: MCP client/server separation** — data_gatherer currently imports server functions directly as Python. Move to proper MCP client so tools are callable over transport (stdio or HTTP). This is a prerequisite — agents need tool definitions to use tool_use.
2. **Phase 2: Agent SDK for analysis agents** — convert corner_analysis, braking_efficiency, balance_diagnosis from single-turn `call_claude_json()` to Agent SDK agents with MCP tools available. Each agent gets a tool list and can request additional data mid-analysis.
3. **Phase 3: Orchestrator as agent** — replace the Python orchestrator with an Agent SDK orchestrator that uses handoffs. It decides which agents to run and in what order, but can also react to intermediate results (e.g., if corner analysis reveals a systemic braking issue across multiple corners, escalate to a dedicated braking deep-dive).
4. **Phase 4: Coaching writer with agent queries** — coaching writer can query individual analysis agents for clarification or request re-analysis with different parameters, producing richer reports.

**Design decisions to make:**

- **Transport:** stdio (simplest, single-process) vs HTTP (multi-process, enables remote agents). Stdio for Phase 1-2, HTTP if we need to scale.
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
