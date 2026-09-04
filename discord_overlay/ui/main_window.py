"""The main window: sidebar metrics, live preview, and the Combatants/Alerts/Log/Settings tabs."""
from __future__ import annotations

import logging
import queue
import time
import tkinter as tk
import warnings
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk
import cv2
from PIL import Image

from .. import APP_NAME, __version__
from ..actor_filter import actor_event_allowed
from ..audio import SoundPlayer, ensure_default_sounds
from ..capture import ScreenCapture
from ..config import Settings
from ..diagnostics import LOGGER_NAME
from ..encounter import EncounterTracker
from ..models import CombatEvent, EventKind, OCRLine, Region
from ..paths import ensure_app_directories
from ..performance import CapabilityResult
from ..scanner import ScannerWorker
from .. import shortcuts
from ..speech import SpeechPlayer
from ..timers import TimerManager, TimerNotification, render_template
from ..triggers import BUILTIN_PREFIX, TriggerMatch, is_builtin_sound
from . import theme
from .alerts_tab import AlertsTab
from .overlays import OverlayManager
from .region_selector import RegionSelector
from .settings_tab import SettingsTab
from .setup_wizard import HardwareSetupWizard
from .tips import ACCURACY_TIPS
from .widgets import Column, MeterView, MetricCard, SortableTree, Sparkline, StatusPill, configure_tree_style

