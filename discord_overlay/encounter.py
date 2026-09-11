"""Encounter bookkeeping: totals, DPS/HPS clocks, per-actor rows, CSV export."""
from __future__ import annotations

import csv
import re
import time
from collections import Counter, deque
from dataclasses import astuple, dataclass
from pathlib import Path

from . import __version__
from .models import DAMAGE_KINDS, CombatEvent, EncounterSnapshot, EventKind
from .names import (  # noqa: F401  (re-exported for callers and tests)
    OCR_CONFUSIONS, clipped_head, glued_article, known_npc, merge_similar_names, ocr_confusable,
)

METRIC_KINDS = DAMAGE_KINDS | {EventKind.HEAL}
COMBAT_KINDS = METRIC_KINDS | {EventKind.MISS}
BREAKDOWN_DAMAGE_KINDS = frozenset({EventKind.DAMAGE_OUT, EventKind.DAMAGE_OTHER})
PLAYER_TARGET_KEY = "__player__"
NPC_BUCKET = "NPC"  # enemies and bystanders share rows; the row type is decided afterwards

COMBATANT_COLUMNS = ("Actor", "Type", "Damage", "Share Percent", "DPS", "10s DPS",
                     "Hits", "Crits", "Healing", "HPS", "App Version")
LOG_COLUMNS = ("Time", "Type", "Actor", "Source Actor", "Target", "Action", "Amount",
               "Absorbed", "Critical", "Pet", "Damage Shield", "OCR Confidence", "Raw Text", "App Version")


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
        # Name merging and per-actor grouping walk every event; with running totals over
        # a long session that is tens of thousands of events several times a second on
        # the UI thread. Both are cached until the event list actually changes.
        self._version = 0            # bumps on every change to the event list
        self._names_version = 0      # bumps only when a never-seen name key appears (or on rebuild)
        self._seen_keys: set[str] = set()
        self._name_map_cache: tuple[tuple, dict[str, str]] | None = None
        self._grouping_cache: dict = {}
        self._sums_cache: tuple | None = None   # (built_up_to, settings_key, sums)

    def _bump(self, rebuild: bool = False) -> None:
        """Note an appended event; ``rebuild`` when earlier events changed or were cleared."""
        self._version += 1
        if rebuild:
            self._names_version += 1
            self._seen_keys = {self.credited_actor(e).casefold().strip() for e in self.events}
            self._seen_keys |= {self._target_key(e.target) for e in self.events}
            self._grouping_cache.clear()
            self._sums_cache = None

    def _note_names(self, event: CombatEvent) -> None:
        if event.kind not in METRIC_KINDS:
            return
        for key in (self.credited_actor(event).casefold().strip(), self._target_key(event.target)):
            if key not in self._seen_keys:
                self._seen_keys.add(key)
                self._names_version += 1
                self._grouping_cache.clear()

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
        self._bump()
        self._note_names(event)
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
            self._bump(rebuild=True)
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
        if changed:
            self._bump(rebuild=True)
        return changed

    def reset(self) -> None:
        self.events.clear()
        self._recent.clear()
        self._bump(rebuild=True)
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

    def _settings_key(self) -> tuple:
        return (self.player_name, self.combine_pet_damage, self.damage_shields_by_wearer,
                frozenset(self.protected_names))

    def _counts_toward_headline(self, event: CombatEvent) -> bool:
        return event.kind == EventKind.DAMAGE_OUT and (self.combine_pet_damage or not event.is_pet)

    # -- summaries ------------------------------------------------------------

    def snapshot(self, now: float | None = None) -> EncounterSnapshot:
        now = time.monotonic() if now is None else now
        self.update(now)
        # Completed segments contribute only their active time, so running totals
        # can combine fights without counting the idle gaps between them.
        duration = self._completed_damage_duration + self._segment_damage_duration()
        settings_key = self._settings_key()
        cache = self._sums_cache
        if cache is None or cache[1] != settings_key or cache[0] > len(self.events):
            start, sums = 0, [0, 0, 0, 0, 0, 0]
        else:
            start, sums = cache[0], list(cache[2])
        for e in self.events[start:]:
            if self._counts_toward_headline(e):
                sums[0] += e.amount
            if e.kind == EventKind.DAMAGE_IN:
                sums[1] += e.amount
            elif e.kind == EventKind.HEAL:
                sums[2] += e.amount
            if e.kind in BREAKDOWN_DAMAGE_KINDS:
                sums[3] += 1
                sums[4] += bool(e.critical)
            elif e.kind == EventKind.MISS:
                sums[5] += 1
        self._sums_cache = (len(self.events), settings_key, tuple(sums))
        total_out, total_in, total_heal, hits, crits, misses = sums
        rolling_out = sum(e.amount for e in self._recent if self._counts_toward_headline(e))
        return EncounterSnapshot(
            active=self.active,
            duration=duration,
            total_out=total_out,
            total_in=total_in,
            total_heal=total_heal,
            dps=total_out / max(1.0, duration),
            rolling_dps=rolling_out / self._rolling_span(),
            hps=total_heal / max(1.0, self._healing_duration()),
            hits=hits,
            crits=crits,
            misses=misses,
            events=self.events.copy(),
        )

    def actor_totals(self, now: float | None = None, target: str | None = None) -> list[ActorRow]:
        """One row per credited actor, optionally scoped to a single target."""
        snapshot = self.snapshot(now)
        names = self._name_map()
        target_key = names.get(self._target_key(target)) if target else None

        def in_scope(event: CombatEvent) -> bool:
            return target_key is None or names.get(self._target_key(event.target)) == target_key

        cache_key = ("group", target_key, self._settings_key(), self._names_version)
        cached = self._grouping_cache.get(cache_key)
        if cached is None or cached["built"] > len(self.events):
            cached = {"built": 0, "metric_events": [], "grouped": {}, "display_names": {}, "damage": {}, "has_in": set()}
            if len(self._grouping_cache) > 8:
                self._grouping_cache.clear()
            self._grouping_cache[cache_key] = cached
        if cached["built"] < len(self.events):
            metric_events, grouped, display_names = cached["metric_events"], cached["grouped"], cached["display_names"]
            for event in self.events[cached["built"]:]:
                if event.kind in METRIC_KINDS and in_scope(event):
                    metric_events.append(event)
                    key, actor = self._actor_key(event, names)
                    grouped.setdefault(key, []).append(event)
                    display_names.setdefault(key, Counter())[actor] += 1
                    if event.kind in DAMAGE_KINDS:
                        cached["damage"][key] = cached["damage"].get(key, 0) + event.amount
                        if event.kind == EventKind.DAMAGE_IN:
                            cached["has_in"].add(key)
            cached["built"] = len(self.events)
            # A mob that hit you and also hit your group is one enemy, not two rows; its
            # share is measured against everything enemies dealt, friendly rows against
            # everything the friendly side dealt.
            row_types = {key: (key[1] if key[1] != NPC_BUCKET else "ENEMY" if key in cached["has_in"] else "OTHER")
                         for key in grouped}
            totals = {"enemy": 0, "friendly": 0}
            for key in grouped:
                side = "enemy" if row_types[key] == "ENEMY" else "friendly"
                totals[side] += cached["damage"].get(key, 0)
            cached["row_types"], cached["totals"] = row_types, totals
        metric_events, grouped, display_names = cached["metric_events"], cached["grouped"], cached["display_names"]
        row_types, totals = cached["row_types"], cached["totals"]
        recent_damage: dict[tuple[str, str], int] = {}
        for event in self._recent:
            if event.kind in DAMAGE_KINDS and in_scope(event):
                key, _actor = self._actor_key(event, names)
                recent_damage[key] = recent_damage.get(key, 0) + event.amount

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
        cache_tag = (self._names_version, self._settings_key())
        if self._name_map_cache is not None and self._name_map_cache[0] == cache_tag:
            return self._name_map_cache[1]
        seen = []
        for event in self.events:
            if event.kind in METRIC_KINDS:
                seen.append(self.credited_actor(event).casefold().strip())
                seen.append(self._target_key(event.target))
        names = merge_similar_names(seen, self.protected_names | {self.player_name.casefold().strip()})
        # Player names are 3 to 15 letters and no mob is shorter either, so a two-letter
        # name that merged into nothing is a clipped fragment: count it as Unknown.
        for name, canonical in names.items():
            if canonical == name and len(name) <= 2 and name != PLAYER_TARGET_KEY:
                names[name] = "unknown"
        self._name_map_cache = (cache_tag, names)
        return names

    @staticmethod
    def _row_type(key: tuple[str, str], events: list[CombatEvent]) -> str:
        if key[1] != NPC_BUCKET:
            return key[1]
        return "ENEMY" if any(e.kind == EventKind.DAMAGE_IN for e in events) else "OTHER"

    def encounter_targets(self) -> list[str]:
        """Distinct damage and healing targets, one entry per (fuzzy) case-insensitive name."""
        targets_key = ("targets", self._names_version, self._settings_key())
        if targets_key in self._grouping_cache:
            return list(self._grouping_cache[targets_key])
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
        result = sorted((_preferred_spelling(c) for c in names.values()), key=str.casefold)
        self._grouping_cache[targets_key] = result
        return list(result)

    def _target_key(self, target: str) -> str:
        key = target.casefold().strip()
        return PLAYER_TARGET_KEY if key in {"you", self.player_name.casefold().strip()} else key

    def _actor_key(self, event: CombatEvent, names: dict[str, str] | None = None) -> tuple[tuple[str, str], str]:
        actor = self.credited_actor(event)
        folded = actor.casefold().strip()
        if names:
            merged = names.get(folded, folded)
            if merged != folded:
                # Merged into a spelling never read this fight (a known NPC): show the shipped spelling.
                actor = "Unknown" if merged == "unknown" else (known_npc(merged) or actor)
            folded = merged
        actor_type = self.credited_actor_type(event, folded)
        bucket = NPC_BUCKET if actor_type in {"ENEMY", "OTHER"} else actor_type
        return (folded, bucket), actor

    def _enemy_shield(self, event: CombatEvent) -> bool:
        """Was this damage-shield hit dealt by something fighting against the player?"""
        if event.kind == EventKind.DAMAGE_IN:
            return True
        if event.kind == EventKind.DAMAGE_OUT or event.is_pet:
            return False
        wearer, target = event.actor, event.target
        if wearer.casefold().strip() in self.protected_names:
            return False
        if wearer != "Damage Shield" and (known_npc(wearer) or wearer[:1].islower()):
            return True   # a mob wore it
        if known_npc(target) or target[:1].islower():
            return False  # it burned a mob, so whoever the mob attacked (a friend) wore it
        return True       # it burned a player, so the player's enemy wore it

    def credited_actor(self, event: CombatEvent) -> str:
        if event.is_damage_shield and not self.damage_shields_by_wearer:
            return "Enemy Damage Shield" if self._enemy_shield(event) else "Damage Shield"
        if event.is_pet and self.combine_pet_damage:
            return self.player_name
        return event.actor

    def credited_actor_type(self, event: CombatEvent, actor: str) -> str:
        if event.is_damage_shield and not self.damage_shields_by_wearer:
            return "ENEMY SHIELD" if self._enemy_shield(event) else "DAMAGE SHIELD"
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
                writer.writerows(row.as_tuple() + (__version__,) for row in self.actor_totals())
                return
            writer.writerow(LOG_COLUMNS)
            for event in self.events:
                writer.writerow([
                    event.wall_time.isoformat(sep=" ", timespec="milliseconds"),
                    event.kind.value, self.credited_actor(event), event.actor, event.target,
                    event.action, event.amount, event.absorbed, event.critical, event.is_pet,
                    event.is_damage_shield, event.confidence, event.raw_text, __version__,
                ])


def _preferred_spelling(spellings: Counter) -> str:
    """Most frequent reading wins; a capitalized reading breaks ties with a lowercase one."""
    return max(spellings.items(), key=lambda item: (item[1], not item[0].islower(), item[0]))[0]


def _span(timestamps) -> float:
    values = list(timestamps)
    return max(1.0, max(values) - min(values)) if values else 1.0
