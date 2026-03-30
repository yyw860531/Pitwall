"""
track.py — corner detection and AC track data parsing.

Primary method: detect corners from telemetry samples aggregated across
multiple laps. This works for any track without needing AC_ROOT.

Fallback (legacy): parse fast_lane.ai from AC installation. Only used if
AC_ROOT is set and the telemetry-based detection produces no results.
"""

import configparser
import re
import struct
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_corners(track_id: str, ac_root: Path | None, laps_samples: list[list[dict]] | None = None) -> list[dict]:
    """
    Return a corner list in the shape:
        [{"name": str, "display": str, "start_m": float, "apex_m": float, "end_m": float}]

    Detection order:
      1. Telemetry-based detection if laps_samples provided (preferred)
      2. fast_lane.ai from AC installation if ac_root is set (legacy fallback)
      3. Empty list — callers degrade gracefully
    """
    if laps_samples:
        corners = corners_from_telemetry(laps_samples)
        if corners:
            return corners
    if ac_root is not None:
        return _corners_from_ai_file(track_id, ac_root)
    return []


def corners_from_telemetry(laps_samples: list[list[dict]]) -> list[dict]:
    """
    Detect corners by finding lateral-G regions that appear consistently
    across multiple laps.

    Real corners produce sustained |lat_g| on every lap; one-off mistakes
    don't repeat consistently. The apex is where |lat_g| peaks per region.

    laps_samples: list of sample lists, each from _fetch_lap_telemetry().
    Returns corner list sorted by track position.
    """
    if not laps_samples:
        return []

    # Collect (start_m, apex_m, end_m) regions from every lap
    all_apexes: list[float] = []
    all_regions: list[tuple[float, float, float]] = []
    for samples in laps_samples:
        for region in _find_corner_regions(samples):
            all_apexes.append(region[1])
            all_regions.append(region)

    if not all_apexes:
        return []

    # Cluster apexes within CLUSTER_WINDOW_M of each other
    CLUSTER_WINDOW_M = 40.0
    MIN_LAP_FRACTION = 0.4

    sorted_apexes = sorted(range(len(all_apexes)), key=lambda i: all_apexes[i])
    clusters: list[list[int]] = []
    current: list[int] = [sorted_apexes[0]]

    for idx in sorted_apexes[1:]:
        if all_apexes[idx] - all_apexes[current[-1]] <= CLUSTER_WINDOW_M:
            current.append(idx)
        else:
            clusters.append(current)
            current = [idx]
    clusters.append(current)

    n_laps = len(laps_samples)
    result = []
    for cluster in clusters:
        if len(cluster) < max(1, n_laps * MIN_LAP_FRACTION):
            continue
        apex_m  = float(np.median([all_apexes[i] for i in cluster]))
        start_m = float(np.median([all_regions[i][0] for i in cluster]))
        end_m   = float(np.median([all_regions[i][2] for i in cluster]))
        result.append({
            "start_m": round(max(0.0, start_m), 1),
            "apex_m":  round(apex_m, 1),
            "end_m":   round(end_m, 1),
        })

    result.sort(key=lambda c: c["start_m"])

    # Merge corners that overlap or have < 20m gap between them.
    # 50m was too aggressive — it swallowed closely-spaced chicanes (e.g. Les Combes, Bus Stop at Spa).
    MIN_GAP_M = 20.0
    merged = []
    for c in result:
        if merged and c["start_m"] - merged[-1]["end_m"] < MIN_GAP_M:
            # Merge: extend end, keep apex with higher lat-G (use later apex as proxy)
            prev = merged[-1]
            prev["end_m"] = max(prev["end_m"], c["end_m"])
            # Keep the apex that's more central to the merged region
            mid = (prev["start_m"] + prev["end_m"]) / 2
            if abs(c["apex_m"] - mid) < abs(prev["apex_m"] - mid):
                prev["apex_m"] = c["apex_m"]
        else:
            merged.append(c)

    for n, c in enumerate(merged, start=1):
        c["name"]    = f"T{n}"
        c["display"] = f"T{n}"

    return merged


