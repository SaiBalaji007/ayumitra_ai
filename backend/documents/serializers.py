from django.urls import reverse
from rest_framework import serializers

from .models import MedicalDocument, ProcessingTask
from .validators import validate_document_file


class ProcessingTaskSerializer(serializers.ModelSerializer):
    task_type_display = serializers.CharField(source="get_task_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ProcessingTask
        fields = [
            "id", "task_type", "task_type_display", "status", "status_display",
            "progress", "message", "started_at", "finished_at", "created_at",
        ]  # `error` holds internal exception text and stays server-side (admin/logs only)


class MedicalDocumentSerializer(serializers.ModelSerializer):
    """Read/update representation. The storage path is never exposed; `file_url` is the
    owner-checked API endpoint, not a public URL."""

    document_type_display = serializers.CharField(source="get_document_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = MedicalDocument
        fields = [
            "id", "original_filename", "title", "content_type", "file_size",
            "document_type", "document_type_display", "status", "status_display",
            "page_count", "document_date", "error_message", "file_url", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "original_filename", "content_type", "file_size", "status",
            "page_count", "error_message", "created_at", "updated_at",
        ]

    def get_file_url(self, obj):
        return reverse("document-file", kwargs={"pk": obj.pk})


class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField(allow_empty_file=True)  # empty files get a clearer message below
    document_type = serializers.ChoiceField(
        choices=MedicalDocument.DocumentType.choices, default=MedicalDocument.DocumentType.UNKNOWN
    )
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_file(self, upload):
        content_type, sha256 = validate_document_file(upload)
        self.context["content_type"] = content_type
        self.context["sha256"] = sha256
        return upload

    def create(self, validated_data):
        upload = validated_data["file"]
        original = (upload.name or "document").replace("\\", "/").rsplit("/", 1)[-1][:255]
        return MedicalDocument.objects.create(
            owner=self.context["request"].user,
            file=upload,
            original_filename=original,
            content_type=self.context["content_type"],
            file_size=upload.size,
            sha256=self.context["sha256"],
            document_type=validated_data["document_type"],
            title=validated_data.get("title", ""),
        )


class DocumentStatusSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    tasks = ProcessingTaskSerializer(many=True, read_only=True)
    processing_enabled = serializers.SerializerMethodField()

    class Meta:
        model = MedicalDocument
        fields = ["id", "status", "status_display", "error_message", "page_count", "processing_enabled", "tasks", "updated_at"]

    def get_processing_enabled(self, obj):
        from django.conf import settings

        return settings.DOCUMENT_PROCESSING_ENABLED
