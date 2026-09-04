"""Trigger rules: Boolean text conditions evaluated against every OCR line."""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field

from .models import Region

MATCH_MODES = ("contains", "exact", "regex")
LOGIC_MODES = ("all", "any")
RETRIGGER_MODES = ("restart", "replace", "ignore", "new")
OVERLAY_LAYOUTS = ("docked", "independent")
OVERLAY_SIZES = ("compact", "standard", "large")
BUILTIN_PREFIX = "builtin:"
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")

_GINA_STRING_TOKEN = re.compile(r"\{(?P<name>s\d*)\}", re.IGNORECASE)
_GINA_NUMBER_TOKEN = re.compile(r"\{(?P<name>n\d*)\}", re.IGNORECASE)
_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"


def normalize_regex(pattern: str) -> str:
    """Translate GINA/.NET regex conveniences into Python's dialect."""
    pattern = _GINA_STRING_TOKEN.sub(lambda m: f"(?P<{m.group('name').casefold()}>.+)", pattern)
    pattern = _GINA_NUMBER_TOKEN.sub(lambda m: f"(?P<{m.group('name').casefold()}>[\\d,]+)", pattern)
    pattern = re.sub(rf"\(\?<({_IDENT})>", r"(?P<\1>", pattern)
    pattern = re.sub(rf"\(\?'({_IDENT})'", r"(?P<\1>", pattern)
    pattern = re.sub(rf"\\k<({_IDENT})>", r"(?P=\1)", pattern)
    pattern = re.sub(rf"\\k'({_IDENT})'", r"(?P=\1)", pattern)
    return pattern


def compile_regex(pattern: str, flags: int = 0) -> re.Pattern:
    return re.compile(normalize_regex(pattern), flags)


def is_builtin_sound(sound: str) -> bool:
    return sound.startswith(BUILTIN_PREFIX)


