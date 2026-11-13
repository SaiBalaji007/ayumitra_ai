from django.contrib import admin

from .models import ExtractedReport, LabParameter, MedicalFinding

admin.site.register([ExtractedReport, LabParameter, MedicalFinding])
