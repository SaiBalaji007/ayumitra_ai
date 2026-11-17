from rest_framework import serializers

from .logic import owner_sex, parse_range, range_info, to_decimal
from .models import ExtractedReport, LabParameter, MedicalFinding


class LabParameterSerializer(serializers.ModelSerializer):
    lab_flag_display = serializers.CharField(source="get_lab_flag_display", read_only=True)
    range_status = serializers.SerializerMethodField()
    range_source = serializers.SerializerMethodField()
    typical_range = serializers.SerializerMethodField()

    class Meta:
        model = LabParameter
        exclude = ["report"]
        read_only_fields = ["normalized_name", "loinc_code", "value_numeric", "reference_low", "reference_high",
                            "confidence", "page", "created_at", "updated_at", "name_as_printed", "lab_flag"]

    def _info(self, obj):
        """range_info once per parameter; the owner's sex is looked up once per serializer run."""
        cache = self.context.setdefault("_range_info", {})
        if obj.pk not in cache:
            if "_sex" not in self.context:
                self.context["_sex"] = owner_sex(obj)
            cache[obj.pk] = range_info(obj, self.context["_sex"])
        return cache[obj.pk]

    def get_range_status(self, obj):
        return self._info(obj)["status"]

    def get_range_source(self, obj):
        """'lab' = the lab's printed range; 'typical' = a cited typical range (report printed none)."""
        return self._info(obj)["source"]

    def get_typical_range(self, obj):
        typ = self._info(obj)["typical"]
        if not typ:
            return None
        keep = ("sex", "display", "publisher", "source_title", "url", "quote", "comparable", "unit")
        return {"selected": {k: typ["selected"][k] for k in keep} if typ["selected"] else None,
                "options": [{k: o[k] for k in keep} for o in typ["options"]]}

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
        sex = owner_sex(obj.parameters.first()) if obj.parameters.exists() else ""
        return sum(1 for p in obj.parameters.all()
                   if range_info(p, sex)["status"] in ("above", "below") or p.lab_flag)
