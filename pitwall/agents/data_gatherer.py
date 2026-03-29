"""
data_gatherer.py -- the ONLY module that calls pitwall.server functions directly.

Fetches all session and telemetry data needed by the analysis agents.
Returns a SessionPayload dict.

Architecture note: pitwall.server is built with FastMCP decorators so it can serve
external clients via stdio/SSE transport. Internally, the orchestrator calls the
server functions directly as Python to avoid transport overhead — the MCP layer is
not used in this path.

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

import numpy as np

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
from pitwall.track import get_corners  # noqa: E402

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


def _flag_balance(balance_samples: list[dict], baseline_ratio: float | None = None) -> bool:
    """Flag a corner for balance analysis if steering/lat_g ratio is anomalous."""
    if not balance_samples:
        return False
    peak_steer = max((abs(s.get("steering_deg") or 0) for s in balance_samples), default=0)
    peak_lat   = max((abs(s.get("lat_g")        or 0) for s in balance_samples), default=0)
    if peak_lat < 0.1:
        return False
    ratio = peak_steer / peak_lat
    # If we have a baseline from other corners, flag if this corner is 2x+ above it.
    # Otherwise fall back to a generous threshold that works across car classes.
    if baseline_ratio and baseline_ratio > 0:
        return ratio > baseline_ratio * 2.0
    return ratio > 50 or peak_steer > 60


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
    # Parse sector boundaries and best-sector lap IDs
    sector_boundaries_json = meta.get("sector_boundaries_json")
    sector_boundaries: list[float] = []
    if sector_boundaries_json:
        import json
        try:
            sector_boundaries = json.loads(sector_boundaries_json)
        except (json.JSONDecodeError, TypeError):
            pass

    n_sectors = len(sector_boundaries) + 1 if sector_boundaries else 2
    sector_keys = [f"s{i+1}_ms" for i in range(n_sectors)]
    best_sector_lap_ids = [meta.get(f"best_s{i+1}_lap_id") for i in range(n_sectors)]

    # Use sector-best reference when we have different sector bests
    use_sector_ref = (
        all(lid is not None for lid in best_sector_lap_ids)
        and any(lid != best_id for lid in best_sector_lap_ids)
    )

    # Per-sector delta (how much best lap loses to each sector-best)
    sector_deltas: list[int | None] = [None] * n_sectors

    if use_sector_ref:
        ref_type = "sector_best"
        log.info("Reference: sector-best  %s",
                 "  ".join(f"S{i+1}={lid}" for i, lid in enumerate(best_sector_lap_ids)))
        for i in range(n_sectors):
            key = sector_keys[i]
            sector_lap = next((l for l in laps if l["lap_id"] == best_sector_lap_ids[i]), None)
            if sector_lap:
                sector_deltas[i] = max(0, (best_lap.get(key) or 0) - (sector_lap.get(key) or 0))
        ref_id = None
    else:
        ref_lap = next((l for l in laps if l["is_reference"]), None)
        if ref_lap is None:
            candidates = [l for l in laps if l["is_valid"] and not l["is_best"] and l["lap_time_ms"]]
            if candidates:
                ref_lap = min(candidates, key=lambda l: l["lap_time_ms"])
        ref_id   = ref_lap["lap_id"] if ref_lap else best_id
        ref_type = "driven" if ref_lap else "self"
        lap_delta = max(0, (best_lap.get("lap_time_ms") or 0) - ((ref_lap or best_lap).get("lap_time_ms") or 0))
        per_sector = lap_delta // max(n_sectors, 1)
        sector_deltas = [per_sector] * n_sectors
        log.info("Reference: %s  lap=%s", ref_type, ref_id)

    # ------------------------------------------------------------------
    # Build per-corner payloads
    # ------------------------------------------------------------------
    valid_laps = [l for l in laps if l["is_valid"]]
    all_valid_samples = [
        get_lap_trace(l["lap_id"], _CORE_CHANNELS)
        for l in valid_laps
    ]
    all_valid_samples = [t.get("samples", []) for t in all_valid_samples if t.get("samples")]
    corners = get_corners(meta.get("track", ""), config.ac_root, all_valid_samples)
    # Pre-compute steering/lat_g baseline across all corners for balance detection
    baseline_ratios = []
    for corner in corners:
        s_m, e_m = float(corner["start_m"]), float(corner["end_m"])
        bal = get_lap_trace(best_id, _BALANCE_CHANNELS, s_m, e_m)
        bal_s = bal.get("samples", [])
        if bal_s:
            ps = max((abs(s.get("steering_deg") or 0) for s in bal_s), default=0)
            pl = max((abs(s.get("lat_g") or 0) for s in bal_s), default=0)
            if pl > 0.1:
                baseline_ratios.append(ps / pl)
    baseline_ratio = float(np.median(baseline_ratios)) if baseline_ratios else None

    corner_payloads = []
    for corner in corners:
        name = corner["name"]
        s_m, e_m = float(corner["start_m"]), float(corner["end_m"])

        best_core = get_lap_trace(best_id, _CORE_CHANNELS, s_m, e_m)

        # Determine which sector this corner falls in
        corner_mid = (s_m + e_m) / 2
        sector_idx = 0
        for bi, b in enumerate(sector_boundaries):
            if corner_mid >= b:
                sector_idx = bi + 1

        if use_sector_ref:
            sector_ref_id = best_sector_lap_ids[sector_idx]
            ref_core = get_lap_trace(sector_ref_id, _CORE_CHANNELS, s_m, e_m)
        else:
            ref_core = get_lap_trace(ref_id, _CORE_CHANNELS, s_m, e_m)

        sector_delta = sector_deltas[sector_idx]

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
        if _flag_balance(bal_samples, baseline_ratio):
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
