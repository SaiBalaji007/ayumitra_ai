import uuid
from pathlib import PurePosixPath

from django.core.files.storage import FileSystemStorage
from django.utils import timezone


class PrivateDocumentStorage(FileSystemStorage):
    """
    Filesystem storage under MEDIA_ROOT (= PRIVATE_MEDIA_ROOT) with no public URL. Files are only
    served by owner-checked API views. The location is read from settings lazily, so
    override_settings(MEDIA_ROOT=...) in tests redirects writes to a temp folder.
    """

    def url(self, name):
        raise NotImplementedError("Medical documents have no public URL. Use /api/documents/{id}/file/.")


private_storage = PrivateDocumentStorage()


def document_upload_path(instance, filename):
    """
    documents/<owner-id>/<yyyy>/<mm>/<random-uuid>.<ext>

    The original filename is never used on disk (it's kept in the database only). That rules out
    path traversal and collisions, and keeps names like "HIV_test_result.pdf" out of file paths.
    """
    ext = PurePosixPath(filename).suffix.lower()
    now = timezone.now()
    return f"documents/{instance.owner_id}/{now:%Y}/{now:%m}/{uuid.uuid4().hex}{ext}"
