"""环境配置加载"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Settings:
    base_dir: Path = BASE_DIR
    data_dir: Path = BASE_DIR / "data"
    app_host: str = os.environ.get("APP_HOST", "0.0.0.0").strip()
    app_port: int = _int("APP_PORT", 7650)
    db_path: str = (
        os.environ.get("LOGISTICS_DB_PATH", "").strip()
        or str(BASE_DIR / "data" / "logistics.db")
    )
    arrival_offset_days: int = _int("ARRIVAL_OFFSET_DAYS", 14)
    api_token: str = os.environ.get("API_TOKEN", "").strip()
    push_token: str = os.environ.get("PUSH_TOKEN", "").strip()


settings = Settings()
