"""
Database-backed document worker (DOCUMENT_QUEUE_BACKEND = "db").

  python manage.py process_documents            run forever, polling every few seconds
  python manage.py process_documents --once     process what's pending, then exit

Jobs are claimed atomically (pending -> running with a conditional UPDATE), so two workers never
process the same document. No Redis needed, which suits local Windows development with SQLite.
"""

import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from documents.models import ProcessingTask
from documents.tasks import process_document, register_default_pipeline


class Command(BaseCommand):
    help = "Process queued medical documents (OCR, classification, extraction)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=3.0)

    def claim_next(self):
        candidate = (ProcessingTask.objects.filter(task_type=ProcessingTask.TaskType.INGEST,
                                                   status=ProcessingTask.Status.PENDING)
                     .order_by("created_at").values_list("pk", flat=True).first())
        if candidate is None:
            return None
        # Conditional update = atomic claim; another worker that raced us updates 0 rows.
        claimed = ProcessingTask.objects.filter(pk=candidate, status=ProcessingTask.Status.PENDING).update(
            status=ProcessingTask.Status.RUNNING, started_at=timezone.now(), celery_task_id="db-worker")
        return candidate if claimed else False

    def handle(self, *args, once=False, interval=3.0, **options):
        register_default_pipeline()
        self.stdout.write("Document worker started (db queue).")
        while True:
            task_id = self.claim_next()
            if task_id is None:
                if once:
                    return
                time.sleep(interval)
                continue
            if task_id is False:
                continue
            self.stdout.write(f"Processing task {task_id}")
            process_document(str(task_id))  # runs synchronously in this worker process
