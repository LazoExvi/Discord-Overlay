"""The Settings tab: scan tuning, attribution options, timer boards, hardware profile."""
from __future__ import annotations

from tkinter import messagebox, simpledialog

import customtkinter as ctk

from .. import __version__, shortcuts
from ..config import MINI_STAT_SLOTS, MINI_STATS, TimerBoard

STAT_NONE = "None"
STAT_KEYS = {label: key for key, label in MINI_STATS.items()}
from . import theme
from .dialogs import AboutWindow, GroupFilterEditor, open_diagnostics_folder

SORT_LABELS = {"started": "Start time", "remaining": "Time remaining", "name": "Name"}
SORT_MODES = {label: mode for mode, label in SORT_LABELS.items()}
GROWTH_LABELS = {"rows": "Across rows", "columns": "Down columns"}
GROWTH_MODES = {label: mode for mode, label in GROWTH_LABELS.items()}
LAYOUT_LABELS = {"docked": "Timer boards", "independent": "Independent"}
LAYOUT_MODES = {label: mode for mode, label in LAYOUT_LABELS.items()}


class SettingsTab:
    def __init__(self, tab, app) -> None:
        self.app = app
        self.settings = app.settings
        self._group_editor: GroupFilterEditor | None = None
        self._editing_board = ""
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        body = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        body.grid(row=0, column=0, sticky="nsew")
        body.grid_columnconfigure(1, weight=1)
        self._build_scan_settings(body)
        self._build_options(body)
        self._build_timer_boards(body)
        self._build_mini_overlay(body)
        self._build_hardware(body)
        self.refresh_from_settings()

    def _build_mini_overlay(self, body) -> None:
        frame = ctk.CTkFrame(body, fg_color=theme.PANEL_2, corner_radius=10)
        frame.grid(row=11, column=0, columnspan=3, padx=20, pady=(12, 0), sticky="ew")
        frame.grid_columnconfigure((0, 1, 2, 3), weight=1)
        ctk.CTkLabel(frame, text="MINI METER OVERLAY", text_color=theme.ACCENT, font=theme.font(bold=True), anchor="w").grid(
            row=0, column=0, columnspan=4, padx=16, pady=(11, 2), sticky="ew")
        theme.note(frame, ("A compact always-on-top meter for use while playing. Toggle it with the sidebar button; "
                           "use Move overlays to drag and resize it, then Lock overlays for click-through. Its position "
                           "is saved per character."), 760).grid(row=1, column=0, columnspan=4, padx=16, pady=(0, 8), sticky="ew")
        for column, label in enumerate(("Show", "Rows", "Opacity (%)")):
            theme.note(frame, label).grid(row=2, column=column, padx=16, pady=(2, 3), sticky="w")
        self.mini_metric_menu = ctk.CTkOptionMenu(frame, values=["Damage", "Healing"], width=150, **theme.MENU)
        self.mini_metric_menu.grid(row=3, column=0, padx=16, pady=(0, 12), sticky="w")
        self.mini_rows_menu = ctk.CTkOptionMenu(frame, values=[str(v) for v in range(1, 13)], width=90, **theme.MENU)
        self.mini_rows_menu.grid(row=3, column=1, padx=16, pady=(0, 12), sticky="w")
        self.mini_opacity_entry = ctk.CTkEntry(frame, width=100)
        self.mini_opacity_entry.grid(row=3, column=2, padx=16, pady=(0, 12), sticky="w")
        theme.note(frame, f"Header stats (up to {MINI_STAT_SLOTS}, shown left to right)").grid(
            row=4, column=0, columnspan=4, padx=16, pady=(2, 3), sticky="w")
        self.mini_stat_menus: list[ctk.CTkOptionMenu] = []
        for slot in range(MINI_STAT_SLOTS):
            menu = ctk.CTkOptionMenu(frame, values=[STAT_NONE, *MINI_STATS.values()], width=150, **theme.MENU)
            menu.grid(row=5, column=slot, padx=16, pady=(0, 12), sticky="w")
            self.mini_stat_menus.append(menu)

    # -- construction ---------------------------------------------------------

    def _build_scan_settings(self, body) -> None:
        rows = (
            ("Scan interval", "Seconds between OCR passes. GPU high-accuracy: 0.20–0.30."),
            ("Fight timeout", "Seconds without damage before an encounter ends."),
            ("Rolling window", "Seconds used for the short-term DPS number."),
            ("OCR confidence", "Reject uncertain text below this value (0–1)."),
        )
        self.number_entries: list[ctk.CTkEntry] = []
        for row, (label, help_text) in enumerate(rows):
            ctk.CTkLabel(body, text=label, text_color=theme.TEXT, anchor="w", font=theme.font(bold=True)).grid(
                row=row, column=0, padx=(20, 10), pady=(16, 0), sticky="nw")
            theme.note(body, help_text).grid(row=row, column=1, padx=8, pady=(16, 0), sticky="nw")
            entry = ctk.CTkEntry(body, width=90)
            entry.grid(row=row, column=2, padx=20, pady=(12, 0))
            self.number_entries.append(entry)
        self.interval_entry, self.timeout_entry, self.rolling_entry, self.confidence_entry = self.number_entries

    def _build_options(self, body) -> None:
        self.topmost_var = ctk.BooleanVar()
        self.combine_pet_var = ctk.BooleanVar()
        self.shield_wearer_var = ctk.BooleanVar()
        self.gpu_var = ctk.BooleanVar()
        self.repair_var = ctk.BooleanVar()
        ctk.CTkCheckBox(body, text="Keep parser above the game", variable=self.topmost_var, **theme.CHECKBOX).grid(
            row=5, column=0, columnspan=2, padx=20, pady=(24, 8), sticky="w")
        theme.note(body, ("All targets includes every recognized damage and healing actor. Enable the Group filter "
                          "to drop fights that do not involve your group."), 650).grid(
            row=6, column=0, columnspan=2, padx=20, pady=8, sticky="w")
        self.group_button = ctk.CTkButton(body, text="", command=self.show_group_filter, width=150, **theme.STEEL_BUTTON)
        self.group_button.grid(row=6, column=2, padx=20, pady=8)
        ctk.CTkCheckBox(body, text="Combine pet damage with mine", variable=self.combine_pet_var, **theme.CHECKBOX).grid(
            row=7, column=0, columnspan=2, padx=20, pady=8, sticky="w")
        ctk.CTkCheckBox(body, text="Attribute damage shields to buff wearer (off = one Damage Shield actor)",
                        variable=self.shield_wearer_var, **theme.CHECKBOX).grid(row=8, column=0, columnspan=2, padx=20, pady=8, sticky="w")
        ctk.CTkCheckBox(body, text="Use GPU acceleration when available", variable=self.gpu_var, **theme.CHECKBOX).grid(
            row=9, column=0, columnspan=2, padx=20, pady=8, sticky="w")
        ctk.CTkCheckBox(body, text="Repair lines partly hidden by the mouse cursor", variable=self.repair_var,
                        **theme.CHECKBOX).grid(row=9, column=2, padx=20, pady=8, sticky="w")

    def _build_timer_boards(self, body) -> None:
        frame = ctk.CTkFrame(body, fg_color=theme.PANEL_2, corner_radius=10)
        frame.grid(row=10, column=0, columnspan=3, padx=20, pady=(12, 0), sticky="ew")
        frame.grid_columnconfigure((0, 1, 2, 3), weight=1)
        ctk.CTkLabel(frame, text="TIMER BOARDS", text_color=theme.ACCENT, font=theme.font(bold=True), anchor="w").grid(
            row=0, column=0, columnspan=4, padx=16, pady=(11, 2), sticky="ew")
        theme.note(frame, "Create any board names you want: spawn timers, buffs, debuffs, boss mechanics.").grid(
            row=1, column=0, columnspan=4, padx=16, pady=(0, 8), sticky="ew")
        for column, label in enumerate(("Display mode", "Selected board", "Visual size", "Columns")):
            theme.note(frame, label).grid(row=2, column=column, padx=16, pady=(2, 3), sticky="w")
        self.layout_menu = ctk.CTkOptionMenu(frame, values=list(LAYOUT_LABELS.values()), width=150, **theme.MENU)
        self.layout_menu.grid(row=3, column=0, padx=16, pady=(0, 8), sticky="w")
        self.board_menu = ctk.CTkOptionMenu(frame, values=["Default"], width=170, command=self._board_selected, **theme.MENU)
        self.board_menu.grid(row=3, column=1, padx=16, pady=(0, 8), sticky="w")
        self.size_menu = ctk.CTkOptionMenu(frame, values=["Compact", "Standard", "Large"], width=150, **theme.MENU)
        self.size_menu.grid(row=3, column=2, padx=16, pady=(0, 8), sticky="w")
        self.columns_menu = ctk.CTkOptionMenu(frame, values=[str(v) for v in range(1, 7)], width=90, **theme.MENU)
        self.columns_menu.grid(row=3, column=3, padx=16, pady=(0, 8), sticky="w")

        theme.note(frame, "Board opacity (%)").grid(row=4, column=0, padx=16, pady=(3, 3), sticky="w")
        self.opacity_entry = ctk.CTkEntry(frame, width=100)
        self.opacity_entry.grid(row=5, column=0, padx=16, pady=(0, 12), sticky="w")
        ctk.CTkButton(frame, text="New board", width=110, command=self.new_board, **theme.STEEL_BUTTON).grid(
            row=5, column=1, padx=16, pady=(0, 12), sticky="w")
        ctk.CTkButton(frame, text="Delete board", width=110, command=self.delete_board, **theme.DANGER_BUTTON).grid(
            row=5, column=2, padx=16, pady=(0, 12), sticky="w")
        ctk.CTkButton(frame, text="Rename board", width=110, command=self.rename_board, **theme.STEEL_BUTTON).grid(
            row=5, column=3, padx=16, pady=(0, 12), sticky="w")

        theme.note(frame, "Order timers by").grid(row=6, column=0, padx=16, pady=(2, 3), sticky="w")
        self.sort_menu = ctk.CTkOptionMenu(frame, values=list(SORT_LABELS.values()), width=150, **theme.MENU)
        self.sort_menu.grid(row=7, column=0, padx=16, pady=(0, 12), sticky="w")
        theme.note(frame, "Fill grid").grid(row=6, column=1, padx=16, pady=(2, 3), sticky="w")
        self.growth_menu = ctk.CTkOptionMenu(frame, values=list(GROWTH_LABELS.values()), width=150, **theme.MENU)
        self.growth_menu.grid(row=7, column=1, padx=16, pady=(0, 12), sticky="w")
        ctk.CTkButton(frame, text="Preview selected board", width=170, command=self.preview_board, **theme.ACCENT_BUTTON).grid(
            row=7, column=2, columnspan=2, padx=16, pady=(0, 12), sticky="w")

        theme.note(frame, "Close overlay gesture").grid(row=8, column=0, padx=16, pady=(5, 3), sticky="w")
        self.close_enabled_var = ctk.BooleanVar()
        ctk.CTkCheckBox(frame, text="Modifier(s) + left-click", width=190, variable=self.close_enabled_var,
                        **theme.CHECKBOX).grid(row=9, column=0, padx=16, pady=(0, 5), sticky="w")
        modifiers = ["Control", "Shift", "Alt"]
        self.modifier1_menu = ctk.CTkOptionMenu(frame, values=modifiers, width=130, **theme.MENU)
        self.modifier1_menu.grid(row=9, column=1, padx=16, pady=(0, 5), sticky="w")
        self.modifier2_menu = ctk.CTkOptionMenu(frame, values=["None", *modifiers], width=130, **theme.MENU)
        self.modifier2_menu.grid(row=9, column=2, padx=16, pady=(0, 5), sticky="w")
        theme.note(frame, ("Works while overlays are locked and click-through. Hold the selected modifier(s), then "
                           "left-click one timer to close only that timer. Other timers stay visible."), 760).grid(
            row=10, column=0, columnspan=4, padx=16, pady=(0, 12), sticky="ew")

    def _build_hardware(self, body) -> None:
        frame = ctk.CTkFrame(body, fg_color=theme.PANEL_2, corner_radius=10)
        frame.grid(row=12, column=0, columnspan=3, padx=20, pady=(12, 0), sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text="OCR performance profile", text_color=theme.TEXT, font=theme.font(bold=True), anchor="w").grid(
            row=0, column=0, padx=16, pady=(12, 2), sticky="ew")
        self.hardware_label = theme.note(frame, "")
        self.hardware_label.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="ew")
        ctk.CTkButton(frame, text="Run hardware setup", command=self.app.show_hardware_setup, width=150, **theme.STEEL_BUTTON).grid(
            row=0, column=1, rowspan=2, padx=14, pady=12)
        ctk.CTkButton(frame, text="Save settings", command=self.app.save_settings, width=120, **theme.ACCENT_BUTTON).grid(
            row=0, column=2, rowspan=2, padx=(0, 14), pady=12)
        footer = ctk.CTkFrame(body, fg_color="transparent")
        footer.grid(row=13, column=0, columnspan=3, padx=20, pady=(12, 18), sticky="ew")
        ctk.CTkButton(footer, text="About Discord Overlay", command=lambda: AboutWindow(self.app), width=170,
                      **theme.STEEL_BUTTON).pack(side="left")
        ctk.CTkButton(footer, text="Start Menu shortcut", width=150, **theme.STEEL_BUTTON,
                      command=lambda: self.app.add_shortcut(shortcuts.start_menu_dir(), "Start Menu")).pack(side="left", padx=(10, 0))
        ctk.CTkButton(footer, text="Desktop shortcut", width=140, **theme.STEEL_BUTTON,
                      command=lambda: self.app.add_shortcut(shortcuts.desktop_dir(), "Desktop")).pack(side="left", padx=(10, 0))
        ctk.CTkButton(footer, text="Open diagnostics", command=open_diagnostics_folder, width=150, **theme.STEEL_BUTTON).pack(
            side="left", padx=10)
        ctk.CTkLabel(footer, text=f"Version {__version__} • Windows 10/11 x64", text_color=theme.MUTED).pack(side="right", padx=4)

    # -- settings <-> widgets -------------------------------------------------

    def refresh_from_settings(self) -> None:
        s = self.settings
        for entry, value in zip(self.number_entries, (s.scan_interval, s.encounter_timeout, s.rolling_window, s.min_confidence)):
            entry.delete(0, "end")
            entry.insert(0, str(value))
        self.topmost_var.set(s.always_on_top)
        self.combine_pet_var.set(s.combine_pet_damage)
        self.shield_wearer_var.set(s.damage_shields_by_wearer)
        self.gpu_var.set(s.prefer_gpu)
        self.repair_var.set(s.repair_occluded_lines)
        self.close_enabled_var.set(s.overlay_close_enabled)
        self.modifier1_menu.set(s.overlay_close_modifier1.title())
        self.modifier2_menu.set(s.overlay_close_modifier2.title())
        self.mini_metric_menu.set(s.mini_overlay_metric.title())
        self.mini_rows_menu.set(str(s.mini_overlay_rows))
        self.mini_opacity_entry.delete(0, "end")
        self.mini_opacity_entry.insert(0, f"{s.mini_overlay_opacity * 100:.0f}")
        for slot, menu in enumerate(self.mini_stat_menus):
            key = s.mini_overlay_stats[slot] if slot < len(s.mini_overlay_stats) else None
            menu.set(MINI_STATS.get(key, STAT_NONE))
        self.refresh_character_fields()
        self.refresh_hardware_label()

    def refresh_character_fields(self) -> None:
        """Re-read the fields that change when the active character changes."""
        self.layout_menu.set(LAYOUT_LABELS[self.settings.timer_layout])
        names = self.settings.board_names()
        self.board_menu.configure(values=names)
        self.board_menu.set(names[0])
        self.load_board_controls(names[0])
        self.refresh_group_button()

    def refresh_group_button(self) -> None:
        if self.settings.actor_filter_enabled:
            self.group_button.configure(text=f"Group filter: On ({len(self.settings.allowed_actor_names)})")
        else:
            self.group_button.configure(text="Group filter: Off")

    def refresh_hardware_label(self) -> None:
        s = self.settings
        if s.performance_profile == "Not tested":
            text = "Not benchmarked yet"
        else:
            text = (f"Last test: {s.performance_profile} • {s.benchmark_provider or 'Unknown provider'} • "
                    f"OCR {s.benchmark_ocr_ms:.0f} ms • {s.scan_interval:.2f}s scan interval")
        self.hardware_label.configure(text=text)

    def apply_to_settings(self) -> None:
        """Copy widget values into settings; raises ValueError with a user-facing message."""
        interval, timeout, rolling, confidence = (float(entry.get()) for entry in self.number_entries)
        if not 0.15 <= interval <= 5.0:
            raise ValueError("Scan interval must be between 0.15 and 5 seconds.")
        if not 2 <= timeout <= 60:
            raise ValueError("Fight timeout must be between 2 and 60 seconds.")
        if not 2 <= rolling <= 60:
            raise ValueError("Rolling window must be between 2 and 60 seconds.")
        if not 0.1 <= confidence <= 0.99:
            raise ValueError("OCR confidence must be between 0.1 and 0.99.")
        modifier1 = self.modifier1_menu.get().casefold()
        modifier2 = self.modifier2_menu.get().casefold()
        if modifier2 != "none" and modifier1 == modifier2:
            raise ValueError("Choose two different overlay-close modifiers, or set the second to None.")
        mini_opacity = float(self.mini_opacity_entry.get()) / 100.0
        if not 0.2 <= mini_opacity <= 1.0:
            raise ValueError("Mini meter opacity must be between 20 and 100 percent.")
        self.store_board_controls()
        s = self.settings
        s.mini_overlay_metric = self.mini_metric_menu.get().casefold()
        s.mini_overlay_rows = int(self.mini_rows_menu.get())
        s.mini_overlay_opacity = mini_opacity
        chosen = [STAT_KEYS[menu.get()] for menu in self.mini_stat_menus if menu.get() in STAT_KEYS]
        s.mini_overlay_stats = list(dict.fromkeys(chosen))  # keep order, drop duplicates
        s.scan_interval, s.encounter_timeout, s.rolling_window, s.min_confidence = interval, timeout, rolling, confidence
        s.always_on_top = bool(self.topmost_var.get())
        s.combine_pet_damage = bool(self.combine_pet_var.get())
        s.damage_shields_by_wearer = bool(self.shield_wearer_var.get())
        s.prefer_gpu = bool(self.gpu_var.get())
        s.repair_occluded_lines = bool(self.repair_var.get())
        s.timer_layout = LAYOUT_MODES[self.layout_menu.get()]
        s.overlay_close_enabled = bool(self.close_enabled_var.get())
        s.overlay_close_modifier1, s.overlay_close_modifier2 = modifier1, modifier2
        # Independent timers use the selected board's visual size as their default.
        s.timer_visual_size = self.settings.timer_board(self.board_menu.get()).visual_size

    def commit_character_state(self) -> None:
        """Pull unsaved board/layout widget values into settings before switching characters."""
        try:
            self.store_board_controls()
        except ValueError:
            pass
        self.settings.timer_layout = LAYOUT_MODES[self.layout_menu.get()]

    # -- timer boards ---------------------------------------------------------

    def load_board_controls(self, name: str) -> None:
        board = self.settings.timer_board(name)
        self._editing_board = board.name
        self.size_menu.set(board.visual_size.title())
        self.columns_menu.set(str(board.columns))
        self.opacity_entry.delete(0, "end")
        self.opacity_entry.insert(0, f"{board.opacity * 100:.0f}")
        self.sort_menu.set(SORT_LABELS.get(board.sort_order, "Start time"))
        self.growth_menu.set(GROWTH_LABELS.get(board.growth_direction, "Across rows"))

    def store_board_controls(self) -> None:
        if not self._editing_board:
            return
        board = self.settings.timer_board(self._editing_board)
        opacity = float(self.opacity_entry.get()) / 100.0
        if not 0.2 <= opacity <= 1.0:
            raise ValueError("Board opacity must be between 20 and 100 percent.")
        board.visual_size = self.size_menu.get().casefold()
        board.columns = int(self.columns_menu.get())
        board.opacity = opacity
        board.sort_order = SORT_MODES.get(self.sort_menu.get(), "started")
        board.growth_direction = GROWTH_MODES.get(self.growth_menu.get(), "rows")

    def _store_or_warn(self) -> bool:
        try:
            self.store_board_controls()
            return True
        except ValueError as exc:
            messagebox.showerror("Invalid timer board", str(exc), parent=self.app)
            return False

    def _board_selected(self, name: str) -> None:
        self._store_or_warn()
        self.load_board_controls(name)

    def _select_board(self, name: str) -> None:
        self.board_menu.configure(values=self.settings.board_names())
        self.board_menu.set(name)
        self.load_board_controls(name)

    def preview_board(self) -> None:
        if not self._store_or_warn():
            return
        board = self.settings.timer_board(self.board_menu.get())
        self.app.overlays.preview_board(board)
        self.app.set_status(f"Previewing timer board: {board.name} (current unsaved controls)", theme.GREEN)

    def _ask_board_name(self, title: str, initial: str = "") -> str | None:
        name = simpledialog.askstring(title, "Board name:", initialvalue=initial, parent=self.app)
        name = (name or "").strip()
        if not name or name == initial:
            return None
        if any(board.name.casefold() == name.casefold() for board in self.settings.timer_boards):
            messagebox.showerror("Duplicate board", "That timer board already exists.", parent=self.app)
            return None
        return name

    def new_board(self) -> None:
        if not self._store_or_warn():
            return
        name = self._ask_board_name("New timer board")
        if name:
            self.settings.timer_boards.append(TimerBoard(name=name))
            self._select_board(name)

    def delete_board(self) -> None:
        if len(self.settings.timer_boards) <= 1:
            messagebox.showinfo("Timer boards", "At least one timer board is required.", parent=self.app)
            return
        board = self.settings.timer_board(self.board_menu.get())
        if not messagebox.askyesno("Delete timer board", f"Delete '{board.name}'? Its triggers move to the first "
                                                         "remaining board.", parent=self.app):
            return
        self.settings.timer_boards.remove(board)
        fallback = self.settings.timer_boards[0].name
        self.app.overlays.rename_board(board.name, fallback)
        self.app.overlays.forget_board(board.id)
        self._select_board(fallback)

    def rename_board(self) -> None:
        if not self._store_or_warn():
            return
        board = self.settings.timer_board(self.board_menu.get())
        name = self._ask_board_name("Rename timer board", board.name)
        if not name:
            return
        self.app.overlays.rename_board(board.name, name)
        self.app.overlays.forget_board(board.id)
        board.name = name
        self._select_board(name)

    # -- group filter ---------------------------------------------------------

    def show_group_filter(self) -> None:
        if self._group_editor and self._group_editor.winfo_exists():
            theme.bring_to_front(self._group_editor)
            return
        self._group_editor = GroupFilterEditor(self.app, self.settings.actor_filter_enabled,
                                               self.settings.allowed_actor_names, self._save_group_filter)

    def _save_group_filter(self, enabled: bool, names: list[str]) -> None:
        self.settings.actor_filter_enabled = enabled
        self.settings.allowed_actor_names = names
        self.settings.save()
        self.refresh_group_button()
        if enabled:
            self.app.set_status(f"Group filter enabled • {len(names)} group names", theme.GREEN)
        else:
            self.app.set_status("Group filter disabled", theme.MUTED)
