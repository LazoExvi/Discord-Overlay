"""Turn one recognized chat line into a ``CombatEvent``.

The grammar is deliberately loose: known verbs improve actor/action labels, but
any line with ``<amount> points of damage`` or ``<amount> Health`` still counts,
so new spells, pets, and shields are never silently dropped. OCR noise that the
game never produces (``I8O`` for ``180``, ``Youcrush``) is corrected first.
"""
from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Iterable
from datetime import datetime
from difflib import SequenceMatcher

from .models import CombatEvent, EventKind

COMBAT_VERBS: tuple[str, ...] = (
    "hits", "hit", "crushes", "crush", "slashes", "slash", "pierces", "pierce",
    "bashes", "bash", "smashes", "smash", "claws", "claw",
    "bites", "bite", "burns", "burn", "blasts", "blast", "damages", "damage",
    "punches", "punch", "kicks", "kick", "stabs", "stab", "shoots", "shoot",
    "cleaves", "cleave", "slices", "slice", "chops", "chop", "mauls", "maul",
    "pummels", "pummel", "smites", "smite", "rends", "rend", "gouges", "gouge",
    "attacks", "attack", "shocks", "shock", "drains", "drain", "poisons", "poison",
    "throws", "throw", "strikes", "strike", "stings", "sting", "whips", "whip", "lashes", "lash",
    "gores", "gore", "stomps", "stomp", "tramples", "trample", "slams", "slam", "rakes", "rake",
    "backstabs", "backstab", "impales", "impale", "scratches", "scratch",
    "bleeds", "bleed", "clobbers", "clobber", "bludgeons", "bludgeon",
)
_VERB_SET = frozenset(COMBAT_VERBS)
_VERB_ALTERNATION = "|".join(COMBAT_VERBS)
_VERB_PATTERN = re.compile(rf"\b({_VERB_ALTERNATION})\b", re.IGNORECASE)
_GLUED_VERBS = tuple(sorted(_VERB_SET | {"tries", "try"}, key=len, reverse=True))

