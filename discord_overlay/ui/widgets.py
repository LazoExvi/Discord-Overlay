"""Reusable widgets: metric cards, status pill, sparkline, meter bars, sortable table."""
from __future__ import annotations

import re
import tkinter as tk
from collections import deque
from collections.abc import Callable, Sequence
from tkinter import ttk

import customtkinter as ctk

from ..encounter import ActorRow
from . import theme


def configure_tree_style(root) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Treeview", background=theme.PANEL, fieldbackground=theme.PANEL, foreground=theme.TEXT,
                    rowheight=30, borderwidth=0, relief="flat", font=("Segoe UI", 10))
    style.configure("Treeview.Heading", background=theme.PANEL_3, foreground=theme.MUTED, borderwidth=0,
                    relief="flat", padding=(8, 7), font=(theme.DISPLAY_FAMILY, 10, "bold"))
    style.map("Treeview", background=[("selected", "#2a3350")], foreground=[("selected", theme.TEXT)])
    style.map("Treeview.Heading", background=[("active", "#28304a")], foreground=[("active", theme.TEXT)])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # no focus border


class MetricCard(ctk.CTkFrame):
    """A labelled number with a colored accent stripe on its left edge."""

    def __init__(self, parent, label: str, color: str = theme.TEXT, size: int = 26) -> None:
        super().__init__(parent, **theme.CARD)
        self.grid_columnconfigure(1, weight=1)
        self.stripe = ctk.CTkFrame(self, width=4, height=1, fg_color=color, corner_radius=2)
        self.stripe.grid(row=0, column=0, rowspan=2, padx=(10, 0), pady=10, sticky="ns")
        ctk.CTkLabel(self, text=label.upper(), text_color=theme.MUTED, font=theme.display_font(10), anchor="w").grid(
            row=0, column=1, padx=(10, 12), pady=(9, 0), sticky="w")
        self.value = ctk.CTkLabel(self, text="—", text_color=color, font=theme.number_font(size), anchor="w")
        self.value.grid(row=1, column=1, padx=(10, 12), pady=(0, 8), sticky="w")

    def set(self, value: str) -> None:
        self.value.configure(text=value)


class StatusPill(ctk.CTkFrame):
    """Rounded status chip with a colored dot that pulses while monitoring."""

    def __init__(self, parent) -> None:
        super().__init__(parent, fg_color=theme.PANEL_2, corner_radius=16, border_width=1, border_color=theme.BORDER, height=32)
        self.grid_propagate(False)
        self.dot = ctk.CTkLabel(self, text="●", text_color=theme.MUTED, width=14, font=theme.font(14))
        self.dot.pack(side="left", padx=(12, 4), pady=4)
        self.label = ctk.CTkLabel(self, text="", text_color=theme.TEXT, font=theme.font(12, bold=True), anchor="w")
        self.label.pack(side="left", padx=(0, 14), pady=4)
        self._color = theme.MUTED
        self._pulsing = False
        self._phase = 0
        self._after: str | None = None

    def set(self, text: str, color: str, pulse: bool = False) -> None:
        self.label.configure(text=text)
        self._color = color
        self.dot.configure(text_color=color)
        width = max(150, min(420, 40 + len(text) * 8))
        self.configure(width=width)
        if pulse and not self._pulsing:
            self._pulsing = True
            self._tick()
        elif not pulse:
            self._pulsing = False

    def _tick(self) -> None:
        if not self._pulsing or not self.winfo_exists():
            return
        self._phase = (self._phase + 1) % 20
        amount = abs(self._phase - 10) / 10 * 0.6
        self.dot.configure(text_color=theme.blend(self._color, theme.PANEL_2, amount))
        self._after = self.after(90, self._tick)


