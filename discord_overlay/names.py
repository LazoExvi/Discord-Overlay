"""Combatant name similarity and the shipped list of known NPC names.

OCR reads the same combatant several ways during a fight. This module decides
when two spellings are the same name (only known OCR confusions, a clipped head,
a glued article, or a stray space) and folds rare spellings into common ones.
A shipped list of NPC names from the community wiki and mnmdrops.com lets a
misread snap to the real spelling even when the correct spelling was never read.
"""
from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache
from importlib import resources

NPC_ASSET = "npc-names.txt"

# Character pairs OCR confuses in the game font. Two spellings merge only when
# every difference between them is one of these swaps, so "Bonaner" and
# "Ronaner" (a real B/R difference) stay separate players while
# "Bone Construet" folds into "Bone Construct".
OCR_CONFUSIONS: frozenset[tuple[str, str]] = frozenset({
    ("c", "e"), ("e", "o"), ("l", "i"), ("l", "1"), ("i", "1"), ("l", "t"), ("i", "j"), ("o", "0"), ("o", "a"),
    ("u", "n"), ("t", "f"), ("s", "5"), ("b", "8"), ("h", "b"), ("g", "q"), ("g", "9"), ("z", "2"),
    ("rn", "m"), ("rb", "m"), ("n", "m"), ("cl", "d"), ("vv", "w"), ("ii", "u"), ("nn", "m"),
    ("'", ""), ("'", "l"), ("'", "1"), ("'", "i"), ("'", "`"), ("-", ""), (" ", ""),
})
_CONFUSABLE = OCR_CONFUSIONS | {(b, a) for a, b in OCR_CONFUSIONS}
MAX_CONFUSIONS = 2
_ARTICLE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)


def ocr_confusable(a: str, b: str, max_edits: int = MAX_CONFUSIONS) -> bool:
    """True when ``a`` and ``b`` differ only by up to ``max_edits`` known OCR swaps."""
    if a == b:
        return False
    edits = 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        edits += 1
        if edits > max_edits:
            return False
        left, right = a[i1:i2], b[j1:j2]
        if (left, right) in _CONFUSABLE:
            continue
        # A doubled letter read as one: an inserted/deleted char that repeats its neighbour.
        if not left or not right:
            longer, at, gap = (a, i1, left) if left else (b, j1, right)
            if len(gap) == 1 and (longer[at - 1:at] == gap or longer[at + 1:at + 2] == gap):
                continue
        return False
    return edits > 0


def clipped_head(name: str, known: str) -> bool:
    """``layername`` -> ``playername``: the capture edge or cursor cut off the first letter or two."""
    minimum = 2 if len(known) <= 4 else 3
    lost = 3 if len(known) >= 12 else 2  # a long name can lose a third letter and still be unmistakable
    return (len(name) >= minimum and 1 <= len(known) - len(name) <= lost and known.endswith(name))


def glued_article(name: str, known: str) -> bool:
    """``abone archer`` -> ``bone archer``: the article lost its space."""
    return name in (f"a{known}", f"an{known}", f"the{known}")


def looks_like(name: str, known: str) -> bool:
    """Any of the accepted ways one reading of ``known`` becomes ``name``."""
    return (name.replace(" ", "") == known.replace(" ", "") or ocr_confusable(name, known)
            or clipped_head(name, known) or glued_article(name, known))


# -- known NPC names ------------------------------------------------------------

def name_key(name: str) -> str:
    """Casefolded, article-free form used for every comparison."""
    return _ARTICLE.sub("", name.strip()).casefold()


@lru_cache(maxsize=1)
def known_npcs() -> dict[str, str]:
    """``{key: display}`` for every shipped NPC name; empty if the asset is missing."""
    try:
        text = resources.files("discord_overlay").joinpath("assets", NPC_ASSET).read_text(encoding="utf-8")
    except (OSError, TypeError, ValueError):
        return {}
    names: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.setdefault(name_key(line), _ARTICLE.sub("", line))
    return names


def known_npc(name: str) -> str | None:
    """The shipped spelling of ``name`` if it is a known NPC, else None."""
    return known_npcs().get(name_key(name))


@lru_cache(maxsize=4096)
def snap_to_known_npc(key: str) -> str | None:
    """The key of the one known NPC ``key`` is a misreading of, or None.

    Exact matches return themselves. Anything ambiguous (two NPCs equally close)
    returns None rather than guessing.
    """
    known = known_npcs()
    if key in known:
        return key
    if len(key) < 4:
        return None
    hits = [candidate for candidate in known
            if abs(len(candidate) - len(key)) <= 3 and looks_like(key, candidate)]
    return hits[0] if len(hits) == 1 else None


# -- merging ----------------------------------------------------------------------

def merge_similar_names(names, protected=(), minority_share: float = 0.25,
                        use_known_npcs: bool = True) -> dict[str, str]:
    """Map each casefolded name onto the spelling it is most likely a misread of.

    A spelling merges into a more common one only when the two differ by known OCR
    character confusions, the rarer spelling is a small minority of the pair (a
    misread is occasional; a second player is not), and neither is a protected
    name such as the player's own or a configured pet. A spelling that matches no
    seen name but is one misread away from a known NPC snaps to that NPC.
    """
    counts = Counter(name for name in names if name)
    protected_keys = {str(name).casefold().strip() for name in protected}
    canonical: dict[str, str] = {}
    accepted: list[tuple[str, int]] = []
    for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        chosen = name
        if len(name) >= 2 and name != "unknown" and name not in protected_keys:
            for existing, existing_count in accepted:
                if existing in protected_keys and count > 2:
                    continue
                if name.replace(" ", "") == existing.replace(" ", ""):
                    chosen = existing  # a stray or missing space is never a different combatant
                    break
                if count <= max(2, existing_count * minority_share) and (
                        ocr_confusable(name, existing) or clipped_head(name, existing)
                        or glued_article(name, existing)):
                    chosen = existing
                    break
        if chosen == name:
            accepted.append((name, count))
        canonical[name] = chosen
    for name in list(canonical):
        if canonical[name] != name or name in protected_keys:
            continue
        # The player's own name is always a merge target, even when rarely seen by that spelling.
        for key in protected_keys:
            if clipped_head(name, key) or ocr_confusable(name, key):
                canonical[name] = key
                break
        else:
            if use_known_npcs and counts[name] <= 2 and name not in known_npcs():
                snapped = snap_to_known_npc(name)
                if snapped:
                    canonical[name] = snapped
    return canonical
