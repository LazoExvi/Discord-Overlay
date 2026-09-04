"""Background capture -> OCR -> parse -> trigger loop.

The worker owns no UI. It posts ``(kind, value)`` tuples onto a queue that the
main window drains on the Tk thread:

``status`` str, ``engine`` (provider, detail), ``preview`` BGR frame,
``ocr`` (lines, seconds, repaired_total), ``event`` CombatEvent,
``trigger`` TriggerMatch, ``error`` str, ``stopped`` worker.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from .capture import ScreenCapture
from .config import Settings
from .dedup import ScrollingTextDeduplicator
from .diagnostics import LOGGER_NAME
from .models import CombatEvent, OCRLine, Region
from .parser import CombatTextParser
from .paths import debug_scans_dir, template_path_for
from .repair import LineRepairer, bundled_grammar, event_names
from .triggers import TriggerEngine

COMBAT_SOURCE = "combat"
CHANGE_THRESHOLD = 0.12     # mean signature difference below which OCR is skipped
FORCED_SCAN_SECONDS = 1.0   # ...but never skip for longer than this
TEMPLATE_SAVE_SECONDS = 60.0
REPAIRED_CONFIDENCE_CAP = 0.85


@dataclass
class ScanSource:
    region: Region
    dedup: ScrollingTextDeduplicator = field(default_factory=ScrollingTextDeduplicator)
    signature: object = None
    last_ocr_at: float = 0.0


def repair_line(repairer: LineRepairer, parser: CombatTextParser, line: OCRLine,
                event: CombatEvent | None) -> tuple[CombatEvent | None, str]:
    """Try to rebuild a cursor-damaged line; return the (event, text) to use.

    Only lines the parser could not attribute at all are "degraded". A clean
    third-party hit parses as DAMAGE_OTHER with a real target and is learned as a
    template rather than rewritten.
    """
    degraded = event is None or event.target == "Unknown"
    fix = repairer.repair(line.text, degraded)
    if fix is None:
        if event is not None and not degraded:
            repairer.observe(line.text, event_names(event))
        return event, line.text
    repaired = parser.parse(fix.text, min(line.confidence, REPAIRED_CONFIDENCE_CAP))
    if repaired is None:
        return event, line.text
    repaired.raw_text = line.text
    repaired.repaired = True
    return repaired, fix.text


def build_sources(settings: Settings, engine: TriggerEngine) -> dict[str, ScanSource]:
    """One capture source for the combat region plus each distinct dedicated trigger region."""
    sources: dict[str, ScanSource] = {}
    if settings.region:
        sources[COMBAT_SOURCE] = ScanSource(settings.region)
    for trigger in engine.triggers:
        if not trigger.use_combat_region and trigger.region:
            sources.setdefault(trigger.source_key(), ScanSource(trigger.region))
    return sources


class ScannerWorker:
    def __init__(self, settings: Settings, output: queue.Queue, *,
                 engine_factory=None, capture: ScreenCapture | None = None,
                 grammar: str | None = None, template_path: Path | None = None) -> None:
        self.settings = settings
        self.output = output
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self._engine_factory = engine_factory
        self._capture = capture
        self._grammar = grammar
        self._template_path = template_path
        self._log = logging.getLogger(LOGGER_NAME)

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run, name="ocr-scanner", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _put(self, kind: str, value) -> None:
        self.output.put((kind, value))

    def _make_engine(self):
        if self._engine_factory is not None:
            return self._engine_factory(self.settings)
        from .ocr_engine import CombatOCREngine

        debug_dir = debug_scans_dir() if self.settings.save_debug_images else None
        return CombatOCREngine(self.settings.min_confidence, debug_dir, prefer_gpu=self.settings.prefer_gpu)

    def _make_repairer(self) -> tuple[LineRepairer | None, Path | None]:
        if not self.settings.repair_occluded_lines:
            return None, None
        repairer = LineRepairer()
        repairer.load_seed_text(bundled_grammar() if self._grammar is None else self._grammar)
        path = self._template_path or template_path_for(self.settings.active_character)
        repairer.load(path)
        return repairer, path

    def _save_templates(self, repairer: LineRepairer | None, path: Path | None) -> None:
        if repairer is None or path is None or not repairer.dirty:
            return
        try:
            repairer.save(path)
        except OSError:
            self._log.warning("Could not save grammar templates to %s", path)

    def run(self) -> None:
        settings = self.settings
        repairer: LineRepairer | None = None
        template_path: Path | None = None
        try:
            self._put("status", "Loading OCR models…")
            engine = self._make_engine()
            self._put("engine", (engine.provider, engine.provider_detail))
            capture = self._capture or ScreenCapture()
            parser = CombatTextParser(settings.player_name)
            repairer, template_path = self._make_repairer()
            trigger_engine = TriggerEngine(settings.effective_triggers())
            sources = build_sources(settings, trigger_engine)
            extra = sum(key != COMBAT_SOURCE for key in sources)
            detail = f" + {extra} trigger region{'s' if extra != 1 else ''}" if extra else ""
            self._put("status", f"Monitoring OCR{detail}")
            last_template_save = time.monotonic()

            while not self.stop_event.is_set() and sources:
                tick = time.monotonic()
                for source_key, source in sources.items():
                    if self.stop_event.is_set():
                        break
                    self._scan_source(source_key, source, tick, engine, capture, parser,
                                      repairer, trigger_engine)
                if repairer is not None and time.monotonic() - last_template_save >= TEMPLATE_SAVE_SECONDS:
                    self._save_templates(repairer, template_path)
                    last_template_save = time.monotonic()
                elapsed = time.monotonic() - tick
                self.stop_event.wait(max(0.01, settings.scan_interval - elapsed))
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI, never swallowed
            self._put("error", f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")
        finally:
            self._save_templates(repairer, template_path)
            self._put("stopped", self)

    def _scan_source(self, source_key: str, source: ScanSource, tick: float, engine, capture,
                     parser: CombatTextParser, repairer: LineRepairer | None,
                     trigger_engine: TriggerEngine) -> None:
        is_combat = source_key == COMBAT_SOURCE
        frame = capture.grab(source.region)
        if is_combat:
            self._put("preview", frame)
        signature = engine.text_signature(frame)
        if source.signature is not None:
            change = cv2.absdiff(signature, source.signature).mean()
            # A short line can affect a tiny fraction of a large region, so a
            # periodic pass guarantees small changes are never skipped forever.
            if change < CHANGE_THRESHOLD and tick - source.last_ocr_at < FORCED_SCAN_SECONDS:
                return
        source.signature = signature
        lines = engine.recognize(frame)
        source.last_ocr_at = time.monotonic()
        if is_combat:
            self._put("ocr", (lines, time.monotonic() - tick, repairer.repaired if repairer else 0))
            for line in lines:  # learn pet aliases even from the initial baseline
                parser.observe(line.text)
        for line in source.dedup.new_lines(lines):
            text = line.text
            event: CombatEvent | None = None
            if is_combat:
                event = parser.parse(text, line.confidence)
                if repairer is not None:
                    event, text = repair_line(repairer, parser, line, event)
            for match in trigger_engine.process(text, source_key):
                self._put("trigger", match)
            if event is not None:
                self._put("event", event)
