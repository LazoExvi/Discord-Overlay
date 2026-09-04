"""Where Discord Overlay keeps its settings, data, and diagnostics."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

APP_DIR_NAME = "DiscordOverlay"


def _local_app_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home()))


def app_root() -> Path:
    return _local_app_data() / APP_DIR_NAME


def config_dir() -> Path:
    return app_root() / "config"


def settings_path() -> Path:
    return config_dir() / "settings.json"


def data_dir() -> Path:
    return app_root() / "data"


def sounds_dir() -> Path:
    return data_dir() / "sounds"


def templates_dir() -> Path:
    """Per-character grammar templates learned for cursor-occlusion repair."""
    return data_dir() / "templates"


def debug_scans_dir() -> Path:
    return data_dir() / "debug-scans"


def trigger_packs_dir() -> Path:
    return app_root() / "trigger-packs"


def diagnostics_dir() -> Path:
    return app_root() / "diagnostics"


def temp_dir() -> Path:
    return Path(tempfile.gettempdir()) / APP_DIR_NAME


def character_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "default"


def template_path_for(character: str) -> Path:
    return templates_dir() / f"{character_slug(character)}.json"


def ensure_app_directories() -> None:
    for directory in (
        config_dir(), data_dir(), sounds_dir(), templates_dir(), trigger_packs_dir(),
        diagnostics_dir(), temp_dir(),
    ):
        directory.mkdir(parents=True, exist_ok=True)
