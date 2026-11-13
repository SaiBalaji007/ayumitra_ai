from django.conf import settings
from django.db import transaction
from django.http import FileResponse
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.audit import audit
from core.models import AuditLog
from core.permissions import IsOwner

from .models import MedicalDocument
from .serializers import DocumentStatusSerializer, DocumentUploadSerializer, MedicalDocumentSerializer
from .tasks import enqueue_document_processing
from .validators import max_upload_bytes


class PayloadTooLarge(APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_code = "file_too_large"


class DocumentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    /api/documents/                GET     list own documents (?document_type=&status=)
    /api/documents/upload/         POST    multipart upload (file, document_type?, title?)
    /api/documents/{id}/           GET     detail · PATCH title/type/date · DELETE
    /api/documents/{id}/status/    GET     processing status and task history
    /api/documents/{id}/file/      GET     the file itself, owner only, never cached
    """

    serializer_class = MedicalDocumentSerializer
    permission_classes = [IsAuthenticated, IsOwner]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        # Isolation boundary: every lookup is restricted to the requesting user's rows, so other
        # users' documents are a 404, indistinguishable from "doesn't exist".
        qs = MedicalDocument.objects.filter(owner=self.request.user)
        if self.action == "list":
            params = self.request.query_params
            if t := params.get("document_type"):
                qs = qs.filter(document_type=t)
            if s := params.get("status"):
                qs = qs.filter(status=s)
        if self.action == "status":
            qs = qs.prefetch_related("tasks")
        return qs

    def get_throttles(self):
        self.throttle_scope = "uploads" if self.action == "upload" else None
        return super().get_throttles()

    @action(detail=False, methods=["post"], url_path="upload")
    def upload(self, request):
        # Reject oversized bodies before parsing the multipart stream into a temp file.
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
        if declared > max_upload_bytes() + 1024 * 1024:
            raise PayloadTooLarge(f"File is too large. Maximum is {settings.DOCUMENT_MAX_UPLOAD_MB} MB.")

        serializer = DocumentUploadSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        duplicate = MedicalDocument.objects.filter(owner=request.user, sha256=serializer.context["sha256"]).first()
        if duplicate:
            return Response(
                {
                    "detail": "You have already uploaded this file.",
                    "code": "duplicate_document",
                    "duplicate_of": str(duplicate.pk),
                },
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            document = serializer.save()
            audit(request, AuditLog.Action.DOCUMENT_UPLOAD, document, size=document.file_size, type=document.content_type)
            if settings.DOCUMENT_PROCESSING_ENABLED:
                enqueue_document_processing(document)

        document.refresh_from_db()
        return Response(MedicalDocumentSerializer(document).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def status(self, request, pk=None):
        return Response(DocumentStatusSerializer(self.get_object()).data)

    @action(detail=True, methods=["get"], url_path="file")
    def file(self, request, pk=None):
        document = self.get_object()
        audit(request, AuditLog.Action.DOCUMENT_VIEW, document)
        response = FileResponse(
            document.file.open("rb"),
            content_type=document.content_type,
            as_attachment=request.query_params.get("download") == "1",
            filename=document.original_filename,
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "sandbox; default-src 'none'"
        return response

    def perform_destroy(self, instance):
        audit(self.request, AuditLog.Action.DOCUMENT_DELETE, instance, size=instance.file_size)
        instance.delete()  # the post_delete signal removes the stored file after commit
