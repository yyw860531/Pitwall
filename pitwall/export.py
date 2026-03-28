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

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Corner map — Vallelunga Club (calibrated from Lap Distance channel)
# Auto-replaced by get_ac_track_line() output when AC_ROOT is set.
# ---------------------------------------------------------------------------

VALLELUNGA_CORNERS = [
    {"name": "T1_Curva_Grande",  "display": "T1 Curva Grande",  "start_m":  50,  "apex_m": 140,  "end_m": 220},
    {"name": "T2_Chicane_Entry", "display": "T2 Chicane Entry", "start_m": 320,  "apex_m": 375,  "end_m": 430},
    {"name": "T3_Chicane_Exit",  "display": "T3 Chicane Exit",  "start_m": 430,  "apex_m": 482,  "end_m": 530},
    {"name": "T4_Tornantino",    "display": "T4 Tornantino",    "start_m": 700,  "apex_m": 798,  "end_m": 900},
    {"name": "T5_Final_Chicane", "display": "T5 Final Chicane", "start_m":1200,  "apex_m":1320,  "end_m":1455},
]

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


# ---------------------------------------------------------------------------
# Main export function
# ---------------------------------------------------------------------------

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

        corner_summary = _build_corner_summary(best_samples, ref_samples, VALLELUNGA_CORNERS)

        dashboard = {
            "$schema": "pitwall-dashboard-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "session": {
                "session_id":            session["session_id"],
                "driver":                session["driver"],
                "car_id":                session["car"],
                "car_display":           "Abarth 500 EsseEsse",
                "track_id":              session["track"],
                "track_display":         "Vallelunga Club",
                "track_length_m":        1720.17,
                "date":                  session["date"],
                "best_lap_number":       best_lap["lap_number"],
                "best_lap_time_ms":      best_lap["lap_time_ms"],
                "reference_lap_number":  ref_lap["lap_number"] if ref_lap else None,
                "reference_type":        ref_type,
                "theoretical_best_ms":   theoretical_best_ms,
                "sector_count":          2,
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
            "coaching_report": coaching_report if coaching_report else {
                "reference_type":  ref_type,
                "reference_note":  None,
                "full_markdown":   "## Analysis pending\n\nRun `python scripts/run_session.py` to generate the full coaching report.",
                "priority_corners": [
                    {
                        "rank":                    c["priority"],
                        "corner_name":             c["corner_name"],
                        "headline":                f"Estimated {c['delta']['estimated_time_loss_ms']}ms to gain",
                        "estimated_time_gain_ms":  c["delta"]["estimated_time_loss_ms"],
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
                "next_action": "Run the full agent pipeline for detailed coaching.",
            },
        }

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
