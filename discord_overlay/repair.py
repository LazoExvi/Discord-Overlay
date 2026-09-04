"""Reconstruct combat lines partially hidden by the mouse cursor or UI overlaps.

OCR sees the cursor as a few garbled, split, or missing characters inside an
otherwise familiar sentence. Combat logs repeat the same grammar constantly, so
a suspicious line is aligned, token by token, against *templates* learned from
lines that parsed cleanly. A template keeps the fixed grammar words and masks
the variable parts:

* ``#`` is a number slot. It only ever matches a real number in the damaged
  line, so amounts are copied, never guessed.
* ``@`` is a name slot (actor, target, pet, or ability), matching one to three
  words.

Two kinds of template are kept. An *exact* template masks only numbers, so it
can restore a damaged target name the player has fought before. A *masked*
template also masks names, so it generalizes to new targets and is safe to
share between players: it carries grammar, not who was playing.

Guard rails, in order of importance: numbers are never invented; a clean,
known word is never "corrected"; a repair needs at most two token edits; and a
tie between templates that would produce different lines is rejected.
"""
from __future__ import annotations

import json
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Iterable

from .models import CombatEvent
from .parser import COMBAT_VERBS

NUMBER = "#"
NAME = "@"
GRAMMAR_ASSET = "grammar-templates.txt"

_GENERIC_ACTIONS = {"attack", "ability", "pet ability", "heal", "health", "miss", "damage shield"}
_NUMERIC = re.compile(r"^\d[\d,]*$")
_LETTERS = re.compile(r"^[a-z][a-z'\-]*$")
_TRAILING = ".!,;:"
_PRONOUNS = {"you", "your", "yours", "yourself"}
_VERB_SET = frozenset(COMBAT_VERBS)


def bundled_grammar() -> str:
    """The shipped grammar dictionary, or "" when the asset is unavailable."""
    try:
        return resources.files("discord_overlay").joinpath("assets", GRAMMAR_ASSET).read_text(encoding="utf-8")
    except (OSError, TypeError, ValueError):
        return ""


def event_names(event: CombatEvent) -> tuple[str, ...]:
    """Names in a parsed line that vary between players: actor, target, and any ability."""
    names = [event.actor, event.target]
    action = event.action.replace(" (Offhand)", "").strip()
    folded = action.casefold()
    if folded and folded not in _GENERIC_ACTIONS and folded not in _VERB_SET:
        names.append(action)
    return tuple(name for name in names if name and name != "Unknown")


def _tokens(text: str) -> tuple[list[str], list[str]]:
    """Split into (raw, normalized) tokens with trailing punctuation removed."""
    raw: list[str] = []
    normalized: list[str] = []
    for token in text.split():
        stripped = token.rstrip(_TRAILING)
        if stripped:
            raw.append(stripped)
            normalized.append(stripped.casefold())
    return raw, normalized


def _is_numeric(token: str) -> bool:
    return bool(_NUMERIC.match(token))


def _is_wordlike(token: str) -> bool:
    return bool(_LETTERS.match(token))


def _is_junk(token: str) -> bool:
    """A cursor artefact: no letters and no digits, e.g. ``~`` or ``|``."""
    return not any(ch.isalnum() for ch in token)


@lru_cache(maxsize=16384)
def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


@dataclass(frozen=True)
class Template:
    tokens: tuple[str, ...]   # normalized, with NUMBER / NAME placeholders
    display: tuple[str, ...]  # original casing for fixed words
    fixed: int                # count of fixed (non-placeholder) tokens
    name_slots: int = 0

    @classmethod
    def build(cls, normalized: list[str], display: list[str]) -> "Template":
        fixed = sum(token not in (NUMBER, NAME) for token in normalized)
        return cls(tuple(normalized), tuple(display), fixed, normalized.count(NAME))

    def text(self) -> str:
        return " ".join(self.display)


@dataclass(frozen=True)
class Repair:
    text: str
    template: str
    replaced: tuple[tuple[str, str], ...]  # (damaged span, template words)
    cost: int


