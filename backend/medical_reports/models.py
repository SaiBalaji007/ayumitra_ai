from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import TimeStampedModel
from documents.models import DocumentPage, MedicalDocument

CONFIDENCE = [MinValueValidator(0.0), MaxValueValidator(1.0)]


class ExtractedReport(TimeStampedModel):
    """Structured content of one lab report. Populated by extraction (Phase 4–5), never typed in."""

    document = models.OneToOneField(MedicalDocument, on_delete=models.CASCADE, related_name="extracted_report")
    lab_name = models.CharField(max_length=200, blank=True)
    report_date = models.DateField(null=True, blank=True, db_index=True)
    sample_collected_at = models.DateTimeField(null=True, blank=True)
    patient_name_on_report = models.CharField(max_length=200, blank=True)
    extractor_version = models.CharField(max_length=40, blank=True, help_text="Pipeline version that produced this.")
    raw = models.JSONField(default=dict, blank=True, help_text="Unmodified extractor output, for audit/debug.")

    class Meta:
        ordering = ["-report_date", "-created_at"]

    def __str__(self):
        return f"Report for {self.document_id}"


class LabParameter(TimeStampedModel):
    """
    One test result exactly as printed, plus parsed values.
    `lab_flag` is what the LAB printed (H/L/*). It is kept separate from any AyuMitra interpretation,
    and the lab's own reference interval is always preserved verbatim in `reference_range_text`.
    """

    class LabFlag(models.TextChoices):
        NONE = "", "No flag printed"
        HIGH = "high", "High"
        LOW = "low", "Low"
        CRITICAL_HIGH = "critical_high", "Critically high"
        CRITICAL_LOW = "critical_low", "Critically low"
        ABNORMAL = "abnormal", "Abnormal"

    report = models.ForeignKey(ExtractedReport, on_delete=models.CASCADE, related_name="parameters")
    page = models.ForeignKey(DocumentPage, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    name_as_printed = models.CharField(max_length=200)
    normalized_name = models.CharField(max_length=120, blank=True, db_index=True)
    loinc_code = models.CharField(max_length=20, blank=True)
    value_text = models.CharField(max_length=100, help_text="Exactly as printed, e.g. '<0.5' or 'Positive'.")
    value_numeric = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    unit = models.CharField(max_length=40, blank=True)
    reference_range_text = models.CharField(max_length=120, blank=True)
    reference_low = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    reference_high = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    lab_flag = models.CharField(max_length=16, choices=LabFlag.choices, blank=True, default=LabFlag.NONE)
    confidence = models.FloatField(null=True, blank=True, validators=CONFIDENCE)
    user_verified = models.BooleanField(default=False)

    class Meta:
        ordering = ["report", "id"]
        indexes = [models.Index(fields=["normalized_name", "report"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(reference_low__isnull=True)
                | models.Q(reference_high__isnull=True)
                | models.Q(reference_low__lte=models.F("reference_high")),
                name="reference_low_lte_high",
            )
        ]

    def __str__(self):
        return f"{self.name_as_printed}: {self.value_text} {self.unit}"


class MedicalFinding(TimeStampedModel):
    """A non-numeric finding extracted from a document (impression, diagnosis mention, note)."""

    class Category(models.TextChoices):
        DIAGNOSIS_MENTION = "diagnosis_mention", "Diagnosis mentioned"
        IMPRESSION = "impression", "Impression"
        SYMPTOM = "symptom", "Symptom"
        PROCEDURE = "procedure", "Procedure"
        NOTE = "note", "Note"

    document = models.ForeignKey(MedicalDocument, on_delete=models.CASCADE, related_name="findings")
    page = models.ForeignKey(DocumentPage, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    category = models.CharField(max_length=24, choices=Category.choices)
    text = models.TextField(help_text="Source text span the finding was extracted from.")
    entity_label = models.CharField(max_length=60, blank=True, help_text="NER label, e.g. DISEASE.")
    normalized_concept = models.CharField(max_length=200, blank=True)
    confidence = models.FloatField(null=True, blank=True, validators=CONFIDENCE)

    class Meta:
        ordering = ["document", "id"]
        indexes = [models.Index(fields=["document", "category"])]

    def __str__(self):
        return f"{self.category}: {self.text[:40]}"
