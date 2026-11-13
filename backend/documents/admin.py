from django.contrib import admin

from .models import DocumentPage, MedicalDocument, ProcessingTask


class ProcessingTaskInline(admin.TabularInline):
    model = ProcessingTask
    extra = 0
    readonly_fields = ("task_type", "status", "progress", "message", "error", "started_at", "finished_at")


@admin.register(MedicalDocument)
class MedicalDocumentAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "owner", "document_type", "status", "file_size", "created_at")
    list_filter = ("document_type", "status")
    search_fields = ("original_filename", "owner__email", "sha256")
    readonly_fields = ("id", "owner", "file", "sha256", "file_size", "content_type", "created_at", "updated_at")
    inlines = [ProcessingTaskInline]


admin.site.register(DocumentPage)
