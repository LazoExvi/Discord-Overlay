"""Optional group filter: keep fights involving you, your pet, or listed names."""
from __future__ import annotations

import re
from collections.abc import Iterable

from .models import CombatEvent, EventKind

PET_KEYS = frozenset({"pet", "yourpet"})


def normalize_actor_name(value: str) -> str:
    """Strip articles, punctuation, and case so OCR variants of one name compare equal."""
    value = re.sub(r"^(?:a|an|the)\s+", "", value.strip(), flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def actor_event_allowed(event: CombatEvent, player_name: str, enabled: bool,
                        allowed_names: Iterable[str]) -> bool:
    """True when the event should enter the log, totals, and exports.

    An event is kept when either side of it is the player, the player's pet, or a
    listed group member. A group member hitting a mob and that mob hitting the
    member are both kept; a stranger fighting a different mob is dropped. Mob
    names never need to be listed.
    """
    if not enabled:
        return True
    # Outgoing/incoming kinds and pet events already carry You/Your context.
    if event.kind in (EventKind.DAMAGE_OUT, EventKind.DAMAGE_IN) or event.is_pet:
        return True
    group = {normalize_actor_name(name) for name in allowed_names if isinstance(name, str) and name.strip()}
    group.add(normalize_actor_name(player_name))
    actor_key = normalize_actor_name(event.actor)
    if actor_key and actor_key in group:
        return True
    target_key = normalize_actor_name(event.target)
    return bool(target_key) and (target_key in group or target_key in PET_KEYS)
