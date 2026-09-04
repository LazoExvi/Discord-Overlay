"""Create Start Menu and desktop shortcuts so a portable install feels installed."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import APP_NAME

SHORTCUT_NAME = f"{APP_NAME}.lnk"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def launch_target() -> tuple[str, str]:
    """(program, arguments) a shortcut should run to start this app."""
    if is_frozen():
        return sys.executable, ""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    program = str(pythonw if pythonw.exists() else sys.executable)
    main_script = Path(__file__).resolve().parents[1] / "main.py"
    return program, f'"{main_script}"'


def start_menu_dir() -> Path:
    base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def desktop_dir() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


def shortcut_exists(directory: Path) -> bool:
    return (directory / SHORTCUT_NAME).is_file()


def create_shortcut(directory: Path) -> Path:
    """Write ``Discord Overlay.lnk`` into ``directory`` pointing at this installation."""
    if sys.platform != "win32":
        raise OSError("Shortcuts are only supported on Windows.")
    program, arguments = launch_target()
    directory.mkdir(parents=True, exist_ok=True)
    link = directory / SHORTCUT_NAME
    icon = Path(program) if is_frozen() else Path(__file__).with_name("assets") / "icon.ico"
    script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$s = $shell.CreateShortcut('{_ps(str(link))}'); "
        f"$s.TargetPath = '{_ps(program)}'; "
        f"$s.Arguments = '{_ps(arguments)}'; "
        f"$s.WorkingDirectory = '{_ps(str(Path(program).parent))}'; "
        f"$s.IconLocation = '{_ps(str(icon))},0'; "
        f"$s.Description = '{APP_NAME}'; "
        "$s.Save()"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=30, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0 or not link.is_file():
        raise OSError(result.stderr.strip() or "Windows did not create the shortcut.")
    return link


def remove_shortcut(directory: Path) -> bool:
    link = directory / SHORTCUT_NAME
    if link.is_file():
        link.unlink()
        return True
    return False


def _ps(value: str) -> str:
    return value.replace("'", "''")
