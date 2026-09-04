"""Secondary windows: About, group filter, speech settings, regex help, replay tester."""
from __future__ import annotations

import copy
import os
import re
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .. import APP_NAME, __version__
from ..config import Settings
from ..paths import diagnostics_dir, ensure_app_directories
from ..speech import installed_voices
from ..triggers import Trigger, TriggerDiagnostic, TriggerEngine, TriggerMatch
from . import theme


def open_diagnostics_folder() -> None:
    ensure_app_directories()
    os.startfile(diagnostics_dir())  # type: ignore[attr-defined]  # Windows only


class AboutWindow(ctk.CTkToplevel):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        theme.apply_window_icon(self)
        self.title(f"About {APP_NAME}")
        self.geometry("560x400")
        self.resizable(False, False)
        self.transient(parent)
        self.attributes("-topmost", True)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=APP_NAME.upper(), text_color=theme.ACCENT, font=theme.font(28, bold=True)).grid(
            row=0, column=0, padx=28, pady=(26, 0))
        ctk.CTkLabel(self, text=f"Version {__version__}", text_color=theme.TEXT, font=theme.font(15)).grid(
            row=1, column=0, padx=28, pady=(2, 18))
        details = ctk.CTkFrame(self, fg_color=theme.PANEL_2, corner_radius=10)
        details.grid(row=2, column=0, padx=28, pady=4, sticky="ew")
        details.grid_columnconfigure(1, weight=1)
        for row, (label, value) in enumerate((
            ("Platform", "Windows 10/11 x64"),
            ("Data access", "Screen capture + OCR only"),
            ("Game client", "Never read, hooked, or injected"),
            ("Settings", "%LOCALAPPDATA%\\DiscordOverlay"),
        )):
            ctk.CTkLabel(details, text=label, text_color=theme.MUTED, anchor="w").grid(
                row=row, column=0, padx=(16, 18), pady=9, sticky="w")
            ctk.CTkLabel(details, text=value, text_color=theme.TEXT, anchor="w").grid(
                row=row, column=1, padx=(0, 16), pady=9, sticky="ew")
        ctk.CTkButton(self, text="Open diagnostics folder", command=open_diagnostics_folder, width=190,
                      **theme.STEEL_BUTTON).grid(row=3, column=0, padx=24, pady=(20, 6))
        ctk.CTkLabel(self, text="Free to use. No license, no telemetry, no update checks.",
                     text_color=theme.MUTED).grid(row=4, column=0, padx=28, pady=(12, 20))


class GroupFilterEditor(ctk.CTkToplevel):
    def __init__(self, parent, enabled: bool, names: list[str], save: Callable[[bool, list[str]], None]) -> None:
        super().__init__(parent, fg_color=theme.BG)
        self.save = save
        self.title("Group Filter")
        self.geometry("650x520")
        self.minsize(560, 460)
        self.transient(parent)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        theme.heading(self, "GROUP FILTER", 21).grid(row=0, column=0, padx=26, pady=(24, 8), sticky="ew")
        theme.note(self, ("Keep only combat involving your group. A line is counted when either side of it is "
                          "you, your pet, or a name listed below, so mobs never need to be listed. Your own "
                          "damage and attacks against you or your pet are always retained. Triggers still "
                          "read every OCR line."), 590, theme.TEXT).grid(row=1, column=0, padx=26, pady=(0, 14), sticky="ew")
        self.enabled_var = ctk.BooleanVar(value=enabled)
        ctk.CTkCheckBox(self, text="Only include combat involving my group", variable=self.enabled_var,
                        font=theme.font(bold=True), **theme.CHECKBOX).grid(row=2, column=0, padx=26, pady=(0, 14), sticky="w")
        frame = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        frame.grid(row=3, column=0, padx=24, pady=4, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(frame, text="Group member and pet names", text_color=theme.TEXT, font=theme.font(bold=True),
                     anchor="w").grid(row=0, column=0, padx=16, pady=(14, 2), sticky="ew")
        theme.note(frame, ("Enter one exact player or pet name per line. Matching ignores capitalization and "
                           "punctuation. Add Damage Shield only if you want unattributed shield lines."), 555).grid(
            row=1, column=0, padx=16, pady=(0, 8), sticky="ew")
        self.names_box = ctk.CTkTextbox(frame, font=theme.font(13), **theme.TEXTBOX)
        self.names_box.grid(row=2, column=0, padx=14, pady=(0, 14), sticky="nsew")
        self.names_box.insert("1.0", "\n".join(names))
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=4, column=0, padx=24, pady=(12, 22), sticky="ew")
        ctk.CTkButton(footer, text="Cancel", command=self.destroy, width=100, **theme.QUIET_BUTTON).pack(side="right", padx=5)
        ctk.CTkButton(footer, text="Save group filter", command=self._save, width=150, **theme.ACCENT_BUTTON).pack(
            side="right", padx=5)
        self.after(100, self.grab_set)

    def _save(self) -> None:
        names: list[str] = []
        seen: set[str] = set()
        for raw in re.split(r"[,\n]", self.names_box.get("1.0", "end")):
            name = re.sub(r"\s+", " ", raw).strip()
            if name and name.casefold() not in seen:
                seen.add(name.casefold())
                names.append(name)
        self.save(bool(self.enabled_var.get()), names)
        self.destroy()


