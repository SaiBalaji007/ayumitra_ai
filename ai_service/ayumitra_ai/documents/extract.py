"""
Patient document extraction (Phase 4): digital PDFs, scanned PDFs, photos (PNG/JPEG).

Stateless: input bytes in, structured pages out. Nothing is written to disk or to the knowledge
base, so private documents stay in Django's per-user storage only.
"""

from __future__ import annotations

import io
from dataclasses import asdict, dataclass, field

import numpy as np

from .ocr import OcrUnavailable, group_rows, run_ocr

MIN_TEXT_CHARS_PER_PAGE = 40  # below this a PDF page is treated as scanned and OCR'd
OCR_DPI = 300


@dataclass
class Table:
    rows: list[list[str]]
    bbox: tuple[float, float, float, float] | None = None
    method: str = "pdf_table"


@dataclass
class Page:
    page_number: int
    text: str
    method: str                  # text_layer | ocr_paddle | ocr_tesseract
    confidence: float | None     # None for an embedded text layer (exact)
    lines: list[dict] = field(default_factory=list)  # {"text", "confidence", "bbox"}
    tables: list[Table] = field(default_factory=list)
    width: float | None = None
    height: float | None = None


@dataclass
class ExtractionResult:
    content_type: str
    pages: list[Page]
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)

    def to_dict(self) -> dict:
        return {"content_type": self.content_type, "page_count": len(self.pages), "warnings": self.warnings,
                "pages": [asdict(p) for p in self.pages]}


def _ocr_page(image: np.ndarray, page_number: int, scale: float = 1.0) -> Page:
    res = run_ocr(image)
    if res.mean_confidence is None or res.mean_confidence < 0.85:
        # Low confidence (phone photo, scan, handwriting): also try a cleaned-up image and keep the better read.
        try:
            from .preprocess import enhance

            enhanced = enhance(image)
            alt = run_ocr(enhanced)
            if (alt.mean_confidence or 0) > (res.mean_confidence or 0) and alt.lines:
                eh = enhanced.shape[0] / image.shape[0]  # enhanced image may be upscaled
                res, scale, image = alt, scale * eh, enhanced
        except Exception:  # preprocessing is an optimisation only
            pass
    method = "ocr_paddle" if res.engine.startswith("paddle") else "ocr_tesseract"
    rows = group_rows(res.lines)
    # Rows with 3+ separated boxes look like table rows (lab reports: test | value | unit | range).
    table_rows = [[ln.text for ln in row] for row in rows if len(row) >= 3]
    tables = [Table(rows=table_rows, method="ocr_rows")] if len(table_rows) >= 2 else []
    lines = [{"text": ln.text, "confidence": round(ln.confidence, 4),
              "bbox": [round(v / scale, 1) for v in ln.bbox]} for ln in res.lines]
    text = "\n".join("  ".join(ln.text for ln in row) for row in rows)
    h, w = image.shape[:2]
    return Page(page_number=page_number, text=text, method=method,
                confidence=round(res.mean_confidence, 4) if res.mean_confidence is not None else None,
                lines=lines, tables=tables, width=w / scale, height=h / scale)


def _load_image(data: bytes) -> np.ndarray:
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)  # phone photos: respect camera orientation
    return np.asarray(img.convert("RGB"))


def extract_image(data: bytes, content_type: str) -> ExtractionResult:
    try:
        page = _ocr_page(_load_image(data), 1)
    except OcrUnavailable as exc:
        return ExtractionResult(content_type, [], warnings=[str(exc)])
    warnings = [] if page.text.strip() else ["No text was found in the image."]
    try:
        from .preprocess import BLURRY_BELOW, blur_score

        if blur_score(_load_image(data)) < BLURRY_BELOW:
            warnings.append("The photo looks blurry, so some words may be misread. A sharper, well-lit photo works best.")
    except Exception:
        pass
    return ExtractionResult(content_type, [page], warnings)


def extract_pdf(data: bytes) -> ExtractionResult:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=data, filetype="pdf")
    pages, warnings = [], []
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        if len(text) >= MIN_TEXT_CHARS_PER_PAGE:
            tables = []
            try:
                for t in page.find_tables().tables:
                    rows = [[(c or "").strip() for c in row] for row in t.extract()]
                    rows = [r for r in rows if any(r)]
                    if len(rows) >= 2:
                        tables.append(Table(rows=rows, bbox=tuple(round(v, 1) for v in t.bbox)))
            except Exception as exc:  # table detection is best-effort
                warnings.append(f"Table detection failed on page {i}: {exc}")
            lines = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    t = "".join(s["text"] for s in line["spans"]).strip()
                    if t:
                        lines.append({"text": t, "confidence": None, "bbox": [round(v, 1) for v in line["bbox"]]})
            pages.append(Page(i, text, "text_layer", None, lines, tables, page.rect.width, page.rect.height))
            continue
        # Scanned page: render and OCR.
        scale = OCR_DPI / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        try:
            pages.append(_ocr_page(img, i, scale))
        except OcrUnavailable as exc:
            warnings.append(f"Page {i} needs OCR but no OCR engine is available: {exc}")
            pages.append(Page(i, text, "text_layer", None))
    return ExtractionResult("application/pdf", pages, warnings)


def extract_document(data: bytes, content_type: str) -> ExtractionResult:
    if content_type == "application/pdf":
        return extract_pdf(data)
    if content_type in ("image/png", "image/jpeg"):
        return extract_image(data, content_type)
    raise ValueError(f"Unsupported content type: {content_type}")
