"""The Alerts & Timers tab: trigger list, profile switcher, and overlay controls."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..audio import DEFAULT_SOUNDS
from ..paths import trigger_packs_dir
from ..trigger_packs import build_trigger_pack, parse_trigger_pack
from ..triggers import BUILTIN_PREFIX, Trigger, is_builtin_sound
from . import theme
from .dialogs import SpeechSettingsEditor, TriggerReplayWindow
from .trigger_editor import TriggerEditor
from .widgets import Column, SortableTree

STATUS_COLORS = {"ok": theme.GREEN, "accent": theme.ACCENT, "muted": theme.MUTED, "error": theme.RED}


class AlertsTab:
    def __init__(self, tab, app) -> None:
        self.app = app
        self.settings = app.settings
        self._editor: TriggerEditor | None = None
        self._speech_editor: SpeechSettingsEditor | None = None
        self.last_fired: dict[str, str] = {}

        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)
        header = ctk.CTkFrame(tab, fg_color="transparent")
        header.grid(row=0, column=0, padx=16, pady=(12, 2), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        theme.heading(header, "OCR ALERTS, OVERLAYS & TIMERS", 18).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(header, text="Active profile", text_color=theme.MUTED).grid(row=0, column=1, padx=(12, 6))
        self.profile_menu = ctk.CTkOptionMenu(header, values=self.settings.trigger_profiles(),
                                              command=self._profile_changed, width=145, **theme.MENU)
        self.profile_menu.set(self.settings.active_trigger_profile)
        self.profile_menu.grid(row=0, column=2)
        theme.note(tab, ("Combine Contains, Exact, and Regex conditions with ALL / ANY / NOT. Play sounds or "
                         "speech, display captured text, and run target-specific timers."), 800).grid(
            row=1, column=0, padx=16, pady=(0, 10), sticky="ew")

        table = ctk.CTkFrame(tab, fg_color="#0e1620")
        table.grid(row=2, column=0, padx=10, pady=4, sticky="nsew")
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(0, weight=1)
        self.tree = SortableTree(table, [
            Column("enabled", "ON", 40), Column("name", "NAME", 130), Column("folder", "FOLDER", 90),
            Column("logic", "LOGIC", 55), Column("conditions", "RULES", 50, numeric=True),
            Column("source", "SOURCE", 75), Column("sound", "SOUND", 75), Column("display", "DISPLAY", 95),
            Column("cooldown", "COOLDOWN", 68, numeric=True), Column("last", "LAST FIRED", 78),
        ], selectmode="browse")
        self.tree.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ctk.CTkScrollbar(table, command=self.tree.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.tree.configure(yscrollcommand=scroll.set)
        self.tree.tree.bind("<Double-1>", lambda _event: self.edit_selected())

        buttons = ctk.CTkFrame(tab, fg_color="transparent")
        buttons.grid(row=3, column=0, padx=10, pady=8, sticky="ew")
        for label, command in (("New", self.new_trigger), ("Edit", self.edit_selected), ("Duplicate", self.duplicate_selected),
                               ("Enable / Disable", self.toggle_selected), ("Delete", self.delete_selected),
                               ("Test sound", self.test_selected_sound), ("Test overlay", self.test_selected_overlay)):
            style = theme.ACCENT_BUTTON if label == "New" else theme.QUIET_BUTTON
            ctk.CTkButton(buttons, text=label, command=command, width=105, **style).pack(side="left", padx=4)
        overlay_buttons = ctk.CTkFrame(tab, fg_color="transparent")
        overlay_buttons.grid(row=4, column=0, padx=10, pady=(0, 6), sticky="ew")
        for label, command in (("Arrange overlay", app.overlays.arrange), ("Lock click-through", app.overlays.lock),
                               ("Hide overlay", app.overlays.hide), ("Speech settings", self.show_speech_settings),
                               ("Import pack", self.import_pack), ("Export pack", self.export_pack),
                               ("Replay tester", self.show_replay_tester)):
            ctk.CTkButton(overlay_buttons, text=label, command=command, width=110, **theme.STEEL_BUTTON).pack(side="left", padx=4)
        self.status_label = ctk.CTkLabel(tab, text="No trigger has fired this session.", text_color=theme.MUTED, anchor="w")
        self.status_label.grid(row=5, column=0, padx=16, pady=(0, 10), sticky="ew")
        self.refresh()

    # -- status & refresh -----------------------------------------------------

    def status(self, text: str, kind: str = "ok") -> None:
        self.status_label.configure(text=text, text_color=STATUS_COLORS.get(kind, kind))

    def refresh_profiles(self) -> None:
        self.profile_menu.configure(values=self.settings.trigger_profiles())
        self.profile_menu.set(self.settings.active_trigger_profile)

    def refresh(self, selected_id: str | None = None) -> None:
        selected_id = selected_id or self.tree.selection()
        rows, iids = [], []
        for trigger in sorted(self.settings.triggers_in_profile(), key=lambda t: (t.folder.casefold(), t.name.casefold())):
            sound = (trigger.sound.removeprefix(BUILTIN_PREFIX) if is_builtin_sound(trigger.sound)
                     else Path(trigger.sound).name if trigger.sound else "None")
            if not trigger.overlay_enabled:
                display = "OFF"
            else:
                kind = "Timer" if trigger.timer_seconds > 0 else "Alert"
                layout = "Ind" if self.settings.timer_layout == "independent" else f"Board: {trigger.timer_board}"
                display = f"{kind} / {layout}"
            rows.append(("YES" if trigger.enabled else "NO", trigger.name, trigger.folder, trigger.logic.upper(),
                         len(trigger.conditions), "Combat" if trigger.use_combat_region else "Dedicated", sound,
                         display, f"{trigger.cooldown_seconds:g}s", self.last_fired.get(trigger.id, "-")))
            iids.append(trigger.id)
        self.tree.set_rows(rows, iids)
        self.tree.select(selected_id)

    def mark_fired(self, trigger_id: str, when: str) -> None:
        self.last_fired[trigger_id] = when
        self.refresh(trigger_id)

    def forget(self, trigger_id: str) -> None:
        self.last_fired.pop(trigger_id, None)

    # -- trigger operations ---------------------------------------------------

    def _selected(self) -> Trigger | None:
        selected = self.tree.selection()
        return self.settings.trigger_by_id(selected) if selected else None

    def _profile_changed(self, profile: str) -> None:
        self.settings.active_trigger_profile = profile
        self.app.save_and_restart()
        self.refresh()
        self.status(f"Active trigger profile: {profile}")

    def new_trigger(self) -> None:
        self._open_editor(Trigger(profile=self.settings.active_trigger_profile, overlay_enabled=True))

    def edit_selected(self) -> None:
        trigger = self._selected()
        if trigger:
            self._open_editor(trigger)

    def _open_editor(self, trigger: Trigger) -> None:
        if self._editor and self._editor.winfo_exists():
            self._editor.destroy()
        self._editor = TriggerEditor(self.app, trigger, list(DEFAULT_SOUNDS), self.settings.board_names(),
                                     self.app.select_region, self.app.play_sound, self.preview_overlay, self._save_trigger)

    def _save_trigger(self, trigger: Trigger) -> None:
        self.settings.upsert_trigger(trigger)
        self.settings.ensure_board(trigger.timer_board)
        if trigger.profile.casefold() != self.settings.active_trigger_profile.casefold():
            self.settings.active_trigger_profile = trigger.profile
        self.app.save_and_restart()
        self.refresh_profiles()
        self.refresh(trigger.id)
        self.status(f"Saved: {trigger.name}")

    def duplicate_selected(self) -> None:
        trigger = self._selected()
        if not trigger:
            return
        duplicate = copy.deepcopy(trigger)
        duplicate.id = Trigger().id
        duplicate.name = f"{trigger.name} (copy)"
        duplicate.overlay_geometry = ""
        duplicate.overlay_positions = {}
        self.settings.triggers.append(duplicate)
        self.app.save_and_restart()
        self.refresh(duplicate.id)

    def toggle_selected(self) -> None:
        trigger = self._selected()
        if trigger:
            trigger.enabled = not trigger.enabled
            self.app.save_and_restart()
            self.refresh(trigger.id)

    def delete_selected(self) -> None:
        trigger = self._selected()
        if not trigger or not messagebox.askyesno("Delete trigger", f"Delete '{trigger.name}'?", parent=self.app):
            return
        self.settings.remove_trigger(trigger.id)
        self.forget(trigger.id)
        self.app.save_and_restart()
        self.refresh()

    def test_selected_sound(self) -> None:
        trigger = self._selected()
        if trigger:
            self.app.play_sound(trigger.sound, trigger.volume, self.app)

    def test_selected_overlay(self) -> None:
        trigger = self._selected()
        if not trigger:
            return
        preview = copy.deepcopy(trigger)
        preview.id = f"preview-{trigger.id}"
        preview.overlay_enabled = True
        preview.retrigger_mode = "replace"
        if preview.timer_seconds > 0:
            preview.timer_seconds = min(preview.timer_seconds, 10.0)
        self.preview_overlay(preview)
        if not trigger.overlay_enabled:
            self.status("Preview shown, but this trigger's overlay is OFF. Edit it and check Enable overlay before saving.",
                        "accent")

    def preview_overlay(self, trigger: Trigger) -> None:
        if self.app.overlays.preview_trigger(trigger):
            self.status("Overlay preview shown with an amber PREVIEW header near the selected combat region.")
        else:
            self.status("Overlay preview could not be started.", "error")

    # -- packs, speech, replay ------------------------------------------------

    def export_pack(self) -> None:
        profile = self.settings.active_trigger_profile
        triggers = self.settings.triggers_in_profile(profile)
        if not triggers:
            messagebox.showinfo("Nothing to export", f"The {profile!r} profile has no triggers.", parent=self.app)
            return
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", profile).strip("_") or "triggers"
        filename = filedialog.asksaveasfilename(parent=self.app, title="Export trigger pack", initialdir=trigger_packs_dir(),
                                                initialfile=f"{safe}_trigger_pack.json", defaultextension=".json",
                                                filetypes=[("Trigger packs", "*.json")])
        if not filename:
            return
        try:
            Path(filename).write_text(json.dumps(build_trigger_pack(profile, triggers), indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc), parent=self.app)
            return
        note = " Custom audio files are referenced, not embedded." if any(t.has_custom_sound() for t in triggers) else ""
        self.status(f"Exported {len(triggers)} triggers from {profile}.{note}")

    def import_pack(self) -> None:
        filename = filedialog.askopenfilename(parent=self.app, title="Import trigger pack", initialdir=trigger_packs_dir(),
                                              filetypes=[("Trigger packs", "*.json"), ("All files", "*.*")])
        if not filename:
            return
        try:
            payload = json.loads(Path(filename).read_text(encoding="utf-8"))
            imported, skipped = parse_trigger_pack(payload, {t.id for t in self.settings.triggers})
        except (OSError, ValueError) as exc:
            messagebox.showerror("Import failed", str(exc), parent=self.app)
            return
        if not imported:
            messagebox.showerror("Nothing imported", "\n".join(skipped[:8]) or "No valid triggers were found.", parent=self.app)
            return
        for trigger in imported:
            self.settings.ensure_board(trigger.timer_board)
        self.settings.triggers.extend(imported)
        self.settings.active_trigger_profile = imported[0].profile
        self.app.save_and_restart()
        self.refresh_profiles()
        self.refresh()
        summary = f"Imported {len(imported)} trigger(s) into {imported[0].profile}."
        if skipped:
            summary += f" Skipped {len(skipped)} invalid item(s)."
        self.status(summary, "accent" if skipped else "ok")

    def show_speech_settings(self) -> None:
        if self._speech_editor and self._speech_editor.winfo_exists():
            theme.bring_to_front(self._speech_editor)
            return
        self._speech_editor = SpeechSettingsEditor(self.app, self.settings, self._save_speech, self.app.test_speech)

    def _save_speech(self, voice: str, rate: int, volume: int, mode: str) -> None:
        self.settings.speech_voice = voice
        self.settings.speech_rate = rate
        self.settings.speech_volume = volume
        self.settings.speech_queue_mode = mode
        self.settings.save()
        self.status("Windows speech settings saved.")

    def show_replay_tester(self) -> None:
        TriggerReplayWindow(self.app, self.settings.triggers_in_profile(), [line.text for line in self.app.last_ocr])
