"""Drive the real Tk window through its main features and report any exception.

Usage: python scripts/ui_smoke.py [--ocr]
Runs against a throwaway %LOCALAPPDATA% so your settings are untouched. With
``--ocr`` it also starts real monitoring on a screen region for a few seconds.
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="discord-overlay-smoke-")

from discord_overlay.config import Settings  # noqa: E402
from discord_overlay.models import CombatEvent, EventKind, OCRLine, Region  # noqa: E402
from discord_overlay.triggers import Trigger, TriggerCondition, TriggerMatch  # noqa: E402
from discord_overlay.ui import theme  # noqa: E402
from discord_overlay.ui.dialogs import AboutWindow, GroupFilterEditor, RegexHelpWindow, TriggerReplayWindow  # noqa: E402
from discord_overlay.ui.main_window import App  # noqa: E402

WITH_OCR = "--ocr" in sys.argv
failures: list[str] = []
steps: list[str] = []


def step(name: str, action) -> None:
    try:
        action()
        steps.append(f"ok   {name}")
    except Exception:  # noqa: BLE001
        failures.append(name)
        steps.append(f"FAIL {name}\n{traceback.format_exc()}")


def main() -> int:
    settings = Settings(region=Region(100, 100, 600, 300), setup_completed=True)
    settings.triggers.append(Trigger(name="Smoke curse", conditions=[TriggerCondition(r"(?<spell>.+) lands on (?<target>\w+)", "regex")],
                                     overlay_enabled=True, timer_seconds=6, timer_key_template="{target}", cooldown_seconds=0))
    settings.save()
    theme.apply_theme()
    app = App()
    app.report_callback_exception = lambda *exc: failures.append("tk callback: " + "".join(traceback.format_exception(*exc)))
    windows: list = []

    def add_events() -> None:
        now = 100.0
        for text, kind, actor, target, amount in (
            ("You crush a rat for 10 points of damage.", EventKind.DAMAGE_OUT, "You", "rat", 10),
            ("a rat bites YOU for 4 points of damage.", EventKind.DAMAGE_IN, "rat", "You", 4),
            ("Klog heals you for 20 Health.", EventKind.HEAL, "Klog", "You", 20),
        ):
            app._add_event(CombatEvent(now, datetime.now(), kind, actor, target, amount, raw_text=text))
            now += 1
        app._refresh_metrics()
        assert app.log_table.tree.get_children() and app.actor_table.tree.get_children()

    def fire_trigger() -> None:
        trigger = app.settings.triggers[0]
        app._trigger_fired(TriggerMatch(trigger.id, trigger.name, "builtin:Alert", 0.3, "Curse lands on Raan",
                                        captures={"spell": "Curse", "target": "Raan"}))
        assert app.timers.timers, "timer did not start"
        app.overlays.render()
        assert app.overlays.all(), "no overlay window created"

    def open_windows() -> None:
        windows.append(AboutWindow(app))
        windows.append(RegexHelpWindow(app))
        windows.append(TriggerReplayWindow(app, app.settings.triggers, ["Curse lands on Raan"]))
        windows.append(GroupFilterEditor(app, False, [], lambda *_: None))
        app.alerts.show_speech_settings()
        app.alerts.new_trigger()
        app.alerts._editor.pattern_entry.insert(0, "hello")
        app.alerts._editor._add_condition()
        app.alerts._editor._save()
        assert len(app.settings.triggers) == 2

    def replay() -> None:
        windows[2]._run()

    def characters() -> None:
        app.settings.add_character("Smoketest", copy_current=True)
        app.settings.switch_character("Smoketest")
        app.settings.save()
        app._apply_character_to_ui()
        assert app.tracker.player_name == "Smoketest"
        app.settings.switch_character("Default")
        app._apply_character_to_ui()

    def boards() -> None:
        board = app.settings.ensure_board("Buffs")
        app.settings_tab.refresh_character_fields()
        app.overlays.preview_board(board)
        app.overlays.arrange()
        app.overlays.lock()
        app.overlays.hide()
        app.settings_tab.apply_to_settings()

    def scanner_messages() -> None:
        app.messages.put(("status", "smoke status"))
        app.messages.put(("engine", ("CPU", "Fake")))
        app.messages.put(("ocr", ([OCRLine("You crush a rat for 3 points of damage.", 0.9)], 0.2, 1)))
        app.messages.put(("event", CombatEvent(200.0, datetime.now(), EventKind.DAMAGE_OUT, "You", "rat", 3)))
        app._poll()

    def close_windows() -> None:
        for window in windows:
            if window.winfo_exists():
                window.destroy()
        for attr in ("_editor", "_speech_editor"):
            window = getattr(app.alerts, attr)
            if window and window.winfo_exists():
                window.destroy()

    def start_ocr() -> None:
        app.start_monitoring()
        assert app.running

    def check_ocr() -> None:
        text = app.status_label.cget("text")
        assert "Monitoring" in text, f"unexpected status: {text!r}"
        assert app._preview_photo is not None, "no live preview frame arrived"
        app.stop_monitoring()

    schedule = [
        (400, "add events", add_events),
        (800, "fire trigger + overlay", fire_trigger),
        (1400, "open windows", open_windows),
        (1900, "replay tester", replay),
        (2300, "character switch", characters),
        (2900, "boards + overlay modes", boards),
        (3300, "scanner messages", scanner_messages),
        (3700, "close windows", close_windows),
    ]
    if WITH_OCR:
        schedule += [(4200, "start OCR monitoring", start_ocr), (16000, "OCR monitoring produced frames", check_ocr)]
    for delay, name, action in schedule:
        app.after(delay, lambda name=name, action=action: step(name, action))
    app.after(schedule[-1][0] + 800, lambda: step("close app", app.close))
    app.mainloop()
    print("\n".join(steps))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
