"""
coaching_writer.py -- assembles all analysis results into the final coaching report.
"""

import json
import logging

from pitwall.agents._base import call_claude_json, load_prompt

log = logging.getLogger(__name__)
_SYSTEM = load_prompt("coaching_writer.txt")


def write(
    session_meta: dict,
    corner_analyses: list[dict],
    braking_results: list[dict],
    balance_results: list[dict],
) -> dict:
    """Generate the coaching_report block for dashboard.json."""
    log.info("Generating coaching report...")

    meta_summary = {
        "session_id":          session_meta.get("session_id"),
        "car":                 session_meta.get("car_id") or session_meta.get("car"),
        "track":               session_meta.get("track_id") or session_meta.get("track"),
        "best_lap_time_ms":    session_meta.get("fastest_time_ms") or session_meta.get("best_lap_time_ms"),
        "theoretical_best_ms": session_meta.get("theoretical_best_ms"),
        "valid_lap_count":     session_meta.get("valid_lap_count"),
        "reference_type":      session_meta.get("reference_type", "driven"),
    }

    user = json.dumps({
        "session_meta":    meta_summary,
        "corner_analyses": corner_analyses,
        "braking_results": [r for r in braking_results if r],
        "balance_results": [r for r in balance_results if r],
    }, separators=(",", ":"))

    try:
        result = call_claude_json(_SYSTEM, user, max_tokens=4096)
        result.setdefault("reference_note", None)
        result.setdefault("priority_corners", [])
        result.setdefault("next_action", "Review the priority corners above.")
        result.setdefault("full_markdown", _fallback_markdown(corner_analyses))
        return result
    except Exception as e:
        log.error("Coaching writer failed: %s", e)
        return _fallback_report(corner_analyses, str(e))


def _fallback_markdown(corner_analyses: list[dict]) -> str:
    lines = ["## Session Analysis", ""]
    lines.append("_Full AI coaching report could not be generated. Raw corner data:_")
    lines.append("")
    for ca in corner_analyses:
        if "error" in ca:
            continue
        lines.append(f"### {ca.get('corner_name', 'Corner').replace('_', ' ')}")
        lines.append(ca.get("overall_assessment", ""))
        for cue in ca.get("key_coaching_cues", []):
            lines.append(f"- {cue}")
        lines.append("")
    return "\n".join(lines)


def _fallback_report(corner_analyses: list[dict], error: str) -> dict:
    priority = []
    for i, ca in enumerate(corner_analyses[:2], start=1):
        if "error" not in ca:
            priority.append({
                "rank": i,
                "corner_name": ca.get("corner_name", ""),
                "headline": (ca.get("overall_assessment") or "")[:100],
                "estimated_time_gain_ms": ca.get("estimated_time_gain_ms", 0),
            })
    return {
        "session_summary": "Session analysis completed with partial data.",
        "reference_note":  f"Coaching writer error: {error[:100]}",
        "priority_corners": priority,
        "full_markdown":   _fallback_markdown(corner_analyses),
        "next_action":     "Check logs and rerun the pipeline.",
    }
