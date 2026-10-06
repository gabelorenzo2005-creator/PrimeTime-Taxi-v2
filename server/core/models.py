import uuid
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

class VehicleOwner(models.Model):
    name = models.CharField(max_length=100)

class Vehicle(models.Model):
    car_number = models.CharField(max_length=3, unique=True)
    license_plate_number = models.CharField(max_length=7, unique=True)
    
    owner = models.ForeignKey(
        VehicleOwner,
        on_delete=models.PROTECT,
        related_name='vehicles'
    )
class Driver(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    call_number = models.CharField(max_length=10, unique=True)
    hack_license_number = models.CharField(max_length=10, unique=True)
    phone_number = models.CharField(max_length=20, unique=True)
    email = models.EmailField(max_length=100, unique=True)
    hack_license_expiration_date = models.DateField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    user = models.OneToOneField(
        User, 
        on_delete=models.PROTECT,
        related_name='driver_profile',
        blank=True,
        null=True
    )
    
class Shift(models.Model):
    driver = models.ForeignKey(
        Driver,
        on_delete=models.PROTECT,
        related_name='shifts'
    )
    
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.PROTECT,
        related_name='shifts'
    )


    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(blank=True, null=True)
    turn_in_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        blank=True, 
        null=True
        )
    turn_in_paid = models.BooleanField(default=False)
    turn_in_cleared = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['driver'], condition=models.Q(end_time__isnull=True), name='one_open_shift_per_driver'),
            models.UniqueConstraint(fields=['vehicle'], condition=models.Q(end_time__isnull=True), name='one_open_shift_per_vehicle'),
        ]

    @property
    def shift_number(self):
        if self.pk is None:
            return None
        return 1000 + self.pk

class Trip(models.Model):
    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open'
        ASSIGNED = 'ASSIGNED', 'Assigned'
        IN_PROGRESS = 'IN_PROGRESS', 'In progress'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    picked_up_at = models.DateTimeField(blank=True, null=True)
    cancellation_reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['driver'], condition=models.Q(status__in=['ASSIGNED', 'IN_PROGRESS']), name='one_active_trip_per_driver'),
        ]

    driver = models.ForeignKey(
        Driver,
        on_delete=models.PROTECT,
        related_name='trips',
        blank=True,
        null=True
    )
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.PROTECT,
        related_name='trips',
        blank=True,
        null=True
    )
    shift = models.ForeignKey(
        Shift,
        on_delete=models.PROTECT,
        related_name='trips',
        blank=True,
        null=True
    )
    pick_up_location = models.CharField(max_length=255)
    drop_off_location = models.CharField(max_length=255)
    fare_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        blank=True,
        null=True
        )
    pickup_time = models.DateTimeField()
    drop_off_time = models.DateTimeField(blank=True, null=True)
    trip_notes = models.TextField(blank=True, null=True)

class Role(models.TextChoices):
    DRIVER = 'DRIVER', 'Driver'
    DISPATCHER = 'DISPATCHER', 'Dispatcher'
    ADMIN = 'ADMIN', 'Admin'
    IT = 'IT', 'Technician'

class AccountProfile(models.Model): 
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE,
        related_name='profile'
        )

    role = models.CharField(
        max_length=20,
        choices=Role.choices
        )   

    must_change_password = models.BooleanField(default=False)


class SafetyAlert(models.Model):
    class Kind(models.TextChoices):
        PANIC = 'PANIC', 'Panic'
        PULLED_OVER = 'PULLED_OVER', 'Pulled over'
        ACCIDENT = 'ACCIDENT', 'Accident'
        BREAKDOWN = 'BREAKDOWN', 'Breakdown'
        OTHER = 'OTHER', 'Other'

    driver = models.ForeignKey(Driver, on_delete=models.PROTECT, related_name='safety_alerts')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='acknowledged_alerts')
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='resolved_alerts')


class DriverLocation(models.Model):
    """Latest real fix for a shift; never infer coordinates from clock-in."""
    shift = models.OneToOneField(Shift, on_delete=models.PROTECT, related_name='latest_location')
    latitude = models.FloatField()
    longitude = models.FloatField()
    accuracy = models.FloatField(help_text='Horizontal accuracy in metres.')
    heading = models.FloatField(null=True, blank=True, help_text='Degrees clockwise from true north.')
    speed = models.FloatField(null=True, blank=True, help_text='Metres per second.')
    timestamp = models.DateTimeField(help_text='Device location-fix time, not upload time.')
    received_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(latitude__gte=-90, latitude__lte=90), name='gps_latitude_range'),
            models.CheckConstraint(condition=models.Q(longitude__gte=-180, longitude__lte=180), name='gps_longitude_range'),
            models.CheckConstraint(condition=models.Q(accuracy__gte=0), name='gps_accuracy_nonnegative'),
            models.CheckConstraint(condition=models.Q(heading__isnull=True) | models.Q(heading__gte=0, heading__lt=360), name='gps_heading_range'),
            models.CheckConstraint(condition=models.Q(speed__isnull=True) | models.Q(speed__gte=0), name='gps_speed_nonnegative'),
        ]


