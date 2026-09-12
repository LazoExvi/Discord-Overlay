"""Find newly appended chat lines across successive OCR passes."""
from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from math import ceil

from .models import OCRLine

RECENT_KEYS = 500      # several minutes of history, so a jump or scroll-back cannot replay old lines
SIMILARITY = 0.94
OVERLAP_RATIO = 0.85


_DIGIT_LOOKALIKES = str.maketrans({"o": "0", "i": "1", "l": "1", "s": "5", "b": "8"})
_NUMBER_TOKEN = re.compile(r"\b[0-9oilsb]*[0-9][0-9oilsb]*\b")


def line_key(text: str) -> str:
    """Case-, punctuation-, and digit-jitter-insensitive identity of a chat line.

    OCR may read the same line as ``for 5O points`` on one scan and ``for 50 points``
    on the next; both must map to one key or the second reading counts as a new hit.
    """
    text = re.sub(r"[^a-z0-9]+", " ", text.casefold())
    text = _NUMBER_TOKEN.sub(lambda m: m.group(0).translate(_DIGIT_LOOKALIKES), text)
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
        overlap, still_visible = self._overlap(previous, current)
        candidates = current[overlap:] if overlap else current
        # Count only the old rows that are still on screen. A row that scrolled off
        # the top must not cancel out an identical new row at the bottom, or every
        # repeated heal tick and fixed-damage auto-attack loses lines.
        old_counts = Counter(line_key(line.text) for line in (still_visible if overlap else previous))
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
    def _overlap(previous: list[OCRLine], current: list[OCRLine]) -> tuple[int, list[OCRLine]]:
        """Rows at the top of ``current`` that repeat ``previous``, and which old rows they are."""
        for size in range(min(len(previous), len(current)), 0, -1):
            matches = [_similar(a.text, b.text) for a, b in zip(previous[-size:], current[:size])]
            # Both boundary rows must match, otherwise a viewport with one new
            # bottom line is mistaken for a complete overlap.
            if matches[0] and matches[-1] and sum(matches) >= max(1, ceil(size * OVERLAP_RATIO)):
                return size, previous[-size:]
        # A static window keeps its prefix and appends at the bottom.
        prefix = 0
        for a, b in zip(previous, current):
            if not _similar(a.text, b.text):
                break
            prefix += 1
        return prefix, previous[:prefix]
