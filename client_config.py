"""Per-user multiplayer settings and data paths."""

import json
import os
import sys
from pathlib import Path


APP_DIRECTORY = "CommanderOleHagersGlade"
DEFAULT_SERVER_LIST_URL = "https://commander-glade.duckdns.org/servers.json"


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def user_data_directory():
    if sys.platform == "win32":
        root = os.getenv("APPDATA")
        base = Path(root) if root else Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        root = os.getenv("XDG_CONFIG_HOME")
        base = Path(root) if root else Path.home() / ".config"
    return base / APP_DIRECTORY


def load_config():
    path = user_data_directory() / "client.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["SERVER_LIST_URL"] = (
        os.getenv("SERVER_LIST_URL")
        or data.get("SERVER_LIST_URL")
        or DEFAULT_SERVER_LIST_URL
    )
    data["DEV_ALLOW_IP"] = os.getenv(
        "DEV_ALLOW_IP", data.get("DEV_ALLOW_IP", False)
    )
    data["DEV_ALLOW_IP"] = _as_bool(data["DEV_ALLOW_IP"])
    return data


def save_config(config):
    path = user_data_directory() / "client.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(config, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
