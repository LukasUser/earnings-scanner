from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines; existing environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


@dataclass
class Config:
    raw: dict = field(default_factory=dict)
    root: Path = ROOT

    @property
    def db_path(self) -> Path:
        return self.root / "data" / "earnings.db"

    @property
    def cache_dir(self) -> Path:
        return self.root / "data" / "cache"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    def get(self, section: str, key: str, default=None):
        return self.raw.get(section, {}).get(key, default)

    @property
    def anthropic_api_key(self) -> str | None:
        return os.environ.get("ANTHROPIC_API_KEY") or None

    @property
    def sec_user_agent(self) -> str:
        # SEC rejects anonymous clients; a generic placeholder works but a real contact is requested.
        return os.environ.get("SEC_USER_AGENT") or "earnings-scanner/0.1 admin@example.com"


def load_config(path: Path | None = None) -> Config:
    load_dotenv(ROOT / ".env")
    path = path or ROOT / "config.toml"
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    cfg = Config(raw=raw)
    for d in (cfg.db_path.parent, cfg.cache_dir, cfg.reports_dir, cfg.logs_dir):
        d.mkdir(parents=True, exist_ok=True)
    return cfg
