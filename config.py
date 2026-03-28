"""
PitWall configuration — loads from .env, exposes a typed PitWallConfig dataclass.
Import config from here; never read os.environ directly elsewhere.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — rely on shell environment


@dataclass
class PitWallConfig:
    anthropic_api_key: str
    claude_model: str
    db_path: Path
    data_dir: Path
    telemetry_export_dir: Path | None
    ac_root: Path | None
    valid_lap_min_ms: int
    valid_lap_max_ms: int

    def __repr__(self) -> str:
        key_preview = self.anthropic_api_key[:8] + "..." if self.anthropic_api_key else "NOT SET"
        return (
            f"PitWallConfig(api_key={key_preview}, model={self.claude_model}, "
            f"db={self.db_path}, telemetry_dir={self.telemetry_export_dir}, ac_root={self.ac_root})"
        )


def load_config() -> PitWallConfig:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )

    def _optional_path(key: str) -> Path | None:
        raw = os.environ.get(key, "").strip()
        return Path(raw) if raw else None

    return PitWallConfig(
        anthropic_api_key=api_key,
        claude_model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
        db_path=Path(os.environ.get("PITWALL_DB_PATH", "db/pitwall.db")),
        data_dir=Path(os.environ.get("PITWALL_DATA_DIR", "data/sessions")),
        telemetry_export_dir=_optional_path("TELEMETRY_EXPORT_DIR"),
        ac_root=_optional_path("AC_ROOT"),
        valid_lap_min_ms=int(os.environ.get("PITWALL_VALID_LAP_MIN_MS", "30000")),
        valid_lap_max_ms=int(os.environ.get("PITWALL_VALID_LAP_MAX_MS", "120000")),
    )


# Module-level singleton — import this everywhere
config = load_config()
