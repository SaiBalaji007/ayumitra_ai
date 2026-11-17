from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.ai_client import AIServiceError, render_report_pdf, run_agent
from core.audit import audit
from core.models import AuditLog
from core.permissions import IsOwner

from .logic import parameter_context, range_status
from .recommendations import build_recommendations
from .models import ExtractedReport, LabParameter, MedicalFinding
from .serializers import ExtractedReportSerializer, LabParameterSerializer, MedicalFindingSerializer


def ai_unavailable(exc: AIServiceError) -> Response:
    return Response({"detail": "The AI service is unavailable right now. Please try again later.",
                     "code": "ai_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class ExtractedReportViewSet(viewsets.ReadOnlyModelViewSet):
    """Reports are produced by the extraction pipeline. Users can verify or correct values and
    request evidence-backed explanations of results outside the lab's range."""

    serializer_class = ExtractedReportSerializer
    permission_classes = [IsAuthenticated, IsOwner]
    owner_lookup = "document__owner"

    def get_queryset(self):
        return (ExtractedReport.objects.filter(document__owner=self.request.user)
                .select_related("document").prefetch_related("parameters"))

    @action(detail=True, methods=["post"])
    def explain(self, request, pk=None):
        report = self.get_object()
        params = [parameter_context(p) for p in report.parameters.all()]
        if not params:
            return Response({"detail": "This report has no extracted results to explain.", "code": "no_results"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            result = run_agent({"lab_results": params})
        except AIServiceError as exc:
            return ai_unavailable(exc)
        raw = report.raw or {}
        raw["explanations"] = result.get("explanations", [])
        raw["explained_at"] = timezone.now().isoformat()
        raw["messages"] = result.get("messages", [])
        report.raw = raw
        report.save(update_fields=["raw", "updated_at"])
        return Response({"explanations": raw["explanations"], "messages": raw["messages"]})

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        """PDF summary: printed values, range comparison, validated explanations with sources."""
        report = self.get_object()
        data = ExtractedReportSerializer(report).data
        payload = {"title": data["document_title"], "report_date": data["report_date"],
                   "parameters": data["parameters"], "explanations": data["explanations"], "education": data["education"]}
        try:
            pdf = render_report_pdf(payload)
        except AIServiceError as exc:
            return ai_unavailable(exc)
        audit(request, AuditLog.Action.REPORT_EXPORT, report)
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="ayumitra-report-{report.pk}.pdf"'
        resp["Cache-Control"] = "private, no-store"
        return resp

    @action(detail=True, methods=["post"])
    def education(self, request, pk=None):
        """Diet and lifestyle education for results outside the lab's range (grounded, not a plan)."""
        report = self.get_object()
        params = [parameter_context(p) for p in report.parameters.all()]
        if not params:
            return Response({"detail": "This report has no extracted results.", "code": "no_results"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            result = run_agent({"lab_results": params, "mode": "education"})
        except AIServiceError as exc:
            return ai_unavailable(exc)
        raw = report.raw or {}
        raw["education"] = {"items": result.get("explanations", []), "messages": result.get("messages", []),
                            "created_at": timezone.now().isoformat()}
        report.raw = raw
        report.save(update_fields=["raw", "updated_at"])
        return Response(raw["education"])

    @action(detail=True, methods=["patch"], url_path=r"parameters/(?P<param_id>\d+)")
    def parameter(self, request, pk=None, param_id=None):
        report = self.get_object()
        param = get_object_or_404(LabParameter, pk=param_id, report=report)
        ser = LabParameterSerializer(param, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(LabParameterSerializer(param).data)


class MedicalFindingViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MedicalFindingSerializer
    permission_classes = [IsAuthenticated, IsOwner]
    owner_lookup = "document__owner"

    def get_queryset(self):
        qs = MedicalFinding.objects.filter(document__owner=self.request.user)
        if doc := self.request.query_params.get("document"):
            qs = qs.filter(document_id=doc)
        return qs


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def timeline(request):
    """
    Health timeline for one test across the user's reports (Phase 11).
      GET /api/timeline/                      -> tests available, with result counts
      GET /api/timeline/?parameter=hemoglobin -> points ordered by report date
    Values are returned exactly as printed; points with different units are kept apart, never mixed.
    """
    base = LabParameter.objects.filter(report__document__owner=request.user)
    name = request.query_params.get("parameter")
    if not name:
        names = {}
        for p in base.only("normalized_name", "name_as_printed"):
            key = p.normalized_name or p.name_as_printed.lower()
            entry = names.setdefault(key, {"parameter": key, "label": p.name_as_printed, "count": 0})
            entry["count"] += 1
        return Response(sorted(names.values(), key=lambda x: (-x["count"], x["parameter"])))

    qs = (base.filter(Q(normalized_name=name) | Q(normalized_name="", name_as_printed__iexact=name))
          .select_related("report__document"))
    points = []
    for p in qs:
        rep = p.report
        date = rep.report_date or rep.document.document_date or rep.document.created_at.date()
        points.append({
            "date": date.isoformat(), "report_id": rep.pk, "document_id": str(rep.document_id),
            "value_text": p.value_text, "value": float(p.value_numeric) if p.value_numeric is not None else None,
            "unit": p.unit, "reference_range_text": p.reference_range_text,
            "reference_low": float(p.reference_low) if p.reference_low is not None else None,
            "reference_high": float(p.reference_high) if p.reference_high is not None else None,
            "lab_flag": p.lab_flag, "range_status": range_status(p.value_numeric, p.reference_low, p.reference_high),
            "user_verified": p.user_verified,
        })
    points.sort(key=lambda x: x["date"])
    units = sorted({pt["unit"] for pt in points})
    return Response({"parameter": name, "units": units, "points": points,
                     "mixed_units": len(units) > 1})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def recommendations(request):
    """Diet and lifestyle education built from the user's own latest results and profile (no LLM needed)."""
    return Response(build_recommendations(request.user))
