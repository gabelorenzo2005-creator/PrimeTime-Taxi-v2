"""Shared authentication and role checks for every operational endpoint."""
from datetime import timedelta
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import BasePermission
from .models import AccountProfile, Role


class ExpiringTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if token.created < timezone.now() - timedelta(hours=12):
            raise AuthenticationFailed('Your session expired. Sign in again.')
        return user, token


class CompanyAccountPermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        try:
            profile = request.user.profile
        except AccountProfile.DoesNotExist:
            raise PermissionDenied('Your account needs a role profile.')
        if profile.role not in Role.values:
            raise PermissionDenied('Your account role is invalid.')
        if profile.must_change_password and not getattr(view, 'allow_password_change', False):
            raise PermissionDenied('Change your password before continuing.')
        return True


def require_role(user, *roles):
    if user.profile.role not in roles:
        raise PermissionDenied('Your role cannot perform this action.')


def exception_handler(exc, context):
    from django.db import OperationalError
    from rest_framework.views import exception_handler as drf_handler
    from rest_framework.response import Response
    if isinstance(exc, OperationalError) and 'locked' in str(exc).lower():
        return Response({'error': 'Another update is in progress. Refresh and try again.'}, status=409)
    return drf_handler(exc, context)
