"""Compact always-on-top DPS meter for use while playing."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence

from ..encounter import ActorRow
from ..models import EncounterSnapshot
from . import theme
from .overlay import OverlayWindow

DEFAULT_GEOMETRY = "340x230+40+80"
HEADER_HEIGHT = 34
ROW_HEIGHT = 24
GAP = 4


class MiniMeterOverlay(OverlayWindow):
    def __init__(self, parent, geometry: str, geometry_changed: Callable[[str], None]) -> None:
        super().__init__(parent, geometry, geometry_changed, display_name="Mini meter",
                         default_geometry=DEFAULT_GEOMETRY, min_size=(220, 90))
        self.canvas = tk.Canvas(self.content, bg=theme.PANEL, highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.snapshot = EncounterSnapshot()
        self.rows: list[ActorRow] = []
        self.metric = "damage"
        self.max_rows = 6
        self.canvas.bind("<Configure>", lambda _e: self.redraw())

    def update_data(self, snapshot: EncounterSnapshot, rows: Sequence[ActorRow], metric: str,
                    max_rows: int, opacity: float) -> None:
        self.snapshot = snapshot
        self.metric = metric
        self.max_rows = max(1, max_rows)
        self.rows = [row for row in rows if getattr(row, metric) > 0]
        if metric == "healing":
            self.rows.sort(key=lambda row: row.healing, reverse=True)
        self.attributes("-alpha", max(0.2, min(1.0, opacity)))
        self.redraw()

    def redraw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 40 or height < 20:
            return
        snap = self.snapshot
        minutes, seconds = divmod(int(snap.duration), 60)
        canvas.create_rectangle(0, 0, width, HEADER_HEIGHT, fill=theme.PANEL_2, outline="")
        canvas.create_rectangle(0, HEADER_HEIGHT, width, HEADER_HEIGHT + 1, fill=theme.BORDER, outline="")
        if self.metric == "healing":
            headline = [("HPS", f"{snap.hps:,.0f}", theme.GREEN), ("HEAL", f"{snap.total_heal:,}", theme.GREEN)]
        else:
            headline = [("DPS", f"{snap.dps:,.0f}", theme.ACCENT), ("10s", f"{snap.rolling_dps:,.0f}", theme.CYAN),
                        ("DMG", f"{snap.total_out:,}", theme.AMBER)]
        x = 10
        for label, value, color in headline:
            canvas.create_text(x, HEADER_HEIGHT / 2, text=label, fill=theme.MUTED, anchor="w", font=(theme.DISPLAY_FAMILY, 9, "bold"))
            x += 8 * len(label) + 6
            canvas.create_text(x, HEADER_HEIGHT / 2, text=value, fill=color, anchor="w", font=(theme.NUMBER_FAMILY, 13, "bold"))
            x += 9 * len(value) + 16
        canvas.create_text(width - 10, HEADER_HEIGHT / 2, text=f"{minutes}:{seconds:02d}", fill=theme.PURPLE, anchor="e",
                           font=(theme.NUMBER_FAMILY, 13, "bold"))
        if snap.active:
            canvas.create_oval(width - 60, HEADER_HEIGHT / 2 - 4, width - 52, HEADER_HEIGHT / 2 + 4, fill=theme.GREEN, outline="")

        visible = self.rows[:self.max_rows]
        if not visible:
            canvas.create_text(width / 2, HEADER_HEIGHT + (height - HEADER_HEIGHT) / 2, text="Waiting for combat…",
                               fill=theme.DIM, font=("Segoe UI", 10))
            return
        peak = max(getattr(row, self.metric) for row in visible) or 1
        y = HEADER_HEIGHT + GAP + 2
        for index, row in enumerate(visible, start=1):
            if y + ROW_HEIGHT > height:
                break
            value = getattr(row, self.metric)
            color = theme.GREEN if self.metric == "healing" else theme.ACTOR_TYPE_COLORS.get(row.actor_type, theme.SLATE)
            end = 8 + (width - 16) * value / peak
            canvas.create_rectangle(8, y, width - 8, y + ROW_HEIGHT, fill=theme.PANEL_2, outline="")
            canvas.create_rectangle(8, y, max(12, end), y + ROW_HEIGHT, fill=theme.blend(color, theme.PANEL, 0.35), outline="")
            canvas.create_rectangle(8, y, max(12, end), y + 2, fill=color, outline="")
            canvas.create_text(16, y + ROW_HEIGHT / 2, text=f"{index}. {row.actor}", fill=theme.TEXT, anchor="w",
                               font=(theme.DISPLAY_FAMILY, 10, "bold"))
            if self.metric == "healing":
                detail = f"{row.healing:,}  {row.hps:,.0f}"
            else:
                detail = f"{row.damage:,}  {row.share:.0f}%  {row.dps:,.0f}"
            canvas.create_text(width - 14, y + ROW_HEIGHT / 2, text=detail, fill=theme.TEXT, anchor="e",
                               font=(theme.NUMBER_FAMILY, 10))
            y += ROW_HEIGHT + GAP
