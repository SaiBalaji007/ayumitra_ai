"""
OCR + extraction evaluation on synthetic documents with exact ground truth.

  python -m evaluation.run_ocr_eval

Per style (printed PDF, printed image, scanned image, handwritten image):
  - CER: character error rate = Levenshtein(ocr_text, truth) / len(truth), whitespace-normalised
  - lab rows:      field-level precision / recall / F1 over (test, value, unit, range) tuples
  - prescriptions: field-level precision / recall / F1 over (name, strength, frequency, timing, duration)
  - safe-failure rate: of wrong or missing fields, the share flagged for user review
Documents are synthetic and fictional (evaluation/synthetic_docs.py); no patient data is used.
"""

from __future__ import annotations

import json
import re
import random
import statistics
import time
from datetime import datetime
from pathlib import Path

from ayumitra_ai.config import SERVICE_ROOT
from ayumitra_ai.documents.extract import extract_document
from ayumitra_ai.nlp.lab_extraction import extract_lab_results
from ayumitra_ai.nlp.prescriptions import extract_prescription

from .synthetic_docs import build_dataset, render_pdf

OUT = SERVICE_ROOT / "evaluation" / "reports"
DATA = SERVICE_ROOT / "data" / "synthetic_docs"


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


def cer(pred: str, truth: str) -> float:
    t = _norm(truth)
    return levenshtein(_norm(pred), t) / max(1, len(t))


def _ws(s):
    """Whitespace-insensitive comparison key ("< 150" vs "<150"); spacing carries no meaning here."""
    return re.sub(r"\s+", "", s or "")


def prf(pred: set, truth: set) -> tuple[float, float, float]:
    tp = len(pred & truth)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(truth) if truth else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def evaluate_doc(doc, data: bytes, ctype: str, lexicon=None) -> dict:
    t0 = time.perf_counter()
    ex = extract_document(data, ctype)
    elapsed = time.perf_counter() - t0
    text = ex.text
    page = ex.pages[0] if ex.pages else None
    conf = page.confidence if page else None
    lines = text.splitlines()
    confs = [conf] * len(lines) if conf is not None else None
    res = {"id": doc.id, "kind": doc.kind, "cer": round(cer(text, doc.text), 4), "seconds": round(elapsed, 2),
           "method": page.method if page else None, "ocr_confidence": conf}
    if doc.kind == "lab_report":
        got = extract_lab_results(lines, line_confidences=confs)
        pred = {(r.name_as_printed, _ws(r.value_text), _ws(r.unit), _ws(r.reference_range_text)) for r in got}
        truth = {(r.name, _ws(r.value), _ws(r.unit), _ws(r.reference_range)) for r in doc.lab_rows}
        flagged = {(r.name_as_printed, _ws(r.value_text), _ws(r.unit), _ws(r.reference_range_text))
                   for r in got if r.needs_review}
    else:
        got = extract_prescription(lines, lexicon, confs)
        pred, flagged = set(), set()
        for it in got:
            for f in ("name_as_written", "strength", "frequency", "timing", "duration"):
                key = (it.line_number, f, _ws(getattr(it, f)))
                pred.add(key)
                review_name = "name" if f == "name_as_written" else f
                if review_name in it.fields_needing_review or (it.field_confidence.get(review_name, 1) < 0.85):
                    flagged.add(key)
        truth = set()
        for i, m in enumerate(doc.medicines, 1):
            for f, v in (("name_as_written", m.name), ("strength", m.strength), ("frequency", m.frequency),
                         ("timing", m.timing), ("duration", m.duration)):
                truth.add((i, f, _ws(v)))
    p, r, f = prf(pred, truth)
    wrong = pred - truth
    res.update({"precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3),
                "wrong_fields": len(wrong), "wrong_flagged": len(wrong & flagged),
                "missed_fields": len(truth - pred)})
    return res


def summarise(rows: list[dict]) -> dict:
    wrong = sum(r["wrong_fields"] for r in rows)
    return {
        "n": len(rows),
        "cer_mean": round(statistics.mean(r["cer"] for r in rows), 4),
        "cer_median": round(statistics.median(r["cer"] for r in rows), 4),
        "f1_mean": round(statistics.mean(r["f1"] for r in rows), 3),
        "precision_mean": round(statistics.mean(r["precision"] for r in rows), 3),
        "recall_mean": round(statistics.mean(r["recall"] for r in rows), 3),
        "wrong_fields": wrong,
        "wrong_fields_flagged_for_review": round(sum(r["wrong_flagged"] for r in rows) / wrong, 3) if wrong else None,
        "seconds_per_doc": round(statistics.mean(r["seconds"] for r in rows), 2),
    }


def main() -> int:
    from ayumitra_ai.documents.ocr import available_engines
    from ayumitra_ai.nlp.medicines import default_lexicon

    engines = [e.name for e in available_engines()]
    print("OCR engines available:", engines or "NONE")
    docs = build_dataset(DATA)
    lexicon = default_lexicon() if default_lexicon().loaded else None
    groups: dict[str, list[dict]] = {}
    for d in docs:
        png = (DATA / f"{d.id}.png").read_bytes()
        if d.style == "printed":
            groups.setdefault(f"{d.kind} / digital PDF", []).append(evaluate_doc(d, render_pdf(d), "application/pdf", lexicon))
        if engines:
            groups.setdefault(f"{d.kind} / {d.style} image", []).append(evaluate_doc(d, png, "image/png", lexicon))
    report = {"created": datetime.now().isoformat(timespec="seconds"), "ocr_engines": engines,
              "rxnorm_lexicon": bool(lexicon), "summary": {k: summarise(v) for k, v in groups.items()},
              "per_document": groups}
    print(json.dumps(report["summary"], indent=2))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"ocr_eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("report:", path)
    random.seed(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
