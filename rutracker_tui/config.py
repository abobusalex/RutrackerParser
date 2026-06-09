from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


APP_NAME = "rutracker-tui"
BASE_URL = "https://rutracker.org/forum/"


def app_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_data_dir() -> Path:
    return app_root() / "data"


def default_db_path() -> Path:
    return default_data_dir() / "rutracker.sqlite3"


@dataclass(frozen=True)
class AppConfig:
    db_path: Path = default_db_path()
    base_url: str = BASE_URL
    request_timeout: float = 30.0
    user_agent: str = (
        "Mozilla/5.0 (compatible; RutrackerTUI/0.1; "
        "+https://github.com/local/rutracker-tui)"
    )
