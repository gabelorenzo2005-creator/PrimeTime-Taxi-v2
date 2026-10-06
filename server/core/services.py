from django.contrib.auth.models import User
from django.db import transaction
from rest_framework.authtoken.models import Token
from .models import AccountProfile, Role
from .audit import record

def generate_username(first_name, last_name): 
    base_username = f"{last_name}{first_name}".lower()
    username = base_username
    counter = 2

    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1
    return username

@transaction.atomic
def create_account(first_name, last_name, password, role, driver=None, *, actor=None):
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

    if actor is not None:
        record(actor, 'account.created', user, {'role': role, 'driver_id': driver.pk if driver else None})
    return user, profile

@transaction.atomic
def deactivate_account(user, *, actor=None):
    user.is_active = False
    user.save()
    Token.objects.filter(user=user).delete()
    if actor is not None:
        record(actor, 'account.deactivated', user)

@transaction.atomic
def reactivate_account(user, *, actor=None):
    user.is_active = True
    user.save()
    if actor is not None:
        record(actor, 'account.reactivated', user)

@transaction.atomic
def reset_password(user, new_password, *, actor=None):
    user.set_password(new_password)
    user.save()
    Token.objects.filter(user=user).delete()
    user.profile.must_change_password = True
    user.profile.save()
    if actor is not None:
        record(actor, 'account.password_reset', user)

@transaction.atomic
def change_password(user, new_password, *, actor=None):
    user.set_password(new_password)
    user.save()
    Token.objects.filter(user=user).delete()

    user.profile.must_change_password = False
    user.profile.save()
    if actor is not None:
        record(actor, 'account.password_changed', user)