_NUMBER_CLASS = r"[\dOoIlSB,]+"
_POINTS_OF = r"p\S{3,6}\s+(?:[oa][a-z]?f?\s*)?"  # "p∂ints", "pomints"
_DAMAGE = re.compile(
    rf"^(?P<prefix>.+?)\s+for\s+(?P<amount>{_NUMBER_CLASS})\s+{_POINTS_OF}"
    r"(?:(?P<school>[A-Za-z]+)\s+)?(?:da[a-z]*[.,!]?|(?P<school_end>[A-Za-z]+)(?=\s*(?:\(|$))|$)"
    rf"(?:\s*\((?P<absorbed>{_NUMBER_CLASS})\s+[a-z]{{6,9}}\))?",
    re.IGNORECASE,
)
_GENERIC_DAMAGE = re.compile(
    rf"(?P<amount>{_NUMBER_CLASS})\s+(?:points?\s+of\s+)?"
    r"(?:(?P<school>[A-Za-z][A-Za-z-]*)\s+)?damage\b",
    re.IGNORECASE,
)
_ABSORBED = re.compile(rf"\(({_NUMBER_CLASS})\s+[a-z]{{6,9}}\)", re.IGNORECASE)
_HEAL = re.compile(
    rf"^(?P<prefix>.+)\s+heals?\s+(?P<target>you|[\w' -]+?)\s+for\s+"
    rf"(?P<amount>{_NUMBER_CLASS})(?:\s+Health)?[.!]?",
    re.IGNORECASE,
)
_HEAL_VERB = re.compile(r"\b(heal\w*|restore\w*|mend\w*|regenerat\w*)\b", re.IGNORECASE)
_GENERIC_HEAL = re.compile(
    rf"\b(?:heal\w*|restore\w*|mend\w*|regenerat\w*)\b.*?"
    rf"(?:\bfor\s+(?P<for_amount>{_NUMBER_CLASS})(?:\s+(?:health|healing))?\b|"
    rf"\b(?P<health_amount>{_NUMBER_CLASS})\s+(?:points?\s+of\s+)?(?:health|healing)\b)",
    re.IGNORECASE,
)
_HEALTH_AMOUNT = re.compile(
    rf"(?P<health_amount>{_NUMBER_CLASS})\s+(?:points?\s+of\s+)?(?:health|healing)\b",
    re.IGNORECASE,
)
_MISS = re.compile(
    r"^(?P<actor>You|Your|.+?)\s+(?:try|tries)\s+to\s+.+?\s+(?P<target>.+?),?\s+but\s+miss",
    re.IGNORECASE,
)
_OFFHAND = re.compile(r"\s+with\s+(?:your|their|its|his|her)\s+(?P<weapon>of[ft]\w{3,5}|bow|crossbow|sling)\b", re.IGNORECASE)
# Environmental damage is not combat and must not start or extend an encounter.
_ENVIRONMENT = re.compile(
    r"\b(?:from|by|due\s+to)\s+(?:falling|a\s+fall|drowning|starvation|hunger|thirst|suffocation)\b"
    r"|\b(?:fall|falling|drowning)\s+damage\b",
    re.IGNORECASE,
)
_PASSIVE_SELF = re.compile(r"^you\s+(?:take|suffer|receive)\b", re.IGNORECASE)
# "Playerone spreads their Spreading Plague to Playertwo. Playertwo takes 400 points of damage!"
_SPREAD = re.compile(
    r"^(?P<spreader>[A-Za-z][A-Za-z'-]*)\s+spreads\s+(?:their|his|her|its)\s+(?P<disease>[A-Za-z][A-Za-z -]*?)"
    r"\s+to\s+(?P<target>you|[A-Za-z][A-Za-z'-]*)[.!]?\s*(?:you|[A-Za-z][A-Za-z'-]*)?\s*takes?\b",
    re.IGNORECASE,
)
# "Tom takes 400 points of damage!" (or a truncated "takes 400 points of damage!")
_TAKES = re.compile(r"^(?:(?P<target>you|[A-Za-z][A-Za-z'-]*)\s+)?takes?\s+\S*\d", re.IGNORECASE)
_JUNK_ACTORS = frozenset({"takes", "take", "hits", "hit", "for", "is", "are", "the", "a", "an"})
_FROM_SOURCE = re.compile(r"\b(?:from|by)\s+(?P<source>[A-Za-z][A-Za-z' -]*?)(?:'s\s+\w+)?[.!]?$", re.IGNORECASE)
_DAMAGE_SHIELD = re.compile(r"\bdamage[\s-]*shield\b", re.IGNORECASE)
_UNKNOWN_VERB = re.compile(
    r"^(?P<actor>[A-Za-z][A-Za-z' -]*?)\s+(?P<verb>[A-Za-z]{3,})\s+(?P<target>(?:(?:a|an|the)\s+.+)|you)$",
    re.IGNORECASE,
)
_NAME = r"[A-Za-z][A-Za-z'-]*"
_NAME_PHRASE = rf"{_NAME}(?:\s+{_NAME}){{0,5}}"
_PET_POSSESSIVE = re.compile(rf"\byour\s+pet\s+(?P<name>{_NAME_PHRASE})'s\b", re.IGNORECASE)
_PET_ACTION = re.compile(
    rf"\byour\s+pet\s+(?P<name>{_NAME_PHRASE})\s+(?:{_VERB_ALTERNATION})\b", re.IGNORECASE,
)
_PET_TARGET = re.compile(
    rf"\byour\s+pet\s+(?P<name>{_NAME}(?:\s+{_NAME}){{0,5}}?)(?:\s+for\b|[.!]|$)", re.IGNORECASE,
)
_NAMED_PET_SPELL = re.compile(rf"^your\s+pet\s+(?P<name>{_NAME_PHRASE})'s\s+(?P<rest>.+)$", re.IGNORECASE)
_UNNAMED_PET_SPELL = re.compile(r"^your\s+pet(?:'s|s')\s+(?P<rest>.+)$", re.IGNORECASE)
_PET_ATTACK = re.compile(r"^your\s+pet\s+(?P<rest>.+)$", re.IGNORECASE)
_REFLEXIVE = frozenset({"them", "themselves", "themself", "himself", "herself", "itself", "self"})
_HEAL_FRAGMENT = re.compile(rf"(?:heal|heals|healed|healing)\s+(?P<name>{_NAME})", re.IGNORECASE)
_DIGIT_FIXES = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8"})

