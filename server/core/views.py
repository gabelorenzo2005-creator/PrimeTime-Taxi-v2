from django.http import HttpResponse
from django.contrib.auth import authenticate
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.authtoken.models import Token
from django.utils import timezone
from datetime import timedelta
from rest_framework.response import Response
from rest_framework import status
from .models import AccountProfile, Role


def home(request):
    return HttpResponse("PrimeTime Taxi v2 backend is running.")


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def login_view(request):
    username = request.data.get("username")
    password = request.data.get("password")

    if not username or not password:
        return Response(
            {"error": "Username and Password are required."},
            status=status.HTTP_400_BAD_REQUEST, 
        )

    user = authenticate(
        username=username, 
        password=password,
    )

    if user is None: 
        return Response(
            {"error": "Invalid username or password."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    try:
        profile = user.profile
    except AccountProfile.DoesNotExist:
        return Response(
            {"error": "Your account needs a role profile. Contact your administrator."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if profile.role not in Role.values:
        return Response(
            {"error": "Your account role is invalid. Contact your administrator."},
            status=status.HTTP_403_FORBIDDEN,
        )

    token, _ = Token.objects.get_or_create(user=user)
    if token.created < timezone.now() - timedelta(hours=12):
        token.delete()
        token = Token.objects.create(user=user)

    return Response(
        {
            "token": token.key,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": profile.role,
            "role_display": profile.get_role_display(),
            "must_change_password": profile.must_change_password,
        },
        status=status.HTTP_200_OK,
    )
