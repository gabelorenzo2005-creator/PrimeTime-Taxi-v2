"""Multiple installations per account, without silently stealing another device's registration."""
from django.db import IntegrityError, transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException
from .models import PushDevice


class DeviceConflict(APIException):
    status_code = 409
    default_detail = 'This installation or APNs token is already registered. Unregister its previous registration before switching accounts or installations.'


def register_device(user, data):
    try:
        with transaction.atomic():
            scope = {'installation_id': data['installation_id'], 'environment': data['environment'], 'topic': data['topic']}
            device = PushDevice.objects.select_for_update().filter(user=user, **scope).first()
            others = PushDevice.objects.filter(is_active=True, environment=data['environment'], topic=data['topic'])
            if device:
                others = others.exclude(pk=device.pk)
            if others.filter(installation_id=data['installation_id']).exists() or others.filter(apns_token=data['apns_token']).exists():
                raise DeviceConflict()
            if device is None:
                return PushDevice.objects.create(user=user, **data), True
            device.apns_token = data['apns_token']
            device.is_active = True
            device.disabled_at = None
            device.last_registered_at = timezone.now()
            device.revision = F('revision') + 1
            device.save(update_fields=['apns_token', 'is_active', 'disabled_at', 'last_registered_at', 'revision'])
            device.refresh_from_db()
            return device, False
    except IntegrityError:
        # The partial unique constraints also protect concurrent registrations.
        raise DeviceConflict()


@transaction.atomic
def unregister_device(user, pk):
    device = get_object_or_404(PushDevice.objects.select_for_update(), pk=pk, user=user)
    if device.is_active:
        device.is_active = False
        device.disabled_at = timezone.now()
        device.revision = F('revision') + 1
        device.save(update_fields=['is_active', 'disabled_at', 'revision'])
