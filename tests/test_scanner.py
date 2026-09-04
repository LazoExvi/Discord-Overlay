"""Drive the scanner loop with a fake OCR engine and capture."""
import queue

import numpy as np

from discord_overlay.config import Settings
from discord_overlay.models import EventKind, OCRLine, Region
from discord_overlay.scanner import ScannerWorker, build_sources
from discord_overlay.triggers import Trigger, TriggerCondition, TriggerEngine


class FakeEngine:
    provider = "CPU"
    provider_detail = "FakeExecutionProvider"

    def __init__(self, frames: list[list[str]], worker_holder: dict) -> None:
        self.frames = frames
        self.calls = 0
        self.holder = worker_holder

    def text_signature(self, frame):
        # Every frame differs so no scan is skipped; the value itself is irrelevant.
        self.calls_sig = getattr(self, "calls_sig", 0) + 1
        return np.full((90, 160), self.calls_sig % 250, dtype=np.uint8)

    def recognize(self, frame):
        index = min(self.calls, len(self.frames) - 1)
        self.calls += 1
        if self.calls >= len(self.frames):
            self.holder["worker"].stop()
        return [OCRLine(text, 0.9, y * 20) for y, text in enumerate(self.frames[index])]


class FakeCapture:
    def grab(self, region):
        return np.zeros((region.height, region.width, 3), dtype=np.uint8)


def run_worker(settings: Settings, frames: list[list[str]], tmp_path):
    output: queue.Queue = queue.Queue()
    holder: dict = {}
    settings.scan_interval = 0.15
    worker = ScannerWorker(settings, output, engine_factory=lambda _s: FakeEngine(frames, holder),
                           capture=FakeCapture(), grammar="", template_path=tmp_path / "templates.json")
    holder["worker"] = worker
    worker.run()
    messages = []
    while not output.empty():
        messages.append(output.get_nowait())
    return messages


def test_scanner_emits_engine_ocr_events_and_triggers(app_data, tmp_path):
    settings = Settings(active_character="Raan", region=Region(0, 0, 200, 100), triggers=[
        Trigger(name="Curse", conditions=[TriggerCondition("curse lands")], cooldown_seconds=0),
    ])
    frames = [
        ["older line", "You crush a rat for 10 points of damage."],
        ["You crush a rat for 10 points of damage.", "Withering curse lands on Raan"],
        ["Withering curse lands on Raan", "a rat bites YOU for 4 points of damage."],
    ]
    messages = run_worker(settings, frames, tmp_path)
    kinds = [kind for kind, _ in messages]
    assert kinds[0] == "status" and kinds[1] == "engine" and kinds[-1] == "stopped"
    assert messages[1][1] == ("CPU", "FakeExecutionProvider")
    events = [value for kind, value in messages if kind == "event"]
    # The first frame is only a baseline; the two later lines are parsed.
    assert [(e.kind, e.amount) for e in events] == [(EventKind.DAMAGE_IN, 4)]
    triggers = [value for kind, value in messages if kind == "trigger"]
    assert [t.trigger_name for t in triggers] == ["Curse"]
    assert sum(kind == "preview" for kind in kinds) == 3
    assert any(kind == "ocr" and len(value[0]) == 2 for kind, value in messages)


def test_scanner_announces_learned_pets(app_data, tmp_path):
    settings = Settings(active_character="Raan", region=Region(0, 0, 200, 100))
    frames = [["baseline"], ["Ssssteve hits a rat for 10 points of damage."],
              ["Your pet Ssssteve bites a rat for 4 points of damage."]]
    messages = run_worker(settings, frames, tmp_path)
    assert [value for kind, value in messages if kind == "pet"] == ["Ssssteve"]


def test_scanner_reports_engine_failures_instead_of_dying(app_data, tmp_path):
    def boom(_settings):
        raise RuntimeError("no models")

    output: queue.Queue = queue.Queue()
    settings = Settings(region=Region(0, 0, 200, 100))
    ScannerWorker(settings, output, engine_factory=boom, capture=FakeCapture(), grammar="",
                  template_path=tmp_path / "t.json").run()
    kinds = [kind for kind, _ in list(output.queue)]
    assert "error" in kinds and kinds[-1] == "stopped"
    assert "RuntimeError: no models" in next(value for kind, value in output.queue if kind == "error")


def test_sources_include_distinct_dedicated_regions_only():
    shared = Region(5, 5, 300, 100)
    settings = Settings(region=Region(0, 0, 200, 100), triggers=[
        Trigger(name="A", conditions=[TriggerCondition("a")], use_combat_region=False, region=shared),
        Trigger(name="B", conditions=[TriggerCondition("b")], use_combat_region=False, region=shared),
        Trigger(name="C", conditions=[TriggerCondition("c")]),
        Trigger(name="D", conditions=[TriggerCondition("d")], use_combat_region=False, enabled=False,
                region=Region(9, 9, 300, 100)),
    ])
    sources = build_sources(settings, TriggerEngine(settings.triggers))
    assert set(sources) == {"combat", "region:5:5:300:100"}
    assert not build_sources(Settings(), TriggerEngine([]))


def test_scanner_learns_templates_and_saves_them(app_data, tmp_path):
    settings = Settings(active_character="Sean", region=Region(0, 0, 200, 100))
    frames = [["baseline"]] + [[f"Sean punches a snake for {n} points of damage"] for n in (501, 505, 540)]
    run_worker(settings, frames, tmp_path)
    assert (tmp_path / "templates.json").is_file()
