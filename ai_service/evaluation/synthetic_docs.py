"""
Synthetic medical documents for OCR and NLP evaluation, with exact ground truth.

Everything here is FICTIONAL: patient names, IDs, lab names and doctors are invented. Lab values
are generated within plain numeric ranges to exercise parsing only; they are not medical claims,
and each report prints its own reference interval, as real labs do. Medicine names are
common generics used only as strings to test recognition. No real patient data is ever used.
"""

from __future__ import annotations

import io
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

FONTS = Path("C:/Windows/Fonts")
PRINT_FONTS = ["arial.ttf", "times.ttf", "consola.ttf"]
HAND_FONTS = ["Inkfree.ttf", "segoepr.ttf", "segoesc.ttf"]

LAB_TESTS = [  # (printed name, unit, low, high, decimals)
    ("Haemoglobin", "g/dL", 12.0, 15.5, 1),
    ("Total WBC Count", "cells/cumm", 4000, 11000, 0),
    ("Platelet Count", "lakhs/cumm", 1.5, 4.5, 2),
    ("Fasting Blood Sugar", "mg/dL", 70, 100, 0),
    ("HbA1c", "%", 4.0, 5.6, 1),
    ("Serum Creatinine", "mg/dL", 0.6, 1.2, 2),
    ("Total Cholesterol", "mg/dL", 0, 200, 0),
    ("Triglycerides", "mg/dL", 0, 150, 0),
    ("SGPT (ALT)", "U/L", 7, 56, 0),
    ("TSH", "mIU/L", 0.4, 4.0, 2),
    ("Vitamin D (25-OH)", "ng/mL", 30, 100, 1),
    ("Uric Acid", "mg/dL", 3.5, 7.2, 1),
]

MEDICINES = [  # (name as printed, strength, form) — generic names used as test strings only
    ("Metformin", "500 mg", "Tab"), ("Amlodipine", "5 mg", "Tab"), ("Atorvastatin", "10 mg", "Tab"),
    ("Paracetamol", "650 mg", "Tab"), ("Pantoprazole", "40 mg", "Tab"), ("Cetirizine", "10 mg", "Tab"),
    ("Amoxicillin", "500 mg", "Cap"), ("Vitamin D3", "60000 IU", "Cap"), ("Levothyroxine", "50 mcg", "Tab"),
]
FREQUENCIES = ["1-0-1", "1-0-0", "0-0-1", "1-1-1", "OD", "BD", "TDS", "HS"]
TIMINGS = ["after food", "before food", "at bedtime", "empty stomach"]
DURATIONS = ["5 days", "7 days", "10 days", "1 month", "3 months"]


@dataclass
class LabRow:
    name: str
    value: str
    unit: str
    reference_range: str
    flag: str  # "", "H" or "L" exactly as printed


@dataclass
class MedLine:
    form: str
    name: str
    strength: str
    frequency: str
    timing: str
    duration: str


@dataclass
class SyntheticDoc:
    id: str
    kind: str  # lab_report | prescription
    style: str  # printed | scanned | handwritten
    text: str
    lab_rows: list[LabRow] = field(default_factory=list)
    medicines: list[MedLine] = field(default_factory=list)


def _fmt(v: float, d: int) -> str:
    return f"{v:.{d}f}" if d else str(int(round(v)))


def make_lab_report(rng: random.Random, doc_id: str, style: str = "printed") -> SyntheticDoc:
    rows = []
    for name, unit, lo, hi, d in rng.sample(LAB_TESTS, 7):
        span = hi - lo
        r = rng.random()
        v = lo - span * rng.uniform(0.05, 0.3) if r < 0.2 and lo > 0 else hi + span * rng.uniform(0.05, 0.4) if r > 0.8 else rng.uniform(lo, hi)
        v = max(v, 0.1)
        flag = "H" if v > hi else "L" if v < lo else ""
        ref = f"< {_fmt(hi, d)}" if lo == 0 else f"{_fmt(lo, d)} - {_fmt(hi, d)}"
        rows.append(LabRow(name, _fmt(v, d), unit, ref, flag))
    header = [
        "SUNRISE DIAGNOSTICS (FICTIONAL TEST LAB)",
        f"Patient: Test Patient {rng.randint(100, 999)}    Age/Sex: {rng.randint(20, 80)} Y / {rng.choice('MF')}",
        f"Lab No: SD{rng.randint(10000, 99999)}    Sample: Blood    Reported on: 1{rng.randint(0, 9)}/0{rng.randint(1, 9)}/2026",
        "Test Name    Result    Units    Biological Reference Interval",
    ]
    body = [f"{r.name}    {r.value} {r.flag}".rstrip() + f"    {r.unit}    {r.reference_range}" for r in rows]
    footer = ["Reference ranges are those of this laboratory.", "Pathologist: Dr. Fictional Signature"]
    return SyntheticDoc(doc_id, "lab_report", style, "\n".join(header + body + footer), lab_rows=rows)


