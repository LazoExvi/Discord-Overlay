"""Screen capture. Reads pixels only; never touches the game process."""
from __future__ import annotations

import re

import threading

import numpy as np

from .models import Region


class ScreenCapture:
    """Thread-local MSS capture returning BGR frames."""

    def __init__(self) -> None:
        self._local = threading.local()

    def _instance(self):
        if not hasattr(self._local, "sct"):
            import mss

            self._local.sct = mss.mss()
        return self._local.sct

    def grab(self, region: Region) -> np.ndarray:
        shot = self._instance().grab(region.as_mss())
        return np.asarray(shot, dtype=np.uint8)[:, :, :3].copy()


def monitor_rects() -> list[dict[str, int]]:
    """Physical monitors in the same coordinate system used by ``ScreenCapture``."""
    import mss

    with mss.mss() as capture:
        return [dict(monitor) for monitor in capture.monitors[1:]]


def region_on_screen(region: Region) -> bool:
    """True when the whole rectangle lies inside one physical monitor."""
    monitor = monitor_containing(region.left + region.width // 2, region.top + region.height // 2)
    if monitor is None:
        return False
    return (region.left >= monitor["left"] and region.top >= monitor["top"]
            and region.left + region.width <= monitor["left"] + monitor["width"]
            and region.top + region.height <= monitor["top"] + monitor["height"])


def tk_geometry(width: int, height: int, x: int, y: int) -> str:
    """A Tk geometry string that also works left of or above the primary monitor.

    ``-2560-139`` means "2560 px from the right edge" to Tk; a negative desktop
    coordinate must be written ``+-2560+-139``.
    """
    return f"{width}x{height}+{x}+{y}"


_GEOMETRY = re.compile(r"(\d+)x(\d+)\+?(-?\d+)\+?(-?\d+)")


def parse_geometry(geometry: str) -> tuple[int, int, int, int] | None:
    """``340x230+-2560+-139`` -> (340, 230, -2560, -139); None when malformed."""
    match = _GEOMETRY.fullmatch(geometry.strip()) if geometry else None
    if not match:
        return None
    return tuple(int(group) for group in match.groups())  # type: ignore[return-value]


def geometry_on_screen(geometry: str) -> bool:
    """True when a saved window position still shows enough of the window to grab.

    After a monitor swap the old coordinates can point past every display; such a
    window would open invisibly and could never be dragged back.
    """
    parsed = parse_geometry(geometry)
    if not parsed:
        return False
    width, height, x, y = parsed
    try:
        monitors = monitor_rects()
    except Exception:  # noqa: BLE001 - without monitor data, trust the saved position
        return True
    if not monitors:
        return True
    probe_x, probe_y = x + min(width, 80) // 2, y + min(height, 40) // 2
    return any(m["left"] <= probe_x < m["left"] + m["width"] and m["top"] <= probe_y < m["top"] + m["height"]
               for m in monitors)


def monitor_containing(x: int, y: int) -> dict[str, int] | None:
    for monitor in monitor_rects():
        if (monitor["left"] <= x < monitor["left"] + monitor["width"]
                and monitor["top"] <= y < monitor["top"] + monitor["height"]):
            return monitor
    return None
