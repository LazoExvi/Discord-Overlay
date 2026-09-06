"""Encounter bookkeeping: totals, DPS/HPS clocks, per-actor rows, CSV export."""
from __future__ import annotations

import csv
import re
import time
from collections import Counter, deque
from dataclasses import astuple, dataclass
from difflib import SequenceMatcher
from pathlib import Path

from .models import DAMAGE_KINDS, CombatEvent, EncounterSnapshot, EventKind

METRIC_KINDS = DAMAGE_KINDS | {EventKind.HEAL}
COMBAT_KINDS = METRIC_KINDS | {EventKind.MISS}
BREAKDOWN_DAMAGE_KINDS = frozenset({EventKind.DAMAGE_OUT, EventKind.DAMAGE_OTHER})
PLAYER_TARGET_KEY = "__player__"
NPC_BUCKET = "NPC"  # enemies and bystanders share rows; the row type is decided afterwards

COMBATANT_COLUMNS = ("Actor", "Type", "Damage", "Share Percent", "DPS", "10s DPS",
                     "Hits", "Crits", "Healing", "HPS")
LOG_COLUMNS = ("Time", "Type", "Actor", "Source Actor", "Target", "Action", "Amount",
               "Absorbed", "Critical", "Pet", "Damage Shield", "OCR Confidence", "Raw Text")


@dataclass(slots=True)
class ActorRow:
    actor: str
    actor_type: str
    damage: int
    share: float
    dps: float
    rolling_dps: float
    hits: int
    crits: int
    healing: int
    hps: float

    def as_tuple(self) -> tuple:
        return astuple(self)


# Character pairs OCR confuses in the game font. Two spellings merge only when
# every difference between them is one of these swaps, so "Konaner" and
# "Lonaner" (a real K/L difference) stay separate players while
# "Bone Construet" folds into "Bone Construct".
OCR_CONFUSIONS: frozenset[tuple[str, str]] = frozenset({
    ("c", "e"), ("l", "i"), ("l", "1"), ("i", "1"), ("l", "t"), ("i", "j"), ("o", "0"), ("o", "a"),
    ("u", "n"), ("t", "f"), ("s", "5"), ("b", "8"), ("h", "b"), ("g", "q"), ("g", "9"), ("z", "2"),
    ("rn", "m"), ("n", "m"), ("cl", "d"), ("vv", "w"), ("ii", "u"), ("nn", "m"),
    ("'", ""), ("'", "l"), ("'", "1"), ("'", "i"), ("'", "`"), ("-", ""), (" ", ""),
})
_CONFUSABLE = OCR_CONFUSIONS | {(b, a) for a, b in OCR_CONFUSIONS}
MAX_CONFUSIONS = 2


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
        # A doubled letter read as one: the inserted/deleted char repeats its neighbour.
        longer, at, gap = (a, i1, left) if len(left) == 1 and not right else (b, j1, right)
        if len(gap) == 1 and (longer[at - 1:at] == gap or longer[at + 1:at + 2] == gap):
            continue
        return False
    return edits > 0


def merge_similar_names(names, protected=(), minority_share: float = 0.25) -> dict[str, str]:
    """Map each casefolded name onto the spelling it is most likely a misread of.

    A spelling merges into a more common one only when the two differ by known OCR
    character confusions, the rarer spelling is a small minority of the pair (a
    misread is occasional; a second player is not), and neither is a protected
    name such as the player's own or a configured pet.
    """
    counts = Counter(name for name in names if name)
    protected_keys = {str(name).casefold().strip() for name in protected}
    canonical: dict[str, str] = {}
    accepted: list[tuple[str, int]] = []
    for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        chosen = name
        if len(name) >= 3 and name != "unknown" and name not in protected_keys:
            for existing, existing_count in accepted:
                if existing in protected_keys and count > 2:
                    continue
                if count <= max(2, existing_count * minority_share) and ocr_confusable(name, existing):
                    chosen = existing
                    break
        if chosen == name:
            accepted.append((name, count))
        canonical[name] = chosen
    return canonical


