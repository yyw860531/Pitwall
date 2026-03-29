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
    sector_boundary_m: float,
    n_points: int = SPEED_TRACE_POINTS,
) -> dict | None:
    """
    Stitch together the best-S1 lap (distance < boundary) and best-S2 lap
    (distance >= boundary) to produce a theoretical best speed trace.
    Returns None if sector data is unavailable.
    """
    if sector_boundary_m is None:
        return None
    valid = [l for l in laps if l["is_valid"] and l["s1_ms"] and l["s2_ms"]]
    if not valid:
        return None

    best_s1_lap = min(valid, key=lambda l: l["s1_ms"])
    best_s2_lap = min(valid, key=lambda l: l["s2_ms"])

    s1_samples = [
        s for s in _fetch_lap_telemetry(conn, best_s1_lap["lap_id"])
        if s["lap_distance_m"] < sector_boundary_m
    ]
    s2_samples = [
        s for s in _fetch_lap_telemetry(conn, best_s2_lap["lap_id"])
        if s["lap_distance_m"] >= sector_boundary_m
    ]
    all_samples = s1_samples + s2_samples
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
        "best_s1_lap_number": best_s1_lap["lap_number"],
        "best_s2_lap_number": best_s2_lap["lap_number"],
        "lap_time_ms": best_s1_lap["s1_ms"] + best_s2_lap["s2_ms"],
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
    Handles multi-layout tracks where the map lives in a layout sub-folder.
    """
    if ac_root is None:
        return None

    tracks_dir = ac_root / "content" / "tracks"

    # 1. Direct match
    direct = tracks_dir / track_id / "map.png"
    if direct.exists():
        return direct

    # 2. Known multi-layout mappings (AC uses parent/layout folder structure)
    known = {
        "ks_vallelungaclub_circuit":     ("ks_vallelunga", "club_circuit"),
        "ks_vallelungaextended_circuit": ("ks_vallelunga", "extended_circuit"),
        "ks_vallelungaclassic_circuit":  ("ks_vallelunga", "classic_circuit"),
        "ks_nordschleife":               ("ks_nordschleife", "nordschleife"),
        "ks_nordschleife_touristenfahrten": ("ks_nordschleife", "touristenfahrten"),
    }
    if track_id in known:
        base, layout = known[track_id]
        p = tracks_dir / base / layout / "map.png"
        if p.exists():
            return p

    # 3. Glob fallback — search under any folder starting with track_id prefix
    prefix = track_id[:8] if len(track_id) > 8 else track_id
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


def export(
    session_id: str,
    output_path: Path | None = None,
    coaching_report: dict | None = None,
) -> Path:
    """
    Build dashboard.json for a session and write it to output_path.
    Returns the path written.
    """
    output_path = output_path or (_ROOT / "dashboard" / "public" / "dashboard.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    conn = _db()
    try:
        # --- Session ---
        session = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if session is None:
            raise ValueError(f"Session not found: {session_id}")

        session = dict(session)

        # --- Laps ---
        laps_rows = conn.execute(
            "SELECT * FROM laps WHERE session_id = ? ORDER BY lap_number",
            (session_id,),
        ).fetchall()
        laps = [dict(r) for r in laps_rows]

        # --- Identify best and reference laps ---
        best_lap = next((l for l in laps if l["is_best"]), None)
        ref_lap  = next((l for l in laps if l["is_reference"]), None)

        # Fallback reference: best valid lap that isn't the best lap
        if ref_lap is None:
            valid_laps = [l for l in laps if l["is_valid"] and not l["is_best"]]
            if valid_laps:
                ref_lap = min(valid_laps, key=lambda l: l["lap_time_ms"])

        if best_lap is None:
            raise ValueError(f"No best lap found for session {session_id}")

        ref_type = "driven" if ref_lap else "none"
        log.info("Best lap: %s  Reference: %s",
                 best_lap["lap_id"], ref_lap["lap_id"] if ref_lap else "none")

        # --- Telemetry ---
        best_samples = _fetch_lap_telemetry(conn, best_lap["lap_id"])
        ref_samples  = _fetch_lap_telemetry(conn, ref_lap["lap_id"]) if ref_lap else best_samples

        # --- Compute sector stats ---
        valid_laps = [l for l in laps if l["is_valid"]]
        best_s1 = min((l["s1_ms"] for l in valid_laps if l["s1_ms"]), default=None)
        best_s2 = min((l["s2_ms"] for l in valid_laps if l["s2_ms"]), default=None)
        theoretical_best_ms = (best_s1 + best_s2) if (best_s1 and best_s2) else None

        # --- Build dashboard JSON ---
        speed_trace = _build_speed_trace(best_samples, ref_samples)
        speed_trace["best_lap_number"]  = best_lap["lap_number"]
        speed_trace["reference_lap_number"] = ref_lap["lap_number"] if ref_lap else None

        input_trace = _build_input_trace(best_samples, ref_samples)
        input_trace["best_lap_number"]  = best_lap["lap_number"]
        input_trace["reference_lap_number"] = ref_lap["lap_number"] if ref_lap else None

        corners = get_corners(session["track"], config.ac_root)
        corner_summary = _build_corner_summary(best_samples, ref_samples, corners)

        sector_boundary_m = session["sector_boundary_m"]

        # --- Per-lap traces for the dashboard lap selector ---
        all_lap_traces       = _build_all_lap_traces(conn, laps)
        theoretical_best_trace = _build_theoretical_best_trace(conn, laps, sector_boundary_m)

        # --- Track map ---
        track_map_url = None
        if config.ac_root is not None:
            map_src = _find_track_map(session["track"], config.ac_root)
            if map_src and map_src.exists():
                map_dst = output_path.parent / "track_map.png"
                import shutil
                shutil.copy2(str(map_src), str(map_dst))
                track_map_url = "track_map.png"
                log.info("Track map copied: %s", map_dst)

        dashboard = {
            "$schema": "pitwall-dashboard-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "session": {
                "session_id":            session["session_id"],
                "driver":                session["driver"],
                "car_id":                session["car"],
                "car_display":           CAR_DISPLAY.get(session["car"], session["car"]),
                "track_id":              session["track"],
                "track_display":         TRACK_DISPLAY.get(session["track"], session["track"]),
                "track_length_m":        TRACK_LENGTH_M.get(session["track"], 0.0),
                "date":                  session["date"],
                "best_lap_number":       best_lap["lap_number"],
                "best_lap_time_ms":      best_lap["lap_time_ms"],
                "reference_lap_number":  ref_lap["lap_number"] if ref_lap else None,
                "reference_type":        ref_type,
                "theoretical_best_ms":   theoretical_best_ms,
                "sector_count":          session["sector_count"],
                "track_map_url":         track_map_url,
                "sector_boundary_m":     sector_boundary_m,
            },
            "laps": [
                {
                    "lap_number":   l["lap_number"],
                    "lap_time_ms":  l["lap_time_ms"],
                    "is_valid":     bool(l["is_valid"]),
                    "is_best":      bool(l["is_best"]),
                    "is_reference": bool(l["is_reference"]),
                    "is_synthetic": bool(l["is_synthetic"]),
                    "sectors": {
                        "s1_ms": l["s1_ms"],
                        "s2_ms": l["s2_ms"],
                        "s3_ms": None,
                    },
                }
                for l in laps
            ],
            "speed_trace": speed_trace,
            "input_trace": input_trace,
            "corner_summary": corner_summary,
            "all_lap_traces":        all_lap_traces,
            "theoretical_best_trace": theoretical_best_trace,
                "coaching_report": _resolve_coaching_report(
                conn, session_id, coaching_report, ref_type,
                theoretical_best_ms, best_lap, corner_summary,
            ),
        }

        # Persist coaching report to DB if newly provided
        if coaching_report is not None:
            conn.execute(
                "UPDATE sessions SET coaching_report_json = ? WHERE session_id = ?",
                (json.dumps(coaching_report), session_id),
            )
            conn.commit()
            log.info("Coaching report saved to DB for %s", session_id)

        output_path.write_text(json.dumps(dashboard, indent=2))
        log.info("Dashboard written to %s", output_path)
        return output_path

    finally:
        conn.close()


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