class PushDevice(models.Model):
    """An installation's APNs registration. Ownership is immutable through the API."""
    class Environment(models.TextChoices):
        SANDBOX = 'sandbox', 'Sandbox'
        PRODUCTION = 'production', 'Production'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='push_devices')
    installation_id = models.UUIDField(help_text='Random UUID generated and persisted by the native app.')
    apns_token = models.CharField(max_length=512, help_text='Hexadecimal APNs device token; treat as sensitive data.')
    environment = models.CharField(max_length=10, choices=Environment.choices)
    topic = models.CharField(max_length=255, help_text='Allowed app bundle identifier / APNs topic.')
    is_active = models.BooleanField(default=True)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    last_registered_at = models.DateTimeField(default=timezone.now)
    disabled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'installation_id', 'environment', 'topic'], name='device_per_account_installation'),
            models.UniqueConstraint(fields=['installation_id', 'environment', 'topic'], condition=models.Q(is_active=True), name='one_active_installation_owner'),
            models.UniqueConstraint(fields=['apns_token', 'environment', 'topic'], condition=models.Q(is_active=True), name='one_active_apns_token_owner'),
        ]


class NotificationEvent(models.Model):
    """Durable intent for a recipient account. No provider or delivery claim exists yet."""
    class Kind(models.TextChoices):
        TRIP_ASSIGNED = 'TRIP_ASSIGNED', 'Trip assigned'
        SAFETY_ALERT = 'SAFETY_ALERT', 'Safety alert'

    recipient = models.ForeignKey(User, on_delete=models.PROTECT, related_name='notification_events')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    trip = models.ForeignKey(Trip, on_delete=models.PROTECT, null=True, blank=True, related_name='notification_events')
    safety_alert = models.ForeignKey(SafetyAlert, on_delete=models.PROTECT, null=True, blank=True, related_name='notification_events')
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    status = models.CharField(max_length=30, default='PENDING_APNS_INTEGRATION', choices=[(s, s.replace('_', ' ').title()) for s in ['PENDING_APNS_INTEGRATION', 'PENDING', 'RETRY', 'WAITING_FOR_DEVICES', 'ACCEPTED_BY_APNS', 'PARTIAL', 'FAILED', 'SKIPPED', 'EXPIRED']])

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(
                models.Q(kind='TRIP_ASSIGNED', trip__isnull=False, safety_alert__isnull=True)
                | models.Q(kind='SAFETY_ALERT', trip__isnull=True, safety_alert__isnull=False)
            ), name='notification_has_matching_subject'),
            models.CheckConstraint(condition=models.Q(status__in=['PENDING_APNS_INTEGRATION', 'PENDING', 'RETRY', 'WAITING_FOR_DEVICES', 'ACCEPTED_BY_APNS', 'PARTIAL', 'FAILED', 'SKIPPED', 'EXPIRED']), name='notification_valid_status'),
            models.UniqueConstraint(fields=['recipient', 'kind', 'trip'], name='one_trip_event_per_recipient'),
            models.UniqueConstraint(fields=['recipient', 'kind', 'safety_alert'], name='one_alert_event_per_recipient'),
        ]
        indexes = [models.Index(fields=['recipient', 'status', 'created_at'], name='notification_pending_idx')]


class PushDelivery(models.Model):
    event = models.ForeignKey(NotificationEvent, on_delete=models.PROTECT, related_name='deliveries')
    device = models.ForeignKey(PushDevice, on_delete=models.PROTECT, related_name='deliveries')
    device_revision = models.PositiveIntegerField()
    apns_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=24, default='PENDING')
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    lease_until = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['event', 'device', 'device_revision'], name='one_delivery_per_device_revision')]
        indexes = [models.Index(fields=['status', 'next_attempt_at'], name='push_delivery_due_idx')]


class PushAttempt(models.Model):
    delivery = models.ForeignKey(PushDelivery, on_delete=models.PROTECT, related_name='attempts')
    number = models.PositiveIntegerField()
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=24, default='STARTED')
    http_status = models.PositiveIntegerField(null=True, blank=True)
    reason = models.CharField(max_length=100, blank=True)
    provider_apns_id = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['delivery', 'number'], name='one_number_per_push_attempt')]