MAX_AMOUNT = 10_000_000
# Two amounts in one line means two messages were read as one (rows fused mid-scroll or
# mid-redraw). Crediting either half would be a guess, so such lines are dropped.
_AMOUNT_PHRASE = re.compile(r"\b\d[\d,]*\s+p[a-z0-9]{3,6}|\b\d[\d,]*\s+Health", re.IGNORECASE)


def is_fused_line(text: str) -> bool:
    """True when a line carries more than one damage or heal amount."""
    return len(_AMOUNT_PHRASE.findall(text)) >= 2


# "(Critical)" even when the region edge cut it short; the only other parenthetical
# after a damage amount is "(N absorbed)", which starts with a digit.
# "(Crippling Blow)" is the fighter's low-health critical, so it counts too.
_CRITICAL = re.compile(r"\(\s*cri[a-z]*|\(\s*cr?$", re.IGNORECASE)


def _is_critical(text: str) -> bool:
    return "critical" in text.casefold() or bool(_CRITICAL.search(text.rstrip()))


def parse_amount(value: str | None) -> int:
    """Read a number OCR may have mangled (``I8O`` -> 180, ``1,234`` -> 1234)."""
    if not value or not re.search(r"\d", value):
        return 0
    cleaned = value.translate(_DIGIT_FIXES).replace(",", "")
    return int(re.sub(r"\D", "", cleaned) or 0)


def closest_combat_verb(value: str) -> str | None:
    """Snap a misread verb (``curshs``) back onto the known list, or None."""
    folded = value.casefold()
    if folded in _VERB_SET:
        return folded
    if len(folded) < 4:
        return None
    candidates = [verb for verb in COMBAT_VERBS if abs(len(verb) - len(folded)) <= 2]
    if not candidates:
        return None
    best = max(candidates, key=lambda verb: SequenceMatcher(None, folded, verb).ratio())
    ratio = SequenceMatcher(None, folded, best).ratio()
    # A misread first letter ("erushes" for "crushes") needs a closer match than a jumbled tail.
    return best if ratio >= (0.72 if best[0] == folded[0] else 0.8) else None


_RANK = r"(?:[IVX]{1,4}|Rk\.?\s*[IVX]{1,4}|\d{1,2})"
_MISREAD_POSSESSIVE = re.compile(
    rf"^(?P<name>[A-Z][A-Za-z-]{{2,}}?)(?P<suffix>[lI1]s|s)\s+"
    rf"(?P<ability>[A-Z][A-Za-z-]+(?:\s+[A-Za-z-]+){{0,3}}?)(?P<rank>\s+{_RANK})?\s+(?:{_VERB_ALTERNATION})\b",
)


def repair_ocr_possessive(text: str) -> str:
    """``Playerls Slice VI hits`` -> ``Player's Slice VI hits`` (apostrophe read as l/I/1 or lost)."""
    match = _MISREAD_POSSESSIVE.match(text)
    if not match or match.group("name").casefold() in {"you", "your"}:
        return text
    # Without a rank numeral, a plain trailing "s" is more likely part of the name.
    if match.group("suffix") == "s" and not match.group("rank"):
        return text
    return f"{match.group('name')}'s {text[match.end('suffix'):].lstrip()}"


_GLUED_ARTICLE = re.compile(r"\b([A-Za-z]{4,})(an|a)(?=\s+[a-z])")
_MISREAD_YOUR = re.compile(r"^Y[o0][uwv]{1,2}r(?=\s)")   # Yowr / Youwr / Yovr
_MISREAD_YOU = re.compile(r"^Y[o0][uwv]{1,2}(?=\s)")     # Yow / Yov
_GLUED_RANK_VERB = re.compile(rf"\b([A-Za-z]{{3,}})(I{{1,3}}|IV|VI{{0,3}}|V|IX|X)({_VERB_ALTERNATION})(?=\s)")


