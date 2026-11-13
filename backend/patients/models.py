from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import TimeStampedModel


def validate_not_future(value):
    if value and value > date.today():
        raise ValidationError("Date of birth cannot be in the future.")


class PatientProfile(TimeStampedModel):
    """Self-reported profile. Used later to personalise education (e.g. age/sex-specific ranges)."""

    class Sex(models.TextChoices):
        FEMALE = "female", "Female"
        MALE = "male", "Male"
        INTERSEX = "intersex", "Intersex"
        UNDISCLOSED = "undisclosed", "Prefer not to say"

    class BloodGroup(models.TextChoices):
        A_POS = "A+", "A+"
        A_NEG = "A-", "A-"
        B_POS = "B+", "B+"
        B_NEG = "B-", "B-"
        AB_POS = "AB+", "AB+"
        AB_NEG = "AB-", "AB-"
        O_POS = "O+", "O+"
        O_NEG = "O-", "O-"
        UNKNOWN = "unknown", "Unknown"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="patient_profile")
    date_of_birth = models.DateField(null=True, blank=True, validators=[validate_not_future])
    sex = models.CharField(max_length=12, choices=Sex.choices, default=Sex.UNDISCLOSED)
    blood_group = models.CharField(max_length=8, choices=BloodGroup.choices, default=BloodGroup.UNKNOWN)
    height_cm = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(30), MaxValueValidator(260)],
    )
    weight_kg = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(400)],
    )
    allergies = models.TextField(blank=True, help_text="As reported by the user.")
    chronic_conditions = models.TextField(blank=True, help_text="As reported by the user.")
    current_medications_note = models.TextField(blank=True)
    dietary_preference = models.CharField(max_length=40, blank=True)

    def __str__(self):
        return f"Profile of {self.user_id}"
