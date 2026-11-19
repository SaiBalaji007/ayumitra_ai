from rest_framework import serializers

from .models import Prescription, PrescriptionMedicine


class PrescriptionMedicineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrescriptionMedicine
        exclude = ["prescription"]


class PrescriptionSerializer(serializers.ModelSerializer):
    document_id = serializers.UUIDField(source="document.id", read_only=True)
    medicines = PrescriptionMedicineSerializer(many=True, read_only=True)
    notices = serializers.SerializerMethodField()

    class Meta:
        model = Prescription
        exclude = ["document", "raw"]

    def get_notices(self, obj):
        """Reading notes from processing (e.g. 'read from handwriting by the vision model: check every line')."""
        return [w for w in (obj.raw or {}).get("warnings", []) if isinstance(w, str)]
