"""
OCR engines (pretrained only).

Primary:  PaddleOCR's pretrained PP-OCR detection + recognition models, run through RapidOCR's
          ONNX runtime (no paddlepaddle framework needed, works on CPU / Windows / Python 3.13).
Fallback: Tesseract, when the `tesseract` binary is installed (pytesseract wrapper).

Every engine returns line-level boxes with a confidence in [0, 1]. Nothing is "corrected": if
the engine is unsure, the low confidence is passed on so later stages can ask the user.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class OcrLine:
    text: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in image pixels


@dataclass
class OcrResult:
    lines: list[OcrLine]
    engine: str

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def mean_confidence(self) -> float | None:
        if not self.lines:
            return None
        weights = [max(1, len(line.text)) for line in self.lines]
        return float(np.average([line.confidence for line in self.lines], weights=weights))


class OcrUnavailable(RuntimeError):
    pass


class PaddleOnnxOcr:
    name = "paddleocr-onnx"

    def __init__(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise OcrUnavailable("rapidocr-onnxruntime is not installed") from exc
        self._engine = RapidOCR()

    def recognize(self, image: np.ndarray) -> OcrResult:
        result, _ = self._engine(image)
        lines = []
        for box, text, score in result or []:
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            lines.append(OcrLine(text=str(text).strip(), confidence=float(score), bbox=(min(xs), min(ys), max(xs), max(ys))))
        return OcrResult(lines=sort_reading_order([ln for ln in lines if ln.text]), engine=self.name)


class TesseractOcr:
    name = "tesseract"

    def __init__(self):
        if not shutil.which("tesseract"):
            raise OcrUnavailable("tesseract binary not found on PATH")
        try:
            import pytesseract
        except ImportError as exc:
            raise OcrUnavailable("pytesseract is not installed") from exc
        self._pt = pytesseract

    def recognize(self, image: np.ndarray) -> OcrResult:
        data = self._pt.image_to_data(image, output_type=self._pt.Output.DICT)
        rows: dict[tuple, list[int]] = {}
        for i, word in enumerate(data["text"]):
            if word.strip() and float(data["conf"][i]) >= 0:
                rows.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(i)
        lines = []
        for idx in rows.values():
            text = " ".join(data["text"][i] for i in idx)
            conf = float(np.mean([float(data["conf"][i]) for i in idx])) / 100
            x0 = min(data["left"][i] for i in idx)
            y0 = min(data["top"][i] for i in idx)
            x1 = max(data["left"][i] + data["width"][i] for i in idx)
            y1 = max(data["top"][i] + data["height"][i] for i in idx)
            lines.append(OcrLine(text=text, confidence=conf, bbox=(x0, y0, x1, y1)))
        return OcrResult(lines=sort_reading_order(lines), engine=self.name)


def sort_reading_order(lines: list[OcrLine]) -> list[OcrLine]:
    """Top-to-bottom, then left-to-right, treating boxes whose vertical centres are close as one row."""
    if not lines:
        return lines
    heights = sorted(ln.bbox[3] - ln.bbox[1] for ln in lines)
    tol = max(4.0, heights[len(heights) // 2] * 0.6)
    ordered = sorted(lines, key=lambda ln: (ln.bbox[1] + ln.bbox[3]) / 2)
    rows: list[list[OcrLine]] = []
    for ln in ordered:
        cy = (ln.bbox[1] + ln.bbox[3]) / 2
        if rows and abs(cy - np.mean([(r.bbox[1] + r.bbox[3]) / 2 for r in rows[-1]])) <= tol:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    return [ln for row in rows for ln in sorted(row, key=lambda r: r.bbox[0])]


def group_rows(lines: list[OcrLine]) -> list[list[OcrLine]]:
    """Group reading-ordered lines into visual rows (used to rebuild table rows from OCR)."""
    rows: list[list[OcrLine]] = []
    if not lines:
        return rows
    heights = sorted(ln.bbox[3] - ln.bbox[1] for ln in lines)
    tol = max(4.0, heights[len(heights) // 2] * 0.6)
    for ln in lines:
        cy = (ln.bbox[1] + ln.bbox[3]) / 2
        if rows and abs(cy - np.mean([(r.bbox[1] + r.bbox[3]) / 2 for r in rows[-1]])) <= tol:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    return [sorted(r, key=lambda x: x.bbox[0]) for r in rows]


@lru_cache(maxsize=1)
def available_engines() -> list:
    engines = []
    for cls in (PaddleOnnxOcr, TesseractOcr):
        try:
            engines.append(cls())
        except OcrUnavailable as exc:
            log.info("OCR engine %s unavailable: %s", cls.name, exc)
    return engines


def run_ocr(image: np.ndarray, *, min_confidence_for_fallback: float = 0.6) -> OcrResult:
    """Primary engine first; if its confidence is low and a fallback exists, keep the better result."""
    engines = available_engines()
    if not engines:
        raise OcrUnavailable("No OCR engine available (install rapidocr-onnxruntime or tesseract).")
    best = engines[0].recognize(image)
    for engine in engines[1:]:
        if best.mean_confidence is not None and best.mean_confidence >= min_confidence_for_fallback:
            break
        other = engine.recognize(image)
        if (other.mean_confidence or 0) > (best.mean_confidence or 0):
            best = other
    return best
