"""Encounter bookkeeping: totals, DPS/HPS clocks, per-actor rows, CSV export."""
from __future__ import annotations

import csv
import re
import time
from collections import deque
from dataclasses import astuple, dataclass
from pathlib import Path

from .models import DAMAGE_KINDS, CombatEvent, EncounterSnapshot, EventKind

METRIC_KINDS = DAMAGE_KINDS | {EventKind.HEAL}
COMBAT_KINDS = METRIC_KINDS | {EventKind.MISS}
BREAKDOWN_DAMAGE_KINDS = frozenset({EventKind.DAMAGE_OUT, EventKind.DAMAGE_OTHER})
PLAYER_TARGET_KEY = "__player__"

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


class EncounterTracker:
    """Group events into encounters separated by ``timeout`` seconds of silence."""

    def __init__(self, timeout: float = 8.0, rolling_window: float = 10.0,
                 player_name: str = "You", combine_pet_damage: bool = True,
                 damage_shields_by_wearer: bool = False,
                 keep_running_totals: bool = False) -> None:
        self.timeout = timeout
        self.rolling_window = rolling_window
        self.player_name = player_name
        self.combine_pet_damage = combine_pet_damage
        self.damage_shields_by_wearer = damage_shields_by_wearer
        self.keep_running_totals = keep_running_totals
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
        target_key = self._target_key(target) if target else None

        def in_scope(event: CombatEvent) -> bool:
            return target_key is None or self._target_key(event.target) == target_key

        metric_events = [e for e in self.events if e.kind in METRIC_KINDS and in_scope(e)]
        damage_events = [e for e in metric_events if e.kind in DAMAGE_KINDS]
        outgoing_total = sum(e.amount for e in damage_events if e.kind != EventKind.DAMAGE_IN)
        incoming_total = sum(e.amount for e in damage_events if e.kind == EventKind.DAMAGE_IN)

        grouped: dict[tuple[str, str], list[CombatEvent]] = {}
        display_names: dict[tuple[str, str], str] = {}
        for event in metric_events:
            key, actor = self._actor_key(event)
            grouped.setdefault(key, []).append(event)
            current = display_names.get(key)
            if current is None or (current.islower() and not actor.islower()):
                display_names[key] = actor  # prefer a capitalized OCR reading
        recent_damage: dict[tuple[str, str], int] = {}
        for event in self._recent:
            if event.kind in DAMAGE_KINDS and in_scope(event):
                key, _actor = self._actor_key(event)
                recent_damage[key] = recent_damage.get(key, 0) + event.amount

        if target_key is None:
            damage_duration = max(1.0, snapshot.duration)
            healing_duration = max(1.0, self._healing_duration())
            rolling_span = self._rolling_span()
        else:
            damage_duration = _span(e.timestamp for e in damage_events)
            healing_duration = _span(e.timestamp for e in metric_events if e.kind == EventKind.HEAL)
            rolling_span = min(self.rolling_window, damage_duration)

        rows: list[ActorRow] = []
        for key, events in grouped.items():
            actor_damage = [e for e in events if e.kind in DAMAGE_KINDS]
            damage = sum(e.amount for e in actor_damage)
            incoming = any(e.kind == EventKind.DAMAGE_IN for e in actor_damage)
            direction_total = incoming_total if incoming else outgoing_total
            healing = sum(e.amount for e in events if e.kind == EventKind.HEAL)
            rows.append(ActorRow(
                actor=display_names[key],
                actor_type=key[1],
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

    def encounter_targets(self) -> list[str]:
        """Distinct damage and healing targets, one entry per case-insensitive name."""
        names: dict[str, str] = {}
        for event in self.events:
            target = event.target.strip()
            if not target or event.kind not in METRIC_KINDS:
                continue
            key = self._target_key(target)
            if key == PLAYER_TARGET_KEY:
                target = "You"
            current = names.get(key)
            if current is None or (current.islower() and not target.islower()):
                names[key] = target
        return sorted(names.values(), key=str.casefold)

    def _target_key(self, target: str) -> str:
        key = target.casefold().strip()
        return PLAYER_TARGET_KEY if key in {"you", self.player_name.casefold().strip()} else key

    def _actor_key(self, event: CombatEvent) -> tuple[tuple[str, str], str]:
        actor = self.credited_actor(event)
        return (actor.casefold().strip(), self.credited_actor_type(event, actor)), actor

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


def _span(timestamps) -> float:
    values = list(timestamps)
    return max(1.0, max(values) - min(values)) if values else 1.0
