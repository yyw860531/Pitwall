# Agent Eval Plan

The agent pipeline currently has no automated way to measure coaching quality. This doc outlines a three-layer eval framework to build once the core pipeline is stable.

---

## Layer 1: Data accuracy (deterministic)

Unit tests against known telemetry files. No LLM needed — this is the foundation.

- Corner detection finds the correct number of corners for known tracks
- Sector times match MoTeC's own sector splits
- Theoretical best equals sum of individual sector bests
- Brake point distance is consistent between identical runs
- Lap validity correctly accepts/rejects edge cases (slow laps, cut laps)

**Implementation:** `pytest` fixtures with 2-3 real `.ld` files and expected outputs.

---

## Layer 2: Agent output quality (LLM-as-judge)

Structured evaluation of each specialist agent's output against manually annotated ground truth.

### Golden sessions fixture

Build `golden_sessions/` with 2-3 sessions where the driver manually annotates:

- Which corners they were slow at (ground truth priority ranking)
- Whether they were braking too early, too late, or about right at each corner
- Whether they had understeer or oversteer at each corner
- What the coaching report *should* say (key points, not exact wording)

### Eval runner

Replay golden sessions through the agent pipeline and score:

| Agent | What to score | How |
|-------|---------------|-----|
| **corner_analysis** | Does it identify the right corners as biggest time loss? | Compare priority ranking vs ground truth |
| **braking_efficiency** | Does it flag the right corners as "braking too early"? | Binary match per corner |
| **balance_diagnosis** | Does it distinguish understeer vs oversteer correctly? | Binary match per corner |
| **coaching_writer** | Is the advice actionable and consistent with data? | LLM-as-judge with rubric |

### What this enables

- **Prompt iteration:** Change a prompt, re-run eval, see if scores improve
- **Model comparison:** Haiku vs Sonnet for each agent — does the cheaper model hold up?
- **Temperature sweeps:** Find the sweet spot between consistency and creativity
- **Regression detection:** Catch when a code change breaks agent quality

---

## Layer 3: Coaching usefulness (multi-session)

The real eval: did the advice actually make the driver faster?

- Session N coaching says "brake later at T4"
- Session N+1: did T4 brake point move later? Did time improve?
- Track coaching accuracy over time: what % of recommendations led to measurable improvement?

**Depends on:** Multi-session progress tracking feature (roadmap item).

This closes the loop between coaching output and on-track outcome — the ultimate measure of whether the system works.

---

## Open questions

- How many golden sessions are enough? 2-3 covers basic cases, but different tracks/cars may expose different failure modes.
- Should eval run in CI? Expensive (API calls per run), but prevents regression.
- LLM-as-judge calibration: how do you validate the judge itself?