class SpeechSettingsEditor(ctk.CTkToplevel):
    def __init__(self, parent, settings: Settings, save: Callable[[str, int, int, str], None],
                 test: Callable[[str, str, int, int, str], None]) -> None:
        super().__init__(parent, fg_color=theme.BG)
        self.save = save
        self.test = test
        self.title("Windows Speech Settings")
        self.geometry("620x500")
        self.minsize(540, 450)
        self.transient(parent)
        self.grid_columnconfigure(1, weight=1)
        theme.heading(self, "WINDOWS TEXT-TO-SPEECH").grid(row=0, column=0, columnspan=3, padx=24, pady=(24, 14), sticky="ew")

        voices = installed_voices()
        self._label("Voice", 1)
        self.voice_menu = ctk.CTkOptionMenu(self, values=["System default"] + voices, **theme.MENU)
        self.voice_menu.set(settings.speech_voice if settings.speech_voice in voices else "System default")
        self.voice_menu.grid(row=1, column=1, columnspan=2, padx=(8, 24), pady=9, sticky="ew")

        self._label("Queue behavior", 2)
        self.queue_menu = ctk.CTkSegmentedButton(self, values=["Queue", "Interrupt"], **theme.SEGMENT)
        self.queue_menu.set("Interrupt" if settings.speech_queue_mode == "interrupt" else "Queue")
        self.queue_menu.grid(row=2, column=1, columnspan=2, padx=(8, 24), pady=9, sticky="w")

        self.rate_var = ctk.DoubleVar(value=settings.speech_rate)
        self._slider("Rate", 3, self.rate_var, -10, 10, 20)
        self.volume_var = ctk.DoubleVar(value=settings.speech_volume)
        self._slider("Volume", 4, self.volume_var, 0, 100, 100)

        self._label("Test message", 5)
        self.test_entry = ctk.CTkEntry(self)
        self.test_entry.insert(0, "Timer ending soon")
        self.test_entry.grid(row=5, column=1, padx=8, pady=9, sticky="ew")
        ctk.CTkButton(self, text="Speak", width=80, command=self._test, **theme.QUIET_BUTTON).grid(
            row=5, column=2, padx=(4, 24), pady=9)
        theme.note(self, ("Queue finishes each message in order. Interrupt immediately stops the current message "
                          "when a newer alert arrives. Speech uses Windows' installed voices."), 560).grid(
            row=6, column=0, columnspan=3, padx=24, pady=(8, 18), sticky="ew")
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=7, column=0, columnspan=3, padx=24, pady=(4, 20), sticky="ew")
        ctk.CTkButton(footer, text="Cancel", command=self.destroy, width=100, **theme.QUIET_BUTTON).pack(side="right", padx=5)
        ctk.CTkButton(footer, text="Save speech settings", command=self._save, width=165, **theme.ACCENT_BUTTON).pack(
            side="right", padx=5)
        self.after(100, self.grab_set)

    def _label(self, text: str, row: int) -> None:
        ctk.CTkLabel(self, text=text, text_color=theme.TEXT, anchor="w").grid(row=row, column=0, padx=(24, 8), pady=9, sticky="w")

    def _slider(self, text: str, row: int, variable, low: int, high: int, steps: int) -> None:
        self._label(text, row)
        ctk.CTkSlider(self, from_=low, to=high, number_of_steps=steps, variable=variable, button_color="#b77a2d").grid(
            row=row, column=1, padx=8, pady=9, sticky="ew")
        value = ctk.CTkLabel(self, text="", text_color=theme.MUTED, width=45)
        value.grid(row=row, column=2, padx=(4, 24), pady=9)

        def refresh(*_args) -> None:
            value.configure(text=f"{int(round(variable.get()))}")

        variable.trace_add("write", refresh)
        refresh()

    def _values(self) -> tuple[str, int, int, str]:
        voice = "" if self.voice_menu.get() == "System default" else self.voice_menu.get()
        return voice, int(round(self.rate_var.get())), int(round(self.volume_var.get())), self.queue_menu.get().casefold()

    def _test(self) -> None:
        self.test(self.test_entry.get(), *self._values())

    def _save(self) -> None:
        self.save(*self._values())
        self.destroy()