def _split_glued_article(match: re.Match) -> str:
    token, article = match.group(1), match.group(2)
    for junk in ("", "i", "l", "1"):  # "hitsia" -> "hits" + "i" + "a"
        stem = token[:-len(junk)] if junk else token
        if stem.endswith(junk) or not junk:
            verb = closest_combat_verb(stem[:-len(junk)] if junk and stem.endswith(junk) else stem)
            if verb and (verb == stem.casefold() or len(stem) >= 4):
                return f"{verb} {article}"
    return match.group(0)


def repair_ocr_spacing(text: str) -> str:
    """Restore spaces OCR drops in a few grammar-backed spots; nothing broader."""
    text = repair_ocr_possessive(text)
    text = re.sub(r"\bfor-(?=\d)", "for ", text)  # "for-407 points"
    text = _MISREAD_YOUR.sub("Your", text)
    text = _MISREAD_YOU.sub("You", text)
    text = _GLUED_RANK_VERB.sub(lambda m: f"{m.group(1)} {m.group(2)} {m.group(3)}", text)
    text = _GLUED_ARTICLE.sub(_split_glued_article, text)
    # Player'sFireball / James'Fireball
    text = re.sub(r"^([A-Za-z][A-Za-z'-]*?'s)([A-Za-z])", r"\1 \2", text)
    text = re.sub(r"^([A-Za-z][A-Za-z'-]*?s')(?!s\b)([A-Za-z])", r"\1 \2", text)

    # Playerpunches a zealot / Youcrush a rat: split a verb suffix off the first token only.
    first, separator, remainder = text.partition(" ")
    folded = first.casefold()
    # Not when a verb follows directly: "Whiplash crushes a rat" keeps its name.
    if remainder and not _VERB_PATTERN.match(remainder):
        for verb in _GLUED_VERBS:
            if folded.endswith(verb) and len(first) - len(verb) >= 2:
                text = f"{first[:-len(verb)]} {first[-len(verb):]}{separator}{remainder}"
                break

    # Player curshsa cryptic weaver -> Player crushes a cryptic weaver (one-token actor only).
    parts = text.split(" ", 2)
    if len(parts) == 3:
        actor, candidate, remainder = parts
        for article in ("an", "a"):
            if candidate.casefold().endswith(article) and len(candidate) > len(article) + 3:
                repaired = closest_combat_verb(candidate[:-len(article)])
                if repaired:
                    text = f"{actor} {repaired} {article} {remainder}"
                    break
    return text


def _repair_damage_prefix(prefix: str) -> str:
    """Correct a fuzzy verb only when an explicit target marker follows it."""
    match = re.match(
        r"^(?P<actor>.+)\s+(?P<verb>[A-Za-z]+)\s+(?P<target>(?:(?:a|an|the)\s+.+)|YOU)$",
        prefix, re.IGNORECASE,
    )
    if not match:
        return prefix
    repaired = closest_combat_verb(match.group("verb"))
    return f"{match.group('actor')} {repaired} {match.group('target')}" if repaired else prefix


def split_possessive(value: str) -> tuple[str, str] | None:
    """``Player's Fireball`` -> (Player, Fireball); ``James' Fireball`` -> (James, Fireball)."""
    regular = re.match(r"^(.+?)'s\s+(.+)$", value, re.IGNORECASE)
    if regular:
        return regular.group(1).strip(), regular.group(2).strip()
    ending_s = re.match(r"^(.+?s)'\s+(.+)$", value, re.IGNORECASE)
    if ending_s:
        return ending_s.group(1).strip(), ending_s.group(2).strip()
    return None


def _letters(value: str) -> str:
    return re.sub(r"[^a-z]", "", value.casefold())


def _pet_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def normalize_quotes(text: str) -> str:
    """OCR renders apostrophes as backticks or acute accents; the grammar needs a plain one."""
    text = text.replace("`", "'").replace("´", "'").replace("’", "'").replace("‘", "'")
    if not text.isascii():
        # "ąf damage": strip diacritics the game never prints, keep anything else as-is.
        text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return text


