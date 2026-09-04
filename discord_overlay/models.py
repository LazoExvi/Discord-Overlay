"""Plain data types shared by the parser, tracker, scanner, and UI."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EventKind(str, Enum):
    DAMAGE_OUT = "damage_out"
    DAMAGE_IN = "damage_in"
    DAMAGE_OTHER = "damage_other"
    HEAL = "heal"
    MISS = "miss"


DAMAGE_KINDS = frozenset({EventKind.DAMAGE_OUT, EventKind.DAMAGE_IN, EventKind.DAMAGE_OTHER})


@dataclass(slots=True)
class CombatEvent:
    timestamp: float
    wall_time: datetime
    kind: EventKind
    actor: str
    target: str
    amount: int = 0
    absorbed: int = 0
    action: str = "Attack"
    critical: bool = False
    raw_text: str = ""
    confidence: float = 1.0
    is_pet: bool = False
    is_damage_shield: bool = False
    repaired: bool = False


@dataclass(slots=True)
class OCRLine:
    text: str
    confidence: float
    y: float = 0.0


@dataclass(slots=True)
class Region:
    left: int
    top: int
    width: int
    height: int

    MIN_WIDTH = 80
    MIN_HEIGHT = 60

    def valid(self) -> bool:
        return self.width >= self.MIN_WIDTH and self.height >= self.MIN_HEIGHT

    def as_mss(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}

    def as_dict(self) -> dict[str, int]:
        return self.as_mss()

    @classmethod
    def from_dict(cls, data: object) -> "Region | None":
        if not isinstance(data, dict):
            return None
        try:
            region = cls(int(data["left"]), int(data["top"]), int(data["width"]), int(data["height"]))
        except (KeyError, TypeError, ValueError):
            return None
        return region if region.valid() else None

    def describe(self) -> str:
        return f"{self.width} x {self.height} at ({self.left}, {self.top})"

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x <= self.left + self.width and self.top <= y <= self.top + self.height


@dataclass
class EncounterSnapshot:
    active: bool = False
    duration: float = 0.0
    total_out: int = 0
    total_in: int = 0
    total_heal: int = 0
    dps: float = 0.0
    rolling_dps: float = 0.0
    hps: float = 0.0
    hits: int = 0
    crits: int = 0
    misses: int = 0
    events: list[CombatEvent] = field(default_factory=list)
