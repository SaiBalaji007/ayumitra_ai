from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import TimeStampedModel
from documents.models import MedicalDocument


class Prescription(TimeStampedModel):
    document = models.OneToOneField(MedicalDocument, on_delete=models.CASCADE, related_name="prescription")
    prescriber_name = models.CharField(max_length=200, blank=True)
    facility_name = models.CharField(max_length=200, blank=True)
    prescribed_date = models.DateField(null=True, blank=True, db_index=True)
    is_handwritten = models.BooleanField(null=True, blank=True)
    # The user must review extraction before it is treated as their medication list.
    user_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-prescribed_date", "-created_at"]

    def __str__(self):
        return f"Prescription for {self.document_id}"


class PrescriptionMedicine(TimeStampedModel):
    """
    One medication line, stored AS WRITTEN. Missing fields stay blank: dose, frequency or duration
    are never inferred or filled in. Uncertain fields are listed in `fields_needing_review`.
    """

    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="medicines")
    line_number = models.PositiveSmallIntegerField(default=1)
    name_as_written = models.CharField(max_length=200)
    generic_name = models.CharField(max_length=200, blank=True, help_text="Only set from a verified source match.")
    rxnorm_cui = models.CharField(max_length=20, blank=True)
    strength = models.CharField(max_length=60, blank=True)
    dosage_form = models.CharField(max_length=60, blank=True)
    dose = models.CharField(max_length=60, blank=True)
    frequency = models.CharField(max_length=80, blank=True)
    timing = models.CharField(max_length=80, blank=True)
    duration = models.CharField(max_length=60, blank=True)
    route = models.CharField(max_length=40, blank=True)
    food_instructions = models.CharField(max_length=120, blank=True)
    field_confidence = models.JSONField(default=dict, blank=True, help_text='e.g. {"name": 0.93, "dose": 0.41}')
    overall_confidence = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )
    fields_needing_review = models.JSONField(default=list, blank=True)
    user_confirmed = models.BooleanField(default=False)

    class Meta:
        ordering = ["prescription", "line_number"]
        indexes = [models.Index(fields=["generic_name"])]

    def __str__(self):
        return self.name_as_written
