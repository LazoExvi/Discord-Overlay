"""Persistent settings with per-character profiles.

Shared settings (scan rate, OCR thresholds, speech, triggers) apply to every
character. Character-specific settings (capture region, timer boards, active
trigger profile, group filter) are snapshotted per character; the active
character's snapshot is mirrored into the live fields listed in
``CHARACTER_FIELDS``. The character name doubles as the player name used for
You/Your attribution.
"""
from __future__ import annotations

import copy
import json
import uuid
from dataclasses import MISSING, asdict, dataclass, field
from pathlib import Path

from .models import Region
from .paths import settings_path
from .triggers import OVERLAY_LAYOUTS, OVERLAY_SIZES, Trigger

SCHEMA_VERSION = 1
PLACEHOLDER_CHARACTER = "Default"
PLACEHOLDER_PLAYER = "You"
REGION_HISTORY_SIZE = 8
BOARD_SORT_ORDERS = ("started", "remaining", "name")
BOARD_GROWTH = ("rows", "columns")
MODIFIERS = ("control", "shift", "alt")
SPEECH_MODES = ("queue", "interrupt")

CHARACTER_FIELDS: tuple[str, ...] = (
    "region", "region_history", "timer_boards", "timer_layout", "timer_visual_size",
    "active_trigger_profile", "trigger_states", "actor_filter_enabled", "allowed_actor_names",
    "pet_names", "mini_overlay_enabled", "mini_overlay_geometry",
)
MINI_METRICS = ("damage", "healing")
# Header stats the mini meter can show; the user picks up to MINI_STAT_SLOTS of them.
MINI_STATS: dict[str, str] = {
    "dps": "Encounter DPS", "rolling_dps": "10s DPS", "damage": "Damage", "incoming": "Incoming",
    "healing": "Healing", "hps": "HPS", "duration": "Duration",
}
MINI_STAT_SLOTS = 4
DEFAULT_MINI_STATS = ["dps", "rolling_dps", "damage", "healing"]


def _choice(value, allowed: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().casefold()
    return text if text in allowed else default


def _clamp(value, low: float, high: float, default: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def _field_default(name: str):
    info = Settings.__dataclass_fields__[name]
    if info.default_factory is not MISSING:
        return info.default_factory()
    return info.default


@dataclass
class TimerBoard:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "Default"
    geometry: str = ""
    positioned: bool = False
    columns: int = 1
    visual_size: str = "standard"
    opacity: float = 0.94
    sort_order: str = "started"
    growth_direction: str = "rows"

    @classmethod
    def from_dict(cls, data: dict) -> "TimerBoard":
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex),
            name=str(data.get("name") or "Default").strip() or "Default",
            geometry=str(data.get("geometry", "")),
            positioned=bool(data.get("positioned", False)),
            columns=int(_clamp(data.get("columns", 1), 1, 6, 1)),
            visual_size=_choice(data.get("visual_size"), OVERLAY_SIZES, "standard"),
            opacity=_clamp(data.get("opacity", 0.94), 0.2, 1.0, 0.94),
            sort_order=_choice(data.get("sort_order"), BOARD_SORT_ORDERS, "started"),
            growth_direction=_choice(data.get("growth_direction"), BOARD_GROWTH, "rows"),
        )


@dataclass
class CharacterProfile:
    name: str = PLACEHOLDER_CHARACTER
    data: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, item: dict) -> "CharacterProfile":
        data = item.get("data")
        return cls(
            name=str(item.get("name") or PLACEHOLDER_CHARACTER).strip() or PLACEHOLDER_CHARACTER,
            data=dict(data) if isinstance(data, dict) else {},
        )


