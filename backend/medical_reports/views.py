from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from core.permissions import IsOwner

from .models import ExtractedReport, MedicalFinding
from .serializers import ExtractedReportSerializer, MedicalFindingSerializer


class ExtractedReportViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only: reports are produced by the extraction pipeline, not created through the API."""

    serializer_class = ExtractedReportSerializer
    permission_classes = [IsAuthenticated, IsOwner]
    owner_lookup = "document__owner"

    def get_queryset(self):
        return (
            ExtractedReport.objects.filter(document__owner=self.request.user)
            .select_related("document")
            .prefetch_related("parameters")
        )


class MedicalFindingViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MedicalFindingSerializer
    permission_classes = [IsAuthenticated, IsOwner]
    owner_lookup = "document__owner"

    def get_queryset(self):
        qs = MedicalFinding.objects.filter(document__owner=self.request.user)
        if doc := self.request.query_params.get("document"):
            qs = qs.filter(document_id=doc)
        return qs
