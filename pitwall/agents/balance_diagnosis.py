"""
balance_diagnosis.py -- understeer/oversteer diagnosis for one corner.
"""

import json
import logging

from pitwall.agents._base import call_claude_json, load_prompt
from config import config

log = logging.getLogger(__name__)
_SYSTEM = load_prompt("balance_diagnosis.txt")


def analyze(corner_payload: dict) -> dict | None:
    """
    Diagnose handling balance. Returns None if no balance trace available.
    """
    name  = corner_payload["corner_name"]
    trace = corner_payload.get("best_balance_trace")
    if not trace:
        return None

    log.info("Balance diagnosis: %s", name)
    user = json.dumps({
        "corner_name":         name,
        "distance_range_m":    [corner_payload["start_m"], corner_payload["end_m"]],
        "best_balance_trace":  trace,
    }, separators=(",", ":"))

    try:
        result = call_claude_json(_SYSTEM, user, max_tokens=512, model=config.claude_model_fast)
        result.setdefault("corner_name", name)
        return result
    except Exception as e:
        log.error("Balance diagnosis failed for %s: %s", name, e)
        return {"corner_name": name, "error": str(e)}
