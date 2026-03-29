"""
ingest.py — parse a MoTeC .ld file (via ldparser) into the PitWall SQLite database.

Usage:
    python pitwall/ingest.py path/to/session.ld

The matching .ldx file must be in the same directory (same stem, .ldx extension).
"""

import logging
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

# ldparser is cloned into the project root — not on PyPI
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "ldparser"))
import ldparser  # noqa: E402

from config import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id          TEXT PRIMARY KEY,
    car                 TEXT NOT NULL,
    track               TEXT NOT NULL,
    date                TEXT NOT NULL,
    driver              TEXT NOT NULL,
    fastest_lap         INTEGER,
    fastest_time_ms     INTEGER,
    sector_count        INTEGER DEFAULT 2,
    sector_boundary_m   REAL,
    venue_length_m      REAL,
    coaching_report_json TEXT
);

CREATE TABLE IF NOT EXISTS laps (
    lap_id          TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    lap_number      INTEGER NOT NULL,
    lap_time_ms     INTEGER,
    is_valid        BOOLEAN NOT NULL DEFAULT 0,
    is_best         BOOLEAN NOT NULL DEFAULT 0,
    is_reference    BOOLEAN NOT NULL DEFAULT 0,
    is_synthetic    BOOLEAN NOT NULL DEFAULT 0,
    s1_ms           INTEGER,
    s2_ms           INTEGER,
    s3_ms           INTEGER,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS telemetry (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lap_id          TEXT NOT NULL,
    sample_index    INTEGER NOT NULL,
    lap_distance_m  REAL NOT NULL,
    car_pos_norm    REAL,
    speed_kph       REAL,
    throttle_pct    REAL,
    brake_pct       REAL,
    steering_deg    REAL,
    gear            INTEGER,
    rpm             INTEGER,
    lat_g           REAL,
    long_g          REAL,
    slip_fl         REAL,
    slip_fr         REAL,
    slip_rl         REAL,
    slip_rr         REAL,
    FOREIGN KEY (lap_id) REFERENCES laps(lap_id)
);

CREATE INDEX IF NOT EXISTS idx_telemetry_lap_id       ON telemetry(lap_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_lap_distance ON telemetry(lap_id, lap_distance_m);
CREATE INDEX IF NOT EXISTS idx_laps_session           ON laps(session_id);
"""



# ---------------------------------------------------------------------------
# .ldx metadata parser
# ---------------------------------------------------------------------------

def parse_ldx(ldx_path: Path) -> dict:
    """Parse the .ldx XML sidecar and return a metadata dict."""
    tree = ET.parse(ldx_path)
    root = tree.getroot()
    details = root.find(".//Details")

    def get_string(id_: str) -> str:
        el = details.find(f"String[@Id='{id_}']")
        return el.attrib.get("Value", "") if el is not None else ""

    def get_numeric(id_: str) -> float | None:
        el = details.find(f"Numeric[@Id='{id_}']")
        if el is None:
            return None
        try:
            return float(el.attrib["Value"])
        except (KeyError, ValueError):
            return None

    fastest_time_str = get_string("Fastest Time")  # e.g. "1:06.693"
    fastest_time_ms = _time_str_to_ms(fastest_time_str)

    vehicle_desc = get_string("Vehicle Desc")

    gear_ratios = []
    for i in range(1, 11):
        v = get_numeric(f"Gear {i}")
        if v and v > 0:
            gear_ratios.append(round(v, 4))

    return {
        "total_laps": int(get_string("Total Laps") or 0),
        "fastest_time_ms": fastest_time_ms,
        "fastest_lap": int(get_string("Fastest Lap") or 0),  # 1-indexed
        "venue_length_m": get_numeric("Venue Length"),
        "vehicle_weight_kg": get_numeric("Vehicle Weight"),
        "vehicle_desc": vehicle_desc,
        "max_rpm": None,  # stored in MathItems, not Details
        "gear_ratios": gear_ratios,
        "input_mode": get_string("InputMode"),
        "app_name": get_string("AppName"),
    }


def _time_str_to_ms(s: str) -> int | None:
    """Convert '1:06.693' to milliseconds (66693)."""
    s = s.strip()
    m = re.match(r"^(\d+):(\d+)\.(\d+)$", s)
    if not m:
        return None
    minutes, seconds, frac = int(m.group(1)), int(m.group(2)), m.group(3)
    ms = (minutes * 60 + seconds) * 1000 + int(frac.ljust(3, "0")[:3])
    return ms


# ---------------------------------------------------------------------------
# Session ID derivation
# ---------------------------------------------------------------------------

def derive_session_id(ld_path: Path) -> str:
    """
    Derive a session ID from the filename.
    '28032026-152157-DriverName-abarth500-ks_vallelungaclub_circuit.ld'
    → '28032026-152157'
    """
    stem = ld_path.stem
    parts = stem.split("-")
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    return stem


def parse_filename(ld_path: Path) -> dict:
    """
    Extract driver, car, track from the filename convention:
    DDMMYYYY-HHMMSS-<driver>-<car>-<track>.ld
    """
    stem = ld_path.stem
    parts = stem.split("-")
    if len(parts) >= 5:
        return {
            "date_str": parts[0],
            "time_str": parts[1],
            "driver": parts[2],
            "car": parts[3],
            "track": "-".join(parts[4:]),
        }
    return {"date_str": "", "time_str": "", "driver": "unknown", "car": "unknown", "track": "unknown"}


# ---------------------------------------------------------------------------
# Channel helpers
# ---------------------------------------------------------------------------

def get_channel(ld: ldparser.ldData, name: str) -> np.ndarray | None:
    """Return channel data array by name, or None if not present."""
    for ch in ld.channs:
        if ch.name == name:
            return np.array(ch.data, dtype=float)
    log.warning("Channel '%s' not found in .ld file", name)
    return None


def align_to_30hz(data_high: np.ndarray, high_freq: int, n_samples_30hz: int) -> np.ndarray:
    """
    Downsample/interpolate a higher-frequency channel to align with 30Hz samples.
    Uses linear interpolation over a shared time axis.
    """
    t_30 = np.arange(n_samples_30hz) / 30.0
    t_high = np.arange(len(data_high)) / float(high_freq)
    return np.interp(t_30, t_high, data_high)


def align_to_30hz_from_channel(ld: ldparser.ldData, name: str, n_30hz: int) -> np.ndarray | None:
    """Fetch a channel by name and align it to 30Hz."""
    for ch in ld.channs:
        if ch.name == name:
            data = np.array(ch.data, dtype=float)
            if ch.freq == 30:
                return data
            return align_to_30hz(data, ch.freq, n_30hz)
    log.warning("Channel '%s' not found — will store NULL", name)
    return None


# ---------------------------------------------------------------------------
# Lap segmentation
# ---------------------------------------------------------------------------

def segment_laps(lap_number_ch: np.ndarray) -> list[tuple[int, np.ndarray]]:
    """
    Return list of (lap_number_0indexed, boolean_mask) for each distinct lap.
    Lap numbers in the channel are 0-indexed.
    """
    unique_laps = sorted(np.unique(lap_number_ch).astype(int))
    return [(n, lap_number_ch == n) for n in unique_laps]


def compute_lap_time_ms(lap_time_ch: np.ndarray, mask: np.ndarray) -> int:
    """Lap time = max of the Lap Time channel within this lap (cumulative timer)."""
    lap_times = lap_time_ch[mask]
    if len(lap_times) == 0:
        return 0
    return int(round(float(lap_times.max()) * 1000))


def compute_sector_time(lap_distance_ch: np.ndarray, lap_time_ch: np.ndarray,
                         mask: np.ndarray, boundary_m: float) -> tuple[int | None, int | None]:
    """
    Compute S1 and S2 times given a distance boundary.
    S1 ends at first sample where lap_distance >= boundary_m.
    Returns (s1_ms, s2_ms) or (None, None) if boundary not found.
    """
    dist = lap_distance_ch[mask]
    times = lap_time_ch[mask]
    if len(dist) == 0:
        return None, None

    crossing = np.where(dist >= boundary_m)[0]
    if len(crossing) == 0:
        return None, None

    s1_time_s = float(times[crossing[0]])
    lap_total_s = float(times.max())
    s1_ms = int(round(s1_time_s * 1000))
    s2_ms = int(round((lap_total_s - s1_time_s) * 1000))
    return s1_ms, s2_ms


def check_lap_invalid(ld: ldparser.ldData, lap_mask_30hz: np.ndarray) -> bool:
    """
    Check the Lap Invalidated channel (1Hz). Returns True if this lap was invalidated.
    Maps 30Hz sample indices to 1Hz indices by integer division.
    """
    inv_ch = None
    for ch in ld.channs:
        if ch.name == "Lap Invalidated":
            inv_ch = ch
            break
    if inv_ch is None:
        return False  # channel not present — assume valid

    inv_data = np.array(inv_ch.data, dtype=float)
    indices_30hz = np.where(lap_mask_30hz)[0]
    if len(indices_30hz) == 0:
        return True
    # Map to 1Hz indices
    indices_1hz = (indices_30hz / 30.0).astype(int)
    indices_1hz = np.clip(indices_1hz, 0, len(inv_data) - 1)
    return bool(np.any(inv_data[indices_1hz] == 1.0))


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    # Migrations: add columns that were introduced after initial release
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "coaching_report_json" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN coaching_report_json TEXT")
    if "sector_boundary_m" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN sector_boundary_m REAL")
    if "venue_length_m" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN venue_length_m REAL")
    conn.commit()
    log.info("Database ready: %s", db_path)
    return conn


def session_exists(conn: sqlite3.Connection, session_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Main ingest function
# ---------------------------------------------------------------------------

def ingest(ld_path: Path, db_path: Path | None = None) -> str:
    """
    Parse a .ld file and store all laps into SQLite.
    Returns the session_id.
    Raises FileNotFoundError or ValueError on bad input.
    """
    # --- Validate input ---
    ld_path = Path(ld_path).resolve()
    if not ld_path.exists():
        raise FileNotFoundError(f"File not found: {ld_path}")
    if not ld_path.is_file() or ld_path.is_symlink():
        raise ValueError(f"Not a regular file: {ld_path}")
    if ld_path.suffix.lower() != ".ld":
        raise ValueError(f"Expected .ld file, got: {ld_path.suffix}")
    if ld_path.stat().st_size == 0 or ld_path.stat().st_size > 500 * 1024 * 1024:
        raise ValueError(f"File size out of range: {ld_path.stat().st_size} bytes")

    ldx_path = ld_path.with_suffix(".ldx")
    if not ldx_path.exists():
        raise FileNotFoundError(f".ldx sidecar not found: {ldx_path}")

    # --- Derive identifiers ---
    session_id = derive_session_id(ld_path)
    meta = parse_filename(ld_path)
    ldx = parse_ldx(ldx_path)

    # Format date: '28032026' → '2026-03-28'
    ds = meta["date_str"]
    date_fmt = f"{ds[4:]}-{ds[2:4]}-{ds[:2]}" if len(ds) == 8 else ds

    log.info("Ingesting session %s — %s laps, best %dms",
             session_id, ldx["total_laps"], ldx["fastest_time_ms"] or 0)

    # --- Init DB ---
    db_path = Path(db_path or config.db_path)
    conn = init_db(db_path)

    if session_exists(conn, session_id):
        log.info("Session %s already in database — skipping", session_id)
        conn.close()
        return session_id

    # --- Parse .ld ---
    log.info("Parsing %s ...", ld_path.name)
    ld = ldparser.ldData.fromfile(str(ld_path))
    log.info("Loaded %d channels", len(ld.channs))

    # --- Extract 30Hz primary channels ---
    lap_number_ch  = get_channel(ld, "Lap Number")
    lap_distance_ch = get_channel(ld, "Lap Distance")
    lap_time_ch    = get_channel(ld, "Lap Time")
    speed_ch       = get_channel(ld, "Ground Speed")
    throttle_ch    = get_channel(ld, "Throttle Pos")
    brake_ch       = get_channel(ld, "Brake Pos")
    steering_ch    = get_channel(ld, "Steering Angle")
    gear_ch        = get_channel(ld, "Gear")
    rpm_ch         = get_channel(ld, "Engine RPM")

    if lap_number_ch is None or lap_distance_ch is None or lap_time_ch is None:
        raise ValueError("Missing critical channels (Lap Number / Lap Distance / Lap Time)")

    n_30hz = len(lap_number_ch)

    # --- Align higher-frequency channels to 30Hz ---
    lat_g_ch  = align_to_30hz_from_channel(ld, "CG Accel Lateral", n_30hz)
    long_g_ch = align_to_30hz_from_channel(ld, "CG Accel Longitudinal", n_30hz)

    # Car Pos Norm is 10Hz
    car_pos_ch = align_to_30hz_from_channel(ld, "Car Pos Norm", n_30hz)

    # Tire Slip Angles at 30Hz (same rate — no alignment needed)
    slip_fl_ch = get_channel(ld, "Tire Slip Angle FL")
    slip_fr_ch = get_channel(ld, "Tire Slip Angle FR")
    slip_rl_ch = get_channel(ld, "Tire Slip Angle RL")
    slip_rr_ch = get_channel(ld, "Tire Slip Angle RR")

    # --- Insert session ---
    # fastest_lap in .ldx is 1-indexed; store as 1-indexed
    venue_length_m = ldx.get("venue_length_m")
    sector_boundary_m = venue_length_m / 2 if venue_length_m else None

    conn.execute(
        """INSERT INTO sessions
           (session_id, car, track, date, driver, fastest_lap, fastest_time_ms,
            sector_count, sector_boundary_m, venue_length_m)
           VALUES (?, ?, ?, ?, ?, ?, ?, 2, ?, ?)""",
        (session_id, meta["car"], meta["track"], date_fmt, meta["driver"],
         ldx["fastest_lap"], ldx["fastest_time_ms"],
         sector_boundary_m, venue_length_m)
    )

    # --- Dynamic lap validity window ---
    # For long tracks (Nordschleife, Spa), the hardcoded 120s max is too short.
    # Estimate a reasonable max from venue length: ~30 kph minimum average pace.
    valid_max_ms = config.valid_lap_max_ms
    if venue_length_m and venue_length_m > 0:
        estimated_max_ms = int((venue_length_m / 1000) / 30 * 3600 * 1000)  # 30 kph avg
        valid_max_ms = max(valid_max_ms, estimated_max_ms)
        if estimated_max_ms > config.valid_lap_max_ms:
            log.info("Adjusted lap validity max to %dms for %.0fm track",
                     valid_max_ms, venue_length_m)

    # --- Segment and store laps ---
    laps_info = segment_laps(lap_number_ch)
    log.info("Found %d lap segments", len(laps_info))

    for file_pos, (lap_idx, mask) in enumerate(laps_info, start=1):
        # Use file-position (1-indexed) as the lap number.
        # The Lap Number channel may start at a non-zero value between sessions,
        # but .ldx Fastest Lap is always 1-indexed from the first lap in the file.
        lap_number_1indexed = file_pos
        lap_id = f"{session_id}_lap{lap_number_1indexed}"

        lap_time_ms = compute_lap_time_ms(lap_time_ch, mask)
        is_invalid_flag = check_lap_invalid(ld, mask)
        is_valid = (
            not is_invalid_flag
            and config.valid_lap_min_ms <= lap_time_ms <= valid_max_ms
        )
        is_best = (file_pos == ldx["fastest_lap"])

        s1_ms, s2_ms = None, None
        if is_valid and sector_boundary_m:
            s1_ms, s2_ms = compute_sector_time(
                lap_distance_ch, lap_time_ch, mask, sector_boundary_m
            )

        log.info("  Lap %d: %dms  valid=%s  best=%s  s1=%s s2=%s",
                 lap_number_1indexed, lap_time_ms, is_valid, is_best, s1_ms, s2_ms)

        conn.execute(
            """INSERT INTO laps
               (lap_id, session_id, lap_number, lap_time_ms,
                is_valid, is_best, is_reference, is_synthetic,
                s1_ms, s2_ms, s3_ms)
               VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, NULL)""",
            (lap_id, session_id, lap_number_1indexed, lap_time_ms,
             int(is_valid), int(is_best), s1_ms, s2_ms)
        )

        # --- Store telemetry samples ---
        indices = np.where(mask)[0]
        samples = []
        for i, global_idx in enumerate(indices):
            def _val(ch_arr, idx):
                if ch_arr is None:
                    return None
                v = float(ch_arr[idx])
                return None if np.isnan(v) else v

            samples.append((
                lap_id,
                i,  # sample_index within lap
                _val(lap_distance_ch, global_idx),
                _val(car_pos_ch, global_idx),
                _val(speed_ch, global_idx),
                _val(throttle_ch, global_idx),
                _val(brake_ch, global_idx),
                _val(steering_ch, global_idx),
                int(_val(gear_ch, global_idx) or 0),
                int(_val(rpm_ch, global_idx) or 0),
                _val(lat_g_ch, global_idx),
                _val(long_g_ch, global_idx),
                _val(slip_fl_ch, global_idx),
                _val(slip_fr_ch, global_idx),
                _val(slip_rl_ch, global_idx),
                _val(slip_rr_ch, global_idx),
            ))

        conn.executemany(
            """INSERT INTO telemetry
               (lap_id, sample_index, lap_distance_m, car_pos_norm,
                speed_kph, throttle_pct, brake_pct, steering_deg, gear, rpm,
                lat_g, long_g, slip_fl, slip_fr, slip_rl, slip_rr)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            samples
        )
        log.info("    Stored %d telemetry samples for lap %d", len(samples), lap_number_1indexed)

    conn.commit()
    conn.close()
    log.info("Session %s ingested successfully", session_id)
    return session_id


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pitwall/ingest.py path/to/session.ld")
        sys.exit(1)

    ld_file = Path(sys.argv[1])
    try:
        sid = ingest(ld_file)
        print(f"Done. Session ID: {sid}")
    except (FileNotFoundError, ValueError) as e:
        log.error("%s", e)
        sys.exit(1)
