"""
track.py — corner map detection from AC fast_lane.ai files.

Shared between server.py (MCP tool) and export.py (dashboard build).
Requires AC_ROOT to be set. Returns an empty list if the file is missing
or AC_ROOT is not configured — callers degrade gracefully with no corner summary.
"""

import re
import struct
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_corners(track_id: str, ac_root: Path | None) -> list[dict]:
    """
    Return a corner list for *track_id* in the shape expected by export.py:
        [{"name": str, "display": str, "start_m": float, "apex_m": float, "end_m": float}]

    Requires AC_ROOT. Returns [] if AC_ROOT is not set or fast_lane.ai is missing.
    """
    if ac_root is None:
        return []
    return _corners_from_ai_file(track_id, ac_root)


# ---------------------------------------------------------------------------
# fast_lane.ai detection
# ---------------------------------------------------------------------------

def _corners_from_ai_file(track_id: str, ac_root: Path) -> list[dict]:
    """Parse fast_lane.ai and return detected corners, or [] on any error."""
    if not re.match(r'^[a-zA-Z0-9_\-]+$', track_id):
        return []

    tracks_dir = ac_root / "content" / "tracks"
    ai_file = tracks_dir / track_id / "ai" / "fast_lane.ai"
    if not ai_file.exists():
        return []

    try:
        points = _parse_ai_file(ai_file)
        raw = _detect_corners(points)
        # Add display name (plain "T1", "T2" … since we have no human name)
        for c in raw:
            c["display"] = c["name"]
        return raw
    except Exception:
        return []


def _parse_ai_file(ai_path: Path) -> list[dict]:
    """
    Parse AC fast_lane.ai binary file.

    Format: int32 count + N records of floats.
    Record layout (all known AC versions):
      float x, y, z       -- world position (metres)
      float speed_ms      -- AI speed hint for this point (m/s)
      float ...           -- optional extra fields (side distances, etc.)

    Record size is auto-detected: whichever of 16/20/24 bytes gives exact
    file coverage with the stored count wins.
    """
    data = ai_path.read_bytes()
    file_size = len(data)

    count = struct.unpack_from("<I", data, 0)[0]

    record_size = None
    for rs in (16, 20, 24):
        if 4 + count * rs == file_size:
            record_size = rs
            break
    if record_size is None:
        for rs in (20, 24, 16):
            if (file_size - 4) % rs == 0:
                count = (file_size - 4) // rs
                record_size = rs
                break
    if record_size is None:
        raise ValueError(
            f"Cannot determine fast_lane.ai record format "
            f"(file_size={file_size}, header_count={count})"
        )

    n_floats = record_size // 4
    fmt = f"<{n_floats}f"
    points = []
    offset = 4
    cum_dist = 0.0
    prev_xyz = None

    for _ in range(count):
        floats = struct.unpack_from(fmt, data, offset)
        offset += record_size
        x, y, z = floats[0], floats[1], floats[2]
        speed_ms = float(floats[3]) if n_floats > 3 else 0.0

        xyz = np.array([x, y, z])
        if prev_xyz is not None:
            cum_dist += float(np.linalg.norm(xyz - prev_xyz))

        points.append({
            "distance_m": round(cum_dist, 2),
            "x":          round(float(x), 3),
            "y":          round(float(y), 3),
            "z":          round(float(z), 3),
            "speed_ms":   round(speed_ms, 3),
        })
        prev_xyz = xyz

    return points


def _detect_corners(
    points: list[dict],
    curvature_threshold: float = 0.015,
    min_gap_m: float = 50.0,
) -> list[dict]:
    """
    Detect corners from XYZ waypoints by computing curvature.
    Returns corner segments with start/apex/end in metres, named T1, T2 …
    """
    if len(points) < 10:
        return []

    xyz = np.array([[p["x"], p["y"], p["z"]] for p in points])
    dists = np.array([p["distance_m"] for p in points])
    curvatures = np.zeros(len(points))

    for i in range(1, len(points) - 1):
        a, b, c = xyz[i - 1], xyz[i], xyz[i + 1]
        ab = np.linalg.norm(b - a)
        bc = np.linalg.norm(c - b)
        ac = np.linalg.norm(c - a)
        area2 = np.linalg.norm(np.cross(b - a, c - a))
        if ab * bc * ac > 1e-6:
            curvatures[i] = area2 / (ab * bc * ac)

    in_corner = False
    corner_start = 0
    corners = []

    for i, (k, d) in enumerate(zip(curvatures, dists)):
        if not in_corner and k > curvature_threshold:
            in_corner = True
            corner_start = i
        elif in_corner and k <= curvature_threshold:
            in_corner = False
            start_m = dists[corner_start]
            end_m = d

            if (end_m - start_m) < 10:
                continue
            if corners and (start_m - corners[-1]["end_m"]) < min_gap_m:
                corners[-1]["end_m"] = round(float(end_m), 1)
                continue

            apex_idx = corner_start + int(np.argmax(curvatures[corner_start:i]))
            corners.append({
                "start_m": round(float(start_m), 1),
                "apex_m":  round(float(dists[apex_idx]), 1),
                "end_m":   round(float(end_m), 1),
            })

    for n, c in enumerate(corners, start=1):
        c["name"] = f"T{n}"

    return corners
