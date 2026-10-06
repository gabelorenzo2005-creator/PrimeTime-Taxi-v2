"""Durable, leased per-device attempts. APNs acceptance is never called device delivery."""
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .models import NotificationEvent, PushDevice, PushDelivery, PushAttempt, Role, Trip
from .apns_transport import APNsResult

TERMINAL_EVENTS = ['ACCEPTED_BY_APNS', 'PARTIAL', 'FAILED', 'SKIPPED', 'EXPIRED']


def relevant(event):
    user = event.recipient
    if not user.is_active or not hasattr(user, 'profile') or user.profile.must_change_password:
        return False
    if event.kind == 'TRIP_ASSIGNED':
        return user.profile.role == Role.DRIVER and event.trip.driver and event.trip.driver.user_id == user.pk and event.trip.status in ['ASSIGNED', 'IN_PROGRESS']
    return user.profile.role in [Role.DISPATCHER, Role.ADMIN, Role.IT] and event.safety_alert.resolved_at is None


def payload_for(event):
    title = 'Trip assigned' if event.kind == 'TRIP_ASSIGNED' else 'Driver safety alert'
    return {'aps': {'alert': {'title': title, 'body': 'Open PrimeTime Taxi to review the details.'}, 'sound': 'default'},
            'event_id': str(event.pk), 'kind': event.kind,
            'trip_id': str(event.trip_id) if event.trip_id else '',
            'safety_alert_id': str(event.safety_alert_id) if event.safety_alert_id else ''}


@transaction.atomic
def prepare_deliveries(event_id, now):
    event = NotificationEvent.objects.select_for_update(of=('self',)).select_related('recipient__profile', 'trip__driver', 'safety_alert').get(pk=event_id)
    if event.status in TERMINAL_EVENTS:
        return []
    expired = now >= event.created_at + timedelta(seconds=settings.APNS_EVENT_TTL_SECONDS)
    if expired or not relevant(event):
        event.status = 'EXPIRED' if expired else 'SKIPPED'
        event.save(update_fields=['status'])
        event.deliveries.filter(status__in=['PENDING', 'RETRY']).update(status='CANCELLED')
        return []
    devices = PushDevice.objects.filter(user=event.recipient, is_active=True, topic__in=settings.APNS_ALLOWED_TOPICS)
    for device in devices:
        if event.deliveries.filter(device=device, status='ACCEPTED_BY_APNS').exists():
            continue
        PushDelivery.objects.get_or_create(event=event, device=device, device_revision=device.revision, defaults={'next_attempt_at': now})
    event.status = 'RETRY' if event.deliveries.exists() else 'WAITING_FOR_DEVICES'
    event.save(update_fields=['status'])
    return list(event.deliveries.values_list('pk', flat=True))


@transaction.atomic
def claim_attempt(delivery_id, now):
    delivery = PushDelivery.objects.select_for_update(of=('self',)).select_related('device', 'event__recipient__profile', 'event__trip__driver', 'event__safety_alert').get(pk=delivery_id)
    if delivery.status not in ['PENDING', 'RETRY', 'SENDING'] or delivery.next_attempt_at > now:
        return None
    if delivery.status == 'SENDING':
        if delivery.lease_until and delivery.lease_until > now:
            return None
        delivery.attempts.filter(status='STARTED').update(status='UNKNOWN', finished_at=now, reason='WorkerLeaseExpired')
    if delivery.attempt_count >= settings.APNS_MAX_ATTEMPTS:
        delivery.status = 'FAILED'
        delivery.save(update_fields=['status'])
        return None
    device, event = delivery.device, delivery.event
    if not device.is_active or device.revision != delivery.device_revision or device.user_id != event.recipient_id or not relevant(event):
        delivery.status = 'CANCELLED'
        delivery.save(update_fields=['status'])
        return None
    if now >= event.created_at + timedelta(seconds=settings.APNS_EVENT_TTL_SECONDS):
        delivery.status = 'CANCELLED'
        delivery.save(update_fields=['status'])
        return None
    delivery.attempt_count += 1
    delivery.status = 'SENDING'
    delivery.lease_until = now + timedelta(seconds=settings.APNS_LEASE_SECONDS)
    delivery.save(update_fields=['attempt_count', 'status', 'lease_until'])
    attempt = PushAttempt.objects.create(delivery=delivery, number=delivery.attempt_count, started_at=now)
    return delivery, attempt


