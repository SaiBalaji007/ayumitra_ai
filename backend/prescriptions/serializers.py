from rest_framework import serializers

from .models import Prescription, PrescriptionMedicine


class PrescriptionMedicineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrescriptionMedicine
        exclude = ["prescription"]


class PrescriptionSerializer(serializers.ModelSerializer):
    document_id = serializers.UUIDField(source="document.id", read_only=True)
    medicines = PrescriptionMedicineSerializer(many=True, read_only=True)

    class Meta:
        model = Prescription
        exclude = ["document", "raw"]
