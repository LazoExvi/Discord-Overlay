"""Drive the real Tk window through its main features and report any exception.

Usage: python scripts/ui_smoke.py [--ocr] [--screenshot PATH]
Runs against a throwaway %LOCALAPPDATA% so your settings are untouched. With
``--ocr`` it also starts real monitoring on a screen region for a few seconds.
``--screenshot`` saves a PNG of the main window once sample data is showing.
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
SCREENSHOT = sys.argv[sys.argv.index("--screenshot") + 1] if "--screenshot" in sys.argv else ""
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
        import time

        now = time.monotonic() - 6
        sample = (
            ("You crush a rat for 810 points of damage.", EventKind.DAMAGE_OUT, "You", "rat", 810, False),
            ("Your pet Ssssteve bites a rat for 240 points of damage.", EventKind.DAMAGE_OUT, "Ssssteve", "rat", 240, True),
            ("Klog's Fireball hits a rat for 1,420 points of damage.", EventKind.DAMAGE_OTHER, "Klog", "rat", 1420, False),
            ("Aernulo slashes a rat for 655 points of damage.", EventKind.DAMAGE_OTHER, "Aernulo", "rat", 655, False),
            ("a rat bites YOU for 96 points of damage.", EventKind.DAMAGE_IN, "rat", "You", 96, False),
            ("Klog heals you for 320 Health.", EventKind.HEAL, "Klog", "You", 320, False),
            ("You crush a rat for 1,105 points of damage.", EventKind.DAMAGE_OUT, "You", "rat", 1105, False),
        )
        for index, (text, kind, actor, target, amount, is_pet) in enumerate(sample * 3):
            app._add_event(CombatEvent(now + index * 0.25, datetime.now(), kind, actor, target, amount,
                                       raw_text=text, is_pet=is_pet, critical=index % 5 == 0, confidence=0.93))
        for index in range(120):
            app.sparkline.add(now - 50 + index * 0.5, 400 + (index * 173) % 900)
        app._refresh_metrics()
        assert app.log_table.tree.get_children() and app.meter.rows
        app.view_toggle.set("Table")
        app._switch_view()
        assert app.actor_table.tree.get_children()
        app.view_toggle.set("Bars")
        app._switch_view()

    def screenshot() -> None:
        if not SCREENSHOT:
            return
        from PIL import ImageGrab

        app.update_idletasks()
        x, y = app.winfo_rootx(), app.winfo_rooty()
        ImageGrab.grab(bbox=(x - 8, y - 32, x + app.winfo_width() + 8, y + app.winfo_height() + 8)).save(SCREENSHOT)

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
        text = app.status_pill.label.cget("text")
        assert "Monitoring" in text, f"unexpected status: {text!r}"
        assert app._preview_photo is not None, "no live preview frame arrived"
        app.stop_monitoring()

    schedule = [
        (400, "add events", add_events),
        (700, "screenshot", screenshot),
        (900, "fire trigger + overlay", fire_trigger),
        (1600, "open windows", open_windows),
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
