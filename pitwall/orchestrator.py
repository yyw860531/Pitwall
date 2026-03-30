"""
orchestrator.py -- coordinates all analysis agents for a session.

Design principles:
  - Never interprets telemetry directly
  - Decides which agents to run based on corner_summary data
  - Always produces a coaching_report (degrades gracefully on agent failure)
  - Patches the existing dashboard.json coaching_report in-place

Usage:
    from pitwall.orchestrator import orchestrate
    coaching_report = orchestrate(session_id, corner_summary)
"""

import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from pitwall.agents import (  # noqa: E402
    data_gatherer,
    corner_analysis,
    braking_efficiency,
    balance_diagnosis,
    synthetic_lap,
    coaching_writer,
)

log = logging.getLogger(__name__)

# Threshold-based corner selection:
#   Analyse every corner with estimated loss >= this value (ms).
#   Cap at _MAX_CORNERS for very long tracks (e.g. Nürburgring).
_MIN_TIME_LOSS_MS = 80
_MAX_CORNERS      = 12


def orchestrate(
    session_id: str,
    corner_summary: list[dict],
    corners: list[dict] | None = None,
) -> dict:
    """
    Run the full agent pipeline for a session.

    session_id:     e.g. '28032026-155415'
    corner_summary: from export.py _build_corner_summary(), already ranked by time loss
    corners:        pre-computed corner list (avoids re-running get_corners)

    Returns a coaching_report dict ready to be written into dashboard.json.
    """
    log.info("=== PitWall orchestrator: %s ===", session_id)

    # ------------------------------------------------------------------
    # Step 1: Gather all data (Data Gatherer -- direct server imports)
    # ------------------------------------------------------------------
    log.info("[1/5] Gathering session data...")
    try:
        payload = data_gatherer.gather(session_id, corner_summary, corners)
    except Exception as e:
        log.error("Data gathering failed: %s", e)
        return _error_report(f"Data gathering failed: {e}")

    session_meta = payload["session_meta"]
    corner_payloads = payload["corner_payloads"]
    session_meta["reference_type"] = payload["ref_type"]

    # ------------------------------------------------------------------
    # Step 2: Corner analysis — all corners above time-loss threshold
    # ------------------------------------------------------------------
    time_loss_map = {
        c["corner_name"]: c.get("delta", {}).get("estimated_time_loss_ms", 0)
        for c in corner_summary
    }
    sorted_corners = sorted(
        corner_payloads,
        key=lambda cp: time_loss_map.get(cp["corner_name"], 0),
        reverse=True,
    )
    # Include corners above threshold; always include at least top 2; cap at _MAX_CORNERS
    top_corners = [
        cp for cp in sorted_corners
        if time_loss_map.get(cp["corner_name"], 0) >= _MIN_TIME_LOSS_MS
    ][:_MAX_CORNERS]
    if not top_corners:
        top_corners = sorted_corners[:2]

    log.info("[2/5] Analysing %d corners (loss >= %dms, cap %d)...",
             len(top_corners), _MIN_TIME_LOSS_MS, _MAX_CORNERS)

    corner_analyses = []
    for cp in top_corners:
        result = corner_analysis.analyze(cp)
        corner_analyses.append(result)

    # ------------------------------------------------------------------
    # Step 3: Braking efficiency (corners flagged by data_gatherer)
    # ------------------------------------------------------------------
    log.info("[3/5] Running braking efficiency analysis...")
    braking_results = []
    for cp in top_corners:
        if cp.get("needs_braking"):
            result = braking_efficiency.analyze(cp)
            if result:
                braking_results.append(result)
    if not braking_results:
        log.info("  No braking analysis triggered (thresholds not met)")

    # ------------------------------------------------------------------
    # Step 4: Balance diagnosis (corners flagged by data_gatherer)
    # ------------------------------------------------------------------
    log.info("[4/5] Running balance diagnosis...")
    balance_results = []
    for cp in top_corners:
        if cp.get("needs_balance"):
            result = balance_diagnosis.analyze(cp)
            if result:
                balance_results.append(result)
    if not balance_results:
        log.info("  No balance anomaly detected")

    # ------------------------------------------------------------------
    # Step 4b: Synthetic lap (only if no real reference and AC_ROOT set)
    # ------------------------------------------------------------------
    synth_result = None
    if payload["ref_type"] == "self":
        log.info("[4b] Building synthetic reference lap...")
        synth_result = synthetic_lap.build(
            payload.get("car_data"),
            payload.get("track_data"),
        )
        if synth_result:
            session_meta["reference_type"] = "synthetic"
            session_meta["reference_note"] = (
                f"No reference lap available. Using synthetic baseline "
                f"({synth_result.get('lap_time_ms')} ms, "
                f"confidence: {synth_result.get('confidence', 'unknown')})."
            )

    # ------------------------------------------------------------------
    # Step 5: Coaching writer
    # ------------------------------------------------------------------
    log.info("[5/5] Generating coaching report...")
    report = coaching_writer.write(
        session_meta=session_meta,
        corner_analyses=corner_analyses,
        braking_results=braking_results,
        balance_results=balance_results,
    )

    log.info("=== Pipeline complete ===")
    return report


def _error_report(message: str) -> dict:
    return {
        "session_summary":  "Analysis pipeline failed.",
        "reference_note":   message,
        "priority_corners": [],
        "full_markdown":    f"## Analysis Failed\n\n{message}",
        "next_action":      "Check logs and rerun the pipeline.",
    }