def make_prescription(rng: random.Random, doc_id: str, style: str = "printed") -> SyntheticDoc:
    meds = [MedLine(form, name, strength, rng.choice(FREQUENCIES), rng.choice(TIMINGS), rng.choice(DURATIONS))
            for name, strength, form in rng.sample(MEDICINES, rng.randint(2, 4))]
    header = ["Dr. Test Physician, MBBS, MD (FICTIONAL)", f"Reg. No: TEST/{rng.randint(1000, 9999)}",
              f"Patient: Test Patient {rng.randint(100, 999)}   Date: 0{rng.randint(1, 9)}/11/2026", "Rx"]
    body = [f"{i}. {m.form}. {m.name} {m.strength}  {m.frequency}  {m.timing}  x {m.duration}" for i, m in enumerate(meds, 1)]
    return SyntheticDoc(doc_id, "prescription", style, "\n".join(header + body + ["Signature"]), medicines=meds)


def render(doc: SyntheticDoc, rng: random.Random) -> bytes:
    """Render to PNG. 'scanned' adds blur, noise and slight rotation; 'handwritten' uses script fonts."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    font_file = rng.choice(HAND_FONTS if doc.style == "handwritten" else PRINT_FONTS)
    size = 30 if doc.style == "handwritten" else 26
    font = ImageFont.truetype(str(FONTS / font_file), size)
    lines = doc.text.splitlines()
    width = 1700
    img = Image.new("RGB", (width, 120 + len(lines) * int(size * 1.9)), "white")
    draw = ImageDraw.Draw(img)
    y = 60
    for line in lines:
        x = 60 + (rng.randint(-6, 6) if doc.style == "handwritten" else 0)
        draw.text((x, y), line, fill=(20, 20, 30), font=font)
        y += int(size * 1.9)
    if doc.style in ("scanned", "handwritten"):
        img = img.rotate(rng.uniform(-1.5, 1.5), expand=True, fillcolor="white")
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 0.9)))
        import numpy as np

        arr = np.asarray(img).astype(np.int16)
        arr += np.random.default_rng(rng.randint(0, 10**6)).normal(0, 9, arr.shape).astype(np.int16)
        img = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def render_pdf(doc: SyntheticDoc) -> bytes:
    """A digital (text-layer) PDF of the document."""
    import fitz

    pdf = fitz.open()
    page = pdf.new_page()
    y = 60
    for line in doc.text.splitlines():
        page.insert_text((40, y), line, fontsize=9.5, fontname="helv")
        y += 16
    return pdf.tobytes()


def build_dataset(out_dir: Path, seed: int = 2026) -> list[SyntheticDoc]:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    docs = []
    for style in ("printed", "scanned"):
        for i in range(6):
            docs.append(make_lab_report(rng, f"lab-{style}-{i}", style))
    for style in ("printed", "scanned", "handwritten"):
        for i in range(6):
            docs.append(make_prescription(rng, f"rx-{style}-{i}", style))
    for d in docs:
        (out_dir / f"{d.id}.png").write_bytes(render(d, rng))
        if d.style == "printed":
            (out_dir / f"{d.id}.pdf").write_bytes(render_pdf(d))
    (out_dir / "ground_truth.json").write_text(json.dumps([asdict(d) for d in docs], indent=2), encoding="utf-8")
    return docs
