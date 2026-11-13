from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from core.permissions import IsOwner

from .models import Prescription
from .serializers import PrescriptionSerializer


class PrescriptionViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only for now. Phase 9 adds field correction and user verification."""

    serializer_class = PrescriptionSerializer
    permission_classes = [IsAuthenticated, IsOwner]
    owner_lookup = "document__owner"

    def get_queryset(self):
        return (
            Prescription.objects.filter(document__owner=self.request.user)
            .select_related("document")
            .prefetch_related("medicines")
        )
