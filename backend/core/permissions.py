from rest_framework.permissions import BasePermission


class IsOwner(BasePermission):
    """
    Object-level check, as defence in depth. Views must ALSO scope their querysets to the
    requesting user so that other users' objects return 404 rather than revealing they exist.
    """

    owner_field = "owner"

    def has_object_permission(self, request, view, obj):
        path = getattr(view, "owner_lookup", self.owner_field)
        owner = obj
        for part in path.split("__"):
            owner = getattr(owner, part)
        return owner == request.user
