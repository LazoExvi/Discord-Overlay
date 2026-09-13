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
    """The real Desktop folder, which OneDrive often redirects away from %USERPROFILE%\\Desktop."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            folder_id = (ctypes.c_ubyte * 16).from_buffer_copy(
                b"\x3a\xcc\xbf\xb8\x5c\xdc\x4d\x43\xb2\x9e\x7f\xe9\x9a\x87\xc6\x41")  # FOLDERID_Desktop
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(folder_id, 0, None, ctypes.byref(out)) == 0 and out.value:
                path = Path(out.value)
                ctypes.windll.ole32.CoTaskMemFree(out)
                return path
        except Exception:  # noqa: BLE001 - fall back to the conventional location
            pass
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


def all_shortcuts() -> list[Path]:
    """Every ``Discord Overlay.lnk`` a user might click: Start Menu (any subfolder) and Desktop."""
    found: list[Path] = []
    start_menu = start_menu_dir()
    if start_menu.is_dir():
        found.extend(sorted(start_menu.rglob(SHORTCUT_NAME)))
    desktops = {desktop_dir(), Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"}
    if os.environ.get("OneDrive"):
        desktops.add(Path(os.environ["OneDrive"]) / "Desktop")
    for desktop in sorted(desktops):
        desktop_link = desktop / SHORTCUT_NAME
        if desktop_link.is_file():
            found.append(desktop_link)
    return found


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


def shortcut_target(directory: Path) -> str | None:
    """The program an existing shortcut launches, or None if there is no shortcut."""
    return link_target(directory / SHORTCUT_NAME)


def link_target(link: Path) -> str | None:
    if sys.platform != "win32" or not link.is_file():
        return None
    script = ("$shell = New-Object -ComObject WScript.Shell; "
              f"$shell.CreateShortcut('{_ps(str(link))}').TargetPath")
    result = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=30, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def repair_shortcuts() -> list[Path]:
    """After the program moved (a new version extracted elsewhere), repoint existing shortcuts."""
    if not is_frozen():
        return []
    program = launch_target()[0]
    repaired = []
    for link in all_shortcuts():
        target = link_target(link)
        if target and os.path.normcase(target) != os.path.normcase(program):
            try:
                repaired.append(create_shortcut(link.parent))
            except OSError:
                pass
    return repaired


def stale_installs() -> list[Path]:
    """Older copies of the app that shortcuts or muscle memory might still launch."""
    program = Path(launch_target()[0])
    candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "DiscordOverlay" / "DiscordOverlay.exe"]
    return [c for c in candidates if c.is_file() and os.path.normcase(str(c)) != os.path.normcase(str(program))]


def remove_shortcut(directory: Path) -> bool:
    link = directory / SHORTCUT_NAME
    if link.is_file():
        link.unlink()
        return True
    return False


def _ps(value: str) -> str:
    return value.replace("'", "''")
