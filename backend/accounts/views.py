from rest_framework import generics
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView

from core.audit import audit
from core.models import AuditLog

from .serializers import RegisterSerializer, UserSerializer


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "auth"

    def perform_create(self, serializer):
        user = serializer.save()
        audit(self.request, AuditLog.Action.REGISTER, user)


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """Login, rate-limited per client to slow password guessing."""

    throttle_scope = "auth"


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user
