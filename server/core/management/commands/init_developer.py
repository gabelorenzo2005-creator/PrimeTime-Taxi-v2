"""Explicit local opt-in; no password or account is automatically seeded."""
from getpass import getpass
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction, IntegrityError
from rest_framework.authtoken.models import Token
from core.models import AccountProfile, Driver, Role


class Command(BaseCommand):
    help = 'In DEBUG only, initialize Gabriel Lorenzo as the sole developer Technician and prompt for a password.'

    def add_arguments(self, parser):
        parser.add_argument('--email', default='', help='Optional developer email; never used to grant dashboard access.')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Developer initialization is disabled when DEBUG=False.')
        username = 'gabriellorenzo'
        candidate = User(username=username, first_name='Gabriel', last_name='Lorenzo', email=options['email'])
        password = getpass('New local developer password: ')
        confirmation = getpass('Confirm local developer password: ')
        if password != confirmation:
            raise CommandError('Passwords do not match; no account was changed.')
        try:
            validate_password(password, candidate)
        except ValidationError as error:
            raise CommandError('; '.join(error.messages)) from None
        try:
            with transaction.atomic():
                user = User.objects.select_for_update().filter(username=username).first()
                if user and (user.first_name != 'Gabriel' or user.last_name != 'Lorenzo'):
                    raise CommandError('The reserved developer username belongs to a different account; no changes made.')
                if AccountProfile.objects.filter(development_dashboard_access=True).exclude(user=user).exists():
                    raise CommandError('Another account already owns development access; no changes made.')
                user = user or candidate
                user.first_name, user.last_name = 'Gabriel', 'Lorenzo'
                if options['email']:
                    user.email = options['email']
                user.is_active = user.is_staff = user.is_superuser = True
                user.set_password(password)
                user.save()
                AccountProfile.objects.update_or_create(user=user, defaults={
                    'role': Role.IT, 'must_change_password': False, 'development_dashboard_access': True})
                if not Driver.objects.filter(user=user).exists():
                    Driver.objects.create(user=user, first_name='Gabriel', last_name='Lorenzo',
                        call_number='DEV-GAB', hack_license_number='DEV-GAB', phone_number='DEV-GABRIEL',
                        email='gabriel.lorenzo@development.invalid', notes='V2 local development record. Not an operational driver credential.')
                Token.objects.filter(user=user).delete()
        except IntegrityError:
            raise CommandError('Development identity conflicts with existing data; transaction rolled back without altering other records.') from None
        self.stdout.write(self.style.SUCCESS('Developer gabriellorenzo initialized as Technician (IT), staff/superuser. Password hashed; existing sessions revoked.'))
