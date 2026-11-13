import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import TimeStampedModel

from .storage import document_upload_path, private_storage


class MedicalDocument(TimeStampedModel):
    class DocumentType(models.TextChoices):
        LAB_REPORT = "lab_report", "Lab report"
        PRESCRIPTION = "prescription", "Prescription"
        DISCHARGE_SUMMARY = "discharge_summary", "Discharge summary"
        IMAGING_REPORT = "imaging_report", "Imaging report"
        OTHER = "other", "Other"
        UNKNOWN = "unknown", "Not yet classified"

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        QUEUED = "queued", "Queued for processing"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Processed"
        FAILED = "failed", "Processing failed"

    # UUIDs in URLs: ids can't be enumerated or used to count other users' documents.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documents")
    file = models.FileField(upload_to=document_upload_path, storage=private_storage, max_length=255)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=50)
    file_size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64, db_index=True)
    document_type = models.CharField(max_length=24, choices=DocumentType.choices, default=DocumentType.UNKNOWN)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UPLOADED)
    page_count = models.PositiveIntegerField(null=True, blank=True)
    title = models.CharField(max_length=200, blank=True)
    document_date = models.DateField(null=True, blank=True, help_text="Date printed on the document, if known.")
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "-created_at"]),
            models.Index(fields=["owner", "document_type"]),
            models.Index(fields=["owner", "status"]),
        ]

    def __str__(self):
        return f"{self.original_filename} ({self.get_document_type_display()})"


class DocumentPage(TimeStampedModel):
    """Per-page extraction output (text and OCR confidence). Filled in Phase 4."""

    class Method(models.TextChoices):
        TEXT_LAYER = "text_layer", "Embedded PDF text"
        OCR_PADDLE = "ocr_paddle", "PaddleOCR"
        OCR_TESSERACT = "ocr_tesseract", "Tesseract"

    document = models.ForeignKey(MedicalDocument, on_delete=models.CASCADE, related_name="pages")
    page_number = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    text = models.TextField(blank=True)
    extraction_method = models.CharField(max_length=20, choices=Method.choices, blank=True)
    ocr_confidence = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )
    layout = models.JSONField(default=dict, blank=True, help_text="Blocks and tables with bounding boxes.")

    class Meta:
        ordering = ["document", "page_number"]
        constraints = [models.UniqueConstraint(fields=["document", "page_number"], name="unique_page_per_document")]

    def __str__(self):
        return f"Page {self.page_number} of {self.document_id}"


class ProcessingTask(TimeStampedModel):
    """One background job against a document. Mirrors Celery state in the database for the UI."""

    class TaskType(models.TextChoices):
        INGEST = "ingest", "Document ingestion"
        OCR = "ocr", "Text extraction / OCR"
        CLASSIFY = "classify", "Document classification"
        NLP = "nlp", "Medical entity extraction"
        REPORT_ANALYSIS = "report_analysis", "Report analysis"
        PRESCRIPTION_EXTRACTION = "prescription_extraction", "Prescription extraction"
        RAG = "rag", "Evidence retrieval"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(MedicalDocument, on_delete=models.CASCADE, related_name="tasks")
    task_type = models.CharField(max_length=32, choices=TaskType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    celery_task_id = models.CharField(max_length=64, blank=True, db_index=True)
    progress = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(100)])
    message = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["document", "task_type"]), models.Index(fields=["status"])]

    def __str__(self):
        return f"{self.task_type} [{self.status}] for {self.document_id}"