EVENT_TAGS = {EventKind.DAMAGE_OUT: "out", EventKind.DAMAGE_IN: "in", EventKind.HEAL: "heal"}
MAX_LOG_ROWS = 1000
ALL_TARGETS = "All targets"
PREVIEW_SIZE = (230, 106)
VIEW_BARS, VIEW_TABLE = "Bars", "Table"
METRIC_DAMAGE, METRIC_HEALING = "Damage", "Healing"


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__(fg_color=theme.BG)
        theme.apply_window_icon(self)
        ensure_app_directories()
        self.logger = logging.getLogger(LOGGER_NAME)
        self.title(f"{APP_NAME} {__version__}")
        self.geometry("1260x900")
        self.minsize(1040, 760)

        self.settings = Settings.load()
        self.tracker = EncounterTracker(
            self.settings.encounter_timeout, self.settings.rolling_window, self.settings.player_name,
            self.settings.combine_pet_damage, self.settings.damage_shields_by_wearer, self.settings.keep_running_totals,
        )
        self.timers = TimerManager(self.settings.timer_layout, self.settings.timer_visual_size)
        self.overlays = OverlayManager(self, self.settings, self.timers, self._overlay_status)
        self.messages: queue.Queue = queue.Queue()
        self.worker: ScannerWorker | None = None
        self.running = False
        self.default_sound_paths = ensure_default_sounds()
        self.sound_player = SoundPlayer()
        self.speech_player = SpeechPlayer()
        self.last_ocr: list[OCRLine] = []
        self._preview_photo = None
        self._log_iids: list[str] = []
        self._target_values = [ALL_TARGETS]
        self._region_selector: RegionSelector | None = None
        self._selector_pending: str | None = None
        self._region_callback = None
        self._setup_wizard: HardwareSetupWizard | None = None

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.attributes("-topmost", self.settings.always_on_top)
        configure_tree_style(self)
        self._build_ui()
        self.after(100, self._poll)
        self.after(250, self._tick)
        self.overlays.start_close_gesture_polling()
        self.after(250, self._maybe_show_setup)

    def report_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:
        self.logger.critical("Unhandled interface exception", exc_info=(exc_type, exc_value, exc_traceback))
        messagebox.showerror(f"{APP_NAME} encountered an error",
                             "The error was saved in the diagnostics folder (Settings > Open diagnostics).", parent=self)

    # -- layout ---------------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_sidebar()
        content = ctk.CTkFrame(self, fg_color=theme.BG, corner_radius=0)
        content.grid(row=1, column=1, padx=16, pady=(12, 16), sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)
        self._build_preview_bar(content)
        self.tabs = ctk.CTkTabview(content, fg_color=theme.PANEL, border_width=1, border_color=theme.BORDER,
                                   segmented_button_fg_color=theme.PANEL_2,
                                   segmented_button_selected_color=theme.ACCENT_DEEP,
                                   segmented_button_selected_hover_color="#6b78ff",
                                   segmented_button_unselected_color=theme.PANEL_2,
                                   segmented_button_unselected_hover_color=theme.PANEL_3)
        self.tabs.grid(row=1, column=0, sticky="nsew")
        self._build_combatants_tab(self.tabs.add("Combatants"))
        self.alerts = AlertsTab(self.tabs.add("Alerts & Timers"), self)
        self._build_log_tab(self.tabs.add("Log"))
        self.settings_tab = SettingsTab(self.tabs.add("Settings"), self)
        self._build_tips_tab(self.tabs.add("OCR Tips"))
        self.tabs.set("Combatants")
        self._refresh_start_button()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=0, height=58, border_width=0)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(2, weight=1)
        logo = theme.icon_image(30)
        ctk.CTkLabel(header, text="", image=logo, width=30).grid(row=0, column=0, padx=(18, 8), pady=14)
        ctk.CTkLabel(header, text="DISCORD OVERLAY", text_color=theme.TEXT, font=theme.display_font(17)).grid(
            row=0, column=1, pady=14, sticky="w")
        ctk.CTkLabel(header, text=f"v{__version__}", text_color=theme.DIM, font=theme.font(11)).grid(
            row=0, column=2, padx=(8, 0), pady=14, sticky="w")
        self.status_pill = StatusPill(header)
        self.status_pill.grid(row=0, column=3, padx=18, pady=13, sticky="e")
        self.status_pill.set("Ready to monitor" if self.settings.region else "Choose the combat region",
                             theme.ACCENT if self.settings.region else theme.MUTED)
        ctk.CTkFrame(self, fg_color=theme.BORDER, height=1, corner_radius=0).grid(row=0, column=0, columnspan=2, sticky="sew")

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, width=282, fg_color="#0e1117", corner_radius=0)
        sidebar.grid(row=1, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(sidebar, text="CHARACTER", text_color=theme.MUTED, font=theme.display_font(10)).grid(
            row=0, column=0, columnspan=2, padx=20, pady=(18, 0), sticky="w")
        bar = ctk.CTkFrame(sidebar, fg_color="transparent")
        bar.grid(row=1, column=0, columnspan=2, padx=20, pady=(4, 12), sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        self.character_menu = ctk.CTkOptionMenu(bar, values=self.settings.character_names(), command=self._character_changed,
                                                height=36, font=theme.display_font(15), **theme.MENU)
        self.character_menu.set(self.settings.active_character)
        self.character_menu.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(bar, text="⋯", width=36, height=36, command=self._show_character_menu, font=theme.font(16, bold=True),
                      **theme.STEEL_BUTTON).grid(row=0, column=1, padx=(6, 0))

        self.start_button = ctk.CTkButton(sidebar, text="Start monitoring", command=self.toggle_monitoring, height=44,
                                          corner_radius=10, text_color="white", font=theme.display_font(14), **theme.START_BUTTON)
        self.start_button.grid(row=2, column=0, columnspan=2, padx=20, pady=(6, 6), sticky="ew")
        ctk.CTkButton(sidebar, text="Select region", command=self.select_region, height=34, corner_radius=10,
                      **theme.STEEL_BUTTON).grid(row=3, column=0, columnspan=2, padx=20, pady=(0, 4), sticky="ew")
        self.mini_button = ctk.CTkButton(sidebar, text="", command=self.toggle_mini_overlay, height=32, corner_radius=10,
                                         **theme.STEEL_BUTTON)
        self.mini_button.grid(row=4, column=0, padx=(20, 3), pady=(0, 4), sticky="ew")
        self.arrange_button = ctk.CTkButton(sidebar, text="Move overlays", command=self.toggle_arrange, height=32,
                                            corner_radius=10, **theme.QUIET_BUTTON)
        self.arrange_button.grid(row=4, column=1, padx=(3, 20), pady=(0, 4), sticky="ew")
        self._refresh_mini_button()

        metrics = ctk.CTkFrame(sidebar, fg_color="transparent")
        metrics.grid(row=5, column=0, columnspan=2, padx=15, pady=(10, 0), sticky="ew")
        metrics.grid_columnconfigure((0, 1), weight=1)
        self.dps_card = MetricCard(metrics, "Encounter DPS", theme.ACCENT)
        self.rolling_card = MetricCard(metrics, "10s DPS", theme.CYAN)
        self.incoming_card = MetricCard(metrics, "Incoming", theme.RED)
        self.damage_card = MetricCard(metrics, "Damage", theme.AMBER)
        self.healing_card = MetricCard(metrics, "Healing", theme.GREEN)
        self.hps_card = MetricCard(metrics, "HPS", theme.GREEN)
        self.duration_card = MetricCard(metrics, "Duration", theme.PURPLE, size=22)
        for index, card in enumerate((self.dps_card, self.rolling_card, self.incoming_card, self.damage_card,
                                      self.healing_card, self.hps_card)):
            card.grid(row=index // 2, column=index % 2, padx=4, pady=4, sticky="ew")
        self.duration_card.grid(row=3, column=0, columnspan=2, padx=4, pady=4, sticky="ew")

        spark_card = theme.card(sidebar)
        spark_card.grid(row=6, column=0, columnspan=2, padx=19, pady=(8, 0), sticky="ew")
        spark_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(spark_card, text="10S DPS TREND", text_color=theme.MUTED, font=theme.display_font(10), anchor="w").grid(
            row=0, column=0, padx=12, pady=(8, 0), sticky="w")
        self.sparkline = Sparkline(spark_card, color=theme.CYAN)
        self.sparkline.grid(row=1, column=0, padx=8, pady=(2, 8), sticky="ew")

        ctk.CTkButton(sidebar, text="Export current data (CSV)", command=self.export_csv, fg_color="transparent",
                      border_width=1, border_color=theme.BORDER, hover_color=theme.PANEL_2, corner_radius=10).grid(
            row=7, column=0, columnspan=2, padx=20, pady=(12, 5), sticky="ew")
        self.running_totals_var = ctk.BooleanVar(value=self.settings.keep_running_totals)
        ctk.CTkCheckBox(sidebar, text="Keep running totals until Reset", variable=self.running_totals_var,
                        command=self._running_totals_changed, text_color=theme.TEXT, font=theme.font(12), **theme.CHECKBOX).grid(
            row=8, column=0, columnspan=2, padx=20, pady=(6, 1), sticky="w")
        ctk.CTkLabel(sidebar, text="Combines fights; idle time is excluded.", text_color=theme.DIM, font=theme.font(10),
                     anchor="w").grid(row=9, column=0, columnspan=2, padx=45, pady=(0, 4), sticky="ew")
        ctk.CTkButton(sidebar, text="Reset", command=self.reset_encounter, height=32, corner_radius=10, **theme.QUIET_BUTTON).grid(
            row=10, column=0, columnspan=2, padx=20, pady=(2, 14), sticky="ew")
        sidebar.grid_rowconfigure(11, weight=1)

    # -- mini overlay ---------------------------------------------------------

    def _refresh_mini_button(self) -> None:
        on = self.settings.mini_overlay_enabled
        self.mini_button.configure(text="Mini meter: On" if on else "Mini meter: Off",
                                   **(theme.ACCENT_BUTTON if on else theme.STEEL_BUTTON))

    def toggle_mini_overlay(self) -> None:
        self.overlays.set_mini_enabled(not self.settings.mini_overlay_enabled)
        self._refresh_mini_button()
        if self.settings.mini_overlay_enabled:
            self._render_mini()
            self.set_status("Mini meter shown. Use Move overlays to place it.", theme.GREEN)
        else:
            self.set_status("Mini meter hidden", theme.MUTED)

    def toggle_arrange(self) -> None:
        if self.overlays.arranging:
            self.overlays.lock()
        else:
            self.overlays.arrange()
        self._refresh_arrange_button()

    def _refresh_arrange_button(self) -> None:
        if self.overlays.arranging:
            self.arrange_button.configure(text="Lock overlays", **theme.ACCENT_BUTTON)
        else:
            self.arrange_button.configure(text="Move overlays", **theme.QUIET_BUTTON)

    def _render_mini(self) -> None:
        if not self.settings.mini_overlay_enabled and self.overlays.mini is None:
            return
        rows = self.tracker.actor_totals()
        self.overlays.render_mini(self.tracker.snapshot(), rows)

    def _build_preview_bar(self, content) -> None:
        bar = theme.card(content, height=126)
        bar.grid(row=0, column=0, pady=(0, 12), sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(1, weight=1)
        self.preview = ctk.CTkLabel(bar, text="LIVE PREVIEW", width=PREVIEW_SIZE[0], height=PREVIEW_SIZE[1],
                                    fg_color=theme.BG_DEEP, corner_radius=7, text_color="#526272")
        self.preview.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        info = ctk.CTkFrame(bar, fg_color="transparent")
        info.grid(row=0, column=1, padx=12, pady=10, sticky="nsew")
        self.region_label = ctk.CTkLabel(info, text=self._region_text(), text_color=theme.TEXT, font=theme.display_font(15), anchor="w")
        self.region_label.pack(fill="x", pady=(8, 2))
        self.scan_label = ctk.CTkLabel(info, text="OCR idle", text_color=theme.MUTED, anchor="w")
        self.scan_label.pack(fill="x")
        self.raw_label = ctk.CTkLabel(info, text="Select the scrolling message area with a small margin; do not cut off any text.",
                                      text_color="#708397", anchor="w", justify="left", wraplength=620)
        self.raw_label.pack(fill="x", pady=(7, 0))

    def _build_combatants_tab(self, tab) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        scope = ctk.CTkFrame(tab, fg_color="transparent")
        scope.grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 4), sticky="ew")
        scope.grid_columnconfigure(2, weight=1)
        self.view_toggle = ctk.CTkSegmentedButton(scope, values=[VIEW_BARS, VIEW_TABLE], command=lambda _v: self._switch_view(),
                                                  **theme.SEGMENT)
        self.view_toggle.set(VIEW_BARS)
        self.view_toggle.grid(row=0, column=0, padx=(0, 8))
        self.metric_toggle = ctk.CTkSegmentedButton(scope, values=[METRIC_DAMAGE, METRIC_HEALING],
                                                    command=lambda _v: self._refresh_metrics(), **theme.SEGMENT)
        self.metric_toggle.set(METRIC_DAMAGE)
        self.metric_toggle.grid(row=0, column=1)
        ctk.CTkLabel(scope, text="Target", text_color=theme.MUTED).grid(row=0, column=3, padx=(12, 6))
        self.target_menu = ctk.CTkOptionMenu(scope, values=[ALL_TARGETS], command=lambda _v: self._refresh_metrics(),
                                             width=210, **theme.MENU)
        self.target_menu.set(ALL_TARGETS)
        self.target_menu.grid(row=0, column=4)

        self.meter_frame = ctk.CTkFrame(tab, fg_color=theme.PANEL, corner_radius=0)
        self.meter_frame.grid(row=1, column=0, columnspan=2, padx=8, pady=(4, 8), sticky="nsew")
        self.meter_frame.grid_columnconfigure(0, weight=1)
        self.meter_frame.grid_rowconfigure(0, weight=1)
        self.meter = MeterView(self.meter_frame)
        self.meter.grid(row=0, column=0, sticky="nsew")
        meter_scroll = ctk.CTkScrollbar(self.meter_frame, command=self.meter.yview)
        meter_scroll.grid(row=0, column=1, sticky="ns")
        self.meter.configure(yscrollcommand=meter_scroll.set)

        self.table_frame = ctk.CTkFrame(tab, fg_color="transparent", corner_radius=0)
        self.table_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")
        self.table_frame.grid_columnconfigure(0, weight=1)
        self.table_frame.grid_rowconfigure(0, weight=1)
        self.table_frame.grid_remove()
        self.actor_table = SortableTree(self.table_frame, [
            Column("actor", "ACTOR", 210), Column("type", "TYPE", 110), Column("damage", "DAMAGE", 115, "e", True),
            Column("share", "SHARE", 80, "e", True), Column("dps", "DPS", 100, "e", True),
            Column("rolling_dps", "10S DPS", 100, "e", True), Column("hits", "HITS", 70, "e", True),
            Column("crits", "CRITS", 70, "e", True), Column("healing", "HEALING", 105, "e", True),
            Column("hps", "HPS", 90, "e", True),
        ], order=self.settings.breakdown_column_order, on_order_changed=lambda order: self._save_column_order("breakdown_column_order", order))
        tree = self.actor_table.tree
        vertical = ctk.CTkScrollbar(self.table_frame, command=tree.yview)
        horizontal = ctk.CTkScrollbar(self.table_frame, orientation="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, padx=(8, 0), pady=(4, 0), sticky="nsew")
        vertical.grid(row=0, column=1, padx=(0, 8), pady=(4, 0), sticky="ns")
        horizontal.grid(row=1, column=0, padx=(8, 0), pady=(0, 8), sticky="ew")

    def _switch_view(self) -> None:
        if self.view_toggle.get() == VIEW_TABLE:
            self.meter_frame.grid_remove()
            self.table_frame.grid()
        else:
            self.table_frame.grid_remove()
            self.meter_frame.grid()
        self._refresh_metrics()

    def _build_log_tab(self, tab) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        self.log_table = SortableTree(tab, [
            Column("time", "TIME", 80), Column("type", "TYPE", 80), Column("actor", "ACTOR", 125),
            Column("action", "ACTION", 105), Column("target", "TARGET", 190), Column("amount", "AMOUNT", 80, "e", True),
            Column("crit", "CRIT", 48), Column("conf", "OCR", 55, "e", True),
        ], order=self.settings.events_column_order,
            on_order_changed=lambda order: self._save_column_order("events_column_order", order), selectmode="browse")
        tree = self.log_table.tree
        tree.tag_configure("out", foreground=theme.DAMAGE_OUT_COLOR)
        tree.tag_configure("in", foreground=theme.DAMAGE_IN_COLOR)
        tree.tag_configure("heal", foreground=theme.HEAL_COLOR)
        tree.tag_configure("other", foreground=theme.SLATE)
        scroll = ctk.CTkScrollbar(tab, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0, column=0, padx=(8, 0), pady=8, sticky="nsew")
        scroll.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="ns")

    @staticmethod
    def _build_tips_tab(tab) -> None:
        tab.grid_columnconfigure(0, weight=1)
        theme.heading(tab, "OCR ACCURACY TIPS").grid(row=0, column=0, padx=28, pady=(28, 12), sticky="ew")
        ctk.CTkLabel(tab, text=ACCURACY_TIPS, text_color=theme.TEXT, font=theme.font(14), justify="left", anchor="nw",
                     wraplength=760).grid(row=1, column=0, padx=28, pady=(0, 24), sticky="nw")

    def _save_column_order(self, field: str, order: list[str]) -> None:
        setattr(self.settings, field, order)
        self.settings.save()

    # -- status helpers -------------------------------------------------------

    def set_status(self, text: str, color: str = theme.MUTED) -> None:
        self.status_pill.set(text, color, pulse=self.running)

    def _overlay_status(self, text: str, kind: str) -> None:
        if hasattr(self, "alerts"):
            self.alerts.status(text, kind)

    def _region_text(self) -> str:
        region = self.settings.region
        return f"Capture: {region.describe()}" if region else "No capture region selected"

    def _refresh_start_button(self) -> None:
        if self.running:
            self.start_button.configure(state="normal", text="Stop monitoring", **theme.STOP_BUTTON)
        elif self.settings.region:
            self.start_button.configure(state="normal", text="Start monitoring", **theme.START_BUTTON)
        else:
            self.start_button.configure(state="disabled", text="Select a region first", **theme.DISABLED_BUTTON)

    # -- characters -----------------------------------------------------------

    def _refresh_character_menu(self) -> None:
        self.character_menu.configure(values=self.settings.character_names())
        self.character_menu.set(self.settings.active_character)

    def _show_character_menu(self) -> None:
        menu = tk.Menu(self, tearoff=0, bg=theme.PANEL_2, fg=theme.TEXT, activebackground="#304a64", activeforeground=theme.TEXT)
        menu.add_command(label="New character (copy current)", command=lambda: self._new_character(True))
        menu.add_command(label="New character (blank)", command=lambda: self._new_character(False))
        menu.add_command(label="Rename character", command=self._rename_character)
        menu.add_separator()
        menu.add_command(label="Delete character", command=self._delete_character)
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def _character_changed(self, name: str) -> None:
        if name.casefold() == self.settings.active_character.casefold():
            return
        self.settings_tab.commit_character_state()
        if not self.settings.switch_character(name):
            self._refresh_character_menu()
            return
        self.settings.save()
        self._apply_character_to_ui()
        self.set_status(f"Switched to {self.settings.active_character}", theme.ACCENT)

    def _new_character(self, copy_current: bool) -> None:
        name = simpledialog.askstring("New character", "Character name (exactly as shown in game, used for You/Your attribution):",
                                      parent=self)
        if not name or not name.strip():
            return
        self.settings_tab.commit_character_state()
        try:
            self.settings.add_character(name, copy_current=copy_current)
            self.settings.switch_character(name.strip())
        except ValueError as exc:
            messagebox.showerror("Character", str(exc), parent=self)
            return
        self.settings.save()
        self._apply_character_to_ui()
        self.set_status(f"Created character {self.settings.active_character}", theme.GREEN)

    def _rename_character(self) -> None:
        current = self.settings.active_character
        name = simpledialog.askstring("Rename character", "Character name:", initialvalue=current, parent=self)
        if not name or not name.strip() or name.strip() == current:
            return
        try:
            self.settings.rename_character(current, name)
        except ValueError as exc:
            messagebox.showerror("Character", str(exc), parent=self)
            return
        self.settings.save()
        self._apply_character_to_ui()

    def _delete_character(self) -> None:
        current = self.settings.active_character
        if len(self.settings.characters) <= 1:
            messagebox.showinfo("Character", "At least one character is required.", parent=self)
            return
        if not messagebox.askyesno("Delete character", f"Delete '{current}' and its saved region, timer boards, and overlay layout?",
                                   parent=self):
            return
        try:
            self.settings.delete_character(current)
        except ValueError as exc:
            messagebox.showerror("Character", str(exc), parent=self)
            return
        self.settings.save()
        self._apply_character_to_ui()
        self.set_status(f"Deleted {current}; now using {self.settings.active_character}", theme.MUTED)

    def _apply_character_to_ui(self) -> None:
        """Rebuild everything that mirrors character-specific settings."""
        was_running = self.running
        if was_running:
            self.stop_monitoring()
        self.overlays.reset_for_character()
        self.tracker.player_name = self.settings.player_name
        self._refresh_character_menu()
        self._refresh_mini_button()
        self.settings_tab.refresh_character_fields()
        self.alerts.refresh_profiles()
        self.alerts.refresh()
        self.region_label.configure(text=self._region_text())
        self._clear_preview()
        if self.settings.region:
            try:
                self._show_preview(ScreenCapture().grab(self.settings.region))
            except Exception:  # noqa: BLE001 - preview is cosmetic
                pass
        self._refresh_start_button()
        if was_running and self.settings.region:
            self.after(150, self.start_monitoring)

    # -- region selection -----------------------------------------------------

    def select_region(self, callback=None) -> None:
        self._region_callback = callback or self._region_selected
        if self.running:
            self.stop_monitoring()
        if self._selector_pending is not None:
            self.after_cancel(self._selector_pending)
        if self._region_selector is not None and not self._region_selector.closed:
            self._region_selector.close()
        self.set_status("Release mouse… selection opening", theme.ACCENT)
        # A topmost overlay must not be created inside the click that pressed the button.
        self._selector_pending = self.after(400, self._open_region_selector)

    def _open_region_selector(self) -> None:
        self._selector_pending = None
        callback = self._region_callback

        def selected(region: Region) -> None:
            self._region_selector = None
            self.settings.remember_region(region)
            self.settings.save()
            if callback:
                callback(region)

        self._region_selector = RegionSelector(self, selected, self.settings.region_history, self._clear_region_history)

    def _clear_region_history(self) -> None:
        self.settings.region_history.clear()
        self.settings.save()
        self.set_status("Saved region history cleared", theme.MUTED)

    def _region_selected(self, region: Region) -> None:
        self.settings.region = region
        self.settings.remember_region(region)
        self.settings.save()
        self.region_label.configure(text=self._region_text())
        self._refresh_start_button()
        self.set_status("Ready to monitor", theme.ACCENT)
        try:
            self._show_preview(ScreenCapture().grab(region))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Capture failed", str(exc), parent=self)

    # -- hardware setup -------------------------------------------------------

    def _maybe_show_setup(self) -> None:
        self._maybe_offer_shortcut()
        if not self.settings.setup_completed:
            self.show_hardware_setup()

    def _maybe_offer_shortcut(self) -> None:
        """Once, for the portable build: offer a Start Menu entry so it feels installed."""
        if not shortcuts.is_frozen():
            return
        if shortcuts.repair_shortcuts():
            self.set_status("Shortcuts updated to this version's location", theme.GREEN)
        if self.settings.shortcut_prompted:
            return
        self.settings.shortcut_prompted = True
        self.settings.save()
        if shortcuts.shortcut_exists(shortcuts.start_menu_dir()):
            return
        if messagebox.askyesno("Add to Start Menu",
                               f"Add {APP_NAME} to your Start Menu so you can launch it without opening this folder?\n\n"
                               "You can add or remove shortcuts later under Settings.", parent=self):
            self.add_shortcut(shortcuts.start_menu_dir(), "Start Menu")

    def add_shortcut(self, directory: Path, label: str) -> None:
        try:
            shortcuts.create_shortcut(directory)
        except OSError as exc:
            messagebox.showerror("Shortcut failed", str(exc), parent=self)
            return
        self.set_status(f"{label} shortcut created", theme.GREEN)

    def show_hardware_setup(self) -> None:
        if self._setup_wizard is not None:
            try:
                if self._setup_wizard.winfo_exists():
                    theme.bring_to_front(self._setup_wizard)
                    return
            except tk.TclError:
                pass

        def select(callback) -> None:
            self.select_region(lambda region: (self._region_selected(region), callback(region)))

        self._setup_wizard = HardwareSetupWizard(self, self.settings.region, select, self._apply_capability_result)

    def _apply_capability_result(self, result: CapabilityResult) -> None:
        s = self.settings
        s.setup_completed = True
        s.performance_profile = result.profile
        s.benchmark_ocr_ms = result.ocr_ms
        s.benchmark_capture_ms = result.capture_ms
        s.benchmark_provider = result.provider_detail
        s.scan_interval = result.recommended_interval
        s.prefer_gpu = result.provider == "GPU"
        s.save()
        self.settings_tab.refresh_from_settings()
        self.set_status(f"{result.profile} OCR profile applied • {result.recommended_interval:.2f}s scans",
                        theme.GREEN if not result.warning else theme.ACCENT)

    # -- settings -------------------------------------------------------------

    def save_settings(self, silent: bool = False) -> None:
        try:
            self.settings_tab.apply_to_settings()
        except ValueError as exc:
            if not silent:
                messagebox.showerror("Invalid setting", str(exc), parent=self)
            return
        self.settings.keep_running_totals = bool(self.running_totals_var.get())
        self.settings.save()
        self.apply_runtime_settings()
        if not silent:
            self.set_status("Settings saved", theme.GREEN)

    def apply_runtime_settings(self) -> None:
        s = self.settings
        self.tracker.timeout = s.encounter_timeout
        self.tracker.rolling_window = s.rolling_window
        self.tracker.player_name = s.player_name
        self.tracker.combine_pet_damage = s.combine_pet_damage
        self.tracker.damage_shields_by_wearer = s.damage_shields_by_wearer
        self.tracker.keep_running_totals = s.keep_running_totals
        self.overlays.sync_layout()
        self.attributes("-topmost", s.always_on_top)
        self.settings_tab.refresh_hardware_label()
        self.alerts.refresh()
        self.overlays.render()

    def save_and_restart(self) -> None:
        """Persist settings after a trigger/profile change and restart a running scan."""
        self.settings.save()
        if self.running:
            self.stop_monitoring()
            self.after(150, self.start_monitoring)

    def _running_totals_changed(self) -> None:
        enabled = bool(self.running_totals_var.get())
        self.settings.keep_running_totals = enabled
        self.tracker.keep_running_totals = enabled
        self.settings.save()
        self.set_status("Running totals enabled; Reset clears them" if enabled else "Per-encounter totals enabled",
                        theme.GREEN if enabled else theme.MUTED)

    # -- monitoring -----------------------------------------------------------

    def toggle_monitoring(self) -> None:
        self.stop_monitoring() if self.running else self.start_monitoring()

    def start_monitoring(self) -> None:
        has_dedicated = any(t.enabled and not t.use_combat_region and t.region for t in self.settings.effective_triggers())
        if not self.settings.region and not has_dedicated:
            self.select_region()
            return
        self.save_settings(silent=True)
        self.running = True
        self._refresh_start_button()
        self.set_status("Starting OCR…", theme.ACCENT)
        self.worker = ScannerWorker(self.settings, self.messages)
        self.worker.start()

    def stop_monitoring(self) -> None:
        worker, self.worker = self.worker, None
        if worker:
            worker.stop()
        self.running = False
        self._refresh_start_button()
        self.set_status("Monitoring stopped", theme.MUTED)

    def reset_encounter(self) -> None:
        self.tracker.reset()
        self.log_table.clear()
        self._log_iids.clear()
        self.actor_table.clear()
        self.sparkline.clear()
        self._target_values = [ALL_TARGETS]
        self.target_menu.configure(values=self._target_values)
        self.target_menu.set(ALL_TARGETS)
        self._refresh_metrics()

    def _poll(self) -> None:
        preview = None
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == "preview":
                    preview = value
                elif kind == "event":
                    self._add_event(value)
                elif kind == "trigger":
                    self._trigger_fired(value)
                elif kind == "pet":
                    if self.tracker.mark_pet(value):
                        self._refresh_metrics()
                    self.set_status(f"Learned pet: {value}", theme.GREEN)
                elif kind == "ocr":
                    self._show_ocr_summary(*value)
                elif kind == "status":
                    self.set_status(value, theme.GREEN)
                elif kind == "engine":
                    provider, detail = value
                    self.set_status(f"Monitoring • {provider} ({detail})", theme.GREEN if provider == "GPU" else theme.MUTED)
                elif kind == "error":
                    self.stop_monitoring()
                    messagebox.showerror("OCR monitor stopped", value, parent=self)
                elif kind == "stopped" and value is self.worker and self.running:
                    self.stop_monitoring()
        except queue.Empty:
            pass
        if preview is not None:
            self._show_preview(preview)
        self.after(100, self._poll)

    def _show_ocr_summary(self, lines: list[OCRLine], seconds: float, repaired: int) -> None:
        self.last_ocr = lines
        self.raw_label.configure(text="  |  ".join(line.text for line in lines[-2:]) or "No text recognized")
        average = sum(line.confidence for line in lines) / max(1, len(lines))
        note = f"  •  {repaired} repaired" if repaired else ""
        self.scan_label.configure(text=f"{len(lines)} lines  •  {average:.0%} mean confidence  •  {seconds:.2f}s scan{note}")

    def _show_preview(self, bgr) -> None:
        image = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        image.thumbnail(PREVIEW_SIZE, Image.Resampling.LANCZOS)
        photo = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
        self.preview.configure(image=photo, text="")  # configure before dropping the old reference
        self._preview_photo = photo

    def _clear_preview(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            self.preview.configure(image="", text="LIVE PREVIEW")
        self._preview_photo = None

    def _tick(self) -> None:
        self.tracker.update()
        self._refresh_metrics()
        now = time.monotonic()
        if self.running or self.tracker.active or self.sparkline.samples:
            self.sparkline.add(now, self.tracker.snapshot(now).rolling_dps)
        self._render_mini()
        self._refresh_arrange_button()
        for notification in self.timers.tick(now):
            self._timer_notification(notification)
        self.overlays.render(now)
        self.after(250, self._tick)

    # -- events & metrics -----------------------------------------------------

    def _add_event(self, event: CombatEvent) -> None:
        if not actor_event_allowed(event, self.settings.player_name, self.settings.actor_filter_enabled,
                                   self.settings.allowed_actor_names):
            return
        self.tracker.add(event)
        iid = self.log_table.insert((
            event.wall_time.strftime("%H:%M:%S"), event.kind.value.replace("damage_", "").upper(), event.actor,
            event.action, event.target, f"{event.amount:,}", "YES" if event.critical else "",
            f"{event.confidence:.0%}{'~' if event.repaired else ''}",
        ), tags=(EVENT_TAGS.get(event.kind, "other"),))
        self._log_iids.append(iid)
        if len(self._log_iids) > MAX_LOG_ROWS:
            self.log_table.tree.delete(self._log_iids.pop(0))
        self.log_table.reapply_sort()
        self.log_table.tree.see(iid)
        self._refresh_metrics()

    def _refresh_metrics(self) -> None:
        snap = self.tracker.snapshot()
        self.dps_card.set(f"{snap.dps:,.1f}")
        self.rolling_card.set(f"{snap.rolling_dps:,.1f}")
        self.damage_card.set(f"{snap.total_out:,}")
        self.incoming_card.set(f"{snap.total_in:,}")
        self.hps_card.set(f"{snap.hps:,.1f}")
        self.healing_card.set(f"{snap.total_heal:,}")
        minutes, seconds = divmod(int(snap.duration), 60)
        self.duration_card.set(f"{minutes}:{seconds:02d}")

        targets = [ALL_TARGETS, *self.tracker.encounter_targets()]
        if targets != self._target_values:
            selected = self.target_menu.get()
            self._target_values = targets
            self.target_menu.configure(values=targets)
            if selected not in targets:
                self.target_menu.set(ALL_TARGETS)
        selected = self.target_menu.get()
        rows = self.tracker.actor_totals(target=None if selected == ALL_TARGETS else selected)
        if self.view_toggle.get() == VIEW_TABLE:
            self.actor_table.set_rows([
                (row.actor, row.actor_type, f"{row.damage:,}", f"{row.share:.1f}%", f"{row.dps:,.1f}",
                 f"{row.rolling_dps:,.1f}", row.hits, row.crits, f"{row.healing:,}", f"{row.hps:,.1f}")
                for row in rows
            ])
        else:
            self.meter.set_rows(rows, "healing" if self.metric_toggle.get() == METRIC_HEALING else "damage")

    def export_csv(self) -> None:
        if not self.tracker.events:
            messagebox.showinfo("Nothing to export", "No combat events have been captured yet.", parent=self)
            return
        choice = messagebox.askyesnocancel("Choose CSV export", "Choose the data to export:\n\nYes — Combatants summary\n"
                                                                "No — Chronological combat log\nCancel — Do not export", parent=self)
        if choice is None:
            return
        export_type = "combatants" if choice else "log"
        filename = filedialog.asksaveasfilename(
            parent=self, title=f"Export {export_type} CSV", defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
            initialfile=time.strftime(f"discord_overlay_{export_type}_%Y%m%d_%H%M%S.csv"))
        if not filename:
            return
        try:
            self.tracker.export_csv(Path(filename), export_type)
        except OSError as exc:
            self.logger.exception("CSV export failed")
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        self.set_status(f"{export_type.title()} CSV exported", theme.GREEN)

    # -- triggers, sounds, speech ---------------------------------------------

    def play_sound(self, sound: str, volume: float, parent=None) -> None:
        if not sound:
            return
        try:
            if is_builtin_sound(sound):
                name = sound.removeprefix(BUILTIN_PREFIX)
                path = self.default_sound_paths.get(name)
                if path is None:
                    raise FileNotFoundError(f"Unknown bundled sound: {name}")
            else:
                path = Path(sound)
            self.sound_player.play(path, volume)
        except Exception as exc:  # noqa: BLE001 - report, never crash the UI
            if parent is not None:
                messagebox.showerror("Sound playback failed", str(exc), parent=parent)
            else:
                self.alerts.status(f"Audio error: {exc}", "error")

    def speak(self, text: str) -> None:
        s = self.settings
        self.speech_player.speak(text, s.speech_voice, s.speech_rate, s.speech_volume,
                                 interrupt=s.speech_queue_mode == "interrupt")

    def test_speech(self, text: str, voice: str, rate: int, volume: int, mode: str) -> None:
        self.speech_player.speak(text, voice, rate, volume, interrupt=mode == "interrupt")

    def _trigger_fired(self, match: TriggerMatch) -> None:
        trigger = self.settings.trigger_by_id(match.trigger_id)
        if match.action == "end":
            if trigger is None:
                return
            ended = self.timers.end(trigger, match)
            for notification in ended:
                self._timer_notification(notification)
            self.overlays.render()
            if ended:
                self.alerts.status(f"Ended {len(ended)} timer(s): {trigger.name}", "accent")
            return
        started = self.timers.start(trigger, match) if trigger else None
        if trigger and trigger.overlay_enabled and started is None:
            self.alerts.status(f"Retrigger ignored while timer is active: {trigger.name}", "muted")
            return
        self.play_sound(match.sound, match.volume)
        if trigger:
            if trigger.start_speech:
                self.speak(render_template(trigger.start_speech, trigger, match))
            self.overlays.render(new_alert=started is not None)
        fired_at = time.strftime("%H:%M:%S")
        self.alerts.mark_fired(match.trigger_id, fired_at)
        self.alerts.status(f"{fired_at}  {match.trigger_name}  -  {match.text}")

    def _timer_notification(self, notification: TimerNotification) -> None:
        timer = notification.timer
        if notification.kind == "ending":
            self.play_sound(timer.ending_sound, timer.volume)
            self.speak(timer.ending_speech)
        elif notification.kind == "expired":
            self.play_sound(timer.expiration_sound, timer.volume)
            self.speak(timer.expiration_speech)

    # -- shutdown -------------------------------------------------------------

    def close(self) -> None:
        if self.worker:
            self.worker.stop()
        for overlay in self.overlays.all():
            overlay.hide_overlay()
        self.sound_player.close()
        self.speech_player.close()
        try:
            self.settings.save()
        except OSError:
            self.logger.exception("Could not save settings on exit")
        self.destroy()
