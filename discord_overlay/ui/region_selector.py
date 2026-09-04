"""Full-screen drag selector for the OCR capture rectangle, one window per monitor."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from ..capture import monitor_rects
from ..models import Region

DIM = "#06111a"
GOLD = "#ffc45c"
TOO_SMALL = "#ff8b99"


class RegionSelector:
    """Darkens every display; left-drag selects, click a gold rectangle reuses it.

    Esc cancels; right-click clears the remembered rectangles. The selection is
    reported in the physical desktop coordinates used by ``ScreenCapture``.
    """

    ARM_DELAY_MS = 300  # ignore the click that opened the selector

    def __init__(self, parent, callback: Callable[[Region], None],
                 remembered: list[Region] | None = None,
                 clear_remembered: Callable[[], None] | None = None) -> None:
        self.parent = parent
        self.callback = callback
        self.remembered = remembered or []
        self.clear_remembered = clear_remembered
        self.overlays: list[tk.Toplevel] = []
        self._states: list[dict] = []
        self.closed = False
        self.armed = False

        monitors = monitor_rects() or [{
            "left": 0, "top": 0, "width": parent.winfo_screenwidth(), "height": parent.winfo_screenheight(),
        }]
        for monitor in monitors:
            self._make_overlay(monitor)
        if self.overlays:
            self.overlays[0].after(50, self.overlays[0].focus_force)
            self.overlays[0].after(self.ARM_DELAY_MS, self._arm)

    def _arm(self) -> None:
        if not self.closed:
            self.armed = True

    def _make_overlay(self, monitor: dict[str, int]) -> None:
        overlay = tk.Toplevel(self.parent)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.38)
        overlay.configure(bg=DIM, cursor="crosshair")
        overlay.geometry(f"{monitor['width']}x{monitor['height']}{monitor['left']:+d}{monitor['top']:+d}")
        overlay.update_idletasks()

        canvas = tk.Canvas(overlay, bg=DIM, highlightthickness=0, borderwidth=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)
        canvas.create_text(monitor["width"] // 2, 46, text="DRAG A BOX AROUND THE COMBAT TEXT",
                           fill="white", font=("Segoe UI", 18, "bold"))
        help_item = canvas.create_text(
            monitor["width"] // 2, 76, fill="#c9d7e5", font=("Segoe UI", 12),
            text=("Include complete text lines with a small margin - do not cut off letters  |  "
                  "Click gold to reuse  |  Right-click clears saved regions  |  Esc cancels"),
        )
        saved: list[Region] = []
        for index, region in enumerate(self.remembered, start=1):
            center_x = region.left + region.width // 2
            center_y = region.top + region.height // 2
            if not (monitor["left"] <= center_x < monitor["left"] + monitor["width"]
                    and monitor["top"] <= center_y < monitor["top"] + monitor["height"]):
                continue
            x1, y1 = region.left - monitor["left"], region.top - monitor["top"]
            canvas.create_rectangle(x1, y1, x1 + region.width, y1 + region.height, outline=GOLD, width=3,
                                    dash=(9, 5), tags=("saved",))
            canvas.create_text(x1 + 7, y1 + 7, text=f"SAVED {index}  {region.width} x {region.height}",
                               anchor="nw", fill=GOLD, font=("Segoe UI", 11, "bold"), tags=("saved",))
            saved.append(region)
        state = {"start": (0, 0), "rect": None, "size": None, "pressed": False, "help": help_item,
                 "saved": saved, "canvas": canvas, "monitor": monitor}
        self._states.append(state)
        canvas.bind("<ButtonPress-1>", lambda event, s=state: self._press(event, s))
        canvas.bind("<B1-Motion>", lambda event, s=state: self._drag(event, s))
        canvas.bind("<ButtonRelease-1>", lambda event, s=state: self._release(event, s))
        overlay.bind("<Escape>", lambda _event: self.close())
        overlay.bind("<Button-3>", self._clear_saved)
        self.overlays.append(overlay)
        overlay.lift()

    def _clear_saved(self, _event=None) -> str:
        self.remembered.clear()
        if self.clear_remembered:
            self.clear_remembered()
        for state in self._states:
            state["saved"].clear()
            state["canvas"].delete("saved")
            state["canvas"].itemconfigure(
                state["help"], text="Saved regions cleared - drag a new box with a small margin  |  Esc cancels")
        return "break"

    def _press(self, event, state: dict) -> None:
        if not self.armed:
            return
        canvas: tk.Canvas = state["canvas"]
        state["pressed"] = True
        state["start"] = (event.x, event.y)
        for key in ("rect", "size"):
            if state[key]:
                canvas.delete(state[key])
        state["rect"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline=GOLD, width=5,
                                                fill="#37627e", stipple="gray50")
        state["size"] = canvas.create_text(event.x + 10, event.y - 12, text="0 × 0", anchor="sw",
                                           fill="white", font=("Segoe UI", 12, "bold"))

    @staticmethod
    def _drag(event, state: dict) -> None:
        if not state["pressed"] or not state["rect"]:
            return
        canvas: tk.Canvas = state["canvas"]
        start_x, start_y = state["start"]
        canvas.coords(state["rect"], start_x, start_y, event.x, event.y)
        canvas.coords(state["size"], event.x + 10, event.y - 12)
        canvas.itemconfigure(state["size"], text=f"{abs(event.x - start_x)} × {abs(event.y - start_y)}")

    def _release(self, event, state: dict) -> None:
        # Only a press that began on this canvas may complete a selection; the
        # mouse-up from the button that opened the selector must not count.
        if not self.armed or not state["pressed"] or not state["rect"]:
            return
        state["pressed"] = False
        monitor = state["monitor"]
        start_x, start_y = state["start"]
        x1, x2 = sorted((start_x, event.x))
        y1, y2 = sorted((start_y, event.y))
        if x2 - x1 < 10 and y2 - y1 < 10:
            absolute_x, absolute_y = event.x + monitor["left"], event.y + monitor["top"]
            for saved in state["saved"]:
                if saved.contains(absolute_x, absolute_y):
                    self.close()
                    self.parent.after(75, lambda: self.callback(saved))
                    return
        region = Region(x1 + monitor["left"], y1 + monitor["top"], x2 - x1, y2 - y1)
        if not region.valid():
            state["canvas"].itemconfigure(state["size"], text="Too small — drag again", fill=TOO_SMALL)
            return
        self.close()
        self.parent.after(75, lambda: self.callback(region))

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for overlay in self.overlays:
            try:
                overlay.destroy()
            except tk.TclError:
                pass
        self.overlays.clear()
        self.parent.lift()
        self.parent.focus_force()
