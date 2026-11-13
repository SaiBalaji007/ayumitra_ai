from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from accounts.views import MeView, RegisterView, ThrottledTokenObtainPairView
from core.views import health
from documents.views import DocumentViewSet
from medical_reports.views import ExtractedReportViewSet, MedicalFindingViewSet
from patients.views import MyProfileView
from prescriptions.views import PrescriptionViewSet

router = DefaultRouter()
router.register("documents", DocumentViewSet, basename="document")
router.register("reports", ExtractedReportViewSet, basename="report")
router.register("findings", MedicalFindingViewSet, basename="finding")
router.register("prescriptions", PrescriptionViewSet, basename="prescription")

# NOTE: there is intentionally no static()/MEDIA_URL route. Medical files are only reachable
# through the owner-checked /api/documents/{id}/file/ endpoint.
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/auth/token/", ThrottledTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/register/", RegisterView.as_view(), name="register"),
    path("api/auth/me/", MeView.as_view(), name="me"),
    path("api/patients/me/profile/", MyProfileView.as_view(), name="my-profile"),
    path("api/", include(router.urls)),
]