class Sparkline(tk.Canvas):
    """Rolling line chart of a single value over the last ``window`` seconds."""

    def __init__(self, parent, window: float = 60.0, color: str = theme.ACCENT, height: int = 56) -> None:
        super().__init__(parent, height=height, bg=theme.PANEL_2, highlightthickness=0, bd=0)
        self.window = window
        self.color = color
        self.samples: deque[tuple[float, float]] = deque()
        self.bind("<Configure>", lambda _e: self.redraw())

    def add(self, timestamp: float, value: float) -> None:
        self.samples.append((timestamp, value))
        cutoff = timestamp - self.window
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()
        self.redraw()

    def clear(self) -> None:
        self.samples.clear()
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width < 10 or height < 10:
            return
        pad = 6
        for fraction in (0.25, 0.5, 0.75):
            y = pad + (height - 2 * pad) * fraction
            self.create_line(pad, y, width - pad, y, fill=theme.PANEL_3, dash=(2, 4))
        if len(self.samples) < 2:
            self.create_text(width / 2, height / 2, text="DPS over the last minute", fill=theme.DIM, font=("Segoe UI", 9))
            return
        newest = self.samples[-1][0]
        peak = max(value for _t, value in self.samples) or 1.0
        points: list[float] = []
        for timestamp, value in self.samples:
            x = pad + (width - 2 * pad) * (1 - min(1.0, (newest - timestamp) / self.window))
            y = pad + (height - 2 * pad) * (1 - value / peak)
            points.extend((x, y))
        fill = theme.blend(self.color, theme.PANEL_2, 0.78)
        self.create_polygon(points[0], height - pad, *points, points[-2], height - pad, fill=fill, outline="")
        self.create_line(*points, fill=self.color, width=2, smooth=True)
        self.create_oval(points[-2] - 3, points[-1] - 3, points[-2] + 3, points[-1] + 3, fill=self.color, outline="")
        self.create_text(width - pad - 2, pad + 2, text=f"peak {peak:,.0f}", fill=theme.DIM, anchor="ne", font=("Segoe UI", 8))


class MeterView(tk.Canvas):
    """Classic DPS-meter bars: one proportional bar per actor with inline numbers."""

    ROW_HEIGHT = 34
    GAP = 6

    def __init__(self, parent) -> None:
        super().__init__(parent, bg=theme.PANEL, highlightthickness=0, bd=0)
        self.rows: list[ActorRow] = []
        self.metric = "damage"
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_rows(self, rows: Sequence[ActorRow], metric: str = "damage") -> None:
        self.metric = metric
        self.rows = [row for row in rows if getattr(row, metric) > 0]
        if metric == "healing":
            self.rows.sort(key=lambda row: row.healing, reverse=True)
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        if width < 40:
            return
        if not self.rows:
            self.create_text(width / 2, 60, text="No combat yet. Bars appear as damage and healing are parsed.",
                             fill=theme.DIM, font=("Segoe UI", 11))
            self.configure(scrollregion=(0, 0, width, 120))
            return
        healing = self.metric == "healing"
        peak = max(getattr(row, self.metric) for row in self.rows) or 1
        x0, x1 = 12, width - 12
        y = self.GAP
        for index, row in enumerate(self.rows, start=1):
            value = getattr(row, self.metric)
            color = theme.GREEN if healing else theme.ACTOR_TYPE_COLORS.get(row.actor_type, theme.SLATE)
            bar_end = x0 + (x1 - x0) * value / peak
            self.create_rectangle(x0, y, x1, y + self.ROW_HEIGHT, fill=theme.PANEL_2, outline="")
            self.create_rectangle(x0, y, max(x0 + 4, bar_end), y + self.ROW_HEIGHT,
                                  fill=theme.blend(color, theme.PANEL, 0.35), outline="")
            self.create_rectangle(x0, y, max(x0 + 4, bar_end), y + 3, fill=color, outline="")
            self.create_text(x0 + 10, y + self.ROW_HEIGHT / 2, text=f"{index}.", fill=theme.DIM, anchor="w", font=("Segoe UI", 10))
            self.create_text(x0 + 34, y + self.ROW_HEIGHT / 2, text=row.actor, fill=theme.TEXT, anchor="w",
                             font=(theme.DISPLAY_FAMILY, 12, "bold"))
            if healing:
                detail = f"{row.healing:,}   {row.hps:,.1f} HPS"
            else:
                detail = f"{row.damage:,}   ({row.share:.1f}%)   {row.dps:,.1f} DPS"
            self.create_text(x1 - 10, y + self.ROW_HEIGHT / 2, text=detail, fill=theme.TEXT, anchor="e",
                             font=(theme.NUMBER_FAMILY, 12))
            y += self.ROW_HEIGHT + self.GAP
        self.configure(scrollregion=(0, 0, width, y))


class Column:
    __slots__ = ("key", "label", "width", "anchor", "numeric")

    def __init__(self, key: str, label: str, width: int, anchor: str = "w", numeric: bool = False) -> None:
        self.key, self.label, self.width, self.anchor, self.numeric = key, label, width, anchor, numeric