@dataclass
class TriggerCondition:
    pattern: str = ""
    mode: str = "contains"
    negate: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "TriggerCondition":
        return cls(
            pattern=str(data.get("pattern", "")),
            mode=str(data.get("mode", "contains")).casefold(),
            negate=bool(data.get("negate", False)),
        )


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Trigger:
    id: str = field(default_factory=_new_id)
    name: str = "New trigger"
    folder: str = "General"
    profile: str = "Default"
    enabled: bool = True
    logic: str = "all"
    conditions: list[TriggerCondition] = field(default_factory=list)
    case_sensitive: bool = False
    window_seconds: float = 0.0
    cooldown_seconds: float = 2.0
    use_combat_region: bool = True
    region: Region | None = None
    sound: str = "builtin:Alert"
    volume: float = 0.85
    overlay_enabled: bool = False
    overlay_text: str = "{trigger}"
    timer_seconds: float = 0.0
    timer_key_template: str = ""
    retrigger_mode: str = "restart"
    bar_color: str = "#d39b47"
    overlay_text_color: str = "#e7edf4"
    timer_board: str = "Default"
    overlay_layout: str = "docked"
    overlay_size: str = "standard"
    overlay_opacity: float = 0.94
    overlay_geometry: str = ""
    overlay_positions: dict[str, str] = field(default_factory=dict)
    ending_soon_seconds: float = 5.0
    ending_sound: str = ""
    expiration_sound: str = ""
    start_speech: str = ""
    ending_speech: str = ""
    expiration_speech: str = ""
    end_pattern: str = ""
    end_mode: str = "contains"

    @classmethod
    def from_dict(cls, data: dict) -> "Trigger":
        def text(key: str, default: str = "") -> str:
            return str(data.get(key, default))

        def number(key: str, default: float) -> float:
            try:
                return float(data.get(key, default))
            except (TypeError, ValueError):
                return default

        positions = data.get("overlay_positions")
        return cls(
            id=text("id") or _new_id(),
            name=text("name", "New trigger"),
            folder=text("folder", "General"),
            profile=text("profile", "Default"),
            enabled=bool(data.get("enabled", True)),
            logic=text("logic", "all").casefold(),
            conditions=[TriggerCondition.from_dict(item)
                        for item in data.get("conditions", []) if isinstance(item, dict)],
            case_sensitive=bool(data.get("case_sensitive", False)),
            window_seconds=number("window_seconds", 0.0),
            cooldown_seconds=number("cooldown_seconds", 2.0),
            use_combat_region=bool(data.get("use_combat_region", True)),
            region=Region.from_dict(data.get("region")),
            sound=text("sound", "builtin:Alert"),
            volume=number("volume", 0.85),
            overlay_enabled=bool(data.get("overlay_enabled", False)),
            overlay_text=text("overlay_text", "{trigger}"),
            timer_seconds=number("timer_seconds", 0.0),
            timer_key_template=text("timer_key_template"),
            retrigger_mode=text("retrigger_mode", "restart").casefold(),
            bar_color=text("bar_color", "#d39b47"),
            overlay_text_color=text("overlay_text_color", "#e7edf4"),
            timer_board=text("timer_board", "Default").strip() or "Default",
            overlay_layout=text("overlay_layout", "docked").casefold(),
            overlay_size=text("overlay_size", "standard").casefold(),
            overlay_opacity=number("overlay_opacity", 0.94),
            overlay_geometry=text("overlay_geometry"),
            overlay_positions={str(k): str(v) for k, v in positions.items()} if isinstance(positions, dict) else {},
            ending_soon_seconds=number("ending_soon_seconds", 5.0),
            ending_sound=text("ending_sound"),
            expiration_sound=text("expiration_sound"),
            start_speech=text("start_speech"),
            ending_speech=text("ending_speech"),
            expiration_speech=text("expiration_speech"),
            end_pattern=text("end_pattern"),
            end_mode=text("end_mode", "contains").casefold(),
        )

    def source_key(self) -> str:
        """Identity of the OCR feed this trigger listens to."""
        if self.use_combat_region:
            return "combat"
        if not self.region:
            return "missing"
        return f"region:{self.region.left}:{self.region.top}:{self.region.width}:{self.region.height}"

    def has_custom_sound(self) -> bool:
        return bool(self.sound) and not is_builtin_sound(self.sound)

    def validate(self) -> list[str]:
        errors: list[str] = []
        for label, value in (("Trigger name", self.name), ("Folder", self.folder),
                             ("Profile", self.profile), ("Timer board", self.timer_board)):
            if not value.strip():
                errors.append(f"{label} is required.")
        if self.logic not in LOGIC_MODES:
            errors.append("Boolean logic must be ALL or ANY.")
        if not self.use_combat_region and not self.region:
            errors.append("Select a dedicated OCR region.")
        if not 0.0 <= self.window_seconds <= 30.0:
            errors.append("Match window must be between 0 and 30 seconds.")
        if not 0.0 <= self.cooldown_seconds <= 3600.0:
            errors.append("Cooldown must be between 0 and 3600 seconds.")
        if not 0.0 <= self.volume <= 1.0:
            errors.append("Volume must be between 0 and 100 percent.")
        if self.retrigger_mode not in RETRIGGER_MODES:
            errors.append("Retrigger behavior is invalid.")
        if self.overlay_layout not in OVERLAY_LAYOUTS:
            errors.append("Overlay layout must be Timer boards or Independent.")
        if self.overlay_size not in OVERLAY_SIZES:
            errors.append("Overlay size must be Compact, Standard, or Large.")
        if not 0.2 <= self.overlay_opacity <= 1.0:
            errors.append("Overlay opacity must be between 20 and 100 percent.")
        if not 0.0 <= self.timer_seconds <= 86_400.0:
            errors.append("Timer duration must be between 0 and 86400 seconds.")
        if not 0.0 <= self.ending_soon_seconds <= 86_400.0:
            errors.append("Ending-soon time must be between 0 and 86400 seconds.")
        for label, color in (("Bar", self.bar_color), ("Text", self.overlay_text_color)):
            if not HEX_COLOR.fullmatch(color):
                errors.append(f"{label} color must use #RRGGBB format.")
        if self.end_mode not in MATCH_MODES:
            errors.append("Early-ending match type is invalid.")
        if self.end_pattern and self.end_mode == "regex":
            try:
                compile_regex(self.end_pattern)
            except re.error as exc:
                errors.append(f"Early-ending regex: {exc}.")
        if not any(not condition.negate for condition in self.conditions):
            errors.append("Add at least one positive condition.")
        for index, condition in enumerate(self.conditions, start=1):
            if not condition.pattern.strip():
                errors.append(f"Condition {index} is empty.")
            if condition.mode not in MATCH_MODES:
                errors.append(f"Condition {index} has an invalid match type.")
            elif condition.mode == "regex" and condition.pattern:
                try:
                    compile_regex(condition.pattern)
                except re.error as exc:
                    errors.append(f"Condition {index} regex: {exc}.")
        return errors


@dataclass(slots=True)
class TriggerMatch:
    trigger_id: str
    trigger_name: str
    sound: str
    volume: float
    text: str
    captures: dict[str, str] = field(default_factory=dict)
    action: str = "fire"  # "fire" or "end"


@dataclass(slots=True)
class ConditionDiagnostic:
    pattern: str
    mode: str
    negate: bool
    matched_this_line: bool
    active: bool
    captures: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class TriggerDiagnostic:
    trigger_id: str
    trigger_name: str
    source_matches: bool
    logic: str
    conditions: list[ConditionDiagnostic] = field(default_factory=list)
    blocked: bool = False
    condition_met: bool = False
    cooldown_remaining: float = 0.0
    fired: bool = False
    ended_timer: bool = False


@dataclass
class _TriggerState:
    matched_at: dict[int, float] = field(default_factory=dict)
    captures_at: dict[int, dict[str, str]] = field(default_factory=dict)
    last_fired_at: float = float("-inf")


END_PATTERN_INDEX = -1


