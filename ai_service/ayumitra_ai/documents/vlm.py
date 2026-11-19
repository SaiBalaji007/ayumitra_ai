"""
Reading handwritten prescriptions with a local vision-language model.

Model: Qwen2.5-VL-3B-Instruct (4-bit GGUF + vision projector), run on the CPU by llama.cpp's
`llama-mtmd-cli`. It reads the image and returns each medicine line as JSON. Nothing leaves the computer.

The model is only a *reader*. Its output goes through the same parser, medicine lexicon and review flags
as OCR text, and pipeline code cross-checks every line against the OCR text (`support_in_text`):
anything not backed by the page is flagged for the user. Missing fields stay empty; nothing is inferred.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

log = logging.getLogger(__name__)

SERVICE_ROOT = Path(__file__).resolve().parent.parent.parent
CLI = SERVICE_ROOT / "runtime" / "llama" / "llama-mtmd-cli.exe"
MODEL = SERVICE_ROOT / "models" / "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
MMPROJ = SERVICE_ROOT / "models" / "mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf"
MAX_SIDE = 1600          # handwriting needs detail: 1600 px read frequencies far better than 1024 px (≈ 4 min vs 2.5 min)
TIMEOUT_S = 600

PROMPT = """This image is a doctor's prescription. Read ONLY the medicines written in the Rx section (ignore the doctor's letterhead, the patient details and the clinical notes).

For each numbered medicine, copy exactly what is handwritten:
- form: Tab, Cap, Syp, Inj, Sachet, Drops, etc.
- name: the medicine or brand name
- strength: e.g. 500, 60K, 150 mg
- dose: how much at a time, e.g. "1 tab", "10 ml"
- frequency: how often, e.g. "once daily", "1 x 2", "once weekly", "BD", "SOS"
- timing: e.g. "morning", "empty stomach", "at night", "after food"
- duration: e.g. "7 days", "1 month", "4 weeks"

Rules:
- Copy only what is written for THAT medicine; never copy a value from another medicine.
- Keep frequency words exactly, including words like weekly, at night, per week, SOS.
- "oral" is not a timing. Leave form empty if no form (Tab/Cap/Syp) is written before the name.
- Copy only what is written. If a field is not written, use "". Never guess or add a value that is not on the paper.

Answer with JSON only, in this format:
{"medicines": [{"number": 1, "form": "", "name": "", "strength": "", "dose": "", "frequency": "", "timing": "", "duration": ""}]}"""

FIELDS = ("form", "name", "strength", "dose", "frequency", "timing", "duration")


def available() -> bool:
    return os.environ.get("AYUMITRA_VISION_ENABLED", "true").lower() != "false" and all(
        p.exists() for p in (CLI, MODEL, MMPROJ))


def _prepare_image(data: bytes, content_type: str) -> bytes:
    """JPEG, longest side ≤ MAX_SIDE. PDFs: first page rendered."""
    from PIL import Image
    import io

    if content_type == "application/pdf":
        import fitz  # PyMuPDF

        page = fitz.open(stream=data, filetype="pdf")[0]
        data = page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _parse(stdout: str) -> list[dict]:
    m = re.search(r"\{.*\}", stdout, re.S)
    if not m:
        return []
    text = m.group(0)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        try:  # small models sometimes add a trailing comma
            obj = json.loads(re.sub(r",\s*([}\]])", r"\1", text))
        except json.JSONDecodeError:
            return []
    meds = obj.get("medicines") if isinstance(obj, dict) else None
    out = []
    for med in meds or []:
        if not isinstance(med, dict):
            continue
        row = {f: str(med.get(f) or "").strip() for f in FIELDS}
        if row["name"]:
            out.append(row)
    return out


def read_prescription(data: bytes, content_type: str, threads: int | None = None) -> list[dict] | None:
    """Medicine rows as written, or None if the model is unavailable or failed (callers fall back to OCR)."""
    if not available():
        return None
    threads = threads or max(2, (os.cpu_count() or 4) - 2)
    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / "rx.jpg"
        img.write_bytes(_prepare_image(data, content_type))
        cmd = [str(CLI), "-m", str(MODEL), "--mmproj", str(MMPROJ), "--image", str(img), "-p", PROMPT,
               "--temp", "0", "-n", "900", "-t", str(threads), "--no-warmup"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=TIMEOUT_S)
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.warning("Vision reader failed: %s", exc)
            return None
    if res.returncode != 0:
        log.warning("Vision reader exited with %s: %s", res.returncode, res.stderr[-300:])
        return None
    return _parse(res.stdout)


def as_line(row: dict) -> str:
    """One prescription line in the order the text parser expects: form name strength dose frequency timing duration."""
    duration = row["duration"]
    if duration and not re.match(r"(?i)^\s*(x|for|×)", duration):
        duration = f"x {duration}"
    parts = [row["form"], row["name"], row["strength"], row["dose"], row["frequency"], row["timing"], duration]
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()


def support_in_text(value: str, page_text: str, threshold: float = 0.6) -> float:
    """How well a value read by the model is backed by the OCR text of the same page (0..1).
    Compares against every window of OCR words of similar length, tolerating handwriting misreads."""
    v = re.sub(r"[^a-z0-9]+", "", value.lower())
    if len(v) < 3:
        return 0.0  # "1", "17": such short values appear somewhere on any page, so they can't be confirmed
    words = re.findall(r"[A-Za-z0-9]+", page_text.lower())
    best = 0.0
    for size in (1, 2, 3):
        for i in range(len(words) - size + 1):
            w = "".join(words[i:i + size])
            if abs(len(w) - len(v)) > max(3, len(v) // 2):
                continue
            best = max(best, SequenceMatcher(None, v, w).ratio())
            if best >= 0.99:
                return best
    return best
