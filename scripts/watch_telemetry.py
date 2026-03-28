"""
watch_telemetry.py — watches TELEMETRY_EXPORT_DIR for new .ld files
and automatically ingests + exports dashboard.json.

Usage:
    python scripts/watch_telemetry.py

Requires: pip install watchdog
Leave running between sessions — when Telemetrick drops a new .ld file
it will be ingested and dashboard.json refreshed automatically.
"""

import logging
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
from config import config  # noqa: E402
from pitwall.ingest import ingest  # noqa: E402
from pitwall.export import export  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("watchdog not installed. Run: pip install watchdog")
    sys.exit(1)


class TelemetryHandler(FileSystemEventHandler):
    def __init__(self):
        self._pending: set[Path] = set()

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() == ".ld":
            # Wait briefly for the matching .ldx to be written alongside it
            log.info("New .ld file detected: %s", path.name)
            self._pending.add(path)

    def on_modified(self, event):
        # Sometimes a create fires as modified — handle the same way
        if not event.is_directory:
            path = Path(event.src_path)
            if path.suffix.lower() == ".ld":
                self._pending.add(path)

    def process_pending(self):
        if not self._pending:
            return
        to_process = list(self._pending)
        self._pending.clear()

        for ld_path in to_process:
            ldx_path = ld_path.with_suffix(".ldx")
            if not ldx_path.exists():
                log.info("Waiting for .ldx sidecar: %s", ldx_path.name)
                self._pending.add(ld_path)  # retry next cycle
                continue

            try:
                session_id = ingest(ld_path)
                log.info("Ingested session: %s", session_id)
                out = export(session_id)
                log.info("Dashboard updated: %s", out)
                print(f"\n✓ New session ready: {session_id} — open http://localhost:5173\n")
            except Exception as e:
                log.error("Failed to ingest %s: %s", ld_path.name, e)


def main():
    if config.telemetry_export_dir is None:
        print("TELEMETRY_EXPORT_DIR is not set in .env — nothing to watch.")
        sys.exit(1)

    watch_dir = config.telemetry_export_dir
    if not watch_dir.exists():
        print(f"Watch directory does not exist: {watch_dir}")
        sys.exit(1)

    log.info("Watching: %s", watch_dir)
    log.info("Press Ctrl+C to stop.")

    handler = TelemetryHandler()
    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(3)
            handler.process_pending()
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