class TriggerEngine:
    """Evaluate enabled, valid triggers against OCR lines with windows and cooldowns."""

    def __init__(self, triggers: list[Trigger]) -> None:
        # Validate and compile once; the OCR loop must not pay for it per line.
        self.triggers = [trigger for trigger in triggers if trigger.enabled and not trigger.validate()]
        self._states = {trigger.id: _TriggerState() for trigger in self.triggers}
        self._regex: dict[tuple[str, int], re.Pattern] = {}
        self.last_diagnostics: list[TriggerDiagnostic] = []
        for trigger in self.triggers:
            flags = 0 if trigger.case_sensitive else re.IGNORECASE
            patterns = [(index, condition.pattern, condition.mode)
                        for index, condition in enumerate(trigger.conditions)]
            patterns.append((END_PATTERN_INDEX, trigger.end_pattern, trigger.end_mode))
            for index, pattern, mode in patterns:
                if mode == "regex" and pattern:
                    try:
                        self._regex[(trigger.id, index)] = compile_regex(pattern, flags)
                    except re.error:
                        pass  # validate() already rejected these; keep the worker alive regardless

    def process(self, text: str, source_key: str, now: float | None = None) -> list[TriggerMatch]:
        now = time.monotonic() if now is None else now
        fired: list[TriggerMatch] = []
        self.last_diagnostics = []
        for trigger in self.triggers:
            if trigger.source_key() != source_key:
                self.last_diagnostics.append(TriggerDiagnostic(trigger.id, trigger.name, False, trigger.logic))
                continue
            state = self._states[trigger.id]
            ended, end_captures = (
                self._matches(trigger, END_PATTERN_INDEX, trigger.end_pattern, trigger.end_mode, text)
                if trigger.end_pattern else (False, {})
            )
            if ended:
                fired.append(TriggerMatch(trigger.id, trigger.name, "", trigger.volume, text,
                                          captures=end_captures, action="end"))

            results = [self._matches(trigger, index, condition.pattern, condition.mode, text)
                       for index, condition in enumerate(trigger.conditions)]
            current = [matched for matched, _captures in results]
            if trigger.window_seconds > 0:
                cutoff = now - trigger.window_seconds
                state.matched_at = {i: t for i, t in state.matched_at.items() if t >= cutoff}
                state.captures_at = {i: c for i, c in state.captures_at.items() if i in state.matched_at}
                for index, (matched, captures) in enumerate(results):
                    if matched:
                        state.matched_at[index] = now
                        state.captures_at[index] = captures
                active = [index in state.matched_at for index in range(len(current))]
            else:
                active = current

            positives = [active[i] for i, c in enumerate(trigger.conditions) if not c.negate]
            blocked = any(active[i] for i, c in enumerate(trigger.conditions) if c.negate)
            condition_met = (all(positives) if trigger.logic == "all" else any(positives)) and not blocked
            cooldown_remaining = max(0.0, trigger.cooldown_seconds - (now - state.last_fired_at))
            diagnostic = TriggerDiagnostic(
                trigger_id=trigger.id, trigger_name=trigger.name, source_matches=True,
                logic=trigger.logic,
                conditions=[
                    ConditionDiagnostic(
                        condition.pattern, condition.mode, condition.negate,
                        results[i][0], active[i], results[i][1] or state.captures_at.get(i, {}),
                    )
                    for i, condition in enumerate(trigger.conditions)
                ],
                blocked=blocked, condition_met=condition_met,
                cooldown_remaining=cooldown_remaining, ended_timer=ended,
            )
            self.last_diagnostics.append(diagnostic)
            if not condition_met or cooldown_remaining > 0:
                continue

            state.last_fired_at = now
            captures: dict[str, str] = {}
            if trigger.window_seconds > 0:
                for index in sorted(state.captures_at):
                    captures.update(state.captures_at[index])
            else:
                for matched, found in results:
                    if matched:
                        captures.update(found)
            # Consume the positive matches so a windowed rule cannot re-fire on
            # unrelated text once its cooldown lapses.
            for index, condition in enumerate(trigger.conditions):
                if not condition.negate:
                    state.matched_at.pop(index, None)
                    state.captures_at.pop(index, None)
            fired.append(TriggerMatch(trigger.id, trigger.name, trigger.sound, trigger.volume, text,
                                      captures=captures))
            diagnostic.fired = True
        return fired

    def _matches(self, trigger: Trigger, index: int, pattern: str, mode: str,
                 text: str) -> tuple[bool, dict[str, str]]:
        if mode == "regex":
            compiled = self._regex.get((trigger.id, index))
            match = compiled.search(text) if compiled else None
            if not match:
                return False, {}
            captures = {key: value for key, value in match.groupdict().items() if value is not None}
            for position, value in enumerate(match.groups(), start=1):
                if value is not None:
                    captures.setdefault(f"${position}", value)
            return True, captures
        if not trigger.case_sensitive:
            pattern, text = pattern.casefold(), text.casefold()
        if mode == "exact":
            return text.strip() == pattern.strip(), {}
        return pattern in text, {}
