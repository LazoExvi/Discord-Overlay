"""Reusable widgets: metric cards and a sortable, reorderable table."""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from tkinter import ttk

import customtkinter as ctk

from . import theme


def configure_tree_style(root) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Treeview", background=theme.PANEL, fieldbackground=theme.PANEL, foreground=theme.TEXT,
                    rowheight=29, borderwidth=0, font=("Segoe UI", 10))
    style.configure("Treeview.Heading", background=theme.PANEL_2, foreground=theme.MUTED, borderwidth=0,
                    font=("Segoe UI", 10, "bold"))
    style.map("Treeview", background=[("selected", "#24415c")])
    style.map("Treeview.Heading", background=[("active", "#203042")])


class MetricCard(ctk.CTkFrame):
    def __init__(self, parent, label: str, color: str = theme.TEXT) -> None:
        super().__init__(parent, fg_color=theme.PANEL_2, corner_radius=10)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=label.upper(), text_color=theme.MUTED, font=theme.font(11, bold=True)).grid(
            row=0, column=0, padx=12, pady=(9, 0), sticky="w")
        self.value = ctk.CTkLabel(self, text="—", text_color=color, font=theme.font(24, bold=True))
        self.value.grid(row=1, column=0, padx=12, pady=(0, 9), sticky="w")

    def set(self, value: str) -> None:
        self.value.configure(text=value)


class Column:
    __slots__ = ("key", "label", "width", "anchor", "numeric")

    def __init__(self, key: str, label: str, width: int, anchor: str = "w", numeric: bool = False) -> None:
        self.key, self.label, self.width, self.anchor, self.numeric = key, label, width, anchor, numeric


class SortableTree:
    """A ``ttk.Treeview`` with click-to-sort headings and drag-to-reorder columns.

    Column order is reported through ``on_order_changed`` so the caller can persist it.
    """

    DRAG_THRESHOLD = 7

    def __init__(self, parent, columns: Sequence[Column], *, order: Sequence[str] = (),
                 on_order_changed: Callable[[list[str]], None] | None = None, **tree_kwargs) -> None:
        self.columns = {column.key: column for column in columns}
        self.on_order_changed = on_order_changed
        self.tree = ttk.Treeview(parent, columns=tuple(self.columns), show="headings", **tree_kwargs)
        for column in columns:
            self.tree.heading(column.key, text=column.label,
                              command=lambda key=column.key: self.sort(key))
            self.tree.column(column.key, width=column.width, minwidth=42, anchor=column.anchor)
        display = [key for key in order if key in self.columns]
        display.extend(key for key in self.columns if key not in display)
        self.tree.configure(displaycolumns=tuple(display))
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
        return self.tree.insert("", "end", values=tuple(values), tags=tuple(tags), **kwargs)

    def set_rows(self, rows: Sequence[Sequence], iids: Sequence[str] | None = None) -> None:
        self.clear()
        for index, values in enumerate(rows):
            self.insert(values, iid=iids[index] if iids else None)
        self.reapply_sort()

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
                return
            key, descending = self._sort_state

        def sort_key(item: str):
            value = str(self.tree.set(item, key)).strip()
            if not numeric:
                return value.casefold()
            try:
                return float(re.sub(r"[^0-9.+-]", "", value))
            except ValueError:
                return float("-inf")

        items = sorted(self.tree.get_children(""), key=sort_key, reverse=descending)
        for position, item in enumerate(items):
            self.tree.move(item, "", position)
        for column_key, column in self.columns.items():
            marker = (" ▼" if descending else " ▲") if column_key == key else ""
            self.tree.heading(column_key, text=f"{column.label}{marker}")

    def reapply_sort(self) -> None:
        if self._sort_state:
            self.sort(self._sort_state[0], toggle=False)

    # -- column drag ----------------------------------------------------------

    def _column_at(self, x: int) -> str | None:
        if self.tree.identify_region(x, 4) != "heading":
            return None
        identifier = self.tree.identify_column(x)
        try:
            index = int(identifier.lstrip("#")) - 1
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