def _find_corner_regions(
    samples: list[dict],
    lat_g_threshold: float = 0.5,
    min_length_m: float = 30.0,
    max_corner_m: float = 300.0,
) -> list[tuple[float, float, float]]:
    """
    Find regions of sustained lateral G in a single lap.
    Returns list of (start_m, apex_m, end_m) tuples.

    Long sweeps (> max_corner_m) are split at lat-G local minima so that
    complex sequences like Maggotts-Becketts or Eau Rouge are detected as
    distinct corners rather than one giant region.
    """
    if len(samples) < 10:
        return []

    dists  = np.array([s["lap_distance_m"] for s in samples])
    lat_gs = np.abs(np.array([s["lat_g"] or 0.0 for s in samples]))

    in_corner   = False
    corner_start_idx = 0
    regions = []

    for i, (g, d) in enumerate(zip(lat_gs, dists)):
        if not in_corner and g >= lat_g_threshold:
            in_corner = True
            corner_start_idx = i
        elif in_corner and g < lat_g_threshold:
            in_corner = False
            _emit_region(dists, lat_gs, corner_start_idx, i, min_length_m, max_corner_m, regions)

    # Handle corner still open at end of lap
    if in_corner:
        _emit_region(dists, lat_gs, corner_start_idx, len(dists), min_length_m, max_corner_m, regions)

    return regions


def _emit_region(
    dists: np.ndarray, lat_gs: np.ndarray,
    start_idx: int, end_idx: int,
    min_length_m: float, max_corner_m: float,
    regions: list,
):
    """Emit one or more corner regions, splitting long sweeps at lat-G dips."""
    start_m = float(dists[start_idx])
    end_m   = float(dists[min(end_idx, len(dists) - 1)])
    if end_m - start_m < min_length_m:
        return

    seg_lat = lat_gs[start_idx:end_idx]

    # If the region is short enough, emit as-is
    if end_m - start_m <= max_corner_m:
        apex_idx = start_idx + int(np.argmax(seg_lat))
        regions.append((start_m, float(dists[apex_idx]), end_m))
        return

    # Long sweep — split at local minima in lat-G
    # Find valleys where lat-G dips below 60% of the region's peak
    peak_g = seg_lat.max()
    split_threshold = peak_g * 0.6
    below = seg_lat < split_threshold

    # Find contiguous below-threshold segments as split points
    sub_start = start_idx
    for j in range(1, len(seg_lat)):
        if below[j] and not below[j - 1] and (float(dists[start_idx + j]) - float(dists[sub_start])) > min_length_m:
            # Split here
            split_end = start_idx + j
            sub_seg = lat_gs[sub_start:split_end]
            apex_idx = sub_start + int(np.argmax(sub_seg))
            s = float(dists[sub_start])
            e = float(dists[split_end])
            if e - s >= min_length_m:
                regions.append((s, float(dists[apex_idx]), e))
            sub_start = split_end
        elif not below[j] and below[j - 1]:
            sub_start = start_idx + j

    # Emit the remaining segment
    if sub_start < start_idx + len(seg_lat):
        sub_seg = lat_gs[sub_start:end_idx]
        if len(sub_seg) > 0:
            s = float(dists[sub_start])
            e = float(dists[min(end_idx, len(dists) - 1)])
            if e - s >= min_length_m:
                apex_idx = sub_start + int(np.argmax(sub_seg))
                regions.append((s, float(dists[apex_idx]), e))


# ---------------------------------------------------------------------------
# AC sections.ini — real sector boundaries
# ---------------------------------------------------------------------------

def read_sectors(sections_ini_path: Path, track_length_m: float) -> list[float]:
    """
    Parse AC sections.ini and return sector boundary distances in metres.

    sections.ini defines sectors as normalised positions (0.0–1.0):
        [SECTION_0]
        IN=0.0
        OUT=0.35
        [SECTION_1]
        IN=0.35
        OUT=0.72
        ...

    Returns a list of boundary distances (the OUT of each sector except the last).
    For 3 sectors this returns [b1_m, b2_m] — two boundaries.
    Returns [] if the file can't be parsed.
    """
    if not sections_ini_path or not sections_ini_path.exists():
        return []
    if track_length_m <= 0:
        return []

    try:
        cp = configparser.ConfigParser(strict=False)
        cp.read(str(sections_ini_path))

        # Collect (index, OUT) pairs from SECTION_N entries
        sections = []
        for section in cp.sections():
            m = re.match(r"SECTION[_\s]*(\d+)", section, re.IGNORECASE)
            if not m:
                continue
            idx = int(m.group(1))
            out_val = None
            for key in ("OUT", "out", "Out"):
                try:
                    out_val = float(cp[section][key])
                    break
                except (KeyError, ValueError):
                    pass
            if out_val is not None:
                sections.append((idx, out_val))

        if len(sections) < 2:
            return []

        sections.sort(key=lambda x: x[0])

        # Boundaries are the OUT values of all sectors except the last
        # (the last sector's OUT is 1.0 = finish line)
        boundaries = []
        for idx, out_norm in sections[:-1]:
            boundary_m = round(out_norm * track_length_m, 1)
            if 0 < boundary_m < track_length_m:
                boundaries.append(boundary_m)

        return boundaries

    except Exception:
        return []


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
