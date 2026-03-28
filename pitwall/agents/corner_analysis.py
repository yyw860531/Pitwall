"""
corner_analysis.py -- analyses best vs reference trace for one corner.
"""

import json
import logging

from pitwall.agents._base import call_claude_json, load_prompt

log = logging.getLogger(__name__)
_SYSTEM = load_prompt("corner_analysis.txt")


def analyze(corner_payload: dict) -> dict:
    """
    Analyse a single corner. Returns a CornerAnalysisResult dict.
    Returns an error dict on failure so the pipeline keeps running.
    """
    name = corner_payload["corner_name"]
    log.info("Corner analysis: %s", name)

    user = json.dumps({
        "corner_name":     name,
        "distance_range_m": [corner_payload["start_m"], corner_payload["end_m"]],
        "best_trace":      corner_payload["best_trace"],
        "ref_trace":       corner_payload["ref_trace"],
    }, separators=(",", ":"))

    try:
        result = call_claude_json(_SYSTEM, user, max_tokens=1024)
        result.setdefault("corner_name", name)
        return result
    except Exception as e:
        log.error("Corner analysis failed for %s: %s", name, e)
        return {"corner_name": name, "error": str(e), "estimated_time_gain_ms": 0}
