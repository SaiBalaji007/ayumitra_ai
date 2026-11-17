from django.db import transaction
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from core.audit import audit
from core.models import AuditLog

from .serializers import (
    AccountDeleteSerializer,
    EmailTokenObtainPairSerializer,
    PasswordChangeSerializer,
    RegisterSerializer,
    UserUpdateSerializer,
)


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "auth"

    def perform_create(self, serializer):
        user = serializer.save()
        audit(self.request, AuditLog.Action.REGISTER, user)


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """Login (case-insensitive email), rate-limited per client to slow password guessing."""

    serializer_class = EmailTokenObtainPairSerializer
    throttle_scope = "auth"


class MeView(generics.RetrieveUpdateAPIView):
    """GET / PATCH (name only) / DELETE (password required) on the requesting user's own account."""

    serializer_class = UserUpdateSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_object(self):
        return self.request.user

    def delete(self, request, *args, **kwargs):
        ser = AccountDeleteSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        user = request.user
        with transaction.atomic():
            # Logged before deletion; the FK becomes NULL but the event (and user id) remain.
            audit(request, AuditLog.Action.ACCOUNT_DELETE, user)
            user.delete()  # cascades to profile, documents (files removed by signal), reports, chats
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    def post(self, request):
        ser = PasswordChangeSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        request.user.set_password(ser.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        audit(request, AuditLog.Action.PASSWORD_CHANGE, request.user)
        return Response({"detail": "Password changed."})
