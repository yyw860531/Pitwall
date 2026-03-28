"""
data_gatherer.py -- the ONLY module allowed to import from pitwall.server.

Fetches all session and telemetry data needed by the analysis agents.
Returns a SessionPayload dict.

Reference lap strategy:
  When the session has sector-best data (best_s1_lap_id / best_s2_lap_id from metadata),
  each corner is compared against the lap that set the best time in that sector.
  This shows the TRUE gap to what the driver has already done — typically 1-2s for
  a driver who has been inconsistent across a session.

  Fallback: use a driven reference lap, or self-comparison if no other laps exist.
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

# Sector 1 / Sector 2 boundary — mirrors the ingest.py SECTOR_BOUNDARY_M constant
SECTOR_BOUNDARY_M = 580.0


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
    if best_lap is None:
        raise ValueError("No best lap found")

    best_id = best_lap["lap_id"]

    # ------------------------------------------------------------------
    # Determine reference strategy
    # ------------------------------------------------------------------
    best_s1_lap_id = meta.get("best_s1_lap_id")
    best_s2_lap_id = meta.get("best_s2_lap_id")

    # Use sector-best reference when we have different sector bests
    # (i.e. the driver's best S1 and best S2 came from different laps, or
    # either sector best is better than the overall best lap)
    use_sector_ref = (
        best_s1_lap_id is not None
        and best_s2_lap_id is not None
        and (best_s1_lap_id != best_id or best_s2_lap_id != best_id)
    )

    if use_sector_ref:
        ref_type = "sector_best"
        log.info("Reference: sector-best  S1=%s  S2=%s", best_s1_lap_id, best_s2_lap_id)
        # Compute per-sector deltas: how much the best lap loses to each sector-best reference
        best_s1_lap = next((l for l in laps if l["lap_id"] == best_s1_lap_id), None)
        best_s2_lap = next((l for l in laps if l["lap_id"] == best_s2_lap_id), None)
        s1_delta_ms = max(0, (best_lap.get("s1_ms") or 0) - (best_s1_lap.get("s1_ms") or 0)) if best_s1_lap else None
        s2_delta_ms = max(0, (best_lap.get("s2_ms") or 0) - (best_s2_lap.get("s2_ms") or 0)) if best_s2_lap else None
        ref_id = None
    else:
        # Fallback: driven reference or self
        ref_lap = next((l for l in laps if l["is_reference"]), None)
        if ref_lap is None:
            candidates = [l for l in laps if l["is_valid"] and not l["is_best"] and l["lap_time_ms"]]
            if candidates:
                ref_lap = min(candidates, key=lambda l: l["lap_time_ms"])
        ref_id   = ref_lap["lap_id"] if ref_lap else best_id
        ref_type = "driven" if ref_lap else "self"
        # Sector delta: whole lap delta, split evenly as a loose bound
        lap_delta = max(0, (best_lap.get("lap_time_ms") or 0) - ((ref_lap or best_lap).get("lap_time_ms") or 0))
        s1_delta_ms = lap_delta // 2
        s2_delta_ms = lap_delta // 2
        log.info("Reference: %s  lap=%s", ref_type, ref_id)

    # ------------------------------------------------------------------
    # Build per-corner payloads
    # ------------------------------------------------------------------
    corner_payloads = []
    for corner in VALLELUNGA_CORNERS:
        name = corner["name"]
        s_m, e_m = float(corner["start_m"]), float(corner["end_m"])

        best_core = get_lap_trace(best_id, _CORE_CHANNELS, s_m, e_m)

        if use_sector_ref:
            # Route each corner to the lap that set the best time in its sector
            corner_mid    = (s_m + e_m) / 2
            sector_ref_id = best_s1_lap_id if corner_mid < SECTOR_BOUNDARY_M else best_s2_lap_id
            ref_core = get_lap_trace(sector_ref_id, _CORE_CHANNELS, s_m, e_m)
        else:
            ref_core = get_lap_trace(ref_id, _CORE_CHANNELS, s_m, e_m)

        corner_mid = (s_m + e_m) / 2
        sector_delta = s1_delta_ms if corner_mid < SECTOR_BOUNDARY_M else s2_delta_ms

        payload = {
            "corner_name":      name,
            "start_m":          s_m,
            "end_m":            e_m,
            "best_trace":       _downsample(best_core.get("samples", [])),
            "ref_trace":        _downsample(ref_core.get("samples", [])),
            "sector_delta_ms":  sector_delta,   # total sector gap — agent must stay within this
            "needs_braking":    False,
            "needs_balance":    False,
        }

        if _flag_braking(corner_summary or [], name):
            bt = get_lap_trace(best_id, _BRAKING_CHANNELS, s_m, e_m)
            payload["best_braking_trace"] = _downsample(bt.get("samples", []))
            payload["needs_braking"] = True

        bal         = get_lap_trace(best_id, _BALANCE_CHANNELS, s_m, e_m)
        bal_samples = bal.get("samples", [])
        if _flag_balance(bal_samples):
            payload["best_balance_trace"] = _downsample(bal_samples)
            payload["needs_balance"] = True

        corner_payloads.append(payload)
        log.info("  %s: best=%d ref=%d", name,
                 len(payload["best_trace"]), len(payload["ref_trace"]))

    # ------------------------------------------------------------------
    # Optional AC data (used by synthetic lap agent, not for reference)
    # ------------------------------------------------------------------
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
        "ref_type":        ref_type,
        "corner_payloads": corner_payloads,
        "car_data":        car_data,
        "track_data":      track_data,
    }
