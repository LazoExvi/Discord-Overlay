"""Always-on-top overlay windows: arrangeable, then locked click-through.

``OverlayWindow`` provides the shared chrome (drag header, resize grip, Win32
click-through, geometry persistence, preview mode). ``TimerOverlay`` fills it with
timer cards; the mini meter in ``mini_overlay.py`` fills it with a canvas.
"""
from __future__ import annotations

import ctypes
import math
import sys
import tkinter as tk
from collections.abc import Callable, Iterable

import customtkinter as ctk

from ..timers import TimerInstance
from . import theme

CARD_STYLES = {  # size -> (font, bar height, label pady, bar pady, time width, radius)
    "compact": (11, 4, (5, 2), (3, 5), 38, 4),
    "standard": (17, 8, (10, 4), (4, 10), 58, 8),
    "large": (27, 12, (16, 8), (7, 16), 92, 12),
}
CARD_GAPS = {"compact": 2, "standard": 5, "large": 8}
PREVIEW_HEADER = "#3b3f7a"

# Win32 constants used to toggle click-through and keep the window topmost.
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW, SWP_FRAMECHANGED = 0x1, 0x2, 0x10, 0x40, 0x20


class OverlayWindow(tk.Toplevel):
    """Borderless topmost window with a drag header and resize grip while arranging."""

    def __init__(self, parent, geometry: str, geometry_changed: Callable[[str], None],
                 display_name: str = "Overlay", default_geometry: str = "420x320+40+80",
                 min_size: tuple[int, int] = (280, 120)) -> None:
        super().__init__(parent)
        self.geometry_changed = geometry_changed
        self.min_size = min_size
        self.edit_mode = False
        self.manually_hidden = False
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._resize_origin: tuple[int, int, int, int] | None = None
        self._save_after: str | None = None
        self._preview_after: str | None = None
        self.withdraw()
        self.title(display_name)
        self.geometry(geometry or default_geometry)
        self.minsize(160, 50)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.94)
        if sys.platform == "win32":
            try:
                self.attributes("-transparentcolor", theme.BG_DEEP)
            except tk.TclError:
                pass
        self.configure(bg=theme.BG_DEEP)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.header = ctk.CTkFrame(self, fg_color=theme.PANEL_2, corner_radius=0, height=32)
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.grid_columnconfigure(0, weight=1)
        self.header_label = ctk.CTkLabel(self.header, text=display_name.upper(), text_color=theme.ACCENT,
                                         font=theme.font(11, bold=True), anchor="w")
        self.header_label.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        self.mode_label = ctk.CTkLabel(self.header, text="", text_color=theme.MUTED, font=theme.font(10))
        self.mode_label.grid(row=0, column=1, padx=10, pady=5)
        for widget in (self.header, self.header_label, self.mode_label):
            widget.bind("<ButtonPress-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

        self.content = ctk.CTkFrame(self, fg_color=theme.BG_DEEP, corner_radius=0)
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.resize_grip = tk.Label(self, text="◢", bg=theme.PANEL_2, fg=theme.ACCENT, cursor="size_nw_se",
                                    font=("Segoe UI", 13))
        self._place_grip()
        self.resize_grip.bind("<ButtonPress-1>", self._resize_start)
        self.resize_grip.bind("<B1-Motion>", self._resize_move)
        self.bind("<Configure>", self._configured)

    # -- hooks for subclasses -------------------------------------------------

    def has_content(self) -> bool:
        return True

    def _set_edit_chrome(self, editing: bool) -> None:
        """Subclasses may show/hide extra chrome (scrollbars) when arranging."""

    # -- modes ----------------------------------------------------------------

    def arrange(self) -> None:
        self.manually_hidden = False
        self.edit_mode = True
        self._set_click_through(False)
        self.header.configure(fg_color=theme.PANEL_2)
        self.header.grid()
        self._place_grip()
        self._set_edit_chrome(True)
        self.mode_label.configure(text="MOVE / RESIZE")
        self.resize_grip.lift()
        self._show()
        self.focus_force()

    def lock(self) -> None:
        self.manually_hidden = False
        self.edit_mode = False
        self.mode_label.configure(text="CLICK-THROUGH")
        self.header.configure(fg_color=theme.PANEL_2)
        self.header.grid_remove()
        self.resize_grip.place_forget()
        self._set_edit_chrome(False)
        self._set_click_through(True)
        self._show()

    def hide_overlay(self) -> None:
        self.manually_hidden = True
        self._save_geometry_now()
        self.withdraw()

    def show_for_alert(self) -> None:
        self.manually_hidden = False

    def show_preview(self, seconds: float = 3.5) -> None:
        """Make a test alert unmistakable, then fall back to locked mode."""
        self.manually_hidden = False
        self.edit_mode = False
        self._set_click_through(False)
        self.header.grid()
        self.resize_grip.place_forget()
        self._set_edit_chrome(False)
        self.header.configure(fg_color=PREVIEW_HEADER)
        self.mode_label.configure(text="PREVIEW - THIS IS THE OVERLAY")
        self._show()
        if self._preview_after:
            try:
                self.after_cancel(self._preview_after)
            except tk.TclError:
                pass
        self._preview_after = self.after(int(seconds * 1000), self._finish_preview)

    def _finish_preview(self) -> None:
        self._preview_after = None
        if self.winfo_exists() and self.has_content():
            self.lock()

    def _show(self) -> None:
        self.deiconify()
        self.lift()
        self._force_topmost()

    def ensure_visible(self) -> None:
        """Show in locked mode if hidden by rendering (not by the user)."""
        if self.state() == "withdrawn" and not self.manually_hidden:
            self.lock()
        else:
            self._force_topmost()

    def _place_grip(self) -> None:
        self.resize_grip.place(relx=1, rely=1, anchor="se", width=24, height=24)

    def contains_point(self, x: int, y: int) -> bool:
        if not self.winfo_viewable():
            return False
        left, top = self.winfo_rootx(), self.winfo_rooty()
        return left <= x < left + self.winfo_width() and top <= y < top + self.winfo_height()

    # -- drag / resize --------------------------------------------------------

    def _drag_start(self, event) -> None:
        if self.edit_mode:
            self._drag_origin = (event.x_root, event.y_root, self.winfo_x(), self.winfo_y())

    def _drag_move(self, event) -> None:
        if self.edit_mode and self._drag_origin:
            start_x, start_y, window_x, window_y = self._drag_origin
            self.geometry(f"+{window_x + event.x_root - start_x}+{window_y + event.y_root - start_y}")

    def _resize_start(self, event) -> None:
        if self.edit_mode:
            self._resize_origin = (event.x_root, event.y_root, self.winfo_width(), self.winfo_height())

    def _resize_move(self, event) -> None:
        if self.edit_mode and self._resize_origin:
            start_x, start_y, width, height = self._resize_origin
            min_w, min_h = self.min_size
            self.geometry(f"{max(min_w, width + event.x_root - start_x)}x{max(min_h, height + event.y_root - start_y)}")

    def _configured(self, _event=None) -> None:
        if not self.edit_mode:
            return
        if self._save_after:
            try:
                self.after_cancel(self._save_after)
            except tk.TclError:
                pass
        self._save_after = self.after(400, self._save_geometry_now)

    def _save_geometry_now(self) -> None:
        self._save_after = None
        if self.winfo_exists():
            self.geometry_changed(self.geometry())

    # -- win32 ----------------------------------------------------------------

    def _native_hwnd(self) -> int:
        hwnd = self.winfo_id()
        if sys.platform == "win32":
            root = ctypes.windll.user32.GetAncestor(hwnd, 2)  # GA_ROOT
            if root:
                hwnd = root
        return hwnd

    def _set_click_through(self, enabled: bool) -> None:
        if sys.platform != "win32":
            return
        self.update_idletasks()
        try:
            hwnd = self._native_hwnd()
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if enabled:
                style |= WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW
            else:
                style = (style & ~WS_EX_TRANSPARENT) | WS_EX_LAYERED | WS_EX_TOOLWINDOW
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            self._force_topmost(frame_changed=True)
        except (AttributeError, OSError, tk.TclError):
            pass

    def _force_topmost(self, frame_changed: bool = False) -> None:
        if sys.platform != "win32":
            return
        try:
            flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW
            if frame_changed:
                flags |= SWP_FRAMECHANGED
            ctypes.windll.user32.SetWindowPos(self._native_hwnd(), HWND_TOPMOST, 0, 0, 0, 0, flags)
        except (AttributeError, OSError, tk.TclError):
            pass


class TimerCard(ctk.CTkFrame):
    def __init__(self, parent) -> None:
        super().__init__(parent, fg_color=theme.PANEL, corner_radius=9)
        self._visual_size = ""
        self.grid_columnconfigure(0, weight=1)
        self.label = ctk.CTkLabel(self, text="", text_color=theme.TEXT, anchor="w", justify="left",
                                  font=theme.font(17, bold=True), wraplength=320)
        self.label.grid(row=0, column=0, padx=(13, 6), pady=(9, 3), sticky="ew")
        self.time_label = ctk.CTkLabel(self, text="", text_color=theme.TEXT, width=58,
                                       font=theme.font(17, bold=True), anchor="e")
        self.time_label.grid(row=0, column=1, padx=(4, 13), pady=(9, 3), sticky="e")
        self.progress = ctk.CTkProgressBar(self, height=9, corner_radius=5, fg_color="#263440",
                                           progress_color=theme.ACCENT)
        self.progress.grid(row=1, column=0, columnspan=2, padx=13, pady=(3, 11), sticky="ew")

    def update_timer(self, timer: TimerInstance, now: float) -> None:
        self._apply_visual_size(timer.overlay_size)
        self.label.configure(text=timer.label, text_color=timer.text_color)
        if timer.show_bar:
            self.time_label.configure(text=f"{math.ceil(timer.remaining(now))}s", text_color=timer.text_color)
            self.progress.configure(progress_color=timer.bar_color)
            self.progress.set(timer.fraction(now))
            self.progress.grid()
        else:
            self.time_label.configure(text="")
            self.progress.grid_remove()

    def _apply_visual_size(self, size: str) -> None:
        if size == self._visual_size:
            return
        self._visual_size = size
        font_size, bar_height, label_y, bar_y, time_width, radius = CARD_STYLES.get(size, CARD_STYLES["standard"])
        self.configure(corner_radius=radius)
        self.label.configure(font=theme.font(font_size, bold=True))
        self.time_label.configure(font=theme.font(font_size, bold=True), width=time_width)
        self.label.grid_configure(pady=label_y, padx=(label_y[0] + 3, 4))
        self.time_label.grid_configure(pady=label_y, padx=(3, label_y[0] + 3))
        self.progress.configure(height=bar_height, corner_radius=max(2, bar_height // 2))
        self.progress.grid_configure(padx=label_y[0] + 3, pady=bar_y)


class TimerOverlay(OverlayWindow):
    """One overlay window: a named board grid or a single independent timer."""

    def __init__(self, parent, geometry: str, geometry_changed: Callable[[str], None],
                 display_name: str = "Timer Overlay") -> None:
        super().__init__(parent, geometry, geometry_changed, display_name)
        self.cards: dict[str, TimerCard] = {}
        self._grid_columns = 1
        self.body = ctk.CTkScrollableFrame(self.content, fg_color=theme.BG_DEEP, corner_radius=0,
                                           scrollbar_button_color="#27394b")
        self.body.grid(row=0, column=0, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)
        self.placeholder = ctk.CTkLabel(
            self.body, text="Overlay layout mode\nDrag the header • Resize from the lower-right corner",
            text_color=theme.MUTED, justify="center")
        self.placeholder.grid(row=0, column=0, padx=18, pady=30, sticky="ew")

    def has_content(self) -> bool:
        return bool(self.cards)

    def _set_edit_chrome(self, editing: bool) -> None:
        try:
            scrollbar = self.body._scrollbar  # CustomTkinter keeps this private
            scrollbar.grid() if editing else scrollbar.grid_remove()
        except (AttributeError, tk.TclError):
            pass

    def render(self, timers: Iterable[TimerInstance], now: float, grid_columns: int = 1,
               growth_direction: str = "rows") -> None:
        active = list(timers)
        grid_columns = max(1, min(6, int(grid_columns)))
        if grid_columns != self._grid_columns:
            for column in range(max(self._grid_columns, grid_columns)):
                self.body.grid_columnconfigure(column, weight=1 if column < grid_columns else 0)
            self._grid_columns = grid_columns
        active_ids = {timer.id for timer in active}
        for timer_id in [key for key in self.cards if key not in active_ids]:
            self.cards.pop(timer_id).destroy()
        row_count = max(1, math.ceil(len(active) / grid_columns))
        for index, timer in enumerate(active):
            card = self.cards.get(timer.id)
            if card is None:
                card = self.cards[timer.id] = TimerCard(self.body)
            card.update_timer(timer, now)
            gap = CARD_GAPS.get(timer.overlay_size, 5)
            if growth_direction == "columns":
                row, column = index % row_count, index // row_count
            else:
                row, column = index // grid_columns, index % grid_columns
            card.grid(row=row, column=column, padx=gap, pady=gap, sticky="ew")
        if active:
            self.attributes("-alpha", max(0.2, min(1.0, max(timer.overlay_opacity for timer in active))))
            self.placeholder.grid_remove()
            self.ensure_visible()
        elif self.edit_mode:
            self.placeholder.grid()
        else:
            self.withdraw()

    def timer_id_at_screen(self, x: int, y: int) -> str | None:
        for timer_id, card in reversed(list(self.cards.items())):
            if not card.winfo_viewable():
                continue
            left, top = card.winfo_rootx(), card.winfo_rooty()
            if left <= x < left + card.winfo_width() and top <= y < top + card.winfo_height():
                return timer_id
        return None
