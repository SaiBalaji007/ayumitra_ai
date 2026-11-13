from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    try:
        connection.ensure_connection()
        db = connection.vendor
    except Exception:
        db = "unavailable"
    return Response({"status": "ok", "service": "ayumitra-backend", "database": db})
