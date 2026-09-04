"""Versioned JSON trigger packs for sharing a profile's triggers."""
from __future__ import annotations

from dataclasses import asdict

from .triggers import Trigger

PACK_FORMAT = "discord-overlay-trigger-pack"
PACK_VERSION = 1


def build_trigger_pack(profile: str, triggers: list[Trigger]) -> dict:
    return {
        "format": PACK_FORMAT,
        "version": PACK_VERSION,
        "profile": profile,
        "triggers": [asdict(t) for t in triggers if t.profile.casefold() == profile.casefold()],
    }


def parse_trigger_pack(payload, existing_ids: set[str] | None = None) -> tuple[list[Trigger], list[str]]:
    """Return (imported, skipped-reasons). Conflicting IDs are regenerated."""
    raw = payload.get("triggers", []) if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        raise ValueError("The file does not contain a trigger list.")
    known_ids = set(existing_ids or ())
    imported: list[Trigger] = []
    skipped: list[str] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            skipped.append(f"Item {index}: not a trigger object")
            continue
        try:
            trigger = Trigger.from_dict(item)
        except (TypeError, ValueError) as exc:
            skipped.append(f"Item {index}: {exc}")
            continue
        errors = trigger.validate()
        if errors:
            skipped.append(f"{trigger.name}: {'; '.join(errors)}")
            continue
        if trigger.id in known_ids:
            trigger.id = Trigger().id
        known_ids.add(trigger.id)
        imported.append(trigger)
    return imported, skipped
