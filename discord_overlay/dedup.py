"""Find newly appended chat lines across successive OCR passes."""
from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from math import ceil

from .models import OCRLine

RECENT_KEYS = 80
SIMILARITY = 0.94
OVERLAP_RATIO = 0.85


def line_key(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", text.casefold())
    return re.sub(r"\s+", " ", text).strip()


def _similar(a: str, b: str) -> bool:
    ka, kb = line_key(a), line_key(b)
    if not ka or not kb:
        return False
    # Combat lines often differ only by the target name, so the threshold stays
    # tight: tolerate isolated OCR jitter, not a different mob.
    return ka == kb or SequenceMatcher(None, ka, kb).ratio() >= SIMILARITY


class ScrollingTextDeduplicator:
    """Track a scrolling viewport and report only the lines that were appended."""

    def __init__(self) -> None:
        self.previous: list[OCRLine] = []
        self.recent_keys: list[str] = []
        self.primed = False

    def reset(self) -> None:
        self.previous.clear()
        self.recent_keys.clear()
        self.primed = False

    def new_lines(self, current: list[OCRLine]) -> list[OCRLine]:
        if not current:
            return []
        if not self.primed:
            # The first viewport has unknown timestamps; use it only as a baseline.
            self.previous = current
            self.recent_keys = [key for line in current if (key := line_key(line.text))][-RECENT_KEYS:]
            self.primed = True
            return []

        previous = self.previous
        overlap = self._overlap(previous, current)
        candidates = current[overlap:] if overlap else current
        old_counts = Counter(line_key(line.text) for line in previous)
        extra_counts = Counter(line_key(line.text) for line in current) - old_counts
        fresh: list[OCRLine] = []
        for line in candidates:
            key = line_key(line.text)
            if not key:
                continue
            if old_counts[key]:
                if extra_counts[key] <= 0:
                    continue  # a still-visible old line that slipped past the overlap
                extra_counts[key] -= 1
            elif not overlap and key in self.recent_keys:
                continue  # no reliable overlap; recent keys are the only evidence
            fresh.append(line)
        self.previous = current

        self.recent_keys.extend(key for line in fresh if (key := line_key(line.text)))
        del self.recent_keys[:-RECENT_KEYS]
        return fresh

    @staticmethod
    def _overlap(previous: list[OCRLine], current: list[OCRLine]) -> int:
        """Rows at the top of ``current`` that repeat the bottom of ``previous``."""
        for size in range(min(len(previous), len(current)), 0, -1):
            matches = [_similar(a.text, b.text) for a, b in zip(previous[-size:], current[:size])]
            # Both boundary rows must match, otherwise a viewport with one new
            # bottom line is mistaken for a complete overlap.
            if matches[0] and matches[-1] and sum(matches) >= max(1, ceil(size * OVERLAP_RATIO)):
                return size
        # A static window keeps its prefix and appends at the bottom.
        prefix = 0
        for a, b in zip(previous, current):
            if not _similar(a.text, b.text):
                break
            prefix += 1
        return prefix
