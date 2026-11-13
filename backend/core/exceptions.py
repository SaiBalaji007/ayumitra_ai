from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    """
    Keep DRF's field-level errors, and add a stable top-level `code` so the frontend can branch
    on error type without parsing messages. Unhandled exceptions still become 500s via Django.
    """
    response = exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, Http404):
        code = "not_found"
    elif isinstance(exc, PermissionDenied):
        code = "permission_denied"
    else:
        code = getattr(exc, "default_code", "error")
    if isinstance(response.data, dict):
        response.data.setdefault("code", code)
    else:
        response.data = {"detail": response.data, "code": code}
    return response
