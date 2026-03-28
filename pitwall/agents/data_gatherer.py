"""
data_gatherer.py -- the ONLY module allowed to import from pitwall.server.

Fetches all session and telemetry data needed by the analysis agents.
Returns a SessionPayload dict.
"""

import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))
from config import config  # noqa: E402

# Architectural rule: only this file imports from pitwall.server
from pitwall.server import (  # noqa: E402
    get_session_metadata,
    list_laps,
    get_lap_trace,
    get_ac_car_data,
    get_ac_track_line,
)
from pitwall.export import VALLELUNGA_CORNERS  # noqa: E402

log = logging.getLogger(__name__)

_CORE_CHANNELS    = ["speed_kph", "brake_pct", "throttle_pct", "gear"]
_BRAKING_CHANNELS = ["speed_kph", "brake_pct", "long_g"]
_BALANCE_CHANNELS = ["speed_kph", "steering_deg", "lat_g"]


def _downsample(samples: list[dict], n: int = 100) -> list[dict]:
    if len(samples) <= n:
        return samples
    step = len(samples) / n
    return [samples[int(i * step)] for i in range(n)]


def _flag_braking(corner_summary: list[dict], corner_name: str) -> bool:
    for c in corner_summary:
        if c["corner_name"] == corner_name:
            d = c.get("delta", {})
            bp = d.get("brake_point_m")
            tl = d.get("estimated_time_loss_ms", 0)
            return (bp is not None and abs(bp) > 10) or tl > 150
    return False


def _flag_balance(balance_samples: list[dict]) -> bool:
    if not balance_samples:
        return False
    peak_steer = max((abs(s.get("steering_deg") or 0) for s in balance_samples), default=0)
    peak_lat   = max((abs(s.get("lat_g")        or 0) for s in balance_samples), default=0)
    if peak_lat < 0.1:
        return False
    return (peak_steer / peak_lat) > 30 or peak_steer > 40


def gather(session_id: str, corner_summary: list[dict] | None = None) -> dict:
    """
    Fetch all data needed for a session analysis.

    Returns a SessionPayload dict with session_meta, lap IDs, and
    per-corner telemetry traces for each analysis type.
    """
    meta = get_session_metadata(session_id)
    if "error" in meta:
        raise ValueError(f"Session not found: {session_id} -- {meta['error']}")

    laps = list_laps(session_id)
    if not laps:
        raise ValueError(f"No laps found for session {session_id}")

    best_lap = next((l for l in laps if l["is_best"]), None)
    ref_lap  = next((l for l in laps if l["is_reference"]), None)

    if best_lap is None:
        raise ValueError("No best lap found")

    if ref_lap is None:
        candidates = [l for l in laps if l["is_valid"] and not l["is_best"] and l["lap_time_ms"]]
        if candidates:
            ref_lap = min(candidates, key=lambda l: l["lap_time_ms"])

    best_id  = best_lap["lap_id"]
    ref_id   = ref_lap["lap_id"] if ref_lap else best_id
    ref_type = "driven" if ref_lap else "self"

    log.info("Best: %s   Ref: %s (%s)", best_id, ref_id, ref_type)

    corner_payloads = []
    for corner in VALLELUNGA_CORNERS:
        name = corner["name"]
        s_m, e_m = float(corner["start_m"]), float(corner["end_m"])

        best_core = get_lap_trace(best_id, _CORE_CHANNELS, s_m, e_m)
        ref_core  = get_lap_trace(ref_id,  _CORE_CHANNELS, s_m, e_m)

        payload = {
            "corner_name": name,
            "start_m":     s_m,
            "end_m":       e_m,
            "best_trace":  _downsample(best_core.get("samples", [])),
            "ref_trace":   _downsample(ref_core.get("samples",  [])),
            "needs_braking": False,
            "needs_balance": False,
        }

        if _flag_braking(corner_summary or [], name):
            bt = get_lap_trace(best_id, _BRAKING_CHANNELS, s_m, e_m)
            payload["best_braking_trace"] = _downsample(bt.get("samples", []))
            payload["needs_braking"] = True

        bal = get_lap_trace(best_id, _BALANCE_CHANNELS, s_m, e_m)
        bal_samples = bal.get("samples", [])
        if _flag_balance(bal_samples):
            payload["best_balance_trace"] = _downsample(bal_samples)
            payload["needs_balance"] = True

        corner_payloads.append(payload)
        log.info("  %s: best=%d ref=%d", name,
                 len(payload["best_trace"]), len(payload["ref_trace"]))

    # Optional AC data
    car_data = track_data = None
    if config.ac_root is not None:
        cd = get_ac_car_data(meta.get("car", ""))
        if "error" not in cd:
            car_data = cd
        td = get_ac_track_line(meta.get("track", ""))
        if "error" not in td:
            track_data = td

    return {
        "session_id":      session_id,
        "session_meta":    meta,
        "best_lap_id":     best_id,
        "ref_lap_id":      ref_id,
        "ref_type":        ref_type,
        "corner_payloads": corner_payloads,
        "car_data":        car_data,
        "track_data":      track_data,
    }
