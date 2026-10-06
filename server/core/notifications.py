"""Transactional notification intent only. No APNs client, secrets, worker or delivery status."""
from django.contrib.auth.models import User
from .models import NotificationEvent, Role


def prepare_trip_assignment(trip):
    return NotificationEvent.objects.get_or_create(
        recipient=trip.driver.user,
        kind=NotificationEvent.Kind.TRIP_ASSIGNED,
        trip=trip,
    )[0]


def prepare_safety_alert(alert):
    recipients = User.objects.filter(is_active=True, profile__role__in=[Role.DISPATCHER, Role.ADMIN, Role.IT])
    for recipient in recipients:
        NotificationEvent.objects.get_or_create(
            recipient=recipient,
            kind=NotificationEvent.Kind.SAFETY_ALERT,
            safety_alert=alert,
        )
