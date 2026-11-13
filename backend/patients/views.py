from rest_framework import generics

from core.audit import audit
from core.models import AuditLog

from .models import PatientProfile
from .serializers import PatientProfileSerializer


class MyProfileView(generics.RetrieveUpdateAPIView):
    """The requesting user's own profile. There is no endpoint that takes another user's id."""

    serializer_class = PatientProfileSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        profile, _ = PatientProfile.objects.get_or_create(user=self.request.user)
        return profile

    def perform_update(self, serializer):
        serializer.save()
        audit(self.request, AuditLog.Action.PROFILE_UPDATE, serializer.instance, fields=sorted(serializer.validated_data))
