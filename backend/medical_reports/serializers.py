from rest_framework import serializers

from .logic import parse_range, range_status, to_decimal
from .models import ExtractedReport, LabParameter, MedicalFinding


class LabParameterSerializer(serializers.ModelSerializer):
    lab_flag_display = serializers.CharField(source="get_lab_flag_display", read_only=True)
    range_status = serializers.SerializerMethodField()

    class Meta:
        model = LabParameter
        exclude = ["report"]
        read_only_fields = ["normalized_name", "loinc_code", "value_numeric", "reference_low", "reference_high",
                            "confidence", "page", "created_at", "updated_at", "name_as_printed", "lab_flag"]

    def get_range_status(self, obj):
        return range_status(obj.value_numeric, obj.reference_low, obj.reference_high)

    def update(self, instance, validated_data):
        """User corrections: re-derive numbers from the corrected text. Correcting implies verification."""
        corrected = {"value_text", "unit", "reference_range_text"} & set(validated_data)
        instance = super().update(instance, validated_data)
        if corrected:
            instance.value_numeric = to_decimal(instance.value_text)
            lo, hi = parse_range(instance.reference_range_text)
            instance.reference_low, instance.reference_high = (lo, hi) if (lo is None or hi is None or lo <= hi) else (None, None)
            instance.user_verified = True
            instance.save()
        return instance


class MedicalFindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicalFinding
        exclude = ["document"]


class ExtractedReportSerializer(serializers.ModelSerializer):
    document_id = serializers.UUIDField(source="document.id", read_only=True)
    document_title = serializers.SerializerMethodField()
    parameters = LabParameterSerializer(many=True, read_only=True)
    explanations = serializers.SerializerMethodField()
    education = serializers.SerializerMethodField()
    abnormal_count = serializers.SerializerMethodField()

    class Meta:
        model = ExtractedReport
        exclude = ["document", "raw"]

    def get_document_title(self, obj):
        return obj.document.title or obj.document.original_filename

    def get_explanations(self, obj):
        return (obj.raw or {}).get("explanations", [])

    def get_education(self, obj):
        return (obj.raw or {}).get("education")

    def get_abnormal_count(self, obj):
        return sum(1 for p in obj.parameters.all()
                   if range_status(p.value_numeric, p.reference_low, p.reference_high) in ("above", "below") or p.lab_flag)
