import hashlib
from dataclasses import dataclass
from pathlib import PurePath

from django.conf import settings
from rest_framework.exceptions import ValidationError


@dataclass(frozen=True)
class FileKind:
    content_type: str
    extensions: tuple[str, ...]
    signature: bytes


# Detection is by file content ("magic bytes"), not the browser-supplied Content-Type,
# which a client can set to anything.
ALLOWED_KINDS = (
    FileKind("application/pdf", (".pdf",), b"%PDF-"),
    FileKind("image/png", (".png",), b"\x89PNG\r\n\x1a\n"),
    FileKind("image/jpeg", (".jpg", ".jpeg"), b"\xff\xd8\xff"),
)
ALLOWED_EXTENSIONS = sorted({e for k in ALLOWED_KINDS for e in k.extensions})


def max_upload_bytes():
    return settings.DOCUMENT_MAX_UPLOAD_MB * 1024 * 1024


def sniff(head: bytes):
    return next((k for k in ALLOWED_KINDS if head.startswith(k.signature)), None)


def validate_document_file(upload):
    """Validate an UploadedFile. Returns (content_type, sha256_hex). Raises ValidationError."""
    name = upload.name or ""
    ext = PurePath(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        shown = ext or "none"
        raise ValidationError(
            f"Unsupported file type ({shown}). Allowed: {', '.join(ALLOWED_EXTENSIONS)}.",
            code="unsupported_file_type",
        )
    if upload.size == 0:
        raise ValidationError("The file is empty.", code="empty_file")
    if upload.size > max_upload_bytes():
        raise ValidationError(
            f"File is too large ({upload.size / 1_048_576:.1f} MB). "
            f"Maximum is {settings.DOCUMENT_MAX_UPLOAD_MB} MB.",
            code="file_too_large",
        )

    upload.seek(0)
    kind = sniff(upload.read(16))
    if kind is None:
        raise ValidationError("File content is not a valid PDF, PNG or JPEG.", code="invalid_file_content")
    if ext not in kind.extensions:
        raise ValidationError(
            f"File extension {ext} does not match its content ({kind.content_type}).",
            code="extension_mismatch",
        )

    digest = hashlib.sha256()
    upload.seek(0)
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return kind.content_type, digest.hexdigest()
