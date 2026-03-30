from __future__ import annotations

"""
export.py — queries SQLite and produces dashboard/public/dashboard.json.

This runs without agents. Corner metrics are computed directly from raw telemetry.
The coaching_report section is a placeholder until the agent pipeline runs.

Usage:
    python -m pitwall.export <session_id> [--output path/to/dashboard.json]
"""

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
from config import config  # noqa: E402
from pitwall.track import get_corners  # noqa: E402

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Corner map — Vallelunga Club (calibrated from Lap Distance channel)
# Auto-replaced by get_ac_track_line() output when AC_ROOT is set.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Display name lookups — maps raw car_id / track_id from filename to
# human-readable strings and known track lengths.
# Falls back to the raw ID if not found (works for any new car/track).
# ---------------------------------------------------------------------------

CAR_DISPLAY: dict[str, str] = {
    "abarth500":    "Abarth 500 EsseEsse",
    "ks_abarth500": "Abarth 500 EsseEsse",
}

TRACK_DISPLAY: dict[str, str] = {
    "ks_vallelungaclub_circuit":     "Vallelunga Club",
    "ks_vallelungaextended_circuit": "Vallelunga Extended",
    "ks_nordschleife":               "Nürburgring Nordschleife",
    "ks_spa":                        "Spa-Francorchamps",
    "ks_monza":                      "Monza",
    "ks_silverstone":                "Silverstone",
    "ks_mugello":                    "Mugello",
    "magione":                       "Autodromo di Magione",
    "ks_magione":                    "Autodromo di Magione",
}

TRACK_LENGTH_M: dict[str, float] = {
    "ks_vallelungaclub_circuit":     1720.17,
    "ks_vallelungaextended_circuit": 3240.0,
    "ks_nordschleife":               20832.0,
    "ks_spa":                        7004.0,
    "ks_monza":                      5793.0,
    "ks_silverstone":                5891.0,
    "ks_mugello":                    5245.0,
}


