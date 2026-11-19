from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsOwner

from .models import Prescription, PrescriptionMedicine
from .serializers import PrescriptionMedicineSerializer, PrescriptionSerializer

EDITABLE = ["name_as_written", "strength", "dosage_form", "dose", "frequency", "timing", "duration", "route",
            "food_instructions"]


class MedicineCorrectionSerializer(serializers.ModelSerializer):
    """The user corrects fields to match their paper prescription and confirms the line.
    `generic_name` may only be set to one of the RxNorm suggestions stored for this line."""

    choose_suggestion = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = PrescriptionMedicine
        fields = [*EDITABLE, "user_confirmed", "choose_suggestion"]

    def validate_choose_suggestion(self, value):
        if not value:
            return value
        allowed = {s["name"].lower(): s for s in (self.instance.field_confidence or {}).get("suggestions", [])}
        if value.lower() not in allowed:
            raise serializers.ValidationError("Pick one of the suggested RxNorm names, or leave it blank.")
        return allowed[value.lower()]

    def update(self, instance, validated_data):
        choice = validated_data.pop("choose_suggestion", None)
        if choice:
            if choice.get("kind") == "indian_brand":  # user confirmed the brand -> its listed generic ingredients
                instance.generic_name = (choice.get("generic") or "")[:200]
            else:
                instance.generic_name = choice["name"].lower() if choice.get("kind") == "ingredient" else ""
            instance.rxnorm_cui = choice.get("rxcui", "")
        edited = [f for f in EDITABLE if f in validated_data]
        instance = super().update(instance, validated_data)
        if edited:
            # A field the user has typed in themselves no longer needs review.
            resolved = {"name" if f == "name_as_written" else f for f in edited}
            instance.fields_needing_review = [f for f in instance.fields_needing_review if f not in resolved]
            instance.save(update_fields=["fields_needing_review", "updated_at"])
        return instance


class PrescriptionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PrescriptionSerializer
    permission_classes = [IsAuthenticated, IsOwner]
    owner_lookup = "document__owner"

    def get_queryset(self):
        return (Prescription.objects.filter(document__owner=self.request.user)
                .select_related("document").prefetch_related("medicines"))

    @action(detail=True, methods=["patch", "delete"], url_path=r"medicines/(?P<med_id>\d+)")
    def medicine(self, request, pk=None, med_id=None):
        rx = self.get_object()
        med = get_object_or_404(PrescriptionMedicine, pk=med_id, prescription=rx)
        if request.method == "DELETE":  # remove a wrong extraction (e.g. clinic header read as a medicine)
            med.delete()
            if rx.user_verified:
                rx.user_verified, rx.verified_at = False, None
                rx.save(update_fields=["user_verified", "verified_at", "updated_at"])
            return Response(status=status.HTTP_204_NO_CONTENT)
        ser = MedicineCorrectionSerializer(med, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        if rx.user_verified:  # any edit re-opens verification
            rx.user_verified, rx.verified_at = False, None
            rx.save(update_fields=["user_verified", "verified_at", "updated_at"])
        return Response(PrescriptionMedicineSerializer(med).data)

    @action(detail=True, methods=["post"], url_path="medicines")
    def add_medicine(self, request, pk=None):
        """Add a medicine the OCR missed, typed by the user from the paper prescription (user-confirmed)."""
        rx = self.get_object()
        name = (request.data.get("name_as_written") or "").strip()
        if not (2 <= len(name) <= 200):
            return Response({"detail": "Type the medicine name as written (2-200 characters).", "code": "invalid_name"},
                            status=status.HTTP_400_BAD_REQUEST)
        last = rx.medicines.order_by("-line_number").values_list("line_number", flat=True).first() or 0
        med = PrescriptionMedicine.objects.create(prescription=rx, line_number=last + 1, name_as_written=name)
        ser = MedicineCorrectionSerializer(med, data={**request.data, "user_confirmed": True}, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        if rx.user_verified:
            rx.user_verified, rx.verified_at = False, None
            rx.save(update_fields=["user_verified", "verified_at", "updated_at"])
        return Response(PrescriptionMedicineSerializer(med).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def insights(self, request, pk=None):
        """Prescription Analyzer: OCR text, schedule (only as written), safety checks, medicine information."""
        from django.core.cache import cache

        from core.ai_client import AIServiceError, medicine_info
        from patients.models import PatientProfile

        from .logic import DISCLAIMER, build_schedule, identified_names, safety_warnings

        rx = self.get_object()
        meds = list(rx.medicines.order_by("line_number"))
        profile = PatientProfile.objects.filter(user=request.user).first()
        info, info_error = [], ""
        names = identified_names(meds)
        missing = [n for n in names if cache.get(f"medinfo:{n.lower()}") is None]
        if missing:
            try:
                for item in medicine_info(missing).get("medicines", []):
                    cache.set(f"medinfo:{item.get('query', '').lower()}", item, 7 * 24 * 3600)
            except AIServiceError:
                info_error = "Medicine information is unavailable right now (AI service offline). Try again later."
        info = [cache.get(f"medinfo:{n.lower()}") for n in names]
        pages = rx.document.pages.order_by("page_number").values_list("page_number", "text", "ocr_confidence")             if hasattr(rx.document, "pages") else []
        return Response({
            "prescription_id": rx.pk,
            "document_id": str(rx.document_id),
            "ocr_pages": [{"page": p, "text": t, "confidence": c} for p, t, c in pages],
            "schedule": build_schedule(meds),
            "safety": safety_warnings(meds, profile.allergies if profile else ""),
            "medicine_info": [i for i in info if i],
            "medicine_info_error": info_error,
            "unidentified": [m.name_as_written or "(unreadable)" for m in meds if not m.generic_name and not m.user_confirmed],
            "disclaimer": DISCLAIMER,
        })

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        rx = self.get_object()
        pending = [m.line_number for m in rx.medicines.all() if not m.user_confirmed]
        if pending:
            return Response({"detail": f"Confirm every medicine line first (lines {', '.join(map(str, pending))}).",
                             "code": "unconfirmed_lines"}, status=status.HTTP_400_BAD_REQUEST)
        rx.user_verified, rx.verified_at = True, timezone.now()
        rx.save(update_fields=["user_verified", "verified_at", "updated_at"])
        return Response(PrescriptionSerializer(rx).data)
