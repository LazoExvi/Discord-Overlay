"""RapidOCR adapter tuned for a dark, scrolling chat panel."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .models import OCRLine

CUDA = "CUDAExecutionProvider"
DIRECTML = "DmlExecutionProvider"
CPU = "CPUExecutionProvider"


def _select_gpu_provider() -> str | None:
    """Return the accelerated ONNX provider available in this environment, if any."""
    try:
        import onnxruntime as ort
    except ImportError:
        return None
    available = ort.get_available_providers()
    provider = CUDA if CUDA in available else DIRECTML if DIRECTML in available else None
    if provider == CUDA:
        # pip-installed CUDA/cuDNN DLLs must be loaded before the sessions are built.
        if hasattr(ort, "preload_dlls"):
            try:
                ort.preload_dlls(directory="")
            except Exception:  # noqa: BLE001 - a system CUDA install may still work
                pass
        if hasattr(ort, "set_default_logger_severity"):
            ort.set_default_logger_severity(3)  # silence the harmless plugin-registry probe
    return provider


class CombatOCREngine:
    """Recognize chat lines from a captured BGR frame with stable top-to-bottom order."""

    def __init__(self, min_confidence: float = 0.52, debug_dir: Path | None = None,
                 prefer_gpu: bool = True) -> None:
        from rapidocr import RapidOCR

        self.min_confidence = min_confidence
        self.debug_dir = debug_dir
        self._debug_counter = 0
        self.provider = "CPU"
        self.provider_detail = CPU

        provider = _select_gpu_provider() if prefer_gpu else None
        params = None
        if provider == CUDA:
            params = {"EngineConfig.onnxruntime.use_cuda": True}
        elif provider == DIRECTML:
            params = {"EngineConfig.onnxruntime.use_dml": True}
        try:
            self._ocr = RapidOCR(params=params)
        except Exception:  # noqa: BLE001 - GPU init must never block startup
            if provider is None:
                raise
            self._ocr = RapidOCR(params={
                "EngineConfig.onnxruntime.use_cuda": False,
                "EngineConfig.onnxruntime.use_dml": False,
            })
            provider = None
        if provider and self._sessions_use(provider):
            self.provider = "GPU"
            self.provider_detail = provider

    def _sessions_use(self, provider: str) -> bool:
        sessions = []
        for component_name in ("text_det", "text_cls", "text_rec"):
            component = getattr(self._ocr, component_name, None)
            session = getattr(getattr(component, "session", None), "session", None)
            if session is not None and hasattr(session, "get_providers"):
                sessions.append(session)
        return bool(sessions) and all(session.get_providers()[0] == provider for session in sessions)

    # -- image helpers --------------------------------------------------------

    @staticmethod
    def preprocess(bgr: np.ndarray) -> np.ndarray:
        """2x Lanczos upscale plus a mild unsharp mask; keeps small serif strokes intact."""
        scaled = cv2.resize(bgr, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_LANCZOS4)
        blurred = cv2.GaussianBlur(scaled, (0, 0), 1.0)
        return cv2.addWeighted(scaled, 1.55, blurred, -0.55, 0)

    @staticmethod
    def text_mask(bgr: np.ndarray) -> np.ndarray:
        """Pixels that look like colored, white, or medium-gray glyphs on a dark background."""
        maximum = bgr.max(axis=2)
        minimum = bgr.min(axis=2)
        colored = ((maximum - minimum) > 35) & (maximum > 100)
        near_white = (minimum > 145) & (maximum > 175)
        neutral_gray = ((maximum - minimum) <= 35) & (minimum >= 82) & (maximum >= 92)
        return colored | near_white | neutral_gray

    @classmethod
    def text_signature(cls, bgr: np.ndarray) -> np.ndarray:
        """Small fingerprint used to skip OCR when the panel has not changed."""
        mask = cls.text_mask(bgr).astype(np.uint8) * 255
        return cv2.resize(mask, (160, 90), interpolation=cv2.INTER_AREA)

    # -- recognition ----------------------------------------------------------

    def recognize(self, bgr: np.ndarray) -> list[OCRLine]:
        if self.debug_dir:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            self._debug_counter += 1
            cv2.imwrite(str(self.debug_dir / f"scan_{self._debug_counter:05d}.png"), self.preprocess(bgr))

        segmented = self._segment_lines(bgr)
        if segmented:
            lines = self._recognize_rows(segmented)
            if lines is not None:
                return self._join_continuations(lines)
        return self._join_continuations(self._recognize_full(bgr))

    def _recognize_rows(self, rows: list[tuple[float, np.ndarray]]) -> list[OCRLine] | None:
        """Batched recognition of pre-segmented rows; None if this RapidOCR lacks the API."""
        try:
            from rapidocr.ch_ppocr_rec.typings import TextRecInput

            result = self._ocr.text_rec(TextRecInput([crop for _y, crop in rows]))
        except (AttributeError, ImportError, TypeError):
            return None
        lines: list[OCRLine] = []
        for (y, _crop), text, score in zip(rows, result.txts or [], result.scores or []):
            clean = self.clean_text(str(text))
            if clean and float(score) >= self.min_confidence:
                lines.append(OCRLine(clean, float(score), y))
        return lines

    def _recognize_full(self, bgr: np.ndarray) -> list[OCRLine]:
        """Detector plus recognizer over the whole panel (slower fallback)."""
        boxes, texts, scores = self._unpack(self._ocr(self.preprocess(bgr)))
        lines: list[OCRLine] = []
        for box, text, score in zip(boxes, texts, scores):
            clean = self.clean_text(str(text))
            if clean and float(score) >= self.min_confidence:
                y = sum(float(point[1]) for point in box) / max(1, len(box))
                lines.append(OCRLine(clean, float(score), y))
        lines.sort(key=lambda line: line.y)
        return lines

    def _segment_lines(self, bgr: np.ndarray) -> list[tuple[float, np.ndarray]]:
        """Split the panel into text rows using the horizontal glyph profile."""
        mask = self.text_mask(bgr)
        minimum_pixels = max(7, int(bgr.shape[1] * 0.012))
        active = (mask.sum(axis=1) >= minimum_pixels).astype(np.uint8)
        active = cv2.morphologyEx(
            active[:, None], cv2.MORPH_CLOSE, np.ones((5, 1), dtype=np.uint8),
        ).ravel().astype(bool)
        spans: list[tuple[int, int]] = []
        start: int | None = None
        last = len(active) - 1
        for y, is_active in enumerate(active):
            if is_active and start is None:
                start = y
            if start is not None and (not is_active or y == last):
                end = y if not is_active else y + 1
                if 7 <= end - start <= 60:
                    spans.append((max(0, start - 3), min(bgr.shape[0], end + 3)))
                start = None
        if not spans or len(spans) > 40:
            return []

        rows: list[tuple[float, np.ndarray]] = []
        for top, bottom in spans:
            xs = np.where(mask[top:bottom])[1]
            if not len(xs):
                continue
            left = max(0, int(xs.min()) - 5)
            right = min(bgr.shape[1], int(xs.max()) + 6)
            if right - left < 18:
                continue
            crop = cv2.resize(bgr[top:bottom, left:right], None, fx=1.5, fy=1.5,
                              interpolation=cv2.INTER_LANCZOS4)
            blur = cv2.GaussianBlur(crop, (0, 0), 0.8)
            rows.append(((top + bottom) / 2.0, cv2.addWeighted(crop, 1.45, blur, -0.45, 0)))
        return rows

    @staticmethod
    def _unpack(result: Any) -> tuple[list, list, list]:
        if hasattr(result, "txts"):  # rapidocr 3.x RapidOCROutput
            return (
                list(result.boxes) if result.boxes is not None else [],
                list(result.txts) if result.txts is not None else [],
                list(result.scores) if result.scores is not None else [],
            )
        raw = result[0] if isinstance(result, tuple) else result
        boxes, texts, scores = [], [], []
        for item in raw or []:
            if len(item) >= 3:
                boxes.append(item[0])
                texts.append(item[1])
                scores.append(item[2])
        return boxes, texts, scores

    @staticmethod
    def clean_text(text: str) -> str:
        text = text.replace("|", "I").replace("…", "...").replace("’", "'").replace("‘", "'")
        text = re.sub(r"\s+", " ", text).strip(" _-")
        text = re.sub(r"(?<=\d)[Oo](?=\d)", "0", text)
        text = re.sub(r"(?<=\d)[Il](?=\d)", "1", text)
        return text

    @staticmethod
    def _join_continuations(lines: list[OCRLine]) -> list[OCRLine]:
        """Glue wrapped fragments such as ``(Critical)`` back onto the previous line."""
        joined: list[OCRLine] = []
        for line in lines:
            lowered = line.text.casefold()
            continuation = (
                lowered.startswith(("(critical", "(crushing", "(glancing"))
                or (joined and lowered.startswith("damage")
                    and "points of damage" not in joined[-1].text.casefold())
            )
            if continuation and joined:
                previous = joined[-1]
                previous.text = f"{previous.text} {line.text}"
                previous.confidence = min(previous.confidence, line.confidence)
            else:
                joined.append(line)
        return joined