class EncounterTracker:
    """Group events into encounters separated by ``timeout`` seconds of silence."""

    def __init__(self, timeout: float = 8.0, rolling_window: float = 10.0,
                 player_name: str = "You", combine_pet_damage: bool = True,
                 damage_shields_by_wearer: bool = False,
                 keep_running_totals: bool = False, protected_names=()) -> None:
        self.timeout = timeout
        self.rolling_window = rolling_window
        self.player_name = player_name
        self.combine_pet_damage = combine_pet_damage
        self.damage_shields_by_wearer = damage_shields_by_wearer
        self.keep_running_totals = keep_running_totals
        self.protected_names: set[str] = {str(n).casefold().strip() for n in protected_names if str(n).strip()}
        self.events: list[CombatEvent] = []
        self.history: list[list[CombatEvent]] = []
        self._recent: deque[CombatEvent] = deque()
        self.active = False
        self.started_at: float | None = None
        self.last_combat_at: float | None = None
        self.last_damage_at: float | None = None
        self.last_heal_at: float | None = None
        self._completed_damage_duration = 0.0
        self._completed_healing_duration = 0.0
        self._last_segment_damage_duration = 0.0

    # -- event intake ---------------------------------------------------------

    def add(self, event: CombatEvent) -> None:
        is_combat = event.kind in COMBAT_KINDS
        if (is_combat and self.active and self.last_combat_at is not None
                and event.timestamp - self.last_combat_at >= self.timeout):
            self._finish_segment()
        if is_combat and not self.active:
            self._begin_segment(event.timestamp)
        self.events.append(event)
        self._recent.append(event)
        if is_combat:
            self.last_combat_at = event.timestamp
        if event.kind in DAMAGE_KINDS:
            self.last_damage_at = event.timestamp
        elif event.kind == EventKind.HEAL:
            self.last_heal_at = event.timestamp

    def _begin_segment(self, timestamp: float) -> None:
        if not self.keep_running_totals:
            if self.events:
                self.history.append(self.events.copy())
            self.events.clear()
            self._completed_damage_duration = 0.0
            self._completed_healing_duration = 0.0
        self._recent.clear()
        self.started_at = timestamp
        self.last_damage_at = None
        self.last_heal_at = None
        self.active = True

    def _finish_segment(self) -> None:
        damage_duration = self._segment_damage_duration()
        self._completed_damage_duration += damage_duration
        self._completed_healing_duration += self._segment_healing_duration()
        self._last_segment_damage_duration = damage_duration
        self.started_at = None
        self.last_damage_at = None
        self.last_heal_at = None
        self.active = False

    def update(self, now: float | None = None) -> bool:
        """Expire the rolling window and close the encounter after the timeout."""
        now = time.monotonic() if now is None else now
        while self._recent and now - self._recent[0].timestamp > self.rolling_window:
            self._recent.popleft()
        if self.active and self.last_combat_at is not None and now - self.last_combat_at >= self.timeout:
            self._finish_segment()
            return True
        return False

    def mark_pet(self, name: str) -> int:
        """Re-attribute earlier events from ``name`` as the player's pet; returns how many changed."""
        key = re.sub(r"[^a-z0-9]", "", name.casefold())
        if not key:
            return 0
        changed = 0
        for event in self.events:
            if event.is_pet or re.sub(r"[^a-z0-9]", "", event.actor.casefold()) != key:
                continue
            event.is_pet = True
            if event.kind == EventKind.DAMAGE_OTHER:
                event.kind = EventKind.DAMAGE_OUT
            changed += 1
        return changed

    def reset(self) -> None:
        self.events.clear()
        self._recent.clear()
        self.active = False
        self.started_at = None
        self.last_combat_at = None
        self.last_damage_at = None
        self.last_heal_at = None
        self._completed_damage_duration = 0.0
        self._completed_healing_duration = 0.0
        self._last_segment_damage_duration = 0.0

    # -- clocks ---------------------------------------------------------------

    def _segment_damage_duration(self) -> float:
        if self.started_at is None:
            return 0.0
        end = (self.last_damage_at if self.last_damage_at is not None
               else self.last_combat_at if self.last_combat_at is not None
               else self.started_at)
        return max(0.0, end - self.started_at)

    def _segment_healing_duration(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.last_heal_at if self.last_heal_at is not None else self.started_at
        return max(0.0, end - self.started_at)

    def _healing_duration(self) -> float:
        return self._completed_healing_duration + self._segment_healing_duration()

    def _rolling_span(self) -> float:
        rolling_duration = (self._segment_damage_duration() if self.active
                            else self._last_segment_damage_duration)
        return min(self.rolling_window, max(1.0, rolling_duration))

    def _counts_toward_headline(self, event: CombatEvent) -> bool:
        return event.kind == EventKind.DAMAGE_OUT and (self.combine_pet_damage or not event.is_pet)

    # -- summaries ------------------------------------------------------------

    def snapshot(self, now: float | None = None) -> EncounterSnapshot:
        now = time.monotonic() if now is None else now
        self.update(now)
        # Completed segments contribute only their active time, so running totals
        # can combine fights without counting the idle gaps between them.
        duration = self._completed_damage_duration + self._segment_damage_duration()
        total_out = sum(e.amount for e in self.events if self._counts_toward_headline(e))
        rolling_out = sum(e.amount for e in self._recent if self._counts_toward_headline(e))
        total_heal = sum(e.amount for e in self.events if e.kind == EventKind.HEAL)
        return EncounterSnapshot(
            active=self.active,
            duration=duration,
            total_out=total_out,
            total_in=sum(e.amount for e in self.events if e.kind == EventKind.DAMAGE_IN),
            total_heal=total_heal,
            dps=total_out / max(1.0, duration),
            rolling_dps=rolling_out / self._rolling_span(),
            hps=total_heal / max(1.0, self._healing_duration()),
            hits=sum(e.kind in BREAKDOWN_DAMAGE_KINDS for e in self.events),
            crits=sum(e.critical and e.kind in BREAKDOWN_DAMAGE_KINDS for e in self.events),
            misses=sum(e.kind == EventKind.MISS for e in self.events),
            events=self.events.copy(),
        )

    def actor_totals(self, now: float | None = None, target: str | None = None) -> list[ActorRow]:
        """One row per credited actor, optionally scoped to a single target."""
        snapshot = self.snapshot(now)
        names = self._name_map()
        target_key = names.get(self._target_key(target)) if target else None

        def in_scope(event: CombatEvent) -> bool:
            return target_key is None or names.get(self._target_key(event.target)) == target_key

        metric_events = [e for e in self.events if e.kind in METRIC_KINDS and in_scope(e)]

        grouped: dict[tuple[str, str], list[CombatEvent]] = {}
        display_names: dict[tuple[str, str], Counter] = {}
        for event in metric_events:
            key, actor = self._actor_key(event, names)
            grouped.setdefault(key, []).append(event)
            display_names.setdefault(key, Counter())[actor] += 1
        recent_damage: dict[tuple[str, str], int] = {}
        for event in self._recent:
            if event.kind in DAMAGE_KINDS and in_scope(event):
                key, _actor = self._actor_key(event, names)
                recent_damage[key] = recent_damage.get(key, 0) + event.amount

        # A mob that hit you and also hit your group is one enemy, not two rows; its
        # share is measured against everything enemies dealt, friendly rows against
        # everything the friendly side dealt.
        row_types = {key: self._row_type(key, events) for key, events in grouped.items()}
        totals = {"enemy": 0, "friendly": 0}
        for key, events in grouped.items():
            side = "enemy" if row_types[key] == "ENEMY" else "friendly"
            totals[side] += sum(e.amount for e in events if e.kind in DAMAGE_KINDS)

        if target_key is None:
            damage_duration = max(1.0, snapshot.duration)
            healing_duration = max(1.0, self._healing_duration())
            rolling_span = self._rolling_span()
        else:
            damage_events = [e for e in metric_events if e.kind in DAMAGE_KINDS]
            damage_duration = _span(e.timestamp for e in damage_events)
            healing_duration = _span(e.timestamp for e in metric_events if e.kind == EventKind.HEAL)
            rolling_span = min(self.rolling_window, damage_duration)

        rows: list[ActorRow] = []
        for key, events in grouped.items():
            actor_damage = [e for e in events if e.kind in DAMAGE_KINDS]
            damage = sum(e.amount for e in actor_damage)
            direction_total = totals["enemy" if row_types[key] == "ENEMY" else "friendly"]
            healing = sum(e.amount for e in events if e.kind == EventKind.HEAL)
            rows.append(ActorRow(
                actor=_preferred_spelling(display_names[key]),
                actor_type=row_types[key],
                damage=damage,
                share=100.0 * damage / max(1, direction_total),
                dps=damage / damage_duration,
                rolling_dps=recent_damage.get(key, 0) / rolling_span,
                hits=len(actor_damage),
                crits=sum(e.critical for e in actor_damage),
                healing=healing,
                hps=healing / healing_duration,
            ))
        return sorted(rows, key=lambda row: (row.damage, row.healing, row.actor.casefold()), reverse=True)

    def _name_map(self) -> dict[str, str]:
        """Canonical spelling for every actor and target name seen this encounter."""
        seen = []
        for event in self.events:
            if event.kind in METRIC_KINDS:
                seen.append(self.credited_actor(event).casefold().strip())
                seen.append(self._target_key(event.target))
        return merge_similar_names(seen, self.protected_names | {self.player_name.casefold().strip()})

    @staticmethod
    def _row_type(key: tuple[str, str], events: list[CombatEvent]) -> str:
        if key[1] != NPC_BUCKET:
            return key[1]
        return "ENEMY" if any(e.kind == EventKind.DAMAGE_IN for e in events) else "OTHER"

    def encounter_targets(self) -> list[str]:
        """Distinct damage and healing targets, one entry per (fuzzy) case-insensitive name."""
        canonical = self._name_map()
        names: dict[str, Counter] = {}
        for event in self.events:
            target = event.target.strip()
            if not target or event.kind not in METRIC_KINDS:
                continue
            key = self._target_key(target)
            if key == PLAYER_TARGET_KEY:
                target = "You"
            names.setdefault(canonical.get(key, key), Counter())[target] += 1
        return sorted((_preferred_spelling(c) for c in names.values()), key=str.casefold)

    def _target_key(self, target: str) -> str:
        key = target.casefold().strip()
        return PLAYER_TARGET_KEY if key in {"you", self.player_name.casefold().strip()} else key

    def _actor_key(self, event: CombatEvent, names: dict[str, str] | None = None) -> tuple[tuple[str, str], str]:
        actor = self.credited_actor(event)
        folded = actor.casefold().strip()
        if names:
            folded = names.get(folded, folded)
        actor_type = self.credited_actor_type(event, actor)
        bucket = NPC_BUCKET if actor_type in {"ENEMY", "OTHER"} else actor_type
        return (folded, bucket), actor

    def credited_actor(self, event: CombatEvent) -> str:
        if event.is_damage_shield and not self.damage_shields_by_wearer:
            return "Damage Shield"
        if event.is_pet and self.combine_pet_damage:
            return self.player_name
        return event.actor

    def credited_actor_type(self, event: CombatEvent, actor: str) -> str:
        if event.is_damage_shield and not self.damage_shields_by_wearer:
            return "DAMAGE SHIELD"
        if actor.casefold() == self.player_name.casefold():
            return "PLAYER"
        if event.is_pet:
            return "PET"
        if event.kind == EventKind.DAMAGE_IN:
            return "ENEMY"
        return "OTHER"

    # -- export ---------------------------------------------------------------

    def export_csv(self, path: Path, export_type: str) -> None:
        """Write the combatant summary or the chronological log as UTF-8 CSV."""
        if export_type not in {"combatants", "log"}:
            raise ValueError(f"Unknown CSV export type: {export_type}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            if export_type == "combatants":
                writer.writerow(COMBATANT_COLUMNS)
                writer.writerows(row.as_tuple() for row in self.actor_totals())
                return
            writer.writerow(LOG_COLUMNS)
            for event in self.events:
                writer.writerow([
                    event.wall_time.isoformat(sep=" ", timespec="milliseconds"),
                    event.kind.value, self.credited_actor(event), event.actor, event.target,
                    event.action, event.amount, event.absorbed, event.critical, event.is_pet,
                    event.is_damage_shield, event.confidence, event.raw_text,
                ])


def _preferred_spelling(spellings: Counter) -> str:
    """Most frequent reading wins; a capitalized reading breaks ties with a lowercase one."""
    return max(spellings.items(), key=lambda item: (item[1], not item[0].islower(), item[0]))[0]


def _span(timestamps) -> float:
    values = list(timestamps)
    return max(1.0, max(values) - min(values)) if values else 1.0
