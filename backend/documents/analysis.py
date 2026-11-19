"""
Pipeline step: send one document to the AI service, store what comes back.

Stored rows, all owned through the document (so per-user isolation applies automatically):
  DocumentPage            text, method, OCR confidence and layout per page
  ExtractedReport         + LabParameter rows (values, units and ranges exactly as printed)
  Prescription            + PrescriptionMedicine rows (as written; uncertain fields flagged)
Re-running replaces previous extraction output for the document. Nothing here calls the LLM.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction

from core.ai_client import analyze_document
from medical_reports.models import ExtractedReport, LabParameter
from prescriptions.models import Prescription, PrescriptionMedicine

from .models import DocumentPage, MedicalDocument

METHOD_MAP = {"text_layer": "text_layer", "ocr_paddle": "ocr_paddle", "ocr_tesseract": "ocr_tesseract"}
FLAG_MAP = {"high": "high", "low": "low", "critical_high": "critical_high", "critical_low": "critical_low",
            "abnormal": "abnormal", "": ""}


def _dec(v):
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    # LabParameter decimals are max_digits=14, decimal_places=4: anything larger can't be stored and
    # would make every later read of the report fail. Keep the printed text, drop the number.
    if not d.is_finite() or abs(d) >= Decimal("1e10"):
        return None
    return d


def analyze_step(document: MedicalDocument, report) -> None:
    report(5, "Reading document")
    with document.file.open("rb") as fh:
        data = fh.read()
    report(15, "Extracting text")
    chosen = document.document_type if document.document_type in (
        MedicalDocument.DocumentType.LAB_REPORT, MedicalDocument.DocumentType.PRESCRIPTION) else ""
    result = analyze_document(data, document.content_type, chosen)
    report(70, "Saving results")
    _store(document, result)
    report(100, "Done")


@transaction.atomic
def _store(document: MedicalDocument, result: dict) -> None:
    ex = result["extraction"]
    cls = result["classification"]

    document.pages.all().delete()
    for p in ex["pages"]:
        conf = p.get("confidence")
        DocumentPage.objects.create(
            document=document, page_number=p["page_number"], text=p["text"],
            extraction_method=METHOD_MAP.get(p["method"], ""),
            ocr_confidence=None if conf is None else max(0.0, min(1.0, float(conf))),
            layout={"lines": p.get("lines", [])[:2000], "tables": p.get("tables", []),
                    "width": p.get("width"), "height": p.get("height")},
        )
    document.page_count = len(ex["pages"])
    suggested = cls["document_type"] if cls["document_type"] in MedicalDocument.DocumentType.values else "other"
    document.suggested_type = suggested
    document.classification_confidence = cls["confidence"]
    if document.document_type == MedicalDocument.DocumentType.UNKNOWN and suggested != "other":
        document.document_type = suggested  # only fills an unknown type; a user's choice always wins
    document.save(update_fields=["page_count", "suggested_type", "classification_confidence", "document_type", "updated_at"])

    pages = {pg.page_number: pg for pg in document.pages.all()}
    meta = {"classification": cls, "warnings": ex.get("warnings", []), "versions": result.get("versions", {})}

    ExtractedReport.objects.filter(document=document).delete()
    if result.get("lab_results"):
        rep = ExtractedReport.objects.create(document=document, extractor_version=str(result.get("versions", {})), raw=meta)
        typical = {}  # parameter id -> cited typical ranges, for results whose report printed no range
        for r in result["lab_results"]:
            lo, hi = _dec(r.get("reference_low")), _dec(r.get("reference_high"))
            if lo is not None and hi is not None and lo > hi:  # never store an impossible range
                lo = hi = None
            lp = LabParameter.objects.create(
                report=rep, page=pages.get(r.get("page")), name_as_printed=r["name_as_printed"][:200],
                normalized_name=r.get("normalized_name", "")[:120], value_text=r["value_text"][:100],
                value_numeric=_dec(r.get("value_numeric")), unit=(r.get("unit") or "")[:40],
                reference_range_text=(r.get("reference_range_text") or "")[:120], reference_low=lo, reference_high=hi,
                lab_flag=FLAG_MAP.get(r.get("lab_flag", ""), ""), confidence=r.get("confidence"),
            )
            if r.get("typical_ranges"):
                typical[str(lp.pk)] = r["typical_ranges"]
        if typical:
            rep.raw = {**meta, "typical_ranges": typical}
            rep.save(update_fields=["raw", "updated_at"])

    Prescription.objects.filter(document=document).delete()
    if result.get("prescription_items"):
        rx = Prescription.objects.create(document=document, raw=meta)
        for it in result["prescription_items"]:
            med = it.get("medicine") or {}
            exact = str(med.get("status", "")).startswith("exact")
            PrescriptionMedicine.objects.create(
                prescription=rx, line_number=it["line_number"], name_as_written=it["name_as_written"][:200] or "(unreadable)",
                generic_name=(med.get("generic_name") or "")[:200] if exact else "",
                rxnorm_cui=(med.get("rxcui") or "")[:20] if exact else "",
                strength=it.get("strength", "")[:60], dosage_form=it.get("dosage_form", "")[:60],
                frequency=it.get("frequency", "")[:80], timing=it.get("timing", "")[:80],
                duration=it.get("duration", "")[:60], route=it.get("route", "")[:40],
                field_confidence={**it.get("field_confidence", {}), "suggestions": med.get("suggestions", []),
                                  "match_status": med.get("status", ""), "frequency_reading": it.get("frequency_reading", ""),
                                  "read_by": it.get("read_by", "ocr")},
                overall_confidence=it.get("overall_confidence"), fields_needing_review=it.get("fields_needing_review", []),
            )
