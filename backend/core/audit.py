from .models import AuditLog


def client_ip(request):
    # Only trust X-Forwarded-For behind a configured proxy; Phase 13 sets that up.
    return request.META.get("REMOTE_ADDR")


def audit(request, action, resource=None, **metadata):
    """Record an audit event. Never store document contents or medical values in metadata."""
    user = getattr(request, "user", None)
    return AuditLog.objects.create(
        user=user if user is not None and user.is_authenticated else None,
        action=action,
        resource_type=resource._meta.label if resource is not None else "",
        resource_id=str(resource.pk) if resource is not None else "",
        ip_address=client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
        metadata=metadata,
    )