SPEED_TRACE_POINTS = 200   # fixed-length arrays for the dashboard charts
BRAKE_THRESHOLD_PCT = 5.0  # Brake Pos > 5% counts as braking
THROTTLE_THRESHOLD_PCT = 10.0  # Throttle Pos > 10% counts as throttle pickup


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_lap_telemetry(conn: sqlite3.Connection, lap_id: str) -> list[dict]:
    """Return all telemetry samples for a lap, ordered by lap_distance_m."""
    rows = conn.execute(
        """SELECT lap_distance_m, speed_kph, throttle_pct, brake_pct,
                  steering_deg, gear, rpm, lat_g, long_g
           FROM telemetry
           WHERE lap_id = ?
           ORDER BY lap_distance_m""",
        (lap_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Speed / input trace — downsample to fixed-length arrays
# ---------------------------------------------------------------------------

def _build_speed_trace(
    best_samples: list[dict],
    ref_samples: list[dict],
    n_points: int = SPEED_TRACE_POINTS,
) -> dict:
    """
    Interpolate both laps onto a common distance grid and build the speed trace.
    """
    best_dist  = np.array([s["lap_distance_m"] for s in best_samples])
    best_speed = np.array([s["speed_kph"] or 0 for s in best_samples])
    ref_dist   = np.array([s["lap_distance_m"] for s in ref_samples])
    ref_speed  = np.array([s["speed_kph"] or 0 for s in ref_samples])

    # Common distance axis clipped to overlap
    d_min = max(best_dist.min(), ref_dist.min())
    d_max = min(best_dist.max(), ref_dist.max())
    grid = np.linspace(d_min, d_max, n_points)

    best_interp = np.interp(grid, best_dist, best_speed)
    ref_interp  = np.interp(grid, ref_dist, ref_speed)
    delta       = best_interp - ref_interp

    return {
        "samples": [
            {
                "distance_m":    round(float(g), 1),
                "best_speed_kph": round(float(b), 2),
                "ref_speed_kph":  round(float(r), 2),
                "delta_kph":      round(float(d), 2),
            }
            for g, b, r, d in zip(grid, best_interp, ref_interp, delta)
        ]
    }


def _build_input_trace(
    best_samples: list[dict],
    ref_samples: list[dict],
    n_points: int = SPEED_TRACE_POINTS,
) -> dict:
    best_dist = np.array([s["lap_distance_m"] for s in best_samples])
    ref_dist  = np.array([s["lap_distance_m"] for s in ref_samples])

    d_min = max(best_dist.min(), ref_dist.min())
    d_max = min(best_dist.max(), ref_dist.max())
    grid = np.linspace(d_min, d_max, n_points)

    def _interp(samples, dist_arr, key):
        vals = np.array([s[key] or 0 for s in samples])
        return np.interp(grid, dist_arr, vals)

    best_thr = _interp(best_samples, best_dist, "throttle_pct")
    best_brk = _interp(best_samples, best_dist, "brake_pct")
    ref_thr  = _interp(ref_samples,  ref_dist,  "throttle_pct")
    ref_brk  = _interp(ref_samples,  ref_dist,  "brake_pct")

    return {
        "samples": [
            {
                "distance_m":        round(float(g), 1),
                "best_throttle_pct": round(float(bt), 1),
                "best_brake_pct":    round(float(bb), 1),
                "ref_throttle_pct":  round(float(rt), 1),
                "ref_brake_pct":     round(float(rb), 1),
            }
            for g, bt, bb, rt, rb in zip(grid, best_thr, best_brk, ref_thr, ref_brk)
        ]
    }


# ---------------------------------------------------------------------------
# Corner metrics — computed directly from telemetry (no agents)
# ---------------------------------------------------------------------------

def _corner_metrics(samples: list[dict], corner: dict) -> dict | None:
    """
    Compute brake_point_m, min_speed_kph, min_speed_distance_m, throttle_pickup_m
    for a single lap within a corner's distance range.
    Returns None if not enough samples.
    """
    seg = [
        s for s in samples
        if corner["start_m"] <= s["lap_distance_m"] <= corner["end_m"]
    ]
    if len(seg) < 5:
        return None

    dists    = np.array([s["lap_distance_m"] for s in seg])
    speeds   = np.array([s["speed_kph"] or 0 for s in seg])
    brakes   = np.array([s["brake_pct"] or 0 for s in seg])
    throttles = np.array([s["throttle_pct"] or 0 for s in seg])

    # Brake point: first sample where brake_pct > threshold
    brake_idx = np.where(brakes > BRAKE_THRESHOLD_PCT)[0]
    brake_point_m = float(dists[brake_idx[0]]) if len(brake_idx) > 0 else None

    # Min speed and its location
    min_speed_idx = int(np.argmin(speeds))
    min_speed_kph = float(speeds[min_speed_idx])
    min_speed_m   = float(dists[min_speed_idx])

    # Throttle pickup: first sample after min speed where throttle > threshold
    throttle_idx = np.where(
        (throttles > THROTTLE_THRESHOLD_PCT) & (dists > min_speed_m)
    )[0]
    throttle_pickup_m = float(dists[throttle_idx[0]]) if len(throttle_idx) > 0 else None

    return {
        "brake_point_m":      round(brake_point_m, 1) if brake_point_m else None,
        "min_speed_kph":      round(min_speed_kph, 1),
        "min_speed_dist_m":   round(min_speed_m, 1),
        "throttle_pickup_m":  round(throttle_pickup_m, 1) if throttle_pickup_m else None,
    }


def _build_corner_summary(
    best_samples: list[dict],
    ref_samples: list[dict],
    corners: list[dict],
) -> list[dict]:
    """
    Build corner summary rows with deltas, sorted by estimated time loss.
    """
    results = []

    for corner in corners:
        best_m = _corner_metrics(best_samples, corner)
        ref_m  = _corner_metrics(ref_samples, corner)

        if best_m is None or ref_m is None:
            continue

        # Delta computations (positive = better for the best lap)
        brake_delta = (
            round(best_m["brake_point_m"] - ref_m["brake_point_m"], 1)
            if best_m["brake_point_m"] and ref_m["brake_point_m"] else None
        )
        min_speed_delta = round(best_m["min_speed_kph"] - ref_m["min_speed_kph"], 1)
        throttle_delta = (
            round(best_m["throttle_pickup_m"] - ref_m["throttle_pickup_m"], 1)
            if best_m["throttle_pickup_m"] and ref_m["throttle_pickup_m"] else None
        )

        # Rough time loss estimate: speed delta at min speed * corner duration
        corner_dur_s = (corner["end_m"] - corner["start_m"]) / max(best_m["min_speed_kph"] / 3.6, 1)
        speed_diff = ref_m["min_speed_kph"] - best_m["min_speed_kph"]
        est_time_loss_ms = max(0, int(round(speed_diff / max(best_m["min_speed_kph"], 1) * corner_dur_s * 1000)))

        results.append({
            "corner_name":    corner["name"],
            "corner_display": corner["display"],
            "start_m":        corner["start_m"],
            "apex_m":         corner["apex_m"],
            "end_m":          corner["end_m"],
            "best_lap":       best_m,
            "reference_lap":  ref_m,
            "delta": {
                "brake_point_m":        brake_delta,
                "min_speed_kph":        min_speed_delta,
                "throttle_pickup_m":    throttle_delta,
                "estimated_time_loss_ms": est_time_loss_ms,
            },
            "priority": 0,  # filled in after sorting
        })

    # Sort by estimated time loss descending; assign priority rank
    results.sort(key=lambda r: r["delta"]["estimated_time_loss_ms"], reverse=True)
    for i, r in enumerate(results):
        r["priority"] = i + 1

    return results



def _build_all_lap_traces(
    conn: sqlite3.Connection,
    laps: list[dict],
    n_points: int = SPEED_TRACE_POINTS,
) -> dict:
    """
    Build downsampled speed + input traces for every valid lap.
    Keyed by lap_number (as string) for easy JSON serialisation.
    Used by the dashboard lap selector.
    """
    result = {}
    for lap in laps:
        if not lap["is_valid"] or not lap["lap_time_ms"]:
            continue
        samples = _fetch_lap_telemetry(conn, lap["lap_id"])
        if len(samples) < 10:
            continue

        dist  = np.array([s["lap_distance_m"] for s in samples])
        speed = np.array([s["speed_kph"]      or 0 for s in samples])
        thr   = np.array([s["throttle_pct"]   or 0 for s in samples])
        brk   = np.array([s["brake_pct"]      or 0 for s in samples])

        grid        = np.linspace(dist.min(), dist.max(), n_points)
        speed_interp = np.interp(grid, dist, speed)
        thr_interp   = np.interp(grid, dist, thr)
        brk_interp   = np.interp(grid, dist, brk)

        result[str(lap["lap_number"])] = {
            "lap_number":  lap["lap_number"],
            "lap_time_ms": lap["lap_time_ms"],
            "is_best":     bool(lap["is_best"]),
            "speed_trace": [
                {"distance_m": round(float(g), 1), "speed_kph": round(float(s), 2)}
                for g, s in zip(grid, speed_interp)
            ],
            "input_trace": [
                {
                    "distance_m":   round(float(g), 1),
                    "throttle_pct": round(float(t), 1),
                    "brake_pct":    round(float(b), 1),
                }
                for g, t, b in zip(grid, thr_interp, brk_interp)
            ],
        }
    return result


def _build_theoretical_best_trace(
    conn: sqlite3.Connection,
    laps: list[dict],
    sector_boundaries: list[float],
    n_points: int = SPEED_TRACE_POINTS,
) -> dict | None:
    """
    Stitch together the best sector laps to produce a theoretical best trace.
    Supports 2 or 3 sectors (1 or 2 boundaries).
    Returns None if sector data is unavailable.
    """
    if not sector_boundaries:
        return None

    sector_keys = ["s1_ms", "s2_ms", "s3_ms"]
    n_sectors = len(sector_boundaries) + 1

    # Find laps with all required sector times
    valid = [l for l in laps if l["is_valid"]]
    valid = [l for l in valid if all(l.get(sector_keys[i]) for i in range(n_sectors))]
    if not valid:
        return None

    # Find the best lap for each sector
    best_sector_laps = []
    for i in range(n_sectors):
        key = sector_keys[i]
        best_sector_laps.append(min(valid, key=lambda l, k=key: l[k]))

    # Build distance ranges for each sector: [0, b1], [b1, b2], [b2, ∞]
    bounds = [0.0] + sorted(sector_boundaries) + [float("inf")]

    # Stitch telemetry from each sector's best lap
    all_samples = []
    sector_info = {}
    total_time_ms = 0
    for i in range(n_sectors):
        lap = best_sector_laps[i]
        lo, hi = bounds[i], bounds[i + 1]
        samples = [
            s for s in _fetch_lap_telemetry(conn, lap["lap_id"])
            if lo <= s["lap_distance_m"] < hi
        ]
        all_samples.extend(samples)
        sector_info[f"best_s{i+1}_lap_number"] = lap["lap_number"]
        total_time_ms += lap[sector_keys[i]]

    if len(all_samples) < 10:
        return None

    dist  = np.array([s["lap_distance_m"] for s in all_samples])
    speed = np.array([s["speed_kph"]      or 0 for s in all_samples])
    thr   = np.array([s["throttle_pct"]   or 0 for s in all_samples])
    brk   = np.array([s["brake_pct"]      or 0 for s in all_samples])

    grid         = np.linspace(dist.min(), dist.max(), n_points)
    speed_interp = np.interp(grid, dist, speed)
    thr_interp   = np.interp(grid, dist, thr)
    brk_interp   = np.interp(grid, dist, brk)

    return {
        **sector_info,
        "lap_time_ms": total_time_ms,
        "speed_trace": [
            {"distance_m": round(float(g), 1), "speed_kph": round(float(s), 2)}
            for g, s in zip(grid, speed_interp)
        ],
        "input_trace": [
            {
                "distance_m":   round(float(g), 1),
                "throttle_pct": round(float(t), 1),
                "brake_pct":    round(float(b), 1),
            }
            for g, t, b in zip(grid, thr_interp, brk_interp)
        ],
    }


def _find_track_map(track_id: str, ac_root) -> Path | None:
    """
    Locate map.png for a track in the AC installation.

    AC multi-layout tracks use a parent/layout folder structure:
        tracks/ks_red_bull_ring/layout_gp/map.png
    But Telemetrick encodes this as a flat track_id in the filename:
        ks_red_bull_ring-layout_gp  (or with underscores)

    Strategy: try direct match, then auto-detect parent/layout split by
    checking which AC track folders actually exist on disk.
    """
    if ac_root is None:
        return None

    tracks_dir = ac_root / "content" / "tracks"
    if not tracks_dir.is_dir():
        return None

    # Normalise: Telemetrick may use hyphens where AC uses underscores
    normalised = track_id.replace("-", "_")

    # 1. Direct match — single-layout track where folder name = track_id
    for tid in (track_id, normalised):
        direct = tracks_dir / tid / "map.png"
        if direct.exists():
            return direct

    # 2. Auto-detect parent/layout split
    #    Try every underscore position: if the left part is an existing
    #    track folder and the right part is a layout sub-folder, use it.
    parts = normalised.split("_")
    for i in range(1, len(parts)):
        parent = "_".join(parts[:i])
        layout = "_".join(parts[i:])
        p = tracks_dir / parent / layout / "map.png"
        if p.exists():
            return p

    # 3. Glob fallback — fuzzy match on prefix
    prefix = normalised[:8] if len(normalised) > 8 else normalised
    for candidate in tracks_dir.glob(f"*{prefix}*/map.png"):
        return candidate
    for candidate in tracks_dir.glob(f"*{prefix}*/*/map.png"):
        return candidate

    return None


# ---------------------------------------------------------------------------
# Main export function
# ---------------------------------------------------------------------------

def _resolve_coaching_report(
    conn, session_id, coaching_report, ref_type, theoretical_best_ms, best_lap, corner_summary
) -> dict:
    """Return coaching report: provided > saved in DB > placeholder."""
    if coaching_report is not None:
        return coaching_report

    # Load from DB if analysis was previously run
    row = conn.execute(
        "SELECT coaching_report_json FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row and row[0]:
        try:
            return json.loads(row[0])
        except Exception:
            pass

    # Placeholder — agents haven't run yet
    return {
        "reference_type":  ref_type,
        "reference_note":  None,
        "full_markdown":   "## Analysis pending\n\nClick **Run AI Analysis** to generate the full coaching report.",
        "priority_corners": [
            {
                "rank":                   c["priority"],
                "corner_name":            c["corner_name"],
                "headline":               f"Estimated {c['delta']['estimated_time_loss_ms']}ms to gain",
                "estimated_time_gain_ms": c["delta"]["estimated_time_loss_ms"],
            }
            for c in corner_summary[:2]
        ],
        "session_summary": (
            f"Best lap: {best_lap['lap_time_ms'] // 60000}:"
            f"{(best_lap['lap_time_ms'] % 60000) / 1000:.3f}  |  "
            f"Theoretical best: "
            + (f"{theoretical_best_ms // 60000}:{(theoretical_best_ms % 60000) / 1000:.3f}"
               if theoretical_best_ms else "N/A")
        ),
        "next_action": "Click Run AI Analysis for detailed coaching.",
    }


def build_dashboard(
    session_id: str,
    coaching_report: dict | None = None,
) -> dict:
    """
    Build and return the dashboard dict for a session.
    If coaching_report is provided it is saved to DB and embedded.
    If not, the saved report is loaded from DB (if any).
    """
    conn = _db()
    try:
        session = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if session is None:
            raise ValueError(f"Session not found: {session_id}")
        session = dict(session)

        laps_rows = conn.execute(
            "SELECT * FROM laps WHERE session_id = ? ORDER BY lap_number",
            (session_id,),
        ).fetchall()
        laps = [dict(r) for r in laps_rows]

        best_lap = next((l for l in laps if l["is_best"] and l["is_valid"]), None)
        # Fallback: fastest valid lap if .ldx best lap was invalidated
        if best_lap is None:
            valid = [l for l in laps if l["is_valid"] and l["lap_time_ms"]]
            if valid:
                best_lap = min(valid, key=lambda l: l["lap_time_ms"])

        if best_lap is None:
            raise ValueError(f"No valid laps found for session {session_id}")

        ref_lap = next((l for l in laps if l["is_reference"]), None)
        if ref_lap is None:
            candidates = [l for l in laps if l["is_valid"] and l["lap_id"] != best_lap["lap_id"] and l["lap_time_ms"]]
            if candidates:
                ref_lap = min(candidates, key=lambda l: l["lap_time_ms"])

        ref_type = "driven" if ref_lap else "none"

        best_samples = _fetch_lap_telemetry(conn, best_lap["lap_id"])
        if not best_samples:
            raise ValueError(f"No telemetry data for best lap {best_lap['lap_id']}")
        ref_samples  = _fetch_lap_telemetry(conn, ref_lap["lap_id"]) if ref_lap else best_samples

        valid_laps = [l for l in laps if l["is_valid"]]

        # Parse sector boundaries from session (N-sector support)
        sector_boundaries_raw = session.get("sector_boundaries_json")
        sector_boundaries: list[float] = []
        if sector_boundaries_raw:
            try:
                sector_boundaries = json.loads(sector_boundaries_raw)
            except (json.JSONDecodeError, TypeError):
                pass

        n_sectors = len(sector_boundaries) + 1 if sector_boundaries else session.get("sector_count", 2) or 2
        sector_keys = ["s1_ms", "s2_ms", "s3_ms"][:n_sectors]

        # Theoretical best = sum of best individual sector times
        best_sectors = []
        for key in sector_keys:
            best_val = min((l[key] for l in valid_laps if l.get(key)), default=None)
            best_sectors.append(best_val)
        theoretical_best_ms = sum(best_sectors) if all(s is not None for s in best_sectors) else None

        speed_trace = _build_speed_trace(best_samples, ref_samples)
        speed_trace["best_lap_number"]      = best_lap["lap_number"]
        speed_trace["reference_lap_number"] = ref_lap["lap_number"] if ref_lap else None

        input_trace = _build_input_trace(best_samples, ref_samples)
        input_trace["best_lap_number"]      = best_lap["lap_number"]
        input_trace["reference_lap_number"] = ref_lap["lap_number"] if ref_lap else None

        all_valid_samples = [
            _fetch_lap_telemetry(conn, l["lap_id"])
            for l in valid_laps
        ]
        corners        = get_corners(session["track"], config.ac_root, all_valid_samples)
        corner_summary = _build_corner_summary(best_samples, ref_samples, corners)

        # Sanity check: all sector boundaries must be within telemetry range
        if sector_boundaries and best_samples:
            max_dist = max(s["lap_distance_m"] for s in best_samples)
            sane = all(0 < b < max_dist for b in sector_boundaries)
            if not sane:
                log.warning(
                    "Sector boundaries %s look wrong for track with %.0fm telemetry — ignoring",
                    sector_boundaries, max_dist,
                )
                sector_boundaries = []

        all_lap_traces         = _build_all_lap_traces(conn, laps)
        theoretical_best_trace = _build_theoretical_best_trace(conn, laps, sector_boundaries)

        # --- Track length: venue_length from ingest > lookup table > telemetry max ---
        track_length_m = session.get("venue_length_m")
        if not track_length_m:
            track_length_m = TRACK_LENGTH_M.get(session["track"])
        if track_length_m is None and best_samples:
            track_length_m = max(s["lap_distance_m"] for s in best_samples)
        if track_length_m is None:
            track_length_m = 0.0

        # --- Track map as base64 data URI (works for both API and file paths) ---
        track_map_url = None
        if config.ac_root is not None:
            map_src = _find_track_map(session["track"], config.ac_root)
            if map_src and map_src.exists():
                import base64
                track_map_url = "data:image/png;base64," + base64.b64encode(
                    map_src.read_bytes()
                ).decode()

        # Persist new coaching report to DB before resolving
        if coaching_report is not None:
            conn.execute(
                "UPDATE sessions SET coaching_report_json = ? WHERE session_id = ?",
                (json.dumps(coaching_report), session_id),
            )
            conn.commit()
            log.info("Coaching report saved to DB for %s", session_id)

        return {
            "$schema":      "pitwall-dashboard-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "session": {
                "session_id":           session["session_id"],
                "driver":               session["driver"],
                "car_id":               session["car"],
                "car_display":          CAR_DISPLAY.get(session["car"], session["car"]),
                "track_id":             session["track"],
                "track_display":        TRACK_DISPLAY.get(session["track"], session["track"]),
                "track_length_m":       track_length_m,
                "date":                 session["date"],
                "best_lap_number":      best_lap["lap_number"],
                "best_lap_time_ms":     best_lap["lap_time_ms"],
                "reference_lap_number": ref_lap["lap_number"] if ref_lap else None,
                "reference_type":       ref_type,
                "theoretical_best_ms":  theoretical_best_ms,
                "sector_count":         n_sectors,
                "track_map_url":        track_map_url,
                "sector_boundaries":    sector_boundaries,
            },
            "laps": [
                {
                    "lap_number":   l["lap_number"],
                    "lap_time_ms":  l["lap_time_ms"],
                    "is_valid":     bool(l["is_valid"]),
                    "is_best":      bool(l["is_best"]),
                    "is_reference": bool(l["is_reference"]),
                    "is_synthetic": bool(l["is_synthetic"]),
                    "sectors": {"s1_ms": l["s1_ms"], "s2_ms": l["s2_ms"], "s3_ms": l.get("s3_ms")},
                }
                for l in laps
            ],
            "speed_trace":            speed_trace,
            "input_trace":            input_trace,
            "corner_summary":         corner_summary,
            "all_lap_traces":         all_lap_traces,
            "theoretical_best_trace": theoretical_best_trace,
            "coaching_report":        _resolve_coaching_report(
                conn, session_id, coaching_report, ref_type,
                theoretical_best_ms, best_lap, corner_summary,
            ),
        }
    finally:
        conn.close()


def export(
    session_id: str,
    output_path: Path | None = None,
    coaching_report: dict | None = None,
) -> Path:
    """Build dashboard.json for a session and write it to output_path."""
    output_path = output_path or (_ROOT / "dashboard" / "public" / "dashboard.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    dashboard = build_dashboard(session_id, coaching_report)
    output_path.write_text(json.dumps(dashboard, indent=2))
    log.info("Dashboard written to %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export PitWall dashboard.json")
    parser.add_argument("session_id", help="Session ID, e.g. 28032026-155415")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output path (default: dashboard/public/dashboard.json)")
    args = parser.parse_args()

    try:
        out = export(args.session_id, args.output)
        print(f"Done → {out}")
    except ValueError as e:
        log.error("%s", e)
        sys.exit(1)
