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
