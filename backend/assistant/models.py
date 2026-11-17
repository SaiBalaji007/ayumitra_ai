import uuid

from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class Conversation(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations")
    title = models.CharField(max_length=200, blank=True)
    # Optional: a conversation about one of the user's own reports (report-specific chat).
    report = models.ForeignKey("medical_reports.ExtractedReport", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="conversations")

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "-updated_at"])]

    def __str__(self):
        return self.title or str(self.id)


class ChatMessage(TimeStampedModel):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    status = models.CharField(max_length=30, blank=True, help_text="answered / insufficient_evidence / error ...")
    citations = models.JSONField(default=list, blank=True)
    safety = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True, help_text="Full structured AI response, for audit.")

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.content[:40]}"
