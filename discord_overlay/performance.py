"""Measure this machine's OCR speed and recommend a scan interval."""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

import cv2
import numpy as np

from .backend import detect_gpu_names
from .capture import ScreenCapture
from .models import Region

# (upper bound of full-scan ms, profile, interval, warning)
PROFILES: tuple[tuple[float, str, float, str], ...] = (
    (260, "Ultra", 0.20, ""),
    (400, "Fast", 0.30, ""),
    (650, "Balanced", 0.50,
     "Busy full-party combat may outrun OCR. Use a tall combat window and reduce unneeded spam."),
    (1000, "Limited", 0.75,
     "This system may miss lines during combat bursts. Increase the combat-window height, "
     "hide unneeded messages, and keep most lines on one row."),
    (float("inf"), "Low", 1.20,
     "Fast OCR detection is not sustainable on this configuration. Accuracy may be affected "
     "when several combat lines arrive each second."),
)
SLOW_PROFILES = frozenset({"Balanced", "Limited", "Low"})


@dataclass(slots=True)
class CapabilityResult:
    gpu_names: list[str]
    provider: str
    provider_detail: str
    ocr_ms: float
    capture_ms: float
    unchanged_check_ms: float
    recognized_lines: int
    profile: str
    recommended_interval: float
    warning: str = ""

    @property
    def full_scan_ms(self) -> float:
        return self.ocr_ms + self.capture_ms

    @property
    def full_scan_fps(self) -> float:
        return 1000.0 / max(1.0, self.full_scan_ms)

    @property
    def change_check_fps(self) -> float:
        return 1000.0 / max(1.0, self.unchanged_check_ms)


def faster_result(first: CapabilityResult, second: CapabilityResult) -> CapabilityResult:
    return first if first.full_scan_ms <= second.full_scan_ms else second


def recommend_profile(full_scan_ms: float) -> tuple[str, float, str]:
    for upper, profile, interval, warning in PROFILES:
        if full_scan_ms <= upper:
            return profile, interval, warning
    raise AssertionError("unreachable")


def representative_combat_frame(width: int = 652, height: int = 477) -> np.ndarray:
    """A deterministic, dense combat panel so benchmarks are comparable across machines."""
    lines = [
        "Your iceblast hits a plagueborn patrolman for 717 points of Cold Damage.",
        "a skeletal cleric hits YOU for 83 points of damage.",
        "Your pet Ssssteve pierces a skeletal cleric for 215 points of damage.",
        "Ssssteve's Staggering Winds hits a skeletal cleric for 15 points of Magic Damage.",
        "Raan's Damage Shield hits a caiman for 35 points of damage.",
        "Your Frenzy hits a crocodile for 100 points of slashing damage.",
        "a caiman crushes YOU for 382 points of damage. (Critical)",
        "Your Mend heals you for 120 Health.",
        "Your pet Ssssteve misses a crocodile.",
        "You crush a crocodile for 81 points of damage.",
    ]
    colors = [
        (40, 160, 255), (50, 50, 240), (40, 160, 255), (40, 160, 255), (130, 130, 130),
        (40, 160, 255), (50, 50, 240), (80, 220, 120), (40, 160, 255), (40, 160, 255),
    ]
    image = np.zeros((height, width, 3), dtype=np.uint8)
    spacing = max(25, min(40, (height - 20) // len(lines)))
    scale = max(0.38, min(0.48, width / 1358.0))
    for index, (line, color) in enumerate(zip(lines, colors)):
        cv2.putText(image, line, (8, 28 + index * spacing), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, color, 1, cv2.LINE_AA)
    return image


def benchmark_capability(region: Region, prefer_gpu: bool = True, ocr_samples: int = 5) -> CapabilityResult:
    from .ocr_engine import CombatOCREngine

    engine = CombatOCREngine(min_confidence=0.45, prefer_gpu=prefer_gpu)
    capture = ScreenCapture()
    frame = representative_combat_frame(region.width, region.height)

    engine.recognize(frame)  # warm the sessions and GPU kernels
    ocr_times: list[float] = []
    lines = []
    for _ in range(max(2, ocr_samples)):
        started = time.perf_counter()
        lines = engine.recognize(frame)
        ocr_times.append((time.perf_counter() - started) * 1000.0)

    capture_times: list[float] = []
    signature_times: list[float] = []
    capture.grab(region)
    for _ in range(30):
        started = time.perf_counter()
        live = capture.grab(region)
        capture_times.append((time.perf_counter() - started) * 1000.0)
        started = time.perf_counter()
        engine.text_signature(live)
        signature_times.append((time.perf_counter() - started) * 1000.0)

    ocr_ms = statistics.median(ocr_times)
    capture_ms = statistics.median(capture_times)
    profile, interval, warning = recommend_profile(ocr_ms + capture_ms)
    return CapabilityResult(
        gpu_names=detect_gpu_names(), provider=engine.provider, provider_detail=engine.provider_detail,
        ocr_ms=ocr_ms, capture_ms=capture_ms,
        unchanged_check_ms=capture_ms + statistics.median(signature_times),
        recognized_lines=len(lines), profile=profile, recommended_interval=interval, warning=warning,
    )
