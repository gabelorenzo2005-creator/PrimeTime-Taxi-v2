from django.http import HttpResponse
from django.contrib.auth import authenticate
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status


def home(request):
    return HttpResponse("PrimeTime Taxi v2 backend is running.")


@api_view(["POST"])
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

    profile = user.profile 

    return Response(
        {
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": profile.role,
            "role_display": profile.get_role_display(),
            "must_change_password": profile.must_change_password,
        },
        status=status.HTTP_200_OK,
    )
