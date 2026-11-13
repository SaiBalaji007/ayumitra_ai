from rest_framework import serializers

from .models import ExtractedReport, LabParameter, MedicalFinding


class LabParameterSerializer(serializers.ModelSerializer):
    lab_flag_display = serializers.CharField(source="get_lab_flag_display", read_only=True)

    class Meta:
        model = LabParameter
        exclude = ["report"]


class MedicalFindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicalFinding
        exclude = ["document"]


class ExtractedReportSerializer(serializers.ModelSerializer):
    document_id = serializers.UUIDField(source="document.id", read_only=True)
    parameters = LabParameterSerializer(many=True, read_only=True)

    class Meta:
        model = ExtractedReport
        exclude = ["document", "raw"]