def _split_verb(text: str) -> tuple[str, str, str] | None:
    """Split ``<before> <verb> <after>`` on the last known verb; None if none."""
    matches = list(_VERB_PATTERN.finditer(text))
    if not matches:
        return None
    match = matches[-1]
    return text[:match.start()].strip(), match.group(0), text[match.end():].strip()


def _strip_offhand(target: str, action: str) -> tuple[str, str]:
    target = re.sub(r"^(?:at|on|into|upon)\s+", "", target, flags=re.IGNORECASE)
    offhand = _OFFHAND.search(target)
    if offhand:
        weapon = offhand.group("weapon")
        weapon = "Offhand" if weapon.casefold().startswith("of") else weapon.title()
        return target[:offhand.start()].strip(), f"{action} ({weapon})"
    return target, action


class CombatTextParser:
    """Stateful parser: remembers learned pet names for later attribution."""

    def __init__(self, player_name: str = "You", pet_names: Iterable[str] = ()) -> None:
        self.player_name = player_name.strip() or "You"
        self._known_pets: set[str] = set()
        self._new_pets: list[str] = []
        for name in pet_names:
            self._remember_pet(str(name), announce=False)

    # -- learning -------------------------------------------------------------

    def observe(self, text: str) -> None:
        """Learn ``Your pet <Name>`` aliases from any visible line without counting it."""
        text = repair_ocr_spacing(re.sub(r"\s+", " ", normalize_quotes(text)).strip())
        for pattern in (_PET_POSSESSIVE, _PET_ACTION, _PET_TARGET):
            match = pattern.search(text)
            if match:
                self._remember_pet(match.group("name"))
                return

    def pop_new_pets(self) -> list[str]:
        """Pet names learned since the last call, so earlier events can be re-attributed."""
        names, self._new_pets = self._new_pets, []
        return names

    def _remember_pet(self, name: str, announce: bool = True) -> None:
        key = _pet_key(name)
        if key and key not in {"pet", "yourpet"} and key not in self._known_pets:
            self._known_pets.add(key)
            if announce:
                self._new_pets.append(name.strip())

    def _is_known_pet(self, name: str) -> bool:
        return _pet_key(name) in self._known_pets

    def _is_your_pet(self, value: str) -> bool:
        """``your pet`` / ``yourpet`` / ``<player>'s pet`` all mean the player's pet."""
        letters = _letters(value)
        return letters in {"yourpet", _letters(self.player_name) + "spet"}

    # -- parsing --------------------------------------------------------------

    def parse(self, text: str, confidence: float = 1.0,
              timestamp: float | None = None) -> CombatEvent | None:
        text = repair_ocr_spacing(re.sub(r"\s+", " ", normalize_quotes(text)).strip())
        self.observe(text)
        if is_fused_line(text):
            return None
        now = time.monotonic() if timestamp is None else timestamp
        wall = datetime.now()
        return (
            self._parse_damage(text, confidence, now, wall)
            or self._parse_heal(text, confidence, now, wall)
            or self._parse_miss(text, confidence, now, wall)
        )

    def _parse_damage(self, text: str, confidence: float, now: float, wall: datetime) -> CombatEvent | None:
        match = _DAMAGE.search(text)
        generic = None if match else _GENERIC_DAMAGE.search(text)
        if not match and not generic:
            return None
        if _ENVIRONMENT.search(text):
            return None  # "You take 65 points of damage from falling."
        amount = parse_amount((match or generic).group("amount"))
        if not 0 < amount <= MAX_AMOUNT:
            return None
        spread = _SPREAD.match(text)
        takes = None if spread or _PASSIVE_SELF.match(text) else _TAKES.match(text)
        if spread or takes:
            # Mechanic damage: credit the disease (or nobody), never the player it spread from.
            target = self._pretty_name((spread or takes).group("target") or "Unknown")
            actor = spread.group("disease").strip().title() if spread else "Unknown"
            action = f"Spread by {spread.group('spreader')}" if spread else "Damage Taken"
            kind = EventKind.DAMAGE_IN if target == self.player_name else EventKind.DAMAGE_OTHER
            return CombatEvent(
                timestamp=now, wall_time=wall, kind=kind, actor=actor, target=target, amount=amount,
                absorbed=parse_amount(m.group(1)) if (m := _ABSORBED.search(text)) else 0,
                action=action, critical=_is_critical(text), raw_text=text, confidence=confidence,
            )
        if match:
            prefix = _repair_damage_prefix(match.group("prefix").strip())
            absorbed = parse_amount(match.group("absorbed"))
        else:
            prefix = text[:generic.start()].strip(" .,:-")
            absorbed_match = _ABSORBED.search(text)
            absorbed = parse_amount(absorbed_match.group(1)) if absorbed_match else 0
        actor, target, action, kind, is_pet = self._damage_parties(prefix)
        actor, target, action, kind, is_pet = self._infer_damage_context(
            text, actor, target, action, kind, is_pet,
        )
        return CombatEvent(
            timestamp=now, wall_time=wall, kind=kind, actor=actor, target=target,
            amount=amount, absorbed=absorbed, action=action,
            critical=_is_critical(text), raw_text=text, confidence=confidence,
            is_pet=is_pet, is_damage_shield=bool(_DAMAGE_SHIELD.search(text)),
        )

    def _parse_heal(self, text: str, confidence: float, now: float, wall: datetime) -> CombatEvent | None:
        match = _HEAL.search(text)
        if match:
            amount = parse_amount(match.group("amount"))
            actor = self._healer_from(match.group("prefix").strip())
            target_text = match.group("target").strip()
            target = actor if target_text.casefold() in _REFLEXIVE else self._pretty_name(target_text)
            if amount > 0:
                return CombatEvent(
                    now, wall, EventKind.HEAL, actor, target,
                    amount, action="Heal", raw_text=text, confidence=confidence,
                    is_pet=self._is_known_pet(actor),
                )
        match = _GENERIC_HEAL.search(text) or _HEALTH_AMOUNT.search(text)
        if not match:
            return None
        groups = match.groupdict()
        amount = parse_amount(groups.get("for_amount") or groups.get("health_amount"))
        if not 0 < amount <= MAX_AMOUNT:
            return None
        verb = _HEAL_VERB.search(text)
        actor_text = text[:verb.start()].strip(" .,:-") if verb else "Unknown"
        actor = self._pretty_name(actor_text or "Unknown")
        if text.casefold().startswith(("you ", "your ")):
            actor = self.player_name
        actor = self._normalize_healer_actor(actor)
        # "Ebola's faith answers, healing them for 375 Health."
        owner = re.match(r"^([A-Za-z][A-Za-z'-]*)'s\s+faith\b", text, re.IGNORECASE)
        if owner:
            actor = self._pretty_name(owner.group(1))
        named = re.search(r"\b(?:heal\w*|restor\w*|mend\w*|regenerat\w*)\s+(?P<target>[A-Za-z][A-Za-z'-]*)\s+for\b",
                          text, re.IGNORECASE)
        if re.search(r"\b(?:you|your)\s+pet\b", text, re.IGNORECASE):
            target = "Pet"
        elif re.search(r"\byou\b", text, re.IGNORECASE):
            target = self.player_name
        elif named and named.group("target").casefold() in _REFLEXIVE:
            target = actor
        elif named and named.group("target").casefold() not in {"for", "the", "a", "an"}:
            target = self._pretty_name(named.group("target"))
        else:
            target = "Unknown"
        return CombatEvent(
            now, wall, EventKind.HEAL, actor, target, amount,
            action=verb.group(1).title() if verb else "Heal", raw_text=text,
            confidence=confidence, is_pet=self._is_known_pet(actor),
        )

    def _parse_miss(self, text: str, confidence: float, now: float, wall: datetime) -> CombatEvent | None:
        match = _MISS.search(text)
        if not match:
            return None
        actor_text = match.group("actor").strip()
        is_pet = actor_text.casefold() == "your pet"
        actor = "Pet" if is_pet else self._pretty_name(actor_text)
        target_text, _action = _strip_offhand(match.group("target"), "Miss")
        return CombatEvent(
            now, wall, EventKind.MISS, actor, self._pretty_name(target_text),
            action="Miss", raw_text=text, confidence=confidence,
            is_pet=is_pet or self._is_known_pet(actor),
        )

    # -- attribution ----------------------------------------------------------

    def _infer_damage_context(self, text: str, actor: str, target: str, action: str,
                              kind: EventKind, is_pet: bool) -> tuple[str, str, str, EventKind, bool]:
        """Use pronouns and source phrases to fix ownership regardless of the verb."""
        if _DAMAGE_SHIELD.search(text):
            action = "Damage Shield"
            passive = re.match(r"^(?P<target>.+?)\s+(?:is|was|takes?|suffers?)\b", text, re.IGNORECASE)
            if passive:
                target = self._pretty_name(passive.group("target"))
            if re.search(r"\byour\s+pet(?:'s|s')\s+damage[\s-]*shield\b", text, re.IGNORECASE):
                return "Pet", target, action, EventKind.DAMAGE_OUT, True
            if re.search(r"\byour\s+damage[\s-]*shield\b", text, re.IGNORECASE):
                return self.player_name, target, action, EventKind.DAMAGE_OUT, False
            wearer = re.search(
                rf"(?:^|\b(?:by|from)\s+)(?:(?:a|an|the)\s+)?(?P<wearer>{_NAME}(?:\s+{_NAME}){{0,3}})'s\s+damage[\s-]*shield\b",
                text, re.IGNORECASE,
            )
            if wearer:
                actor = self._pretty_name(wearer.group("wearer"))
                wearer_is_pet = self._is_known_pet(actor)
                mine = actor.casefold() == self.player_name.casefold() or wearer_is_pet
                return actor, target, action, EventKind.DAMAGE_OUT if mine else EventKind.DAMAGE_OTHER, wearer_is_pet
            return "Damage Shield", target, action, kind, False

        folded = text.casefold()
        if _PASSIVE_SELF.match(text):
            # "You take 40 points of damage from a trap." is damage *to* you, not by you.
            source = _FROM_SOURCE.search(text)
            actor = self._pretty_name(source.group("source")) if source else "Unknown"
            return actor, self.player_name, action, EventKind.DAMAGE_IN, False
        if re.search(r"\b(?:from|by)\s+your\s+pet\b", text, re.IGNORECASE):
            return "Pet", target, action, EventKind.DAMAGE_OUT, True
        if folded.startswith(("your pet ", "your pet's ")):
            return actor, target, action, EventKind.DAMAGE_OUT, True
        if folded.startswith(("you ", "your ")):
            return self.player_name, target, action, EventKind.DAMAGE_OUT, False
        if re.search(r"\byou\b", text, re.IGNORECASE):
            return actor, self.player_name, action, EventKind.DAMAGE_IN, is_pet
        if re.search(r"\b(?:hits?|strikes?|damages?|attacks?|to)\s+your\s*pet\b", text, re.IGNORECASE):
            return actor, "Pet", action, EventKind.DAMAGE_IN, is_pet
        return actor, target, action, kind, is_pet

    def _damage_parties(self, prefix: str) -> tuple[str, str, str, EventKind, bool]:
        """Split the text before ``for N points`` into actor, target, action, and kind."""
        prefix = prefix.strip(" .")

        pet_match = _NAMED_PET_SPELL.match(prefix) or _UNNAMED_PET_SPELL.match(prefix) or _PET_ATTACK.match(prefix)
        if pet_match:
            return self._pet_parties(prefix, pet_match)

        if prefix.casefold().startswith("your "):
            # Your Feint IV hits a comely courtesan
            rest = prefix[5:].strip()
            parts = _split_verb(rest)
            if parts:
                before, verb, target = parts
                action = before or verb.title()
            else:
                action, target = "Ability", rest
            return self.player_name, self._pretty_name(target), action, EventKind.DAMAGE_OUT, False

        parts = _split_verb(prefix)
        if parts:
            actor_text, verb, target_text = parts
            action = verb.title()
            if self._is_your_pet(actor_text):  # "Player's pet hits ..."
                target_text, action = _strip_offhand(target_text, action)
                return "Pet", self._pretty_name(target_text), action, EventKind.DAMAGE_OUT, True
            possessive = split_possessive(actor_text)
            if possessive and possessive[1].casefold() == "pet":
                pass  # "a Plagueborn runescribe's pet hits ...": the pet itself is the actor
            elif possessive and possessive[1].casefold().startswith("pet's "):
                # "a Pyrmos mercenary's pet's Strike hits ...": the pet is the actor, Strike the ability.
                actor_text = f"{possessive[0]}'s pet"
                action = possessive[1][6:].strip() or action
            elif possessive:
                actor_text, ability = possessive
                action = ability or action
            target_text, action = _strip_offhand(target_text, action)
        else:
            unknown_verb = _UNKNOWN_VERB.match(prefix)
            if unknown_verb:
                # "Bone Construct wallops YOU": an unlisted or misread verb before a clear target.
                actor_text, target_text = unknown_verb.group("actor"), unknown_verb.group("target")
                action = unknown_verb.group("verb").title()
            else:
                actor_text, target_text, action = prefix, "Unknown", "Attack"

        actor_is_player = actor_text.strip().casefold() in {"you", self.player_name.casefold()}
        actor_is_pet = self._is_known_pet(actor_text)
        target_is_player = target_text.strip().casefold() == "you"
        target_is_pet = self._is_your_pet(target_text)
        actor = self._pretty_name(actor_text)
        target = self._pretty_name(target_text)
        if actor_is_player:
            return self.player_name, target, action, EventKind.DAMAGE_OUT, False
        if actor_is_pet:
            return actor, target, action, EventKind.DAMAGE_OUT, True
        if target_is_player or target_is_pet:
            return actor, "Pet" if target_is_pet else self.player_name, action, EventKind.DAMAGE_IN, False
        return actor, target, action, EventKind.DAMAGE_OTHER, False

    def _pet_parties(self, prefix: str, pet_match: re.Match) -> tuple[str, str, str, EventKind, bool]:
        named = pet_match.re is _NAMED_PET_SPELL
        actor = pet_match.group("name") if named else "Pet"
        rest = pet_match.group("rest").strip()
        if pet_match.re is _PET_ATTACK:
            # "Your pet Aernulo pierces ..." — the words before the first verb name the pet.
            first_verb = _VERB_PATTERN.search(rest)
            if first_verb and first_verb.start() > 0:
                candidate = rest[:first_verb.start()].strip()
                if candidate:
                    actor, rest = candidate, rest[first_verb.start():]
        parts = _split_verb(rest)
        if parts:
            before, verb, target = parts
            action = before or verb.title()
        else:
            action, target = "Pet Ability", rest
        target, action = _strip_offhand(target, action)
        if actor != "Pet":
            self._remember_pet(actor)
        return actor, self._pretty_name(target), action, EventKind.DAMAGE_OUT, True

    def _healer_from(self, prefix: str) -> str:
        value = prefix.strip()
        if value.casefold().startswith("your "):
            return self.player_name
        possessive = split_possessive(value)
        return self._normalize_healer_actor(self._pretty_name(possessive[0] if possessive else value))

    @staticmethod
    def _normalize_healer_actor(actor: str) -> str:
        """Repair an OCR fragment such as ``heals Evollate`` used as an actor."""
        fragment = _HEAL_FRAGMENT.fullmatch(actor.strip())
        return fragment.group("name") if fragment else actor

    def _pretty_name(self, value: str) -> str:
        value = re.sub(r"^(?:a|an|the)\s+", "", value.strip(" .,!:;-"), flags=re.IGNORECASE)
        if self._is_your_pet(value):
            return "Pet"
        if value.casefold() in {"you", "your"}:
            return self.player_name
        # OCR sometimes loses the start of a line; never credit an empty or article-only name,
        # nor a single lowercase letter ("r slashes ..."). Two-letter clips such as "om"
        # are kept so the display-time merge can fold them into the full name.
        if not re.search(r"[A-Za-z0-9]", value) or value.casefold() in _JUNK_ACTORS:
            return "Unknown"
        if len(value) == 1 and value.islower():
            return "Unknown"
        return value