@dataclass
class Settings:
    schema_version: int = SCHEMA_VERSION
    # -- shared -------------------------------------------------------------
    scan_interval: float = 0.22
    encounter_timeout: float = 8.0
    rolling_window: float = 10.0
    min_confidence: float = 0.52
    combine_pet_damage: bool = True
    damage_shields_by_wearer: bool = False
    keep_running_totals: bool = False
    always_on_top: bool = True
    prefer_gpu: bool = True
    save_debug_images: bool = False
    repair_occluded_lines: bool = True
    events_column_order: list[str] = field(default_factory=list)
    breakdown_column_order: list[str] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    setup_completed: bool = False
    performance_profile: str = "Not tested"
    benchmark_ocr_ms: float = 0.0
    benchmark_capture_ms: float = 0.0
    benchmark_provider: str = ""
    overlay_close_enabled: bool = True
    overlay_close_modifier1: str = "control"
    overlay_close_modifier2: str = "shift"
    speech_voice: str = ""
    speech_rate: int = 0
    speech_volume: int = 100
    speech_queue_mode: str = "queue"
    shortcut_prompted: bool = False
    mini_overlay_rows: int = 6
    mini_overlay_opacity: float = 0.9
    mini_overlay_metric: str = "damage"
    mini_overlay_stats: list[str] = field(default_factory=lambda: list(DEFAULT_MINI_STATS))
    characters: list[CharacterProfile] = field(default_factory=list)
    active_character: str = PLACEHOLDER_CHARACTER
    # -- per character (live copy of the active profile) --------------------
    region: Region | None = None
    region_history: list[Region] = field(default_factory=list)
    timer_boards: list[TimerBoard] = field(default_factory=lambda: [TimerBoard()])
    timer_layout: str = "docked"
    timer_visual_size: str = "standard"
    active_trigger_profile: str = "Default"
    trigger_states: dict[str, bool] = field(default_factory=dict)  # trigger id -> enabled, per character
    actor_filter_enabled: bool = False
    allowed_actor_names: list[str] = field(default_factory=list)
    pet_names: list[str] = field(default_factory=list)
    mini_overlay_enabled: bool = False
    mini_overlay_geometry: str = ""

    def __post_init__(self) -> None:
        self._normalize_characters()

    # -- derived ------------------------------------------------------------

    @property
    def player_name(self) -> str:
        """The character name, or ``You`` for the unnamed placeholder profile."""
        name = self.active_character.strip()
        return PLACEHOLDER_PLAYER if not name or name.casefold() == PLACEHOLDER_CHARACTER.casefold() else name

    # -- persistence --------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = settings_path() if path is None else path
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls.from_dict(data) if isinstance(data, dict) else cls()

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        data = dict(data)
        region_data = data.pop("region", None)
        history_data = data.pop("region_history", [])
        trigger_data = data.pop("triggers", [])
        board_data = data.pop("timer_boards", [])
        character_data = data.pop("characters", [])
        legacy_player_name = str(data.pop("player_name", "") or "").strip()
        known = cls.__dataclass_fields__.keys()
        scalars = {key: value for key, value in data.items() if key in known}
        # Build without running __post_init__'s normalization until every field is set.
        settings = cls.__new__(cls)
        for name in cls.__dataclass_fields__:
            setattr(settings, name, scalars[name] if name in scalars else _field_default(name))
        settings.region = Region.from_dict(region_data)
        settings.region_history = [r for r in (Region.from_dict(i) for i in history_data) if r]
        settings.triggers = [Trigger.from_dict(i) for i in trigger_data if isinstance(i, dict)]
        settings.timer_boards = [TimerBoard.from_dict(i) for i in board_data if isinstance(i, dict)]
        settings.characters = [CharacterProfile.from_dict(i) for i in character_data if isinstance(i, dict)]
        if (not settings.characters and legacy_player_name
                and legacy_player_name.casefold() != PLACEHOLDER_PLAYER.casefold()
                and str(settings.active_character).casefold() == PLACEHOLDER_CHARACTER.casefold()):
            settings.active_character = legacy_player_name
        settings.schema_version = SCHEMA_VERSION
        settings._normalize_characters()
        return settings

    def to_dict(self) -> dict:
        self.store_active_character()
        return asdict(self)

    def save(self, path: Path | None = None) -> None:
        path = settings_path() if path is None else path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    # -- validation ---------------------------------------------------------

    def _sanitize(self) -> None:
        self.scan_interval = _clamp(self.scan_interval, 0.15, 5.0, 0.22)
        self.encounter_timeout = _clamp(self.encounter_timeout, 2.0, 60.0, 8.0)
        self.rolling_window = _clamp(self.rolling_window, 2.0, 60.0, 10.0)
        self.min_confidence = _clamp(self.min_confidence, 0.1, 0.99, 0.52)
        self.speech_rate = int(_clamp(self.speech_rate, -10, 10, 0))
        self.speech_volume = int(_clamp(self.speech_volume, 0, 100, 100))
        self.speech_queue_mode = _choice(self.speech_queue_mode, SPEECH_MODES, "queue")
        self.overlay_close_modifier1 = _choice(self.overlay_close_modifier1, MODIFIERS, "control")
        self.overlay_close_modifier2 = _choice(self.overlay_close_modifier2, MODIFIERS + ("none",), "shift")
        if self.overlay_close_modifier2 == self.overlay_close_modifier1:
            self.overlay_close_modifier2 = "none"
        self.timer_layout = _choice(self.timer_layout, OVERLAY_LAYOUTS, "docked")
        self.timer_visual_size = _choice(self.timer_visual_size, OVERLAY_SIZES, "standard")
        self.mini_overlay_rows = int(_clamp(self.mini_overlay_rows, 1, 12, 6))
        self.mini_overlay_opacity = _clamp(self.mini_overlay_opacity, 0.2, 1.0, 0.9)
        self.mini_overlay_metric = _choice(self.mini_overlay_metric, MINI_METRICS, "damage")
        stats: list[str] = []
        for key in self.mini_overlay_stats or []:
            key = str(key).strip().casefold()
            if key in MINI_STATS and key not in stats:
                stats.append(key)
        self.mini_overlay_stats = stats[:MINI_STAT_SLOTS]
        self.mini_overlay_enabled = bool(self.mini_overlay_enabled)
        self.mini_overlay_geometry = str(self.mini_overlay_geometry or "")
        self.active_trigger_profile = str(self.active_trigger_profile or "Default").strip() or "Default"
        self.allowed_actor_names = [str(n).strip() for n in self.allowed_actor_names if str(n).strip()]
        self.pet_names = [str(n).strip() for n in (self.pet_names or []) if str(n).strip()]
        known_ids = {trigger.id for trigger in self.triggers}
        self.trigger_states = {
            str(key): bool(value) for key, value in dict(self.trigger_states or {}).items() if str(key) in known_ids
        }
        self.events_column_order = [str(c) for c in self.events_column_order]
        self.breakdown_column_order = [str(c) for c in self.breakdown_column_order]
        if not self.timer_boards:
            self.timer_boards = [TimerBoard()]
        board_names = {board.name.casefold() for board in self.timer_boards}
        default_board = self.timer_boards[0].name
        for trigger in self.triggers:
            if trigger.timer_board.casefold() not in board_names:
                trigger.timer_board = default_board

    # -- regions ------------------------------------------------------------

    def remember_region(self, region: Region) -> None:
        """Move a valid region to the front of the bounded recent-region list."""
        if not region.valid():
            return
        self.region_history = [item for item in self.region_history if item != region]
        self.region_history.insert(0, region)
        del self.region_history[REGION_HISTORY_SIZE:]

    # -- triggers -----------------------------------------------------------

    def trigger_by_id(self, trigger_id: str) -> Trigger | None:
        return next((t for t in self.triggers if t.id == trigger_id), None)

    def triggers_in_profile(self, profile: str | None = None) -> list[Trigger]:
        wanted = (self.active_trigger_profile if profile is None else profile).casefold()
        return [t for t in self.triggers if t.profile.casefold() == wanted]

    def trigger_profiles(self) -> list[str]:
        profiles = {t.profile.strip() for t in self.triggers if t.profile.strip()}
        profiles.update({self.active_trigger_profile or "Default", "Default"})
        return sorted(profiles, key=str.casefold)

    # Triggers are shared by every character; whether each one is switched on is
    # remembered per character, falling back to the trigger's own ``enabled`` flag.

    def trigger_enabled(self, trigger: Trigger) -> bool:
        return self.trigger_states.get(trigger.id, trigger.enabled)

    def set_trigger_enabled(self, trigger_id: str, enabled: bool) -> None:
        self.trigger_states[trigger_id] = bool(enabled)

    def effective_triggers(self, profile: str | None = None) -> list[Trigger]:
        """Copies of the profile's triggers with ``enabled`` resolved for this character."""
        resolved = []
        for trigger in self.triggers_in_profile(profile):
            item = copy.deepcopy(trigger)
            item.enabled = self.trigger_enabled(trigger)
            resolved.append(item)
        return resolved

    def upsert_trigger(self, trigger: Trigger) -> None:
        for index, existing in enumerate(self.triggers):
            if existing.id == trigger.id:
                self.triggers[index] = trigger
                break
        else:
            self.triggers.append(trigger)
        self.set_trigger_enabled(trigger.id, trigger.enabled)

    def remove_trigger(self, trigger_id: str) -> None:
        self.triggers = [t for t in self.triggers if t.id != trigger_id]
        self.trigger_states.pop(trigger_id, None)
        for profile in self.characters:
            states = profile.data.get("trigger_states")
            if isinstance(states, dict):
                states.pop(trigger_id, None)

    def timer_board(self, name: str) -> TimerBoard:
        return next((b for b in self.timer_boards if b.name.casefold() == name.casefold()),
                    self.timer_boards[0])

    def board_names(self) -> list[str]:
        return [board.name for board in self.timer_boards]

    def ensure_board(self, name: str) -> TimerBoard:
        board = next((b for b in self.timer_boards if b.name.casefold() == name.casefold()), None)
        if board is None:
            board = TimerBoard(name=name)
            self.timer_boards.append(board)
        return board

    # -- character profiles -------------------------------------------------

    def character_snapshot(self) -> dict:
        payload = asdict(self)
        return {key: payload[key] for key in CHARACTER_FIELDS}

    def _apply_character_data(self, data: dict) -> None:
        for key in CHARACTER_FIELDS:
            setattr(self, key, copy.deepcopy(data[key]) if key in data else _field_default(key))
        self.region = self.region if isinstance(self.region, Region) else Region.from_dict(self.region)
        self.region_history = [
            item if isinstance(item, Region) else Region.from_dict(item) for item in self.region_history
        ]
        self.region_history = [item for item in self.region_history if item]
        self.timer_boards = [
            item if isinstance(item, TimerBoard) else TimerBoard.from_dict(item)
            for item in self.timer_boards if isinstance(item, (dict, TimerBoard))
        ]
        self._sanitize()

    def character(self, name: str) -> CharacterProfile | None:
        return next((c for c in self.characters if c.name.casefold() == name.casefold()), None)

    def character_names(self) -> list[str]:
        return [c.name for c in self.characters]

    def _ensure_active_character(self) -> CharacterProfile:
        self.active_character = str(self.active_character or PLACEHOLDER_CHARACTER).strip() or PLACEHOLDER_CHARACTER
        if not self.characters:
            self._sanitize()
            self.characters = [CharacterProfile(self.active_character, self.character_snapshot())]
        active = self.character(self.active_character) or self.characters[0]
        self.active_character = active.name
        return active

    def _normalize_characters(self) -> None:
        self._apply_character_data(self._ensure_active_character().data)

    def store_active_character(self) -> None:
        self._ensure_active_character().data = self.character_snapshot()

    def switch_character(self, name: str) -> bool:
        target = self.character(name)
        if target is None:
            return False
        self.store_active_character()
        self.active_character = target.name
        self._apply_character_data(target.data)
        return True

    def add_character(self, name: str, copy_current: bool = True) -> CharacterProfile:
        name = name.strip()
        if not name:
            raise ValueError("Character name cannot be empty.")
        if self.character(name) is not None:
            raise ValueError("That character already exists.")
        self.store_active_character()
        profile = CharacterProfile(name, self.character_snapshot() if copy_current else {})
        self.characters.append(profile)
        return profile

    def rename_character(self, old_name: str, new_name: str) -> None:
        new_name = new_name.strip()
        profile = self.character(old_name)
        if profile is None:
            raise ValueError("Unknown character.")
        if not new_name:
            raise ValueError("Character name cannot be empty.")
        existing = self.character(new_name)
        if existing is not None and existing is not profile:
            raise ValueError("That character already exists.")
        if self.active_character.casefold() == profile.name.casefold():
            self.active_character = new_name
        profile.name = new_name

    def delete_character(self, name: str) -> None:
        profile = self.character(name)
        if profile is None:
            raise ValueError("Unknown character.")
        if len(self.characters) <= 1:
            raise ValueError("At least one character is required.")
        self.characters.remove(profile)
        if self.active_character.casefold() == profile.name.casefold():
            self.active_character = self.characters[0].name
            self._apply_character_data(self.characters[0].data)