class SortableTree:
    """A ``ttk.Treeview`` with click-to-sort headings, drag-to-reorder columns, and striped rows.

    Column order is reported through ``on_order_changed`` so the caller can persist it.
    """

    DRAG_THRESHOLD = 7

    def __init__(self, parent, columns: Sequence[Column], *, order: Sequence[str] = (),
                 on_order_changed: Callable[[list[str]], None] | None = None, **tree_kwargs) -> None:
        self.columns = {column.key: column for column in columns}
        self.on_order_changed = on_order_changed
        self.tree = ttk.Treeview(parent, columns=tuple(self.columns), show="headings", **tree_kwargs)
        for column in columns:
            self.tree.heading(column.key, text=column.label, command=lambda key=column.key: self.sort(key))
            self.tree.column(column.key, width=column.width, minwidth=42, anchor=column.anchor)
        display = [key for key in order if key in self.columns]
        display.extend(key for key in self.columns if key not in display)
        self.tree.configure(displaycolumns=tuple(display))
        self.tree.tag_configure("odd", background=theme.PANEL)
        self.tree.tag_configure("even", background="#151922")
        self._sort_state: tuple[str, bool] | None = None
        self._drag: dict | None = None
        self.tree.bind("<ButtonPress-1>", self._drag_start, add="+")
        self.tree.bind("<B1-Motion>", self._drag_move, add="+")
        self.tree.bind("<ButtonRelease-1>", self._drag_finish, add="+")

    # -- rows -----------------------------------------------------------------

    def clear(self) -> None:
        self.tree.delete(*self.tree.get_children(""))

    def insert(self, values: Sequence, tags: Sequence[str] = (), iid: str | None = None) -> str:
        kwargs = {"iid": iid} if iid else {}
        item = self.tree.insert("", "end", values=tuple(values), tags=tuple(tags), **kwargs)
        self.restripe()
        return item

    def set_rows(self, rows: Sequence[Sequence], iids: Sequence[str] | None = None) -> None:
        self.clear()
        for index, values in enumerate(rows):
            kwargs = {"iid": iids[index]} if iids else {}
            self.tree.insert("", "end", values=tuple(values), **kwargs)
        self.reapply_sort()

    def restripe(self) -> None:
        for index, item in enumerate(self.tree.get_children("")):
            tags = [tag for tag in self.tree.item(item, "tags") if tag not in ("odd", "even")]
            tags.append("even" if index % 2 else "odd")
            self.tree.item(item, tags=tuple(tags))

    def selection(self) -> str | None:
        selected = self.tree.selection()
        return selected[0] if selected else None

    def select(self, iid: str | None) -> None:
        if iid and self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)

    # -- sorting --------------------------------------------------------------

    def sort(self, key: str, toggle: bool = True) -> None:
        numeric = self.columns[key].numeric
        if toggle:
            previous = self._sort_state
            descending = not previous[1] if previous and previous[0] == key else numeric
            self._sort_state = (key, descending)
        else:
            if not self._sort_state:
                self.restripe()
                return
            key, descending = self._sort_state
            numeric = self.columns[key].numeric

        def sort_key(item: str):
            value = str(self.tree.set(item, key)).strip()
            if not numeric:
                return value.casefold()
            try:
                return float(re.sub(r"[^0-9.+-]", "", value))
            except ValueError:
                return float("-inf")

        for position, item in enumerate(sorted(self.tree.get_children(""), key=sort_key, reverse=descending)):
            self.tree.move(item, "", position)
        for column_key, column in self.columns.items():
            marker = (" ▼" if descending else " ▲") if column_key == key else ""
            self.tree.heading(column_key, text=f"{column.label}{marker}")
        self.restripe()

    def reapply_sort(self) -> None:
        self.sort(self._sort_state[0], toggle=False) if self._sort_state else self.restripe()

    # -- column drag ----------------------------------------------------------

    def _column_at(self, x: int) -> str | None:
        if self.tree.identify_region(x, 4) != "heading":
            return None
        try:
            index = int(self.tree.identify_column(x).lstrip("#")) - 1
        except ValueError:
            return None
        displayed = list(self.tree["displaycolumns"])
        return displayed[index] if 0 <= index < len(displayed) else None

    def _drag_start(self, event) -> None:
        column = self._column_at(event.x)
        self._drag = {"source": column, "start_x": event.x, "moved": False} if column else None

    def _drag_move(self, event) -> None:
        if self._drag and abs(event.x - self._drag["start_x"]) >= self.DRAG_THRESHOLD:
            self._drag["moved"] = True
            self.tree.configure(cursor="sb_h_double_arrow")

    def _drag_finish(self, event):
        state, self._drag = self._drag, None
        if not state:
            return None
        self.tree.configure(cursor="")
        if not state["moved"]:
            return None
        target = self._column_at(event.x)
        if target and target != state["source"]:
            displayed = list(self.tree["displaycolumns"])
            displayed.remove(state["source"])
            displayed.insert(displayed.index(target), state["source"])
            self.tree.configure(displaycolumns=tuple(displayed))
            if self.on_order_changed:
                self.on_order_changed(displayed)
        return "break"  # keep the heading's sort command from firing after a drag
