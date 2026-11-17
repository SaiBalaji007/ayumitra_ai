from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "documents"

    def ready(self):
        from django.conf import settings

        from . import signals  # noqa: F401

        if settings.DOCUMENT_PROCESSING_ENABLED:
            from .tasks import register_default_pipeline

            register_default_pipeline()
