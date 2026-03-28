"""
server.py — FastMCP server exposing 6 data-only tools.

Design rule: zero analysis logic here. Every tool is a SQL query or a file read.
Racing knowledge lives exclusively in agents.

Run standalone (stdio transport, for use by orchestrator):
    python -m pitwall.server
"""

import json
import logging
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from fastmcp import FastMCP

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
from config import config  # noqa: E402

log = logging.getLogger(__name__)

mcp = FastMCP("pitwall")

# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Path safety — used by tools that read AC files
# ---------------------------------------------------------------------------

def _safe_ac_path(base: Path, user_id: str) -> Path:
    """Resolve a car_id or track_id to a path under base, blocking traversal."""
    if not re.match(r'^[a-zA-Z0-9_\-]+$', user_id):
        raise ValueError(f"Invalid id (only alphanumeric, _ and - allowed): {user_id!r}")
    resolved = (base / user_id).resolve()
    if not str(resolved).startswith(str(base.resolve())):
        raise ValueError(f"Path traversal attempt blocked for id: {user_id!r}")
    return resolved


# ---------------------------------------------------------------------------
# Tool 1: list_sessions
# ---------------------------------------------------------------------------

@mcp.tool()
def list_sessions() -> list[dict]:
    """
    Return all ingested sessions with basic metadata.
    """
    conn = _db()
    try:
        rows = conn.execute("""
            SELECT
                s.session_id,
                s.car,
                s.track,
                s.date,
                s.driver,
                s.fastest_lap,
                s.fastest_time_ms,
                COUNT(l.lap_id)         AS lap_count,
                SUM(l.is_valid)         AS valid_lap_count
            FROM sessions s
            LEFT JOIN laps l ON s.session_id = l.session_id
            GROUP BY s.session_id
            ORDER BY s.date DESC, s.session_id DESC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tool 2: list_laps
# ---------------------------------------------------------------------------

@mcp.tool()
def list_laps(session_id: str) -> list[dict]:
    """
    Return all laps for a session with per-lap metadata.
    session_id: e.g. '28032026-152157'
    """
    conn = _db()
    try:
        rows = conn.execute("""
            SELECT
                lap_id,
                lap_number,
                lap_time_ms,
                is_valid,
                is_best,
                is_reference,
                is_synthetic,
                s1_ms,
                s2_ms
            FROM laps
            WHERE session_id = ?
            ORDER BY lap_number
        """, (session_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tool 3: get_lap_trace
# ---------------------------------------------------------------------------

@mcp.tool()
def get_lap_trace(
    lap_id: str,
    channels: list[str],
    distance_start_m: float = 0.0,
    distance_end_m: float = 9999.0,
) -> dict:
    """
    Return raw telemetry samples for a lap within a distance range.
    Only the requested channels are returned — agents should request only what they need.

    lap_id: e.g. '28032026-152157_lap4'
    channels: subset of [speed_kph, throttle_pct, brake_pct, steering_deg,
                          gear, rpm, lat_g, long_g, slip_fl, slip_fr, slip_rl, slip_rr,
                          car_pos_norm, lap_distance_m]
    distance_start_m / distance_end_m: filter by lap_distance_m range
    """
    # Whitelist of allowed column names to prevent SQL injection
    ALLOWED = {
        "lap_distance_m", "car_pos_norm", "speed_kph", "throttle_pct",
        "brake_pct", "steering_deg", "gear", "rpm",
        "lat_g", "long_g", "slip_fl", "slip_fr", "slip_rl", "slip_rr",
    }
    bad = [c for c in channels if c not in ALLOWED]
    if bad:
        raise ValueError(f"Unknown channel(s): {bad}. Allowed: {sorted(ALLOWED)}")

    # Always include lap_distance_m as the x-axis
    cols = list({"lap_distance_m"} | set(channels))
    col_sql = ", ".join(cols)

    conn = _db()
    try:
        # Verify lap exists
        lap = conn.execute(
            "SELECT lap_id FROM laps WHERE lap_id = ?", (lap_id,)
        ).fetchone()
        if lap is None:
            return {"error": "lap_id not found", "code": "NOT_FOUND"}

        rows = conn.execute(
            f"""SELECT {col_sql}
                FROM telemetry
                WHERE lap_id = ?
                  AND lap_distance_m >= ?
                  AND lap_distance_m <= ?
                ORDER BY lap_distance_m""",
            (lap_id, distance_start_m, distance_end_m),
        ).fetchall()

        samples = [dict(r) for r in rows]
        return {
            "lap_id": lap_id,
            "distance_range_m": [distance_start_m, distance_end_m],
            "sample_count": len(samples),
            "channels": cols,
            "samples": samples,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tool 4: get_session_metadata
# ---------------------------------------------------------------------------

@mcp.tool()
def get_session_metadata(session_id: str) -> dict:
    """
    Return session-level metadata: car, track, lap summary, gear ratios.
    Reads from the sessions and laps tables (populated from .ldx at ingest).
    """
    conn = _db()
    try:
        session = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if session is None:
            return {"error": "session_id not found", "code": "NOT_FOUND"}

        laps = conn.execute(
            """SELECT lap_number, lap_time_ms, is_valid, is_best, is_reference,
                      s1_ms, s2_ms
               FROM laps WHERE session_id = ? ORDER BY lap_number""",
            (session_id,),
        ).fetchall()

        valid_times = [r["lap_time_ms"] for r in laps if r["is_valid"]]
        best_s1 = min((r["s1_ms"] for r in laps if r["s1_ms"] is not None), default=None)
        best_s2 = min((r["s2_ms"] for r in laps if r["s2_ms"] is not None), default=None)
        theoretical_best_ms = (best_s1 + best_s2) if (best_s1 and best_s2) else None

        best_s1_row = conn.execute(
            "SELECT lap_id FROM laps WHERE session_id=? AND s1_ms IS NOT NULL AND is_valid=1 ORDER BY s1_ms LIMIT 1",
            (session_id,)
        ).fetchone()
        best_s2_row = conn.execute(
            "SELECT lap_id FROM laps WHERE session_id=? AND s2_ms IS NOT NULL AND is_valid=1 ORDER BY s2_ms LIMIT 1",
            (session_id,)
        ).fetchone()

        return {
            **dict(session),
            "lap_count": len(laps),
            "valid_lap_count": len(valid_times),
            "theoretical_best_ms": theoretical_best_ms,
            "best_s1_lap_id": best_s1_row["lap_id"] if best_s1_row else None,
            "best_s2_lap_id": best_s2_row["lap_id"] if best_s2_row else None,
            "laps": [dict(r) for r in laps],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tool 5: get_ac_car_data
# ---------------------------------------------------------------------------

@mcp.tool()
def get_ac_car_data(car_id: str) -> dict:
    """
    Read AC car physics files from the AC installation.
    Returns mass, grip coefficients, engine power curve, and drivetrain data
    for use by the Synthetic Lap Agent.

    car_id: e.g. 'abarth500'
    Requires AC_ROOT to be set in .env.
    """
    if config.ac_root is None:
        return {"error": "AC_ROOT not configured", "code": "AC_ROOT_MISSING"}

    cars_dir = config.ac_root / "content" / "cars"
    try:
        car_path = _safe_ac_path(cars_dir, car_id)
    except ValueError as e:
        return {"error": str(e), "code": "INVALID_ID"}

    if not car_path.exists():
        return {"error": f"Car directory not found: {car_id}", "code": "NOT_FOUND"}

    # Parse car.ini for basic specs
    car_ini = car_path / "data" / "car.ini"
    if not car_ini.exists():
        return {"error": "car.ini not found", "code": "FILE_MISSING"}

    import configparser
    cp = configparser.ConfigParser(strict=False)
    cp.read(str(car_ini))

    def _ini_float(section: str, key: str) -> float | None:
        try:
            return float(cp[section][key])
        except (KeyError, ValueError):
            return None

    # Read ai.ini: contains SPEED_MULTIPLIER that scales fast_lane.ai speed hints
    # for this specific car's performance envelope.
    ai_ini = car_path / "data" / "ai.ini"
    ai_speed_multiplier = 1.0
    if ai_ini.exists():
        cp2 = configparser.ConfigParser(strict=False)
        cp2.read(str(ai_ini))
        for section in cp2.sections():
            for key in ("SPEED_MULTIPLIER", "speed_multiplier"):
                try:
                    ai_speed_multiplier = float(cp2[section][key])
                    break
                except (KeyError, ValueError):
                    pass

    return {
        "car_id":              car_id,
        "mass_kg":             _ini_float("BASIC", "TOTALMASS"),
        "fuel_consumption":    _ini_float("FUEL", "CONSUMPTION"),
        "ai_speed_multiplier": ai_speed_multiplier,
    }


# ---------------------------------------------------------------------------
# Tool 6: get_ac_track_line
# ---------------------------------------------------------------------------

@mcp.tool()
def get_ac_track_line(track_id: str) -> dict:
    """
    Parse the AC fast_lane.ai file for a track.
    Returns XYZ waypoints with computed curvature and auto-detected corner segments.
    Used by the Synthetic Lap Agent to build corner maps.

    track_id: e.g. 'ks_vallelungaclub_circuit'
    Requires AC_ROOT to be set in .env.
    """
    if config.ac_root is None:
        return {"error": "AC_ROOT not configured", "code": "AC_ROOT_MISSING"}

    tracks_dir = config.ac_root / "content" / "tracks"
    try:
        track_path = _safe_ac_path(tracks_dir, track_id)
    except ValueError as e:
        return {"error": str(e), "code": "INVALID_ID"}

    ai_file = track_path / "ai" / "fast_lane.ai"
    if not ai_file.exists():
        # Try alternate layout path
        ai_file = track_path / "ai" / "fast_lane.ai"

    if not ai_file.exists():
        return {"error": f"fast_lane.ai not found for track: {track_id}", "code": "FILE_MISSING"}

    try:
        points = _parse_ai_file(ai_file)
    except Exception as e:
        return {"error": f"Failed to parse fast_lane.ai: {e}", "code": "PARSE_ERROR"}

    corners = _detect_corners(points)

    return {
        "track_id": track_id,
        "track_length_m": points[-1]["distance_m"] if points else 0,
        "sample_count": len(points),
        "points": points[::5],  # downsample to every 5th point for context efficiency
        "corners_detected": corners,
    }


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
    import struct
    data = ai_path.read_bytes()
    file_size = len(data)

    count = struct.unpack_from("<I", data, 0)[0]

    # Detect record size: which multiplier gives exact file coverage?
    record_size = None
    for rs in (16, 20, 24):
        if 4 + count * rs == file_size:
            record_size = rs
            break
    if record_size is None:
        # Header count may be stale — infer from arithmetic
        for rs in (20, 24, 16):
            if (file_size - 4) % rs == 0:
                count = (file_size - 4) // rs
                record_size = rs
                break
    if record_size is None:
        raise ValueError(
            f"Cannot determine fast_lane.ai record format (file_size={file_size}, "
            f"header_count={count})"
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
        # Field 3 (index 3) is the AI speed hint in m/s across all AC formats.
        # In 16-byte records it is the only non-xyz field.
        # In 20/24-byte records extra fields follow (side distances, etc.).
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


def _detect_corners(points: list[dict], curvature_threshold: float = 0.015,
                    min_gap_m: float = 50.0) -> list[dict]:
    """
    Detect corners from XYZ waypoints by computing curvature.
    Returns corner segments with start/apex/end in metres.
    """
    if len(points) < 10:
        return []

    # Compute curvature at each point using 3-point method
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

    # Find segments above threshold
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

            # Skip if too short or too close to last corner
            if (end_m - start_m) < 10:
                continue
            if corners and (start_m - corners[-1]["end_m"]) < min_gap_m:
                # Merge with previous corner
                corners[-1]["end_m"] = round(float(end_m), 1)
                continue

            apex_idx = corner_start + int(np.argmax(curvatures[corner_start:i]))
            corners.append({
                "start_m": round(float(start_m), 1),
                "apex_m": round(float(dists[apex_idx]), 1),
                "end_m": round(float(end_m), 1),
            })

    # Name corners sequentially
    for n, c in enumerate(corners, start=1):
        c["name"] = f"T{n}"

    return corners


# ---------------------------------------------------------------------------
# HTTP API endpoints (used by the dashboard Import button)
# These run on the same uvicorn server as the MCP tools when started with --http.
# ---------------------------------------------------------------------------

@mcp.custom_route("/api/scan", methods=["POST"])
async def api_scan(request) -> dict:
    """
    Scan TELEMETRY_EXPORT_DIR for .ld files not yet in the DB.
    Ingest any new ones and export the latest session's dashboard.json.
    """
    from pitwall.ingest import ingest
    from pitwall.export import export

    if config.telemetry_export_dir is None:
        return {"error": "TELEMETRY_EXPORT_DIR not configured", "new_sessions": 0}

    export_dir = config.telemetry_export_dir
    if not export_dir.exists():
        return {"error": f"Directory not found: {export_dir}", "new_sessions": 0}

    # Find all .ld files
    ld_files = sorted(export_dir.rglob("*.ld"))

    # Check which are already in DB
    conn = _db()
    existing = {
        row[0] for row in conn.execute("SELECT session_id FROM sessions").fetchall()
    }
    conn.close()

    new_sessions = []
    for ld_path in ld_files:
        from pitwall.ingest import derive_session_id
        sid = derive_session_id(ld_path)
        if sid not in existing:
            try:
                ingested_sid = ingest(ld_path)
                new_sessions.append(ingested_sid)
                log.info("Auto-ingested: %s", ingested_sid)
            except Exception as e:
                log.error("Failed to ingest %s: %s", ld_path.name, e)

    # Export the most recent session
    if new_sessions:
        try:
            export(new_sessions[-1])
        except Exception as e:
            log.error("Export failed: %s", e)

    return {"new_sessions": len(new_sessions), "sessions": new_sessions}


@mcp.custom_route("/api/export/{session_id}", methods=["POST"])
async def api_export(request) -> dict:
    """Export a specific session to dashboard.json."""
    from pitwall.export import export
    session_id = request.path_params.get("session_id", "")
    try:
        out = export(session_id)
        return {"status": "ok", "output": str(out)}
    except ValueError as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
