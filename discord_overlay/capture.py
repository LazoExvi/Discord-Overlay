"""Screen capture. Reads pixels only; never touches the game process."""
from __future__ import annotations

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


def monitor_containing(x: int, y: int) -> dict[str, int] | None:
    for monitor in monitor_rects():
        if (monitor["left"] <= x < monitor["left"] + monitor["width"]
                and monitor["top"] <= y < monitor["top"] + monitor["height"]):
            return monitor
    return None
