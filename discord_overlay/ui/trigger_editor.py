"""Editor window for one trigger: conditions, sound, overlay/timer, speech, organization."""
from __future__ import annotations

import copy
import re
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

import customtkinter as ctk

from ..audio import SOUND_EXTENSIONS
from ..models import Region
from ..triggers import BUILTIN_PREFIX, HEX_COLOR, Trigger, TriggerCondition, is_builtin_sound
from . import theme
from .dialogs import RegexHelpWindow

RETRIGGER_LABELS = {"restart": "Restart", "replace": "Replace", "ignore": "Ignore", "new": "Create another"}
RETRIGGER_MODES = {label: mode for mode, label in RETRIGGER_LABELS.items()}
RETRIGGER_HELP = {
    "Restart": "Reset only the matching timer to its full duration. Other timers created by this trigger continue.",
    "Replace": "Remove every active timer created by this trigger, then start one new timer.",
    "Ignore": "If the matching timer is already active, do nothing. Its countdown continues without resetting.",
    "Create another": ("Always start an additional timer, including mobs with the same name. "
                       "A matching end message removes the oldest copy."),
}
NONE = "None"
CUSTOM = "Custom file..."


class TriggerEditor(ctk.CTkToplevel):
    def __init__(self, parent, trigger: Trigger, sound_names: list[str], board_names: list[str],
                 select_region: Callable, play_sound: Callable, preview_overlay: Callable,
                 save_trigger: Callable[[Trigger], None]) -> None:
        super().__init__(parent, fg_color=theme.BG)
        self.trigger = copy.deepcopy(trigger)
        self.select_region = select_region
        self.play_sound = play_sound
        self.preview_overlay = preview_overlay
        self.save_trigger = save_trigger
        self.conditions = copy.deepcopy(trigger.conditions)
        self.custom_sound = "" if is_builtin_sound(trigger.sound) else trigger.sound
        self.title("Trigger: sound, overlay, timer, speech")
        self.geometry("860x780")
        self.minsize(700, 620)
        self.transient(parent)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        theme.heading(self, "TRIGGER").grid(row=0, column=0, padx=24, pady=(20, 8), sticky="ew")
        body = self.body = ctk.CTkScrollableFrame(self, fg_color=theme.PANEL, corner_radius=10)
        body.grid(row=1, column=0, padx=20, pady=8, sticky="nsew")
        body.grid_columnconfigure(1, weight=1)
        self._row = 0
        self._build_general(body, trigger, sound_names)
        self._build_conditions(body)
        self._build_sound(body, trigger, sound_names)
        self._build_overlay(body, trigger, board_names, sound_names)
        self._build_speech(body, trigger)
        self._build_organization(body, trigger)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, padx=20, pady=(8, 18), sticky="ew")
        ctk.CTkButton(footer, text="Cancel", command=self.destroy, width=110, **theme.QUIET_BUTTON).pack(side="right", padx=5)
        ctk.CTkButton(footer, text="Save trigger", command=self._save, width=130, **theme.ACCENT_BUTTON).pack(side="right", padx=5)
        self._refresh_conditions()
        self._source_changed(self.source_control.get())
        self.after(100, self.grab_set)

    # -- layout helpers -------------------------------------------------------

    def _next(self) -> int:
        self._row += 1
        return self._row

    def _label(self, parent, text: str, row: int) -> None:
        ctk.CTkLabel(parent, text=text, text_color=theme.TEXT, anchor="w", font=theme.font(bold=True)).grid(
            row=row, column=0, padx=12, pady=8, sticky="w")

    def _section(self, parent, text: str) -> None:
        ctk.CTkLabel(parent, text=text, text_color=theme.ACCENT, font=theme.font(bold=True), anchor="w").grid(
            row=self._next(), column=0, columnspan=4, padx=12, pady=(22, 6), sticky="ew")

    def _help(self, parent, row: int, text: str) -> ctk.CTkLabel:
        label = theme.note(parent, text, 400)
        label.grid(row=row, column=2, columnspan=2, padx=8, pady=7, sticky="w")
        return label

    def _entry(self, parent, row: int, value, width: int = 120, placeholder: str = "", span: int = 1) -> ctk.CTkEntry:
        entry = ctk.CTkEntry(parent, width=width, placeholder_text=placeholder)
        entry.insert(0, str(value))
        entry.grid(row=row, column=1, columnspan=span, padx=10, pady=7, sticky="w" if span == 1 else "ew")
        return entry

    # -- sections -------------------------------------------------------------

    def _build_general(self, body, trigger: Trigger, sound_names: list[str]) -> None:
        self._label(body, "Name", 0)
        self.name_entry = ctk.CTkEntry(body, placeholder_text="Example: Enrage warning")
        self.name_entry.insert(0, trigger.name)
        self.name_entry.grid(row=0, column=1, columnspan=3, padx=10, pady=8, sticky="ew")

        row = self._next()
        self.enabled_var = ctk.BooleanVar(value=trigger.enabled)
        self.case_var = ctk.BooleanVar(value=trigger.case_sensitive)
        ctk.CTkCheckBox(body, text="Enabled", variable=self.enabled_var, **theme.CHECKBOX).grid(
            row=row, column=1, padx=10, pady=8, sticky="w")
        ctk.CTkCheckBox(body, text="Case sensitive", variable=self.case_var, **theme.CHECKBOX).grid(
            row=row, column=2, padx=10, pady=8, sticky="w")

        row = self._next()
        self._label(body, "OCR source", row)
        self.source_control = ctk.CTkSegmentedButton(body, values=["Combat region", "Dedicated region"],
                                                     command=self._source_changed, **theme.SEGMENT)
        self.source_control.grid(row=row, column=1, columnspan=2, padx=10, pady=8, sticky="w")
        self.source_control.set("Combat region" if trigger.use_combat_region else "Dedicated region")
        self.region_button = ctk.CTkButton(body, text="Select region", width=110, command=self._choose_region,
                                           **theme.QUIET_BUTTON)
        self.region_button.grid(row=row, column=3, padx=10, pady=8, sticky="e")
        self.region_label = theme.note(body, self._region_text())
        self.region_label.grid(row=self._next(), column=1, columnspan=3, padx=10, pady=(0, 8), sticky="ew")

        row = self._next()
        self._label(body, "Boolean logic", row)
        self.logic_menu = ctk.CTkOptionMenu(body, values=["ALL (AND)", "ANY (OR)"], width=140, **theme.MENU)
        self.logic_menu.set("ALL (AND)" if trigger.logic == "all" else "ANY (OR)")
        self.logic_menu.grid(row=row, column=1, padx=10, pady=8, sticky="w")
        ctk.CTkLabel(body, text="Window (seconds)", text_color=theme.MUTED).grid(row=row, column=2, padx=(16, 4), pady=8, sticky="e")
        self.window_entry = ctk.CTkEntry(body, width=75)
        self.window_entry.insert(0, str(trigger.window_seconds))
        self.window_entry.grid(row=row, column=3, padx=10, pady=8, sticky="w")
        theme.note(body, "0 = every condition must match one OCR line. A larger window allows ALL conditions "
                         "across multiple lines.").grid(row=self._next(), column=1, columnspan=3, padx=10, pady=(0, 8), sticky="ew")

        row = self._next()
        self._label(body, "Cooldown", row)
        self.cooldown_entry = self._entry(body, row, trigger.cooldown_seconds, 90)
        theme.note(body, "seconds after firing before this trigger can fire again").grid(
            row=row, column=2, columnspan=2, padx=10, pady=8, sticky="w")

    def _build_conditions(self, body) -> None:
        ctk.CTkLabel(body, text="CONDITIONS", text_color=theme.TEXT, font=theme.font(bold=True), anchor="w").grid(
            row=self._next(), column=0, columnspan=4, padx=12, pady=(18, 4), sticky="ew")
        row = self._next()
        self.pattern_entry = ctk.CTkEntry(body, placeholder_text="Text or regular expression")
        self.pattern_entry.grid(row=row, column=0, columnspan=2, padx=(12, 6), pady=6, sticky="ew")
        self.mode_menu = ctk.CTkOptionMenu(body, values=["Contains", "Exact", "Regex"], width=105, **theme.MENU)
        self.mode_menu.grid(row=row, column=2, padx=6, pady=6)
        self.not_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(body, text="NOT", variable=self.not_var, width=60, **theme.CHECKBOX).grid(row=row, column=3, padx=8, pady=6)

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=self._next(), column=0, columnspan=4, padx=8, pady=(0, 6), sticky="ew")
        for text, command in (("Add", self._add_condition), ("Update selected", self._update_condition),
                              ("Remove selected", self._remove_condition), ("Regex help", self._show_regex_help)):
            ctk.CTkButton(actions, text=text, command=command, width=120, **theme.QUIET_BUTTON).pack(side="left", padx=4)

        frame = ctk.CTkFrame(body, fg_color="#0e1620", height=145)
        frame.grid(row=self._next(), column=0, columnspan=4, padx=12, pady=4, sticky="nsew")
        frame.grid_propagate(False)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        self.condition_tree = ttk.Treeview(frame, columns=("not", "type", "pattern"), show="headings", height=5)
        for column, label, width in (("not", "NOT", 55), ("type", "TYPE", 90), ("pattern", "PATTERN", 520)):
            self.condition_tree.heading(column, text=label)
            self.condition_tree.column(column, width=width, anchor="w")
        self.condition_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.condition_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.condition_tree.configure(yscrollcommand=scroll.set)
        self.condition_tree.bind("<<TreeviewSelect>>", self._condition_selected)

    def _build_sound(self, body, trigger: Trigger, sound_names: list[str]) -> None:
        row = self._next()
        self._label(body, "Sound", row)
        options = [NONE] + sound_names + [CUSTOM]
        self.sound_menu = ctk.CTkOptionMenu(body, values=options, command=self._sound_changed, **theme.MENU)
        selected = (NONE if not trigger.sound else trigger.sound.removeprefix(BUILTIN_PREFIX)
                    if is_builtin_sound(trigger.sound) else CUSTOM)
        self.sound_menu.set(selected if selected in options else sound_names[0])
        self.sound_menu.grid(row=row, column=1, padx=10, pady=(18, 8), sticky="w")
        ctk.CTkButton(body, text="Browse", width=90, command=self._browse_sound, **theme.QUIET_BUTTON).grid(
            row=row, column=2, padx=6, pady=(18, 8), sticky="w")
        ctk.CTkButton(body, text="Test", width=80, command=self._test_sound, **theme.ACCENT_BUTTON).grid(
            row=row, column=3, padx=10, pady=(18, 8), sticky="e")
        self.sound_path_label = theme.note(body, self.custom_sound or ("No sound" if not trigger.sound else "Bundled sound"), 630)
        self.sound_path_label.grid(row=self._next(), column=1, columnspan=3, padx=10, pady=(0, 8), sticky="ew")

        row = self._next()
        self._label(body, "Volume", row)
        self.volume_var = ctk.DoubleVar(value=round(trigger.volume * 100))
        ctk.CTkSlider(body, from_=0, to=100, number_of_steps=100, variable=self.volume_var,
                      command=self._volume_changed, button_color="#b77a2d").grid(
            row=row, column=1, columnspan=2, padx=10, pady=8, sticky="ew")
        self.volume_label = ctk.CTkLabel(body, text=f"{self.volume_var.get():.0f}%", text_color=theme.TEXT)
        self.volume_label.grid(row=row, column=3, padx=10, pady=8)

    def _build_overlay(self, body, trigger: Trigger, board_names: list[str], sound_names: list[str]) -> None:
        self._section(body, "OVERLAY & TIMER")
        row = self._next()
        self.overlay_var = ctk.BooleanVar(value=trigger.overlay_enabled)
        ctk.CTkCheckBox(body, text="Enable overlay for this trigger (required to display text or a timer)",
                        variable=self.overlay_var, **theme.CHECKBOX).grid(row=row, column=1, columnspan=2, padx=10, pady=7, sticky="w")
        ctk.CTkButton(body, text="Preview overlay", command=self._test_overlay, width=125, **theme.STEEL_BUTTON).grid(
            row=row, column=3, padx=10, pady=7, sticky="e")

        row = self._next()
        self._label(body, "Overlay text", row)
        self.overlay_text_entry = self._entry(body, row, trigger.overlay_text, placeholder="Example: {spell} on {target}", span=3)

        row = self._next()
        self._label(body, "Duration", row)
        self.timer_entry = self._entry(body, row, trigger.timer_seconds)
        self._help(body, row, "Seconds shown. Use 0 for a five-second text alert without a countdown bar.")

        row = self._next()
        self._label(body, "Retrigger behavior", row)
        self.retrigger_menu = ctk.CTkOptionMenu(body, values=list(RETRIGGER_LABELS.values()), width=150,
                                                command=self._retrigger_changed, **theme.MENU)
        label = RETRIGGER_LABELS.get(trigger.retrigger_mode, "Restart")
        self.retrigger_menu.set(label)
        self.retrigger_menu.grid(row=row, column=1, padx=10, pady=7, sticky="w")
        self.retrigger_help = self._help(body, row, RETRIGGER_HELP[label])

        row = self._next()
        self._label(body, "Timer key", row)
        self.timer_key_entry = self._entry(body, row, trigger.timer_key_template, 180, "Example: {target}")
        self._help(body, row, "Optional. Use {target} to keep a separate timer for each captured target.")

        row = self._next()
        self._label(body, "Timer board", row)
        board_names = board_names or ["Default"]
        self.board_menu = ctk.CTkOptionMenu(body, values=board_names, width=180, **theme.MENU)
        self.board_menu.set(trigger.timer_board if trigger.timer_board in board_names else board_names[0])
        self.board_menu.grid(row=row, column=1, padx=10, pady=7, sticky="w")
        self._help(body, row, "Which named grid receives this timer. Create boards under Settings.")

        row = self._next()
        self._label(body, "Independent opacity", row)
        self.opacity_entry = self._entry(body, row, f"{trigger.overlay_opacity * 100:.0f}")
        self._help(body, row, "Used in Independent mode (percent). Named boards have their own opacity in Settings.")

        row = self._next()
        self._label(body, "Bar color", row)
        self.bar_color_entry, self.bar_swatch = self._color_picker(body, row, trigger.bar_color)
        self._help(body, row, "Countdown progress color. Click the colored square to choose visually.")

        row = self._next()
        self._label(body, "Text color", row)
        self.text_color_entry, self.text_swatch = self._color_picker(body, row, trigger.overlay_text_color)
        self._help(body, row, "Alert and remaining-time color.")

        row = self._next()
        self._label(body, "Ending-soon time", row)
        self.ending_seconds_entry = self._entry(body, row, trigger.ending_soon_seconds)
        self._help(body, row, "Seconds remaining when the ending-soon sound or speech should fire.")

        optional = [NONE] + sound_names
        row = self._next()
        self._label(body, "Ending-soon sound", row)
        self.ending_sound_menu = ctk.CTkOptionMenu(body, values=optional, width=150, **theme.MENU)
        self.ending_sound_menu.set(trigger.ending_sound.removeprefix(BUILTIN_PREFIX) or NONE)
        self.ending_sound_menu.grid(row=row, column=1, padx=10, pady=7, sticky="w")
        self._help(body, row, "Optional sound played once at the ending-soon threshold.")

        row = self._next()
        self._label(body, "Expiration sound", row)
        self.expiration_sound_menu = ctk.CTkOptionMenu(body, values=optional, width=150, **theme.MENU)
        self.expiration_sound_menu.set(trigger.expiration_sound.removeprefix(BUILTIN_PREFIX) or NONE)
        self.expiration_sound_menu.grid(row=row, column=1, padx=10, pady=7, sticky="w")
        self._help(body, row, "Optional sound played when the countdown reaches zero.")

        row = self._next()
        self._label(body, "End-early text", row)
        self.end_pattern_entry = self._entry(body, row, trigger.end_pattern, 180, "Effect has worn off")
        self._help(body, row, "Optional OCR text that immediately removes the matching active timer.")

        row = self._next()
        self._label(body, "End match type", row)
        self.end_mode_menu = ctk.CTkOptionMenu(body, values=["Contains", "Exact", "Regex"], width=150, **theme.MENU)
        self.end_mode_menu.set(trigger.end_mode.title())
        self.end_mode_menu.grid(row=row, column=1, padx=10, pady=7, sticky="w")
        self._help(body, row, "How the end-early text is compared with recognized OCR lines.")

    def _color_picker(self, body, row: int, color: str) -> tuple[ctk.CTkEntry, ctk.CTkButton]:
        frame = ctk.CTkFrame(body, fg_color="transparent")
        frame.grid(row=row, column=1, padx=10, pady=7, sticky="w")
        entry = ctk.CTkEntry(frame, width=108)
        entry.insert(0, color)
        entry.pack(side="left")
        swatch = ctk.CTkButton(frame, text="", width=34, height=28, fg_color=color, hover_color=color)
        swatch.configure(command=lambda: self._choose_color(entry, swatch))
        swatch.pack(side="left", padx=(7, 0))
        entry.bind("<KeyRelease>", lambda _event: self._sync_swatch(entry, swatch))
        return entry, swatch

    def _build_speech(self, body, trigger: Trigger) -> None:
        self._section(body, "SPEECH TEMPLATES")
        theme.note(body, ("Optional Windows text-to-speech. Leave a field blank to disable it. On trigger speaks "
                          "immediately; Ending soon uses the threshold above; On expiration speaks at zero. "
                          "Variables such as {trigger}, {target}, and {spell} are replaced with matched values."),
                   680).grid(row=self._next(), column=1, columnspan=3, padx=10, pady=(0, 8), sticky="ew")
        self.start_speech_entry = self._speech_row(body, "On trigger", trigger.start_speech)
        self.ending_speech_entry = self._speech_row(body, "Ending soon", trigger.ending_speech)
        self.expiration_speech_entry = self._speech_row(body, "On expiration", trigger.expiration_speech)
        theme.note(body, ("GINA-style regex groups such as (?<target>.+?) become {target}. An early-ending regex "
                          "with the same capture ends only that target's timer."), 680).grid(
            row=self._next(), column=1, columnspan=3, padx=10, pady=(2, 18), sticky="ew")

    def _speech_row(self, body, label: str, value: str) -> ctk.CTkEntry:
        row = self._next()
        self._label(body, label, row)
        return self._entry(body, row, value, placeholder="Optional spoken message", span=3)

    def _build_organization(self, body, trigger: Trigger) -> None:
        self._section(body, "ORGANIZATION")
        row = self._next()
        self._label(body, "Folder", row)
        self.folder_entry = ctk.CTkEntry(body, placeholder_text="General")
        self.folder_entry.insert(0, trigger.folder)
        self.folder_entry.grid(row=row, column=1, padx=10, pady=(6, 18), sticky="ew")
        ctk.CTkLabel(body, text="Profile", text_color=theme.TEXT, anchor="e", font=theme.font(bold=True)).grid(
            row=row, column=2, padx=10, pady=(6, 18), sticky="e")
        self.profile_entry = ctk.CTkEntry(body, placeholder_text="Default")
        self.profile_entry.insert(0, trigger.profile)
        self.profile_entry.grid(row=row, column=3, padx=10, pady=(6, 18), sticky="ew")

    # -- behavior -------------------------------------------------------------

    def _source_changed(self, value: str) -> None:
        self.region_button.configure(state="normal" if value == "Dedicated region" else "disabled")
        self.region_label.configure(text=self._region_text())

    def _region_text(self) -> str:
        if self.source_control.get() == "Combat region":
            return "Uses the parser's main combat capture without another OCR pass."
        region = self.trigger.region
        return f"Dedicated capture: {region.describe()}" if region else "No dedicated region selected."

    def _choose_region(self) -> None:
        theme.release_grab(self)
        self.select_region(self._region_received)

    def _region_received(self, region: Region) -> None:
        self.trigger.region = region
        self.region_label.configure(text=self._region_text())
        theme.bring_to_front(self, grab=True)

    def _condition_from_inputs(self) -> TriggerCondition | None:
        pattern = self.pattern_entry.get().strip()
        if not pattern:
            messagebox.showerror("Condition required", "Enter text or a regular expression.", parent=self)
            return None
        return TriggerCondition(pattern, self.mode_menu.get().casefold(), bool(self.not_var.get()))

    def _show_regex_help(self) -> None:
        theme.release_grab(self)
        RegexHelpWindow(self)

    def _add_condition(self) -> None:
        condition = self._condition_from_inputs()
        if condition:
            self.conditions.append(condition)
            self._refresh_conditions()
            self.pattern_entry.delete(0, "end")

    def _selected_index(self) -> int | None:
        selection = self.condition_tree.selection()
        try:
            return int(selection[0]) if selection else None
        except ValueError:
            return None

    def _update_condition(self) -> None:
        index = self._selected_index()
        if index is None:
            messagebox.showinfo("Select a condition", "Select the condition to update.", parent=self)
            return
        condition = self._condition_from_inputs()
        if condition:
            self.conditions[index] = condition
            self._refresh_conditions(index)

    def _remove_condition(self) -> None:
        index = self._selected_index()
        if index is not None:
            self.conditions.pop(index)
            self._refresh_conditions()

    def _condition_selected(self, _event=None) -> None:
        index = self._selected_index()
        if index is None or index >= len(self.conditions):
            return
        condition = self.conditions[index]
        self.pattern_entry.delete(0, "end")
        self.pattern_entry.insert(0, condition.pattern)
        self.mode_menu.set(condition.mode.title())
        self.not_var.set(condition.negate)

    def _refresh_conditions(self, selected: int | None = None) -> None:
        self.condition_tree.delete(*self.condition_tree.get_children())
        for index, condition in enumerate(self.conditions):
            self.condition_tree.insert("", "end", iid=str(index),
                                       values=("YES" if condition.negate else "", condition.mode.upper(), condition.pattern))
        if selected is not None and selected < len(self.conditions):
            self.condition_tree.selection_set(str(selected))

    def _sound_changed(self, value: str) -> None:
        if value == CUSTOM and not self.custom_sound:
            self._browse_sound()
        self.sound_path_label.configure(text=(self.custom_sound or "No custom file selected") if value == CUSTOM
                                        else ("No sound" if value == NONE else "Bundled sound"))

    def _browse_sound(self) -> None:
        filename = filedialog.askopenfilename(parent=self, title="Choose trigger sound",
                                              filetypes=[("Audio files", "*.wav *.ogg *.mp3"), ("All files", "*.*")])
        if filename:
            self.custom_sound = filename
            self.sound_menu.set(CUSTOM)
            self.sound_path_label.configure(text=filename)

    def _selected_sound(self) -> str:
        selected = self.sound_menu.get()
        if selected == NONE:
            return ""
        return self.custom_sound if selected == CUSTOM else f"{BUILTIN_PREFIX}{selected}"

    def _test_sound(self) -> None:
        self.play_sound(self._selected_sound(), self.volume_var.get() / 100.0, self)

    def _volume_changed(self, value: float) -> None:
        self.volume_label.configure(text=f"{value:.0f}%")

    def _retrigger_changed(self, value: str) -> None:
        self.retrigger_help.configure(text=RETRIGGER_HELP.get(value, ""))

    def _choose_color(self, entry, swatch) -> None:
        initial = entry.get().strip()
        _rgb, selected = colorchooser.askcolor(color=initial if HEX_COLOR.fullmatch(initial) else None,
                                               parent=self, title="Choose timer color")
        if selected:
            entry.delete(0, "end")
            entry.insert(0, selected.lower())
            self._sync_swatch(entry, swatch)

    @staticmethod
    def _sync_swatch(entry, swatch) -> None:
        value = entry.get().strip()
        if HEX_COLOR.fullmatch(value):
            swatch.configure(fg_color=value, hover_color=value)

    @staticmethod
    def _optional_sound(value: str) -> str:
        return "" if value == NONE else f"{BUILTIN_PREFIX}{value}"

    def _apply_overlay_inputs(self, trigger: Trigger, force_enabled: bool | None = None) -> None:
        trigger.overlay_enabled = bool(self.overlay_var.get()) if force_enabled is None else force_enabled
        trigger.overlay_text = self.overlay_text_entry.get().strip() or "{trigger}"
        trigger.timer_seconds = float(self.timer_entry.get())
        trigger.timer_key_template = self.timer_key_entry.get().strip()
        trigger.retrigger_mode = RETRIGGER_MODES[self.retrigger_menu.get()]
        trigger.bar_color = self.bar_color_entry.get().strip()
        trigger.overlay_text_color = self.text_color_entry.get().strip()
        trigger.timer_board = self.board_menu.get().strip() or "Default"
        trigger.overlay_opacity = float(self.opacity_entry.get()) / 100.0
        trigger.ending_soon_seconds = float(self.ending_seconds_entry.get())
        trigger.ending_sound = self._optional_sound(self.ending_sound_menu.get())
        trigger.expiration_sound = self._optional_sound(self.expiration_sound_menu.get())
        trigger.end_pattern = self.end_pattern_entry.get().strip()
        trigger.end_mode = self.end_mode_menu.get().casefold()
        trigger.start_speech = self.start_speech_entry.get().strip()
        trigger.ending_speech = self.ending_speech_entry.get().strip()
        trigger.expiration_speech = self.expiration_speech_entry.get().strip()

    def _test_overlay(self) -> None:
        preview = copy.deepcopy(self.trigger)
        try:
            self._apply_overlay_inputs(preview, force_enabled=True)
        except ValueError:
            messagebox.showerror("Invalid overlay value", "Timer, ending-soon, and opacity values must be numbers.", parent=self)
            return
        for label, color in (("Bar", preview.bar_color), ("Text", preview.overlay_text_color)):
            if not HEX_COLOR.fullmatch(color):
                messagebox.showerror("Invalid color", f"{label} color must use #RRGGBB format.", parent=self)
                return
        if not 0.2 <= preview.overlay_opacity <= 1.0:
            messagebox.showerror("Invalid opacity", "Overlay opacity must be between 20 and 100 percent.", parent=self)
            return
        preview.id = f"preview-{self.trigger.id}"
        preview.name = self.name_entry.get().strip() or "Overlay preview"
        preview.retrigger_mode = "replace"
        if preview.timer_seconds > 0:
            preview.timer_seconds = min(preview.timer_seconds, 10.0)
        self.preview_overlay(preview)

    def _save(self) -> None:
        trigger = self.trigger
        try:
            trigger.name = self.name_entry.get().strip()
            trigger.folder = self.folder_entry.get().strip()
            trigger.profile = self.profile_entry.get().strip()
            trigger.enabled = bool(self.enabled_var.get())
            trigger.case_sensitive = bool(self.case_var.get())
            trigger.logic = "all" if self.logic_menu.get().startswith("ALL") else "any"
            trigger.window_seconds = float(self.window_entry.get())
            trigger.cooldown_seconds = float(self.cooldown_entry.get())
            trigger.use_combat_region = self.source_control.get() == "Combat region"
            trigger.conditions = copy.deepcopy(self.conditions)
            trigger.sound = self._selected_sound()
            trigger.volume = self.volume_var.get() / 100.0
            self._apply_overlay_inputs(trigger)
        except ValueError:
            messagebox.showerror("Invalid number", "Window, cooldown, timer, opacity, and ending-soon values must be numbers.",
                                 parent=self)
            return
        errors = trigger.validate()
        if trigger.has_custom_sound():
            path = Path(trigger.sound)
            if path.suffix.casefold() not in SOUND_EXTENSIONS:
                errors.append("Custom sound must be WAV, OGG, or MP3.")
            if not path.is_file():
                errors.append("Custom sound file was not found.")
        if errors:
            messagebox.showerror("Invalid trigger", "\n".join(errors), parent=self)
            return
        self.save_trigger(trigger)
        self.destroy()
