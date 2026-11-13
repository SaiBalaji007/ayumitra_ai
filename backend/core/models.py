import uuid

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuditLog(models.Model):
    """Append-only record of security-relevant events (uploads, reads, deletions, auth)."""

    class Action(models.TextChoices):
        REGISTER = "register", "Account registered"
        DOCUMENT_UPLOAD = "document.upload", "Document uploaded"
        DOCUMENT_VIEW = "document.view", "Document file accessed"
        DOCUMENT_DELETE = "document.delete", "Document deleted"
        PROFILE_UPDATE = "profile.update", "Patient profile updated"
        ACCESS_DENIED = "access.denied", "Access denied"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_logs"
    )
    action = models.CharField(max_length=40, choices=Action.choices)
    resource_type = models.CharField(max_length=60, blank=True)
    resource_id = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["resource_type", "resource_id"]),
        ]

    def __str__(self):
        return f"{self.action} by {self.user_id} at {self.created_at:%Y-%m-%d %H:%M}"