@transaction.atomic
def finish_attempt(delivery_id, attempt_id, result, now):
    delivery = PushDelivery.objects.select_for_update().get(pk=delivery_id)
    attempt = PushAttempt.objects.select_for_update().get(pk=attempt_id, delivery=delivery)
    # A late response from an expired lease cannot overwrite a newer attempt.
    if attempt.status != 'STARTED' or delivery.attempt_count != attempt.number:
        return
    attempt.finished_at = now
    attempt.http_status = result.status or None
    attempt.reason = result.reason
    attempt.provider_apns_id = result.apns_id
    retry = result.status == 0 or result.status == 429 or result.status >= 500 or result.status == 403
    if result.status == 200:
        delivery.status = attempt.status = 'ACCEPTED_BY_APNS'
        delivery.accepted_at = now
    elif retry and delivery.attempt_count < settings.APNS_MAX_ATTEMPTS:
        delivery.status = attempt.status = 'RETRY'
        delay = max(result.retry_after, min(3600, 60 * 2 ** (delivery.attempt_count - 1)))
        if result.status >= 500:
            delay = max(delay, 900)
        delivery.next_attempt_at = now + timedelta(seconds=delay)
    else:
        delivery.status = attempt.status = 'FAILED'
    if result.status == 410 or (result.status == 400 and result.reason in ['BadDeviceToken', 'DeviceTokenNotForTopic']):
        devices = PushDevice.objects.filter(pk=delivery.device_id, revision=delivery.device_revision, is_active=True)
        if result.invalid_since_ms is not None:
            # Compare in the query without trusting an arbitrary out-of-range datetime.
            if 0 <= result.invalid_since_ms <= int(now.timestamp() * 1000):
                from datetime import datetime, timezone as utc
                devices = devices.filter(last_registered_at__lte=datetime.fromtimestamp(result.invalid_since_ms / 1000, utc.utc))
            else:
                devices = devices.none()
        from django.db.models import F
        devices.update(is_active=False, disabled_at=now, revision=F('revision') + 1)
    delivery.lease_until = None
    delivery.save()
    attempt.save()


@transaction.atomic
def summarize(event_id):
    event = NotificationEvent.objects.select_for_update().get(pk=event_id)
    if event.status in ['SKIPPED', 'EXPIRED']:
        return event.status
    statuses = list(event.deliveries.values_list('status', flat=True))
    if not statuses:
        status = 'WAITING_FOR_DEVICES'
    elif any(s in ['PENDING', 'RETRY', 'SENDING'] for s in statuses):
        status = 'RETRY'
    elif 'ACCEPTED_BY_APNS' in statuses:
        status = 'PARTIAL' if 'FAILED' in statuses else 'ACCEPTED_BY_APNS'
    else:
        # Cancelled old revisions can be replaced on a later worker pass.
        status = 'FAILED' if 'FAILED' in statuses else 'WAITING_FOR_DEVICES'
    event.status = status
    event.save(update_fields=['status'])
    return status


def process_event(event_id, transport, now=None):
    now = now or timezone.now()
    ids = prepare_deliveries(event_id, now)
    for pk in ids:
        claimed = claim_attempt(pk, now)
        if claimed is None:
            continue
        delivery, attempt = claimed
        device, event = delivery.device, delivery.event
        try:
            result = transport.send(token=device.apns_token, environment=device.environment, topic=device.topic,
                                    apns_id=delivery.apns_id, event_id=event.pk, payload=payload_for(event),
                                    expires_at=int((event.created_at + timedelta(seconds=settings.APNS_EVENT_TTL_SECONDS)).timestamp()))
        except Exception:
            # Never persist exception text: transport URLs may contain raw tokens.
            result = APNsResult(0, 'TransportError')
        finish_attempt(delivery.pk, attempt.pk, result, now)
    return summarize(event_id)
