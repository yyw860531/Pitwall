"""
run_session.py -- end-to-end CLI: ingest + analyse + export dashboard.json.

Usage:
    python scripts/run_session.py path/to/session.ld
    python scripts/run_session.py --session-id 28032026-155415
    python scripts/run_session.py path/to/session.ld --output custom/path/dashboard.json
    python scripts/run_session.py --list   # show all ingested sessions

After running, open http://localhost:5173 to see the updated dashboard.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _fmt_ms(ms: int | None) -> str:
    if ms is None:
        return "--:--.---"
    m = ms // 60000
    s = (ms % 60000) / 1000
    return f"{m}:{s:06.3f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="PitWall session analysis pipeline")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("ld_file", nargs="?", type=Path, help="Path to .ld telemetry file")
    group.add_argument("--session-id", help="Re-run analysis on an already-ingested session")
    group.add_argument("--list", action="store_true", help="List all ingested sessions")

    parser.add_argument(
        "--output", type=Path, default=None,
        help="Output path for dashboard.json (default: dashboard/public/dashboard.json)"
    )
    parser.add_argument(
        "--no-agents", action="store_true",
        help="Skip AI agent pipeline (export data-only dashboard)"
    )
    args = parser.parse_args()

    from config import config

    # ------------------------------------------------------------------ List
    if args.list:
        from pitwall.server import list_sessions
        sessions = list_sessions()
        if not sessions:
            print("No sessions ingested yet.")
            return
        print(f"{'Session ID':<25}  {'Car':<20}  {'Best Lap':<12}  {'Laps'}")
        print("-" * 70)
        for s in sessions:
            print(f"{s['session_id']:<25}  {s['car']:<20}  "
                  f"{_fmt_ms(s['fastest_time_ms']):<12}  {s['lap_count']}")
        return

    # -------------------------------------------- Determine session_id
    session_id = args.session_id

    if args.ld_file:
        if not args.ld_file.exists():
            log.error("File not found: %s", args.ld_file)
            sys.exit(1)

        log.info("Step 1/3: Ingesting %s...", args.ld_file.name)
        from pitwall.ingest import ingest, derive_session_id
        session_id = ingest(args.ld_file)
        log.info("  Ingested: %s", session_id)

    if session_id is None:
        parser.print_help()
        sys.exit(1)

    # -------------------------------------------- Export (data only first)
    log.info("Step 2/3: Exporting base dashboard...")
    from pitwall.export import export, _build_corner_summary, _fetch_lap_telemetry
    from pitwall.track import get_corners
    import sqlite3

    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row

    session_row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    session = dict(session_row) if session_row else {}

    laps_rows = conn.execute(
        "SELECT * FROM laps WHERE session_id = ? ORDER BY lap_number", (session_id,)
    ).fetchall()
    laps = [dict(r) for r in laps_rows]

    best_lap = next((l for l in laps if l["is_best"]), None)
    ref_lap  = next((l for l in laps if l["is_reference"]), None)
    if ref_lap is None:
        candidates = [l for l in laps if l["is_valid"] and not l["is_best"] and l["lap_time_ms"]]
        if candidates:
            ref_lap = min(candidates, key=lambda l: l["lap_time_ms"])

    corner_summary = []
    if best_lap and ref_lap:
        best_samples = _fetch_lap_telemetry(conn, best_lap["lap_id"])
        ref_samples  = _fetch_lap_telemetry(conn, ref_lap["lap_id"])
        valid_laps_s = [l for l in laps if l["is_valid"]]
        all_valid_samples = [_fetch_lap_telemetry(conn, l["lap_id"]) for l in valid_laps_s]
        corners = get_corners(session.get("track", ""), config.ac_root, all_valid_samples)
        corner_summary = _build_corner_summary(best_samples, ref_samples, corners)

    conn.close()

    # Write data-only dashboard first (so UI shows data while agents run)
    out_path = export(session_id, args.output)
    log.info("  Dashboard written: %s", out_path)

    if args.no_agents:
        print(f"\nDone (data-only). Open http://localhost:5173")
        return

    # -------------------------------------------- Run agent pipeline
    log.info("Step 3/3: Running AI analysis pipeline...")

    if not config.anthropic_api_key or config.anthropic_api_key.startswith("your_"):
        log.error("ANTHROPIC_API_KEY is not set in .env -- skipping agent pipeline.")
        log.error("Set the key and rerun, or use --no-agents to export data only.")
        sys.exit(1)

    from pitwall.orchestrator import orchestrate
    coaching_report = orchestrate(session_id, corner_summary)

    # Write final dashboard with coaching report
    out_path = export(session_id, args.output, coaching_report=coaching_report)
    log.info("  Final dashboard written: %s", out_path)

    # Print summary
    best_time = _fmt_ms(best_lap["lap_time_ms"]) if best_lap else "N/A"
    print(f"\n{'=' * 50}")
    print(f"  Session:   {session_id}")
    print(f"  Best lap:  {best_time}")
    print(f"  Dashboard: {out_path}")
    print(f"  Open:      http://localhost:5173")
    print(f"{'=' * 50}\n")


if __name__ == "__main__":
    main()
