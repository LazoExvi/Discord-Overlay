"""Owns every overlay window and decides which timers appear where."""
from __future__ import annotations

import ctypes
import os
import re
import time
import tkinter as tk
from collections.abc import Callable
from ctypes import wintypes

from ..capture import monitor_containing
from ..config import Settings, TimerBoard
from ..timers import TimerInstance, TimerManager
from ..triggers import Trigger, TriggerMatch
from .overlay import TimerOverlay

DEFAULT_SIZE = (420, 320)
INDEPENDENT_SIZES = {"compact": (250, 80), "standard": (360, 125), "large": (540, 210)}
STACK_OFFSET = 28
VIRTUAL_KEYS = {"control": 0x11, "shift": 0x10, "alt": 0x12}
VK_LBUTTON = 0x01
PREVIEW_CAPTURES = {"target": "Sample Target", "spell": "Sample Spell", "player": "Sample Player", "amount": "1,234"}
BOARD_PREVIEW_PREFIX = "board-preview-"


def offset_geometry(geometry: str, index: int) -> str:
    match = re.fullmatch(r"(\d+x\d+)([+-]\d+)([+-]\d+)", geometry)
    if not match or index <= 0:
        return geometry
    delta = index * STACK_OFFSET
    return f"{match.group(1)}{int(match.group(2)) + delta:+d}{int(match.group(3)) + delta:+d}"


