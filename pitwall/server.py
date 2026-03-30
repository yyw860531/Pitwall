"""
server.py — FastMCP server exposing 6 data-only tools.

Design rule: zero analysis logic here. Every tool is a SQL query or a file read.
Racing knowledge lives exclusively in agents.

Security note: The HTTP companion server binds to 127.0.0.1 only and has no
authentication. This is intentional for a single-user local tool. Do not expose
the HTTP port to untrusted networks.

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
from starlette.responses import JSONResponse

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
from config import config  # noqa: E402
from pitwall.track import _parse_ai_file, _detect_corners  # noqa: E402

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

def _find_ac_track_file(tracks_dir: Path, track_id: str, *subpath: str) -> Path | None:
    """
    Locate a file within an AC track folder, handling multi-layout directory splits.
    AC uses tracks/{parent}/{layout}/ but Telemetrick encodes as a flat track_id.
    """
    if not re.match(r'^[a-zA-Z0-9_\-]+$', track_id):
        return None

    normalised = track_id.replace("-", "_")

    # 1. Direct match
    for tid in (track_id, normalised):
        candidate = tracks_dir / tid / Path(*subpath)
        if candidate.exists():
            return candidate

    # 2. Auto-detect parent/layout split at each underscore position
    parts = normalised.split("_")
    for i in range(1, len(parts)):
        parent = "_".join(parts[:i])
        layout = "_".join(parts[i:])
        candidate = tracks_dir / parent / layout / Path(*subpath)
        if candidate.exists():
            return candidate

    # 3. Glob fallback — validate results stay within tracks_dir
    prefix = normalised[:8] if len(normalised) > 8 else normalised
    target = str(Path(*subpath))
    resolved_base = tracks_dir.resolve()
    for candidate in tracks_dir.glob(f"*{prefix}*/{target}"):
        if candidate.resolve().is_relative_to(resolved_base):
            return candidate
    for candidate in tracks_dir.glob(f"*{prefix}*/*/{target}"):
        if candidate.resolve().is_relative_to(resolved_base):
            return candidate

    return None


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
            """SELECT lap_number, lap_id, lap_time_ms, is_valid, is_best, is_reference,
                      s1_ms, s2_ms, s3_ms
               FROM laps WHERE session_id = ? ORDER BY lap_number""",
            (session_id,),
        ).fetchall()

        session_dict = dict(session)

        # Determine sector count from session metadata
        sector_boundaries_json = session_dict.get("sector_boundaries_json")
        n_sectors = session_dict.get("sector_count") or 2
        if sector_boundaries_json:
            import json as _json
            try:
                n_sectors = len(_json.loads(sector_boundaries_json)) + 1
            except (ValueError, TypeError):
                pass

        valid_times = [r["lap_time_ms"] for r in laps if r["is_valid"]]
        sector_keys = [f"s{i+1}_ms" for i in range(min(n_sectors, 3))]

        # Theoretical best = sum of individual sector bests
        best_sectors = []
        for key in sector_keys:
            best_val = min((r[key] for r in laps if r[key] is not None), default=None)
            best_sectors.append(best_val)
        theoretical_best_ms = sum(best_sectors) if all(s is not None for s in best_sectors) else None

        # Best lap per sector (for sector-best reference in agents)
        # Allowlist column names to avoid SQL injection via interpolation
        _SECTOR_COLS = {"s1_ms", "s2_ms", "s3_ms"}
        best_sector_lap_ids = {}
        for i, key in enumerate(sector_keys):
            if key not in _SECTOR_COLS:
                continue
            row = conn.execute(
                f"SELECT lap_id FROM laps WHERE session_id=? AND {key} IS NOT NULL AND is_valid=1 ORDER BY {key} LIMIT 1",
                (session_id,)
            ).fetchone()
            best_sector_lap_ids[f"best_s{i+1}_lap_id"] = row["lap_id"] if row else None

        return {
            **session_dict,
            "lap_count": len(laps),
            "valid_lap_count": len(valid_times),
            "theoretical_best_ms": theoretical_best_ms,
            **best_sector_lap_ids,
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

    # Read tyres.ini for grip data
    tyres_ini = car_path / "data" / "tyres.ini"
    tyre_grip = None
    if tyres_ini.exists():
        cp3 = configparser.ConfigParser(strict=False)
        cp3.read(str(tyres_ini))
        for section in cp3.sections():
            for key in ("FRICTION_LIMIT_ANGLE", "DY_REF"):
                try:
                    tyre_grip = float(cp3[section][key])
                    break
                except (KeyError, ValueError):
                    pass
            if tyre_grip:
                break

    # Read aero.ini for downforce
    aero_ini = car_path / "data" / "aero.ini"
    cl_front = cl_rear = None
    if aero_ini.exists():
        cp4 = configparser.ConfigParser(strict=False)
        cp4.read(str(aero_ini))
        for section in cp4.sections():
            if cl_front is None:
                for key in ("CL", "CL_GAIN"):
                    try:
                        val = float(cp4[section][key])
                        if "FRONT" in section.upper():
                            cl_front = val
                        elif "REAR" in section.upper():
                            cl_rear = val
                        break
                    except (KeyError, ValueError):
                        pass

    # Determine drivetrain type from drivetrain.ini
    dt_ini = car_path / "data" / "drivetrain.ini"
    drivetrain = None
    if dt_ini.exists():
        cp5 = configparser.ConfigParser(strict=False)
        cp5.read(str(dt_ini))
        for key in ("TYPE", "type"):
            try:
                drivetrain = cp5["TRACTION"][key]
                break
            except (KeyError, ValueError):
                pass

    return {
        "car_id":              car_id,
        "mass_kg":             _ini_float("BASIC", "TOTALMASS"),
        "fuel_consumption":    _ini_float("FUEL", "CONSUMPTION"),
        "ai_speed_multiplier": ai_speed_multiplier,
        "tyre_grip_ref":       tyre_grip,
        "cl_front":            cl_front,
        "cl_rear":             cl_rear,
        "drivetrain":          drivetrain,
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

    ai_file = _find_ac_track_file(tracks_dir, track_id, "ai", "fast_lane.ai")
    if ai_file is None:
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


# ---------------------------------------------------------------------------
# HTTP API endpoints (used by the dashboard Import button)
# These run on the same uvicorn server as the MCP tools when started with --http.
# ---------------------------------------------------------------------------

@mcp.custom_route("/api/sessions", methods=["GET"])
async def api_sessions(request):
    """List all ingested sessions."""
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
                COUNT(l.lap_id)     AS lap_count,
                SUM(l.is_valid)     AS valid_lap_count
            FROM sessions s
            LEFT JOIN laps l ON s.session_id = l.session_id
            GROUP BY s.session_id
            ORDER BY s.date DESC, s.session_id DESC
        """).fetchall()
        return JSONResponse([dict(r) for r in rows])
    finally:
        conn.close()