REGEX_HELP = r"""REGEX QUICK START

Regex is useful when part of a combat message changes, such as a spell, player,
target, or amount. Choose Regex as the condition type. Matching is
case-insensitive unless the trigger's Case sensitive option is enabled.

COMMON PIECES

  \d+                 one or more digits
  [\d,]+              a number that may contain commas
  \w+                 letters, digits, or underscore
  [A-Za-z'-]+         a typical one-word character name
  .+?                 some text, stopping as soon as the rest can match
  \s+                 one or more spaces
  [.!]?               optional final period or exclamation mark
  ^                    start of the OCR line
  $                    end of the OCR line
  (?:one|two)          either value without creating a capture
  \(                   a literal opening parenthesis

CAPTURES (GINA-COMPATIBLE)

  (?<target>pattern)  GINA/.NET named capture (recommended)
  {S} or {S1}         capture changing text
  {N} or {N1}         capture a number
  (pattern)           numbered capture, available as {$1}, {$2}, etc.
  (?P<target>pattern) Python spelling; also supported

Captured values can be used in overlay text, timer keys, and speech. Token
names are case-insensitive, so {S1} in a pattern can be displayed with {s1}.

  Regex:            ^(?<spell>.+?) lands on (?<target>[A-Za-z][A-Za-z'-]*)[.!]?$
  Overlay/speech:   {spell} on {target}
  Timer key:        {target}

Using {target} as the timer key keeps a separate countdown for every captured
target. Capture names may contain letters, digits, and underscores only.

USEFUL EXAMPLES

  Damage amount:            hits YOU for (?<amount>[\d,]+) points
  Several warnings:         begins to (?:cast|channel) (?<spell>.+?)[.!]?$
  Flexible OCR spacing:     (?<player>[A-Za-z'-]+)\s+has\s+been\s+cursed
  Targeted start:           ^(?<spell>.+?) affects (?<target>[A-Za-z'-]+)[.!]?$
  Targeted early ending:    ^(?<spell>.+?) has worn off (?<target>[A-Za-z'-]+)[.!]?$

Set both rules' timer key to {target}. When the ending rule captures the same
target, only that target's timer ends. If an ending rule cannot produce the full
timer key, every active timer belonging to that trigger ends.

BOOLEAN AND MULTI-LINE RULES

Each condition normally tests one OCR line. Set a Match Window above zero to let
different ALL conditions become active across several lines. Regex captures from
those lines are combined when the trigger fires. NOT conditions block the rule
while they remain active in that window.

OCR-FRIENDLY ADVICE

  • Anchor predictable messages with ^ and $ to reduce false matches.
  • Use \s+ instead of a literal space when OCR spacing can vary.
  • Make only the changing portion flexible; prefer .+? over .* when text follows.
  • Avoid expensive nested repetition such as (.+)+.
  • Enter only the pattern: no quote marks, no r prefix.
  • Use the Replay tester to see Match Now, Active in Window, Miss, captures,
    cooldowns, NOT blockers, and the final reason without firing an alert.
"""


