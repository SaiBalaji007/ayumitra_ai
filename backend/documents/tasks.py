"""
Background processing foundation.

`process_document` runs each step registered in `PIPELINE` in order, mirroring progress into
ProcessingTask rows so the UI can show live status. Phase 3 registers no steps; Phase 4 adds
text extraction and OCR, and Phase 5 adds medical NLP. A step is a plain function
`step(document, report_progress)` and must raise on failure; it must never fabricate output.
"""

import logging
from collections.abc import Callable

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import MedicalDocument, ProcessingTask

logger = logging.getLogger(__name__)

Step = Callable[[MedicalDocument, Callable[[int, str], None]], None]

# (task_type, step function). Filled by later phases.
PIPELINE: list[tuple[str, Step]] = []


def enqueue_document_processing(document: MedicalDocument) -> ProcessingTask:
    """Create the tracking row and enqueue the job once the upload transaction commits."""
    task = ProcessingTask.objects.create(document=document, task_type=ProcessingTask.TaskType.INGEST)
    document.status = MedicalDocument.Status.QUEUED
    document.save(update_fields=["status", "updated_at"])

    def _send():
        result = process_document.delay(str(task.id))
        ProcessingTask.objects.filter(pk=task.pk).update(celery_task_id=result.id or "")

    transaction.on_commit(_send)
    return task


def _mark(task, **fields):
    for k, v in fields.items():
        setattr(task, k, v)
    task.save(update_fields=[*fields, "updated_at"])


@shared_task(bind=True, acks_late=True, max_retries=0)
def process_document(self, task_id: str):
    try:
        task = ProcessingTask.objects.select_related("document").get(pk=task_id)
    except ProcessingTask.DoesNotExist:
        logger.info("Task %s no longer exists (document deleted?), skipping.", task_id)
        return
    document = task.document

    _mark(task, status=ProcessingTask.Status.RUNNING, started_at=timezone.now(), progress=0)
    document.status = MedicalDocument.Status.PROCESSING
    document.save(update_fields=["status", "updated_at"])

    try:
        steps = list(PIPELINE)
        for index, (step_type, step) in enumerate(steps):
            sub = ProcessingTask.objects.create(
                document=document, task_type=step_type, status=ProcessingTask.Status.RUNNING, started_at=timezone.now()
            )

            def report(pct: int, message: str = "", _sub=sub, _i=index):
                _mark(_sub, progress=max(0, min(100, pct)), message=message[:255])
                overall = int(((_i + pct / 100) / len(steps)) * 100)
                _mark(task, progress=overall, message=message[:255])

            try:
                step(document, report)
            except Exception as exc:
                _mark(sub, status=ProcessingTask.Status.FAILED, error=str(exc)[:2000], finished_at=timezone.now())
                raise
            _mark(sub, status=ProcessingTask.Status.SUCCEEDED, progress=100, finished_at=timezone.now())

        if steps:
            _mark(task, status=ProcessingTask.Status.SUCCEEDED, progress=100, finished_at=timezone.now(), message="")
            document.status = MedicalDocument.Status.COMPLETED
        else:
            # Nothing to run yet: say so plainly instead of reporting a fake "processed" state.
            _mark(
                task, status=ProcessingTask.Status.SUCCEEDED, progress=100, finished_at=timezone.now(),
                message="No processing steps are configured yet.",
            )
            document.status = MedicalDocument.Status.UPLOADED
        document.error_message = ""
        document.save(update_fields=["status", "error_message", "updated_at"])
    except Exception as exc:
        logger.exception("Processing failed for document %s", document.pk)
        _mark(task, status=ProcessingTask.Status.FAILED, error=str(exc)[:2000], finished_at=timezone.now())
        document.status = MedicalDocument.Status.FAILED
        document.error_message = "Processing failed. You can retry or delete this document."
        document.save(update_fields=["status", "error_message", "updated_at"])
