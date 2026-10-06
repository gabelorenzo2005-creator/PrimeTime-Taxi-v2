"""Read-only development previews never change an account's authorization role."""
from django.conf import settings
from rest_framework.exceptions import PermissionDenied, ValidationError
from .models import Role

PREVIEW_ROLES = [Role.DRIVER, Role.DISPATCHER, Role.ADMIN, Role.IT]


def can_preview_dashboards(user):
    profile = getattr(user, 'profile', None)
    return bool(settings.DEBUG and user.is_authenticated and user.is_active
                and user.is_staff and user.is_superuser and profile
                and profile.role == Role.IT and not profile.must_change_password
                and profile.development_dashboard_access)


def require_dashboard_preview(user, role):
    if not can_preview_dashboards(user):
        raise PermissionDenied('Development dashboard access is not available for this account or server.')
    if role not in PREVIEW_ROLES:
        raise ValidationError({'error': 'Choose Driver, Dispatcher, Admin or Technician.'})
    return role
