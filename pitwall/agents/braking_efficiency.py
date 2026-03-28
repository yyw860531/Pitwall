"""
braking_efficiency.py -- braking zone analysis for one corner.
"""

import json
import logging

from pitwall.agents._base import call_claude_json, load_prompt

log = logging.getLogger(__name__)
_SYSTEM = load_prompt("braking_efficiency.txt")


def analyze(corner_payload: dict) -> dict | None:
    """
    Analyse braking efficiency. Returns None if no braking trace available.
    """
    name  = corner_payload["corner_name"]
    trace = corner_payload.get("best_braking_trace")
    if not trace:
        return None

    log.info("Braking analysis: %s", name)
    user = json.dumps({
        "corner_name":        name,
        "distance_range_m":   [corner_payload["start_m"], corner_payload["end_m"]],
        "best_braking_trace": trace,
    }, separators=(",", ":"))

    try:
        result = call_claude_json(_SYSTEM, user, max_tokens=512)
        result.setdefault("corner_name", name)
        return result
    except Exception as e:
        log.error("Braking analysis failed for %s: %s", name, e)
        return {"corner_name": name, "error": str(e)}
