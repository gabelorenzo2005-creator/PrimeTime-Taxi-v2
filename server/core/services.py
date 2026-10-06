from django.contrib.auth.models import User
from django.db import transaction
from rest_framework.authtoken.models import Token
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
def create_account(first_name, last_name, password, role, driver=None): 
    if role not in Role.values:
        raise ValueError('Choose a valid account role.')
    if driver is not None and (role != Role.DRIVER or driver.user_id is not None):
        raise ValueError('Only an unlinked driver can be attached to a new Driver account.')
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

    if role == Role.DRIVER and driver is not None:
        driver.user = user
        driver.save()

    return user, profile 

def deactivate_account(user): 
    user.is_active = False
    user.save()
    Token.objects.filter(user=user).delete()
    
def reactivate_account(user): 
    user.is_active = True
    user.save()

def reset_password(user, new_password):
    user.set_password(new_password)
    user.save()
    Token.objects.filter(user=user).delete()
    user.profile.must_change_password = True
    user.profile.save()

def change_password(user, new_password):
    user.set_password(new_password)
    user.save()
    Token.objects.filter(user=user).delete()

    user.profile.must_change_password = False
    user.profile.save()