class OverlayManager:
    def __init__(self, root: tk.Misc, settings: Settings, timers: TimerManager,
                 status: Callable[[str, str], None]) -> None:
        self.root = root
        self.settings = settings
        self.timers = timers
        self.status = status
        self.board_overlays: dict[str, TimerOverlay] = {}
        self.independent_overlays: dict[tuple[str, str], TimerOverlay] = {}
        self._left_down = False

    # -- lifecycle ------------------------------------------------------------

    def all(self) -> list[TimerOverlay]:
        return [overlay for overlay in (*self.board_overlays.values(), *self.independent_overlays.values())
                if overlay.winfo_exists()]

    def destroy_all(self) -> None:
        for overlay in self.all():
            overlay.destroy()
        self.board_overlays.clear()
        self.independent_overlays.clear()

    def reset_for_character(self) -> None:
        self.destroy_all()
        self.timers.clear()
        self.sync_layout()

    def sync_layout(self) -> None:
        """Push the saved layout and independent size onto the manager and live timers."""
        self.timers.overlay_layout = self.settings.timer_layout
        self.timers.overlay_size = self.settings.timer_visual_size
        for timer in self.timers.timers.values():
            timer.overlay_layout = self.settings.timer_layout
            if self.settings.timer_layout == "independent":
                timer.overlay_size = self.settings.timer_visual_size

    def forget_board(self, board_id: str) -> None:
        overlay = self.board_overlays.pop(board_id, None)
        if overlay and overlay.winfo_exists():
            overlay.destroy()

    def rename_board(self, old_name: str, new_name: str) -> None:
        for trigger in self.settings.triggers:
            if trigger.timer_board.casefold() == old_name.casefold():
                trigger.timer_board = new_name
        for timer in self.timers.timers.values():
            if timer.timer_board.casefold() == old_name.casefold():
                timer.timer_board = new_name

    # -- geometry -------------------------------------------------------------

    def _anchor_geometry(self) -> str:
        """A default position just above (or below) the combat region."""
        width, height = DEFAULT_SIZE
        region = self.settings.region
        if region is None:
            return f"{width}x{height}+40+80"
        x = region.left + max(0, (region.width - width) // 2)
        y = region.top - height - 24
        try:
            monitor = monitor_containing(region.left + region.width // 2, region.top + region.height // 2)
        except Exception:  # noqa: BLE001 - the region is still a better anchor than (0, 0)
            monitor = None
        if monitor:
            right = monitor["left"] + monitor["width"]
            bottom = monitor["top"] + monitor["height"]
            x = min(max(x, monitor["left"] + 12), right - width - 12)
            if y < monitor["top"] + 12:
                below = region.top + region.height + 24
                y = below if below + height <= bottom - 12 else region.top + 24
            y = min(max(y, monitor["top"] + 12), bottom - height - 12)
        return f"{width}x{height}{x:+d}{y:+d}"

    def _board_overlay(self, board: TimerBoard) -> TimerOverlay:
        overlay = self.board_overlays.get(board.id)
        if overlay is None or not overlay.winfo_exists():
            geometry = board.geometry if board.positioned and board.geometry else ""
            if not geometry:
                geometry = offset_geometry(self._anchor_geometry(), self.settings.timer_boards.index(board))
            overlay = TimerOverlay(self.root, geometry,
                                   lambda value, board_id=board.id: self._board_moved(board_id, value),
                                   display_name=board.name)
            self.board_overlays[board.id] = overlay
        return overlay

    def _board_moved(self, board_id: str, geometry: str) -> None:
        board = next((item for item in self.settings.timer_boards if item.id == board_id), None)
        if board is not None:
            board.geometry = geometry
            board.positioned = True
            self.settings.save()

    def _independent_overlay(self, source: TimerInstance | Trigger, index: int = 0) -> TimerOverlay:
        is_timer = isinstance(source, TimerInstance)
        trigger_id = source.trigger_id if is_timer else source.id
        placement_key = source.placement_key if is_timer else source.id
        surface_key = (trigger_id, placement_key)
        overlay = self.independent_overlays.get(surface_key)
        if overlay is None or not overlay.winfo_exists():
            geometry = source.overlay_geometry
            saved = self.settings.trigger_by_id(trigger_id)
            has_saved_key = bool(saved and placement_key in saved.overlay_positions)
            if geometry and is_timer and not has_saved_key:
                geometry = offset_geometry(geometry, max(0, index - 1))
            if not geometry:
                width, height = INDEPENDENT_SIZES.get(self.settings.timer_visual_size, INDEPENDENT_SIZES["standard"])
                match = re.fullmatch(r"\d+x\d+([+-]\d+)([+-]\d+)", self._anchor_geometry())
                x, y = (int(match.group(1)), int(match.group(2))) if match else (40, 80)
                geometry = f"{width}x{height}{x + index * STACK_OFFSET:+d}{y + index * STACK_OFFSET:+d}"
            overlay = TimerOverlay(
                self.root, geometry,
                lambda value, t=trigger_id, p=placement_key: self._independent_moved(t, p, value),
            )
            self.independent_overlays[surface_key] = overlay
        return overlay

    def _independent_moved(self, trigger_id: str, placement_key: str, geometry: str) -> None:
        trigger = self.settings.trigger_by_id(trigger_id)
        if trigger is None:
            return
        trigger.overlay_positions[placement_key] = geometry
        if placement_key == trigger.id:
            trigger.overlay_geometry = geometry
        self.settings.save()

    # -- rendering ------------------------------------------------------------

    def render(self, now: float | None = None, new_alert: bool = False) -> list[TimerOverlay]:
        if not self.timers.timers and not self.board_overlays and not self.independent_overlays:
            return []
        now = time.monotonic() if now is None else now
        docked: dict[str, list[TimerInstance]] = {}
        independent: dict[tuple[str, str], list[TimerInstance]] = {}
        for timer in self.timers.timers.values():
            if timer.overlay_layout == "independent":
                independent.setdefault((timer.trigger_id, timer.placement_key), []).append(timer)
            else:
                docked.setdefault(timer.timer_board, []).append(timer)

        rendered: list[TimerOverlay] = []
        active_boards: set[str] = set()
        for board_name, timers in docked.items():
            board = self.settings.timer_board(board_name)
            active_boards.add(board.id)
            if board.sort_order == "remaining":
                timers.sort(key=lambda t: (t.remaining(now), t.label.casefold()))
            elif board.sort_order == "name":
                timers.sort(key=lambda t: t.label.casefold())
            else:
                timers.sort(key=lambda t: t.started_at)
            for timer in timers:
                timer.overlay_size = board.visual_size
                timer.overlay_opacity = board.opacity
            overlay = self._board_overlay(board)
            if new_alert:
                overlay.show_for_alert()
            overlay.render(timers, now, board.columns, board.growth_direction)
            rendered.append(overlay)
        for board_id, overlay in list(self.board_overlays.items()):
            if board_id not in active_boards and overlay.winfo_exists():
                overlay.render([], now, 1)

        for index, (_key, timers) in enumerate(independent.items(), start=1):
            overlay = self._independent_overlay(timers[0], index)
            if new_alert:
                overlay.show_for_alert()
            overlay.render(timers, now, 1)
            rendered.append(overlay)
        for surface_key, overlay in list(self.independent_overlays.items()):
            if surface_key not in independent and overlay.winfo_exists():
                overlay.render([], now, 1)
        return rendered

    # -- user actions ---------------------------------------------------------

    def arrange(self) -> None:
        profile = self.settings.active_trigger_profile.casefold()
        visible = [t for t in self.settings.triggers if t.overlay_enabled and t.profile.casefold() == profile]
        if self.settings.timer_layout == "independent":
            for index, trigger in enumerate(visible, start=1):
                self._independent_overlay(trigger, index).arrange()
            if not visible:
                self._board_overlay(self.settings.timer_boards[0]).arrange()
        else:
            names = {t.timer_board for t in visible} or {self.settings.timer_boards[0].name}
            for name in names:
                self._board_overlay(self.settings.timer_board(name)).arrange()
        self.status("Overlay unlocked — drag its header and resize from the lower-right corner.", "accent")

    def lock(self) -> None:
        overlays = self.all() or [self._board_overlay(self.settings.timer_boards[0])]
        for overlay in overlays:
            overlay.lock()
        self.status("Overlay locked and click-through.", "ok")

    def hide(self) -> None:
        for overlay in self.all():
            overlay.hide_overlay()
        self.status("Overlay hidden until the next timer.", "muted")

    def preview_trigger(self, trigger: Trigger) -> bool:
        match = TriggerMatch(trigger.id, trigger.name, "", trigger.volume, "Overlay preview",
                             captures=dict(PREVIEW_CAPTURES))
        if self.timers.start(trigger, match) is None:
            return False
        for overlay in self.render(new_alert=True):
            overlay.show_preview()
        return True

    def preview_board(self, board: TimerBoard) -> None:
        prefix = f"{BOARD_PREVIEW_PREFIX}{board.id}-"
        self.timers.remove_where(lambda timer: timer.id.startswith(prefix))
        now = time.monotonic()
        samples = (("Sample Timer A", 18.0, 30.0, "#d39b47"), ("Sample Timer B", 11.0, 24.0, "#57c7ff"),
                   ("Sample Timer C", 25.0, 40.0, "#67d391"))
        for index, (label, remaining, duration, color) in enumerate(samples, start=1):
            timer = TimerInstance(
                id=f"{prefix}{index}", trigger_id=f"{prefix}trigger", key=f"sample-{index}", label=label,
                started_at=now - (duration - remaining), ends_at=now + remaining, duration=duration,
                show_bar=True, bar_color=color, text_color="#e7edf4", timer_board=board.name,
                overlay_layout="docked", overlay_size=board.visual_size, overlay_opacity=board.opacity,
                overlay_geometry=board.geometry, placement_key=board.id, ending_soon_seconds=0.0,
                ending_sound="", expiration_sound="", volume=0.0, ending_speech="", expiration_speech="",
            )
            self.timers.timers[timer.id] = timer
        rendered = self.render(new_alert=True)
        overlay = self._board_overlay(board)
        if overlay in rendered:
            overlay.show_preview()

    # -- close gesture --------------------------------------------------------

    @staticmethod
    def _key_down(code: int) -> bool:
        try:
            return bool(ctypes.windll.user32.GetAsyncKeyState(code) & 0x8000)
        except (AttributeError, OSError):
            return False

    def start_close_gesture_polling(self) -> None:
        if os.name == "nt":
            self.root.after(25, self._poll_close_gesture)

    def _poll_close_gesture(self) -> None:
        """Hide one timer card under a configured modifier-click even while click-through."""
        try:
            left_down = self._key_down(VK_LBUTTON)
            required = [self.settings.overlay_close_modifier1]
            if self.settings.overlay_close_modifier2 != "none":
                required.append(self.settings.overlay_close_modifier2)
            armed = self.settings.overlay_close_enabled and all(
                self._key_down(VIRTUAL_KEYS[name]) for name in required if name in VIRTUAL_KEYS)
            point = wintypes.POINT()
            has_point = bool(ctypes.windll.user32.GetCursorPos(ctypes.byref(point)))
            if armed and left_down and not self._left_down and has_point:
                dismissed = self.dismiss_at(point.x, point.y)
                if dismissed is not None:
                    self.render()
                    self.status(f"Closed timer overlay: {dismissed.label}", "muted")
            self._left_down = left_down
        except (AttributeError, OSError, tk.TclError):
            pass
        if self.root.winfo_exists():
            self.root.after(25, self._poll_close_gesture)

    def dismiss_at(self, x: int, y: int) -> TimerInstance | None:
        for overlay in reversed(self.all()):
            if overlay.contains_point(x, y):
                timer_id = overlay.timer_id_at_screen(x, y)
                return self.timers.dismiss(timer_id) if timer_id else None
        return None