class LineRepairer:
    """Fill cursor-sized holes in a combat line from learned and shipped templates."""

    # Alignment costs. A direct word fix must beat "stretch a name slot over the
    # damaged word and erase the real one", so slot growth is cheap but nonzero
    # and erasure is the most expensive edit. Two fixes are allowed; a fix plus
    # an erasure is not.
    KEEP = 0
    EXTRA_NAME_TOKEN = 1
    FIX = 10
    JUNK = 10
    ERASED = 20
    MAX_COST = 25
    MIN_FIXED = 3
    CLEAN_WORD_SIMILARITY = 0.75
    MAX_NAME_TOKENS = 3

    def __init__(self, capacity: int = 400, min_word_similarity: float = 0.45) -> None:
        self.capacity = capacity
        self.min_word_similarity = min_word_similarity
        self._templates: OrderedDict[tuple[str, ...], Template] = OrderedDict()  # learned, newest last
        self._seed: dict[tuple[str, ...], Template] = {}  # shipped grammar, consulted second
        self._words: Counter[str] = Counter()
        self._candidate_cache: list[Template] | None = None
        self.repaired = 0
        self.rejected = 0
        self.dirty = False

    def __len__(self) -> int:
        return len(self._templates)

    # -- learning -------------------------------------------------------------

    def observe(self, text: str, names: Iterable[str] = ()) -> None:
        """Remember a clean line as an exact template and, given names, a masked one."""
        raw, normalized = _tokens(text)
        if len(normalized) < self.MIN_FIXED + 1:
            return
        exact_tokens = [NUMBER if _is_numeric(token) else token for token in normalized]
        exact_display = [NUMBER if _is_numeric(token) else word for token, word in zip(normalized, raw)]
        self._remember(Template.build(exact_tokens, exact_display))
        masked_tokens, masked_display = self._mask_names(exact_tokens, exact_display, names)
        if masked_tokens != exact_tokens:
            self._remember(Template.build(masked_tokens, masked_display))

    def _remember(self, template: Template) -> None:
        if template.fixed < self.MIN_FIXED:
            return
        self._candidate_cache = None
        if template.tokens in self._templates:
            self._templates.move_to_end(template.tokens)
            return
        self._templates[template.tokens] = template
        self._words.update(token for token in template.tokens if token not in (NUMBER, NAME))
        self.dirty = True
        while len(self._templates) > self.capacity:
            old, _ = self._templates.popitem(last=False)
            self._words.subtract(token for token in old if token not in (NUMBER, NAME))

    @staticmethod
    def _mask_names(tokens: list[str], display: list[str],
                    names: Iterable[str]) -> tuple[list[str], list[str]]:
        tokens = list(tokens)
        display = list(display)
        for name in names:
            _raw, parts = _tokens(str(name))
            parts = [part for part in parts if part not in _PRONOUNS]
            if not parts or any(_is_numeric(part) for part in parts):
                continue
            size = len(parts)
            index = 0
            while index + size <= len(tokens):
                window = tokens[index:index + size]
                last = window[-1]
                if (window[:-1] == parts[:-1]
                        and (last == parts[-1] or last in (f"{parts[-1]}'s", f"{parts[-1]}'"))):
                    tokens[index:index + size] = [NAME]
                    display[index:index + size] = [NAME]
                index += 1
        # Adjacent slots are kept: "Training's Celestial Strike" is an actor slot
        # followed by an ability slot, and each still matches one to three words.
        return tokens, display

    def _is_known_word(self, word: str) -> bool:
        return word in _VERB_SET or self._words[word] > 0

    # -- seed dictionary & persistence ---------------------------------------

    def load_seed_text(self, text: str) -> int:
        """Load shipped templates, one per line (``@ hits @ for # points of damage``)."""
        loaded = 0
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(("#!", "//")):
                continue
            raw, normalized = _tokens(line)
            template = Template.build(normalized, raw)
            if template.fixed < self.MIN_FIXED or template.tokens in self._seed:
                continue
            self._seed[template.tokens] = template
            self._words.update(token for token in template.tokens if token not in (NUMBER, NAME))
            loaded += 1
        self._candidate_cache = None
        return loaded

    def save(self, path: Path) -> None:
        payload = {
            "version": 1,
            "templates": [{"tokens": list(t.tokens), "display": list(t.display)}
                          for t in self._templates.values()],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        self.dirty = False

    def load(self, path: Path) -> int:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        items = payload.get("templates") if isinstance(payload, dict) else None
        loaded = 0
        for item in items if isinstance(items, list) else []:
            tokens = item.get("tokens") if isinstance(item, dict) else None
            display = item.get("display") if isinstance(item, dict) else None
            if not isinstance(tokens, list) or not isinstance(display, list) or len(tokens) != len(display):
                continue
            self._remember(Template.build([str(t) for t in tokens], [str(d) for d in display]))
            loaded += 1
        self.dirty = False
        return loaded

    def masked_templates(self) -> list[str]:
        """Learned templates that contain no names, suitable for sharing or seeding."""
        return [
            template.text() for template in self._templates.values()
            if NAME in template.tokens or not any(self._words[token] == 1 for token in template.tokens)
        ]

    # -- repair ---------------------------------------------------------------

    def _candidates(self) -> list[Template]:
        if self._candidate_cache is None:
            self._candidate_cache = list(reversed(self._templates.values())) + list(self._seed.values())
        return self._candidate_cache

    def repair(self, text: str, degraded: bool = False) -> Repair | None:
        """Return a repaired line, or None when no template safely explains it.

        ``degraded`` says the parser could not attribute the line at all (no
        event, or an unknown target). Only then may a fully erased word be
        restored; every other edit needs visible evidence of damage.
        """
        raw, damaged = _tokens(text)
        m = len(damaged)
        if m < self.MIN_FIXED or not (self._templates or self._seed):
            return None
        exact = tuple(NUMBER if _is_numeric(token) else token for token in damaged)
        if exact in self._templates or exact in self._seed:
            return None  # a known line; nothing to repair
        flags = [(_is_numeric(t), _is_wordlike(t), _is_junk(t)) for t in damaged]
        best_key: tuple[int, int] | None = None
        best: list[tuple[Template, list]] = []
        # The most specific template that explains the line with name slots alone.
        # Any edit must come from a strictly more specific template than that,
        # otherwise a stretched slot plus a "fix" would rewrite a valid line.
        explained_fixed = -1
        for template in self._candidates():
            n = len(template.tokens)
            if m > n + template.name_slots * (self.MAX_NAME_TOKENS - 1) + 2 or m < n - 2:
                continue
            aligned = self._align(template, damaged, flags, degraded)
            if aligned is None:
                continue
            cost, ops = aligned
            if not any(op[0] in ("fix", "merge", "erased", "junk") for _index, op in ops):
                if cost == 0:
                    return None  # matches a known line exactly
                explained_fixed = max(explained_fixed, template.fixed)
                continue
            key = (cost, -template.fixed)
            if best_key is None or key < best_key:
                best_key, best = key, [(template, ops)]
            elif key == best_key:
                best.append((template, ops))
        if best_key is None or best[0][0].fixed <= explained_fixed:
            self.rejected += 1
            return None
        outputs: dict[str, tuple[Template, tuple]] = {}
        for template, ops in best:
            rebuilt, replaced = self._rebuild(template, raw, ops)
            outputs.setdefault(rebuilt, (template, replaced))
        if len(outputs) != 1:
            self.rejected += 1
            return None
        rebuilt, (template, replaced) = next(iter(outputs.items()))
        self.repaired += 1
        return Repair(text=rebuilt, template=template.text(), replaced=replaced, cost=best_key[0])

    @staticmethod
    def _relax(cost, back, i: int, j: int, ni: int, nj: int, add: int, op: tuple) -> None:
        total = cost[i][j] + add
        if total < cost[ni][nj]:
            cost[ni][nj] = total
            back[ni][nj] = (i, j, op)

    def _align(self, template: Template, damaged: list[str],
               flags: list[tuple[bool, bool, bool]], degraded: bool) -> tuple[int, list] | None:
        """Minimum-cost alignment of ``damaged`` onto ``template`` (None if > MAX_COST)."""
        tokens = template.tokens
        n, m = len(tokens), len(damaged)
        inf = self.MAX_COST + 1
        cost = [[inf] * (m + 1) for _ in range(n + 1)]
        back: list[list[tuple | None]] = [[None] * (m + 1) for _ in range(n + 1)]
        cost[0][0] = 0
        relax = self._relax
        for i in range(n + 1):
            for j in range(m + 1):
                if cost[i][j] > self.MAX_COST:
                    continue
                if i < n:
                    word = tokens[i]
                    if j < m:
                        token = damaged[j]
                        numeric, _wordlike, junk = flags[j]
                        if word == NUMBER:
                            if numeric:
                                relax(cost, back, i, j, i + 1, j + 1, 0, ("slot", j, 1))
                        elif word == NAME:
                            for size in range(1, self.MAX_NAME_TOKENS + 1):
                                if j + size > m or not flags[j + size - 1][1]:
                                    break
                                relax(cost, back, i, j, i + 1, j + size,
                                      (size - 1) * self.EXTRA_NAME_TOKEN, ("slot", j, size))
                        else:
                            if token == word:
                                relax(cost, back, i, j, i + 1, j + 1, 0, ("keep", j, 1))
                            else:
                                similarity = self._substitution_similarity(word, token, degraded)
                                if similarity is not None:
                                    relax(cost, back, i, j, i + 1, j + 1,
                                          self._fix_cost(similarity), ("fix", j, 1))
                            if j + 1 < m:
                                similarity = self._split_similarity(token, damaged[j + 1], word)
                                if similarity is not None:
                                    relax(cost, back, i, j, i + 1, j + 2,
                                          self._fix_cost(similarity), ("fix", j, 2))
                            if i + 1 < n and tokens[i + 1] not in (NUMBER, NAME):
                                similarity = self._merge_similarity(token, word, tokens[i + 1])
                                if similarity is not None:
                                    relax(cost, back, i, j, i + 2, j + 1,
                                          self._fix_cost(similarity), ("merge", j, 1))
                        if junk:
                            relax(cost, back, i, j, i, j + 1, self.JUNK, ("junk", j, 1))
                    if degraded and word not in (NUMBER, NAME):
                        relax(cost, back, i, j, i + 1, j, self.ERASED, ("erased", j, 0))
                elif j < m and flags[j][2]:
                    relax(cost, back, i, j, i, j + 1, self.JUNK, ("junk", j, 1))
        if cost[n][m] > self.MAX_COST:
            return None
        ops = []
        i, j = n, m
        while (i, j) != (0, 0):
            pi, pj, op = back[i][j]
            ops.append((pi if pi < i else None, op))
            i, j = pi, pj
        ops.reverse()
        return cost[n][m], ops

    def _fix_cost(self, similarity: float) -> int:
        return self.FIX + int(round((1.0 - similarity) * 10))

    def _is_real_word(self, token: str) -> bool:
        """A clean, known word is evidence of a different line, not of damage."""
        return _is_wordlike(token) and self._is_known_word(token)

    @staticmethod
    def _structural_similarity(damaged: str, expected: str) -> float | None:
        shorter, longer = sorted((len(damaged), len(expected)))
        if shorter < 0.7 * longer:
            return None
        similarity = _similarity(damaged, expected)
        return similarity if similarity >= 0.6 else None

    def _split_similarity(self, first: str, second: str, word: str) -> float | None:
        """``first second`` is one word the cursor split, unless both are real words."""
        if _is_numeric(first) or _is_numeric(second):
            return None
        if self._is_real_word(first) and self._is_real_word(second):
            return None  # "punch a" is grammar, not a broken "punches"
        return self._structural_similarity(first + second, word)

    def _merge_similarity(self, token: str, first: str, second: str) -> float | None:
        """``token`` is two template words the cursor glued, unless it is a real word."""
        if _is_numeric(token) or self._is_real_word(token):
            return None
        return self._structural_similarity(token, first + second)

    def _substitution_similarity(self, word: str, token: str, degraded: bool) -> float | None:
        if _is_numeric(token):
            return None
        if not (degraded or not _is_wordlike(token) or len(token) <= 2):
            return None  # a clean word with no other evidence of damage
        if self._is_real_word(token):
            return None
        similarity = _similarity(token, word)
        # A clean, unknown word (a new mob or spell) is only "damage" when it is
        # very close to the template word; symbols or fragments need less.
        threshold = (self.CLEAN_WORD_SIMILARITY if _is_wordlike(token) and len(token) > 2
                     else self.min_word_similarity)
        return similarity if similarity >= threshold else None

    @staticmethod
    def _rebuild(template: Template, raw: list[str], ops: list) -> tuple[str, tuple[tuple[str, str], ...]]:
        out: list[str] = []
        replaced: list[tuple[str, str]] = []
        for index, (kind, j, size) in ops:
            if kind == "junk":
                continue
            display = template.display[index]
            if kind == "slot":
                out.append(" ".join(raw[j:j + size]))
            elif kind == "keep":
                out.append(display)
            elif kind == "fix":
                out.append(display)
                replaced.append((" ".join(raw[j:j + size]), display))
            elif kind == "merge":
                out.extend((display, template.display[index + 1]))
                replaced.append((raw[j], f"{display} {template.display[index + 1]}"))
            elif kind == "erased":
                out.append(display)
                replaced.append(("", display))
        return " ".join(out), tuple(replaced)
