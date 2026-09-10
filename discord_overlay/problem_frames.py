"""Save the captured region whenever OCR produced a line the parser could not use.

Turned on from Settings, this writes ``problem-frames/<time>_<n>.png`` (the exact
pixels handed to OCR) and a matching ``.txt`` listing every line read from that
frame, its confidence, and why it was flagged. Looking at the pixels is the only
way to tell a bad capture (overlap, fade, tearing) from a parser gap.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

from .models import CombatEvent, OCRLine
from .parser import is_fused_line

MAX_FILES = 300          # keep the folder bounded; oldest are not pruned, saving just stops
MIN_INTERVAL = 0.5       # seconds between saves, so a bad minute does not write hundreds of frames
_DIGIT = re.compile(r"\d")
_ZERO_AMOUNT = re.compile(r"\bfor\s+0\s+p", re.IGNORECASE)


def problem_reason(line: OCRLine, event: CombatEvent | None) -> str | None:
    """Why this line counts as a problem, or None when it is fine."""
    text = line.text
    if is_fused_line(text):
        return "two messages fused into one line"
    if not _DIGIT.search(text):
        return None  # flavour text carries no amount and is meant to be ignored
    if event is None:
        if _ZERO_AMOUNT.search(text):
            return None  # "hits Nitwit for 0 points of damage." is a real message with nothing to count
        return "numbered line did not parse"
    if event.actor == "Unknown" or event.target == "Unknown":
        return "actor or target unreadable"
    return None


class ProblemFrameSaver:
    def __init__(self, directory: Path, max_files: int = MAX_FILES, min_interval: float = MIN_INTERVAL) -> None:
        self.directory = directory
        self.max_files = max_files
        self.min_interval = min_interval
        self.saved = 0
        self._last_saved_at = 0.0
        self._pending: list[tuple[OCRLine, str]] = []

    def note(self, line: OCRLine, event: CombatEvent | None) -> None:
        """Record a line from the current frame; call ``flush`` once the frame is done."""
        reason = problem_reason(line, event)
        if reason:
            self._pending.append((line, reason))

    def flush(self, frame, all_lines: list[OCRLine], now: float | None = None) -> Path | None:
        """Write the frame if any noted line was a problem. Returns the PNG path or None."""
        flagged, self._pending = self._pending, []
        if not flagged or frame is None:
            return None
        now = time.monotonic() if now is None else now
        if self.saved >= self.max_files or now - self._last_saved_at < self.min_interval:
            return None
        import cv2  # local import keeps this module importable without OpenCV in tests

        self.directory.mkdir(parents=True, exist_ok=True)
        self.saved += 1
        self._last_saved_at = now
        stem = f"{datetime.now():%Y%m%d_%H%M%S}_{self.saved:03d}"
        png = self.directory / f"{stem}.png"
        cv2.imwrite(str(png), frame)
        report = [f"frame {stem}  ({frame.shape[1]}x{frame.shape[0]} px)", "", "flagged:"]
        report += [f"  [{reason}] conf={line.confidence:.2f}  {line.text}" for line, reason in flagged]
        report += ["", "every line read from this frame (top to bottom):"]
        report += [f"  y={line.y:6.1f} conf={line.confidence:.2f}  {line.text}" for line in all_lines]
        (self.directory / f"{stem}.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
        return png
