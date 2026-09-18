from django.contrib.auth.models import User
from django.db import transaction
from .models import AccountProfile, Role 

def generate_username(first_name, last_name): 
    base_username = f"{last_name}{first_name}".lower()
    username = base_username
    counter = 2

    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1
    return username

@transaction.atomic
def create_account(first_name, last_name, password, role): 
    username = generate_username(first_name, last_name)
    user = User.objects.create_user(
        username=username,
        first_name=first_name,
        last_name=last_name,
        password=password,
    )

    profile = AccountProfile.objects.create(
    user=user, 
    role=role,
    )

    return user, profile 
    