class RegexHelpWindow(ctk.CTkToplevel):
    def __init__(self, parent) -> None:
        super().__init__(parent, fg_color=theme.BG)
        self.parent_window = parent
        self.title("Regex Help")
        self.geometry("780x720")
        self.minsize(640, 560)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        theme.heading(self, "REGEX & CAPTURE HELP", 21).grid(row=0, column=0, padx=22, pady=(20, 8), sticky="ew")
        box = ctk.CTkTextbox(self, font=theme.font(12, family="Consolas"), wrap="word", **theme.TEXTBOX)
        box.grid(row=1, column=0, padx=20, pady=6, sticky="nsew")
        box.insert("1.0", REGEX_HELP)
        theme.note(self, "The examples are selectable and can be copied into a trigger condition.").grid(
            row=2, column=0, padx=22, pady=(4, 8), sticky="ew")
        ctk.CTkButton(self, text="Close", command=self._close, width=100, **theme.QUIET_BUTTON).grid(
            row=3, column=0, padx=20, pady=(0, 18), sticky="e")
        self.after(100, self.grab_set)

    def _close(self) -> None:
        theme.release_grab(self)
        self.destroy()
        theme.bring_to_front(self.parent_window, grab=True)


class TriggerReplayWindow(ctk.CTkToplevel):
    """Run pasted OCR lines through one trigger and explain every decision."""

    def __init__(self, parent, triggers: list[Trigger], initial_lines: list[str]) -> None:
        super().__init__(parent, fg_color=theme.BG)
        self.trigger_labels = {f"{t.folder} / {t.name}  [{t.id[:6]}]": t for t in triggers}
        self.title("OCR Trigger Replay & Diagnostics")
        self.geometry("900x760")
        self.minsize(720, 620)
        self.transient(parent)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.grid_rowconfigure(6, weight=1)
        theme.heading(self, "OCR REPLAY & TRIGGER DIAGNOSTICS").grid(row=0, column=0, padx=22, pady=(20, 8), sticky="ew")

        controls = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=9)
        controls.grid(row=1, column=0, padx=20, pady=5, sticky="ew")
        controls.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(controls, text="Trigger", text_color=theme.TEXT).grid(row=0, column=0, padx=(14, 8), pady=12)
        labels = list(self.trigger_labels) or ["No triggers in active profile"]
        self.trigger_menu = ctk.CTkOptionMenu(controls, values=labels, **theme.MENU)
        self.trigger_menu.set(labels[0])
        self.trigger_menu.grid(row=0, column=1, padx=8, pady=12, sticky="ew")
        ctk.CTkButton(controls, text="Load text file", command=self._load_file, width=115, **theme.QUIET_BUTTON).grid(
            row=0, column=2, padx=8, pady=12)
        ctk.CTkButton(controls, text="Run replay", command=self._run, width=110, **theme.ACCENT_BUTTON).grid(
            row=0, column=3, padx=(8, 14), pady=12)

        theme.note(self, "Recognized OCR lines — one line per event").grid(row=2, column=0, padx=24, pady=(8, 2), sticky="ew")
        self.input_box = ctk.CTkTextbox(self, **theme.TEXTBOX)
        self.input_box.grid(row=3, column=0, padx=20, pady=(2, 8), sticky="nsew")
        if initial_lines:
            self.input_box.insert("1.0", "\n".join(initial_lines))
        theme.note(self, "Why it matched or failed").grid(row=5, column=0, padx=24, pady=(6, 2), sticky="ew")
        self.output_box = ctk.CTkTextbox(self, font=theme.font(12, family="Consolas"), **theme.TEXTBOX)
        self.output_box.grid(row=6, column=0, padx=20, pady=(2, 10), sticky="nsew")
        self.output_box.insert("1.0", "Run the replay to inspect source selection, each Boolean condition, window "
                                      "state, NOT blockers, cooldowns, regex captures, and timer-end matches.")
        self.output_box.configure(state="disabled")
        ctk.CTkButton(self, text="Close", command=self.destroy, width=100, **theme.QUIET_BUTTON).grid(
            row=7, column=0, padx=20, pady=(0, 18), sticky="e")

    def _load_file(self) -> None:
        filename = filedialog.askopenfilename(parent=self, title="Load OCR replay text",
                                              filetypes=[("Text files", "*.txt *.log"), ("All files", "*.*")])
        if not filename:
            return
        try:
            text = Path(filename).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            messagebox.showerror("Unable to load replay", str(exc), parent=self)
            return
        self.input_box.delete("1.0", "end")
        self.input_box.insert("1.0", text)

    def _run(self) -> None:
        trigger = self.trigger_labels.get(self.trigger_menu.get())
        if not trigger:
            messagebox.showinfo("No trigger", "Create a trigger in this profile first.", parent=self)
            return
        lines = [line.strip() for line in self.input_box.get("1.0", "end").splitlines() if line.strip()]
        if not lines:
            messagebox.showinfo("No OCR lines", "Paste or load at least one OCR line.", parent=self)
            return
        engine = TriggerEngine([copy.deepcopy(trigger)])
        reports = []
        for index, line in enumerate(lines, start=1):
            matches = engine.process(line, trigger.source_key(), now=100.0 + index * 0.25)
            diagnostic = engine.last_diagnostics[0] if engine.last_diagnostics else None
            reports.append(format_report(index, line, diagnostic, matches))
        self.output_box.configure(state="normal")
        self.output_box.delete("1.0", "end")
        self.output_box.insert("1.0", "\n\n".join(reports))
        self.output_box.configure(state="disabled")


