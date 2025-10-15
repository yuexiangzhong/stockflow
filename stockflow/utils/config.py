from dataclasses import dataclass
from pathlib import Path
import yaml
from typing import Any, Dict, Optional

@dataclass
class AppConfig:
    app_name: str
    database_path: str
    features: Dict[str, Any]
    security: Dict[str, Any]
    paths: Dict[str, Any]
    logging: Optional[Dict[str, Any]] = None

def _with_defaults(data: dict) -> dict:
    # 基本默认
    data.setdefault("app_name", "StockFlow")
    data.setdefault("database_path", "./data/stockflow.db")
    data.setdefault("features", {})

    # security 默认
    sec = data.setdefault("security", {})
    sec.setdefault("secret_key", "CHANGE_ME_TO_A_RANDOM_LONG_STRING")
    sec.setdefault("access_token_minutes", 30)
    sec.setdefault("refresh_token_days", 14)
    sec.setdefault("cookie_name", "sf_session")

    # paths 默认
    paths = data.setdefault("paths", {})
    paths.setdefault("event_log_dir", "./logs")
    paths.setdefault("snapshots_dir", "./snapshots")
    paths.setdefault("backups_dir", "./backups")

    # logging 可选
    log = data.setdefault("logging", {})
    log.setdefault("level", "INFO")

    # 确保数据库目录存在
    db_path = Path(data["database_path"])
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # 确保路径目录存在
    Path(paths["event_log_dir"]).mkdir(parents=True, exist_ok=True)
    Path(paths["snapshots_dir"]).mkdir(parents=True, exist_ok=True)
    Path(paths["backups_dir"]).mkdir(parents=True, exist_ok=True)

    return data

def load_config(path: str = "config.yaml") -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data = _with_defaults(data)
    return AppConfig(**data)