@mcp.custom_route("/api/scan", methods=["POST"])
async def api_scan(request):
    """
    Scan TELEMETRY_EXPORT_DIR for .ld files not yet in the DB.
    Ingest any new ones and export the latest session's dashboard.json.
    """
    from pitwall.ingest import ingest
    from pitwall.export import export

    if config.telemetry_export_dir is None:
        return JSONResponse({"error": "TELEMETRY_EXPORT_DIR not configured", "new_sessions": 0})

    export_dir = config.telemetry_export_dir
    if not export_dir.exists():
        return JSONResponse({"error": f"Directory not found: {export_dir}", "new_sessions": 0})

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

    return JSONResponse({"new_sessions": len(new_sessions), "sessions": new_sessions})


@mcp.custom_route("/api/export/{session_id}", methods=["POST"])
async def api_export(request):
    """Return full dashboard data for a session directly as JSON."""
    from pitwall.export import build_dashboard
    session_id = request.path_params.get("session_id", "")
    try:
        dashboard = build_dashboard(session_id)
        return JSONResponse(dashboard)
    except Exception as e:
        log.error("Export failed for %s: %s", session_id, e)
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/analyse/{session_id}", methods=["POST"])
async def api_analyse(request):
    """Run the full AI agent pipeline and return the updated dashboard data."""
    import asyncio

    session_id = request.path_params.get("session_id", "")

    if not config.anthropic_api_key or config.anthropic_api_key.startswith("your_"):
        return JSONResponse({"error": "ANTHROPIC_API_KEY not configured"}, status_code=400)

    def _run():
        from pitwall.orchestrator import orchestrate
        from pitwall.export import build_dashboard, _build_corner_summary, _fetch_lap_telemetry
        from pitwall.track import get_corners
        import sqlite3 as _sqlite3

        conn = _sqlite3.connect(str(config.db_path))
        conn.row_factory = _sqlite3.Row
        session_row = conn.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        laps = [dict(r) for r in conn.execute(
            "SELECT * FROM laps WHERE session_id=? ORDER BY lap_number", (session_id,)
        ).fetchall()]
        best_lap = next((l for l in laps if l["is_best"]), None)
        ref_lap  = next((l for l in laps if l.get("is_reference")), None)
        if ref_lap is None:
            candidates = [l for l in laps if l["is_valid"] and not l["is_best"] and l["lap_time_ms"]]
            if candidates:
                ref_lap = min(candidates, key=lambda l: l["lap_time_ms"])
        corner_summary = []
        corners = []
        if best_lap and ref_lap and session_row:
            best_samples = _fetch_lap_telemetry(conn, best_lap["lap_id"])
            ref_samples  = _fetch_lap_telemetry(conn, ref_lap["lap_id"])
            valid_laps_s = [l for l in laps if l["is_valid"]]
            all_valid_samples = [_fetch_lap_telemetry(conn, l["lap_id"]) for l in valid_laps_s]
            corners = get_corners(session_row["track"], config.ac_root, all_valid_samples)
            corner_summary = _build_corner_summary(best_samples, ref_samples, corners)
        conn.close()

        coaching_report = orchestrate(session_id, corner_summary, corners)
        return build_dashboard(session_id, coaching_report)

    try:
        loop = asyncio.get_event_loop()
        dashboard = await loop.run_in_executor(None, _run)
        return JSONResponse(dashboard)
    except Exception as e:
        log.error("Analysis failed for %s: %s", session_id, e)
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _start_file_watcher():
    """
    Start the telemetry file watcher in a background thread if
    TELEMETRY_EXPORT_DIR is configured. Silently skips if watchdog is not
    installed or the directory doesn't exist.
    """
    if config.telemetry_export_dir is None:
        return
    watch_dir = config.telemetry_export_dir
    if not watch_dir.exists():
        log.warning("TELEMETRY_EXPORT_DIR does not exist, watcher not started: %s", watch_dir)
        return
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        log.warning("watchdog not installed — auto-ingest disabled. Run: pip install watchdog")
        return

    import threading
    import time
    from pitwall.ingest import ingest

    class _Handler(FileSystemEventHandler):
        def __init__(self):
            self._pending: set[Path] = set()
            self._lock = threading.Lock()

        def _add(self, path: Path):
            if path.suffix.lower() == ".ld":
                with self._lock:
                    self._pending.add(path)

        def on_created(self, event):
            if not event.is_directory:
                self._add(Path(event.src_path))

        def on_modified(self, event):
            if not event.is_directory:
                self._add(Path(event.src_path))

        def process_pending(self):
            with self._lock:
                to_process, self._pending = list(self._pending), set()
            for ld_path in to_process:
                ldx_path = ld_path.with_suffix(".ldx")
                if not ldx_path.exists():
                    with self._lock:
                        self._pending.add(ld_path)  # retry next cycle
                    continue
                try:
                    session_id = ingest(ld_path)
                    log.info("Auto-ingested: %s", session_id)
                except Exception as e:
                    log.error("Auto-ingest failed for %s: %s", ld_path.name, e)

    handler = _Handler()
    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=True)
    observer.start()

    def _loop():
        while observer.is_alive():
            time.sleep(3)
            handler.process_pending()

    t = threading.Thread(target=_loop, daemon=True, name="telemetry-watcher")
    t.start()
    log.info("File watcher started: %s", watch_dir)


if __name__ == "__main__":
    import argparse as _ap
    _parser = _ap.ArgumentParser(description="PitWall MCP server")
    _parser.add_argument("--http", action="store_true",
                         help="Run as HTTP server (for dashboard API)")
    _parser.add_argument("--port", type=int, default=8765,
                         help="HTTP port (default: 8765)")
    _args = _parser.parse_args()

    if _args.http:
        import asyncio as _asyncio
        _start_file_watcher()
        _asyncio.run(mcp.run_http_async(
            transport="sse",
            host="127.0.0.1",
            port=_args.port,
            show_banner=True,
        ))
    else:
        mcp.run()
