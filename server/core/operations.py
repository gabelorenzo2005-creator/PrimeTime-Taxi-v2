"""Editable dispatch rules. Transactions and database constraints protect assignments."""
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError, PermissionDenied
from .models import Driver, Shift, Trip, Vehicle, Role
from .api_access import require_role
from .notifications import prepare_trip_assignment
from .audit import record

ACTIVE_TRIP_STATUSES = [Trip.Status.ASSIGNED, Trip.Status.IN_PROGRESS]
DISPATCH_ROLES = (Role.DISPATCHER, Role.ADMIN)
PAYMENT_ROLES = (Role.ADMIN, Role.IT)


def driver_for(user):
    try:
        return user.driver_profile
    except Driver.DoesNotExist:
        raise ValidationError({'error': 'Your account needs a linked driver record. Ask Admin or IT to link it.'})


def pending_turn_ins(driver):
    return Shift.objects.filter(driver=driver, end_time__isnull=False, turn_in_cleared=False)


def ensure_turn_in_cleared(driver):
    if pending_turn_ins(driver).exists():
        raise ValidationError({'error': 'Your required turn-in is awaiting clearance. Admin or IT must clear it before another shift or trip.', 'code': 'TURN_IN_REQUIRED'})


def active_shift(driver):
    shift = Shift.objects.select_for_update().filter(driver=driver, end_time__isnull=True).first()
    if not shift:
        raise ValidationError({'error': 'The driver must clock in first.'})
    return shift


@transaction.atomic
def start_shift(user, vehicle_id):
    require_role(user, Role.DRIVER)
    driver = Driver.objects.select_for_update().get(pk=driver_for(user).pk)
    ensure_turn_in_cleared(driver)
    vehicle = get_object_or_404(Vehicle, pk=vehicle_id)
    if Shift.objects.filter(driver=driver, end_time__isnull=True).exists():
        raise ValidationError({'error': 'You already have an active shift.'})
    if Shift.objects.filter(vehicle=vehicle, end_time__isnull=True).exists():
        raise ValidationError({'error': 'This vehicle is already in use.'})
    shift = Shift.objects.create(driver=driver, vehicle=vehicle)
    record(user, "shift.started", shift)
    return shift


@transaction.atomic
def end_shift(user, shift_id, amount):
    require_role(user, Role.DRIVER)
    driver = Driver.objects.select_for_update().get(pk=driver_for(user).pk)
    shift = get_object_or_404(Shift.objects.select_for_update(), pk=shift_id, driver=driver)
    if shift.end_time:
        raise ValidationError({'error': 'This shift has already ended.'})
    if Trip.objects.filter(shift=shift, status__in=ACTIVE_TRIP_STATUSES).exists():
        raise ValidationError({'error': 'Finish or cancel the active trip before clocking out.'})
    shift.end_time = timezone.now()
    shift.turn_in_amount = amount
    shift.save(update_fields=['end_time', 'turn_in_amount'])
    record(user, 'shift.ended', shift, {'turn_in_amount': str(amount)})
    return shift


@transaction.atomic
def claim_trip(user, trip_id, driver_id=None):
    if user.profile.role == Role.DRIVER:
        driver = driver_for(user)
    else:
        require_role(user, *DISPATCH_ROLES)
        driver = get_object_or_404(Driver, pk=driver_id)
    driver = Driver.objects.select_for_update().get(pk=driver.pk)
    ensure_turn_in_cleared(driver)
    if not driver.user or not driver.user.is_active or not hasattr(driver.user, 'profile') or driver.user.profile.role != Role.DRIVER:
        raise ValidationError({'error': 'This driver needs an active Driver account.'})
    shift = active_shift(driver)
    if Trip.objects.filter(driver=driver, status__in=ACTIVE_TRIP_STATUSES).exists():
        raise ValidationError({'error': 'This driver already has an active trip.'})
    trip = get_object_or_404(Trip, pk=trip_id)
    if user.profile.role == Role.DRIVER and trip.pickup_time > timezone.now():
        raise ValidationError({'error': 'This reservation is not ready to accept.'})
    # Conditional update prevents a second acceptance from overwriting the first.
    changed = Trip.objects.filter(pk=trip_id, status=Trip.Status.OPEN, driver__isnull=True).update(
        driver=driver, vehicle=shift.vehicle, shift=shift, status=Trip.Status.ASSIGNED,
    )
    if not changed:
        raise ValidationError({'error': 'This call is no longer available. Refresh the board.'})
    trip.refresh_from_db()
    prepare_trip_assignment(trip)
    record(user, "trip.assigned", trip, {"driver_id": driver.pk, "shift_id": shift.pk})
    return trip


@transaction.atomic
def advance_trip(user, trip_id, action, amount=None, reason=''):
    trip = get_object_or_404(Trip.objects.select_for_update(), pk=trip_id)
    if user.profile.role == Role.DRIVER:
        if trip.driver_id != driver_for(user).pk:
            raise PermissionDenied('This trip is not assigned to you.')
    else:
        require_role(user, *DISPATCH_ROLES)
    if action == 'pickup' and trip.status == Trip.Status.ASSIGNED:
        trip.status = Trip.Status.IN_PROGRESS
        trip.picked_up_at = timezone.now()
    elif action == 'complete' and trip.status == Trip.Status.IN_PROGRESS:
        trip.status = Trip.Status.COMPLETED
        trip.drop_off_time = timezone.now()
        trip.fare_amount = amount
    elif action == 'cancel' and trip.status in [Trip.Status.OPEN, *ACTIVE_TRIP_STATUSES]:
        trip.status = Trip.Status.CANCELLED
        trip.cancellation_reason = reason
    else:
        raise ValidationError({'error': 'This action is not valid for the current trip status.'})
    trip.save()
    record(user, f"trip.{action}", trip, {"status": trip.status})
    return trip
