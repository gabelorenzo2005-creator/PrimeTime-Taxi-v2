"""Real GPS ingestion and computed presence, without a background tracker or map UI."""
from django.conf import settings
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .api_access import require_role
from .models import Driver, DriverLocation, Role, Shift
from .operations import driver_for


def location_data(location):
    if location is None:
        return None
    return {
        'latitude': location.latitude, 'longitude': location.longitude,
        'accuracy': location.accuracy, 'heading': location.heading, 'speed': location.speed,
        'timestamp': location.timestamp, 'received_at': location.received_at,
        'shift_id': location.shift_id, 'vehicle_id': location.shift.vehicle_id,
        'car_number': location.shift.vehicle.car_number,
    }


@transaction.atomic
def report_location(user, data):
    require_role(user, Role.DRIVER)
    driver = driver_for(user)
    # Same shift lock used by clock-out. A delayed prior-shift upload cannot attach
    # to a newer shift or to a vehicle selected by the client.
    shift = Shift.objects.select_for_update().filter(
        pk=data['shift_id'], driver=driver, end_time__isnull=True,
    ).first()
    if shift is None:
        raise ValidationError({'error': 'Report GPS only for your own active shift.'})
    if data['timestamp'] < shift.start_time:
        raise ValidationError({'timestamp': 'The fix timestamp predates this shift.'})
    values = {name: data.get(name) for name in ['latitude', 'longitude', 'accuracy', 'heading', 'speed', 'timestamp']}
    values['received_at'] = timezone.now()
    location, created = DriverLocation.objects.get_or_create(shift=shift, defaults=values)
    accepted = created
    if not created:
        accepted = bool(DriverLocation.objects.filter(pk=location.pk, timestamp__lt=data['timestamp']).update(**values))
        location.refresh_from_db()
    return location, accepted


def workspace_locations(drivers, now):
    """Every scoped driver appears, including those off shift or awaiting a fix."""
    drivers = list(drivers)
    driver_ids = [driver.pk for driver in drivers]
    active = {shift.driver_id: shift for shift in Shift.objects.filter(driver_id__in=driver_ids, end_time__isnull=True).select_related('vehicle')}
    # Only latest-per-shift rows are stored. Pick the newest shift's fix for each
    # driver; an active shift without a fix never inherits the previous shift's fix.
    newest_fix = DriverLocation.objects.filter(shift__driver_id=OuterRef('pk')).order_by('-shift__start_time', '-shift_id').values('pk')[:1]
    fix_ids = Driver.objects.filter(pk__in=driver_ids).annotate(latest_fix_id=Subquery(newest_fix)).values_list('latest_fix_id', flat=True)
    fixes = {
        fix.shift.driver_id: fix
        for fix in DriverLocation.objects.filter(pk__in=fix_ids).select_related('shift__vehicle')
    }
    result = []
    for driver in drivers:
        shift = active.get(driver.pk)
        fix = fixes.get(driver.pk)
        if shift is not None and (fix is None or fix.shift_id != shift.pk):
            fix = None
        fix_age = max(0, (now - fix.timestamp).total_seconds()) if fix else None
        received_age = max(0, (now - fix.received_at).total_seconds()) if fix else None
        status, reason = 'offline', 'off_shift'
        if shift is not None:
            if fix is None:
                reason = 'awaiting_fix'
            else:
                age = max(fix_age, received_age)
                if age <= settings.GPS_ONLINE_SECONDS:
                    status, reason = 'online', 'fresh_fix'
                elif age <= settings.GPS_OFFLINE_SECONDS:
                    status, reason = 'stale', 'stale_fix'
                else:
                    reason = 'fix_timeout'
        # Deactivated/unlinked/non-driver accounts are never presented as online.
        if not driver.user or not driver.user.is_active or not hasattr(driver.user, 'profile') or driver.user.profile.role != Role.DRIVER:
            status, reason = 'offline', 'account_unavailable'
        result.append({
            'driver_id': driver.pk, 'call_number': driver.call_number,
            'driver_name': f'{driver.first_name} {driver.last_name}'.strip(),
            'shift_id': shift.pk if shift else None,
            'vehicle_id': shift.vehicle_id if shift else None,
            'car_number': shift.vehicle.car_number if shift else None,
            'status': status, 'status_reason': reason,
            'fix_age_seconds': fix_age, 'received_age_seconds': received_age,
            'location': location_data(fix),
        })
    return result
