from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir


APP_NAME = "rutracker-tui"
BASE_URL = "https://rutracker.org/forum/"


def default_data_dir() -> Path:
    return Path(user_data_dir(APP_NAME, appauthor=False))


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
