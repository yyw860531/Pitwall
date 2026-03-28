"""
synthetic_lap.py -- builds a synthetic reference lap when no real reference exists.

Skips gracefully if AC_ROOT is not configured.
"""

import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))
from config import config  # noqa: E402
from pitwall.agents._base import call_claude_json, load_prompt  # noqa: E402

log = logging.getLogger(__name__)
_SYSTEM = load_prompt("synthetic_lap.txt")


def build(car_data: dict | None, track_data: dict | None) -> dict | None:
    """
    Build a synthetic reference lap using car physics and track geometry.
    Returns None if prerequisites are missing.
    """
    if config.ac_root is None:
        log.info("Synthetic lap skipped: AC_ROOT not configured")
        return None
    if car_data is None or track_data is None:
        log.info("Synthetic lap skipped: car or track data unavailable")
        return None

    log.info("Building synthetic reference lap...")
    user = json.dumps({
        "car_data":       car_data,
        "track_data": {
            "track_id":         track_data.get("track_id"),
            "track_length_m":   track_data.get("track_length_m"),
            "corners_detected": track_data.get("corners_detected"),
        },
        "track_length_m": track_data.get("track_length_m"),
    }, separators=(",", ":"))

    try:
        result = call_claude_json(_SYSTEM, user, max_tokens=1024)
        log.info("Synthetic lap: %s ms", result.get("lap_time_ms"))
        return result
    except Exception as e:
        log.error("Synthetic lap failed: %s", e)
        return None
