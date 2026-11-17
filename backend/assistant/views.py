from django.shortcuts import get_object_or_404
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.ai_client import AIServiceError, run_agent
from medical_reports.logic import parameter_context
from medical_reports.models import ExtractedReport

from .models import ChatMessage, Conversation


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ["id", "role", "content", "status", "citations", "safety", "created_at"]


class ConversationSerializer(serializers.ModelSerializer):
    messages = ChatMessageSerializer(many=True, read_only=True)
    report_id = serializers.IntegerField(source="report.id", read_only=True, default=None)

    class Meta:
        model = Conversation
        fields = ["id", "title", "report_id", "created_at", "updated_at", "messages"]


class ConversationListSerializer(serializers.ModelSerializer):
    report_id = serializers.IntegerField(source="report.id", read_only=True, default=None)

    class Meta:
        model = Conversation
        fields = ["id", "title", "report_id", "created_at", "updated_at"]


class ConversationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin,
                          viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Conversation.objects.filter(owner=self.request.user).prefetch_related("messages")

    def get_serializer_class(self):
        return ConversationListSerializer if self.action == "list" else ConversationSerializer


class AskSerializer(serializers.Serializer):
    question = serializers.CharField(min_length=3, max_length=1000, trim_whitespace=True)
    conversation_id = serializers.UUIDField(required=False)
    report_id = serializers.IntegerField(required=False)


def _assistant_text(result: dict) -> tuple[str, str, list, dict]:
    ans = result.get("answer") or {}
    messages = result.get("messages") or []
    safety = ans.get("safety") or result.get("safety") or {}
    if ans:
        parts = [ans.get("answer", "")] + [m for m in messages if m not in ans.get("answer", "")]
        return "\n\n".join(p for p in parts if p), ans.get("status", ""), ans.get("citations", []), safety
    return "\n\n".join(messages), result.get("intent", ""), [], safety


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ask(request):
    """
    POST /api/assistant/ask/ {question, conversation_id?, report_id?}
    Grounded answer from the AI service; the exchange is stored in the user's conversation.
    With report_id, the user's own results from that report steer retrieval (report-specific chat).
    """
    ser = AskSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data
    user = request.user

    report = None
    if "report_id" in data:
        report = get_object_or_404(ExtractedReport, pk=data["report_id"], document__owner=user)
    if "conversation_id" in data:
        convo = get_object_or_404(Conversation, pk=data["conversation_id"], owner=user)
        report = report or convo.report
    else:
        convo = Conversation.objects.create(owner=user, title=data["question"][:120], report=report)

    payload = {"question": data["question"]}
    if "conversation_id" in data:
        # Follow-ups ("what foods contain it?") are understood using the previous question of this
        # conversation. Only the user's own earlier question is sent, never other users' data.
        prev = convo.messages.filter(role=ChatMessage.Role.USER).order_by("-created_at").first()
        if prev is not None:
            payload["previous_question"] = prev.content[:1000]
    if report is not None:
        payload["report_results"] = [parameter_context(p) for p in report.parameters.all()]

    ChatMessage.objects.create(conversation=convo, role=ChatMessage.Role.USER, content=data["question"])
    try:
        result = run_agent(payload)
    except AIServiceError:
        msg = ChatMessage.objects.create(conversation=convo, role=ChatMessage.Role.ASSISTANT, status="error",
                                         content="The AI assistant is unavailable right now. Please try again later.")
        return Response({"detail": msg.content, "code": "ai_unavailable", "conversation_id": str(convo.id),
                         "message": ChatMessageSerializer(msg).data}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    content, status_text, citations, safety = _assistant_text(result)
    msg = ChatMessage.objects.create(conversation=convo, role=ChatMessage.Role.ASSISTANT, content=content or "-",
                                     status=status_text, citations=citations, safety=safety,
                                     payload={k: result.get(k) for k in ("intent", "answer", "trace")})
    convo.save(update_fields=["updated_at"])
    return Response({"conversation_id": str(convo.id), "message": ChatMessageSerializer(msg).data,
                     "intent": result.get("intent")}, status=status.HTTP_201_CREATED)


# Rate-limited by the default ScopedRateThrottle ("assistant" scope in settings).
ask.cls.throttle_scope = "assistant"