def format_report(index: int, line: str, diagnostic: TriggerDiagnostic | None, matches: list[TriggerMatch]) -> str:
    output = [f"LINE {index}: {line}"]
    if diagnostic is None:
        output.append("  Trigger is disabled or invalid and was not evaluated.")
        return "\n".join(output)
    if not diagnostic.source_matches:
        output.append("  FAIL — line came from the wrong OCR source.")
        return "\n".join(output)
    for number, condition in enumerate(diagnostic.conditions, start=1):
        state = "MATCH NOW" if condition.matched_this_line else ("ACTIVE IN WINDOW" if condition.active else "MISS")
        role = "NOT" if condition.negate else diagnostic.logic.upper()
        captures = ", ".join(f"{k}={v!r}" for k, v in condition.captures.items())
        output.append(f"  {number}. [{role} {condition.mode.upper()}] {state}: {condition.pattern!r}"
                      f"{f'; captures: {captures}' if captures else ''}")
    if diagnostic.ended_timer:
        output.append("  TIMER END MATCH — the early-ending rule matched this line.")
    if diagnostic.blocked:
        output.append("  RESULT: BLOCKED by an active NOT condition.")
    elif not diagnostic.condition_met:
        output.append("  RESULT: NOT FIRED — required positive conditions are missing.")
    elif diagnostic.cooldown_remaining > 0:
        output.append(f"  RESULT: NOT FIRED — cooldown has {diagnostic.cooldown_remaining:.2f}s remaining.")
    elif diagnostic.fired:
        fire = next((m for m in matches if m.action == "fire"), None)
        captures = ", ".join(f"{k}={v!r}" for k, v in (fire.captures if fire else {}).items())
        output.append(f"  RESULT: FIRED{f' — {captures}' if captures else ''}.")
    else:
        output.append("  RESULT: NOT FIRED.")
    return "\n".join(output)
