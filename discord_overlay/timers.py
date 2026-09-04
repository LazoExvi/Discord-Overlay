"""Countdown timers started by triggers, plus ``{capture}`` template rendering."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from .triggers import Trigger, TriggerMatch


class _TemplateValues(dict):
    """Case-insensitive lookup that leaves unknown ``{placeholders}`` in place."""

    def __missing__(self, key: str) -> str:
        folded = key.casefold()
        for existing, value in self.items():
            if existing.casefold() == folded:
                return value
        return "{" + key + "}"


def render_template(template: str, trigger: Trigger, match: TriggerMatch) -> str:
    values = _TemplateValues(match.captures)
    values.update(trigger=trigger.name, text=match.text)
    try:
        return template.format_map(values)
    except (ValueError, AttributeError, IndexError):
        return template


@dataclass(slots=True)
class TimerInstance:
    id: str
    trigger_id: str
    key: str
    label: str
    started_at: float
    ends_at: float
    duration: float
    show_bar: bool
    bar_color: str
    text_color: str
    timer_board: str
    overlay_layout: str
    overlay_size: str
    overlay_opacity: float
    overlay_geometry: str
    placement_key: str
    ending_soon_seconds: float
    ending_sound: str
    expiration_sound: str
    volume: float
    ending_speech: str
    expiration_speech: str
    captures: dict[str, str] = field(default_factory=dict)
    ending_notified: bool = False

    def remaining(self, now: float) -> float:
        return max(0.0, self.ends_at - now)

    def fraction(self, now: float) -> float:
        return min(1.0, max(0.0, self.remaining(now) / max(0.001, self.duration)))


@dataclass(slots=True)
class TimerNotification:
    kind: str  # "ending", "expired", or "ended"
    timer: TimerInstance


ALERT_ONLY_SECONDS = 5.0


class TimerManager:
    """Own timer identity, retrigger behavior, and lifecycle notifications."""

    def __init__(self, overlay_layout: str = "docked", overlay_size: str = "standard") -> None:
        self.timers: dict[str, TimerInstance] = {}
        self.overlay_layout = overlay_layout
        self.overlay_size = overlay_size

    def start(self, trigger: Trigger, match: TriggerMatch, now: float | None = None) -> TimerInstance | None:
        if not trigger.overlay_enabled:
            return None
        now = time.monotonic() if now is None else now
        duration = trigger.timer_seconds if trigger.timer_seconds > 0 else ALERT_ONLY_SECONDS
        rendered_key = render_template(trigger.timer_key_template, trigger, match).strip()
        base_key = rendered_key or trigger.id
        matching = [t for t in self.timers.values() if t.trigger_id == trigger.id and t.key == base_key]

        if trigger.retrigger_mode == "ignore" and matching:
            return None
        if trigger.retrigger_mode == "replace":
            self._remove_trigger(trigger.id)
        elif trigger.retrigger_mode == "restart" and matching:
            timer = matching[0]
            self._fill(timer, trigger, match, base_key, now, duration)
            return timer

        key = f"{base_key}:{uuid.uuid4().hex}" if trigger.retrigger_mode == "new" else base_key
        timer = TimerInstance(
            id=uuid.uuid4().hex, trigger_id=trigger.id, key=key, label="", started_at=now,
            ends_at=now + duration, duration=duration, show_bar=trigger.timer_seconds > 0,
            bar_color=trigger.bar_color, text_color=trigger.overlay_text_color,
            timer_board=trigger.timer_board, overlay_layout=self.overlay_layout,
            overlay_size=self.overlay_size, overlay_opacity=trigger.overlay_opacity,
            overlay_geometry=trigger.overlay_geometry, placement_key=base_key,
            ending_soon_seconds=trigger.ending_soon_seconds, ending_sound=trigger.ending_sound,
            expiration_sound=trigger.expiration_sound, volume=trigger.volume,
            ending_speech="", expiration_speech="",
        )
        self._fill(timer, trigger, match, key, now, duration)
        self.timers[timer.id] = timer
        return timer

    def _fill(self, timer: TimerInstance, trigger: Trigger, match: TriggerMatch,
              key: str, now: float, duration: float) -> None:
        timer.key = key
        timer.label = render_template(trigger.overlay_text or "{trigger}", trigger, match)
        timer.started_at = now
        timer.ends_at = now + duration
        timer.duration = duration
        timer.show_bar = trigger.timer_seconds > 0
        timer.bar_color = trigger.bar_color
        timer.text_color = trigger.overlay_text_color
        timer.timer_board = trigger.timer_board
        timer.overlay_layout = self.overlay_layout
        timer.overlay_size = self.overlay_size
        timer.overlay_opacity = trigger.overlay_opacity
        timer.placement_key = key.rsplit(":", 1)[0] if trigger.retrigger_mode == "new" else key
        timer.overlay_geometry = trigger.overlay_positions.get(timer.placement_key, trigger.overlay_geometry)
        timer.ending_soon_seconds = trigger.ending_soon_seconds
        timer.ending_sound = trigger.ending_sound
        timer.expiration_sound = trigger.expiration_sound
        timer.volume = trigger.volume
        timer.ending_speech = render_template(trigger.ending_speech, trigger, match)
        timer.expiration_speech = render_template(trigger.expiration_speech, trigger, match)
        timer.captures = dict(match.captures)
        timer.ending_notified = False

    def end(self, trigger: Trigger, match: TriggerMatch) -> list[TimerNotification]:
        """Stop timers for an early-ending match; a complete key ends only that target."""
        rendered_key = render_template(trigger.timer_key_template, trigger, match).strip()
        has_complete_key = bool(trigger.timer_key_template.strip()) and "{" not in rendered_key
        matching = [
            timer for timer in self.timers.values()
            if timer.trigger_id == trigger.id
            and (not has_complete_key or timer.key == rendered_key or timer.key.startswith(rendered_key + ":"))
        ]
        # Same-name mobs share a display name, so a wear-off line ends the oldest copy.
        if trigger.retrigger_mode == "new" and has_complete_key and matching:
            matching = [min(matching, key=lambda timer: (timer.started_at, timer.id))]
        for timer in matching:
            self.timers.pop(timer.id, None)
        return [TimerNotification("ended", timer) for timer in matching]

    def tick(self, now: float | None = None) -> list[TimerNotification]:
        now = time.monotonic() if now is None else now
        notifications: list[TimerNotification] = []
        for timer_id, timer in list(self.timers.items()):
            remaining = timer.remaining(now)
            if remaining <= 0:
                self.timers.pop(timer_id, None)
                notifications.append(TimerNotification("expired", timer))
            elif (timer.show_bar and 0 < timer.ending_soon_seconds >= remaining
                  and not timer.ending_notified):
                timer.ending_notified = True
                notifications.append(TimerNotification("ending", timer))
        return notifications

    def clear(self) -> None:
        self.timers.clear()

    def dismiss(self, timer_id: str) -> TimerInstance | None:
        return self.timers.pop(timer_id, None)

    def remove_where(self, predicate) -> None:
        for timer_id in [t.id for t in self.timers.values() if predicate(t)]:
            self.timers.pop(timer_id, None)

    def _remove_trigger(self, trigger_id: str) -> None:
        self.remove_where(lambda timer: timer.trigger_id == trigger_id)
