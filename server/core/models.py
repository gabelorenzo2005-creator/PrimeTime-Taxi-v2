from django.db import models 
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

    @property
    def shift_number(self):
        if self.pk is None:
            return None
        return 1000 + self.pk

class Trip(models.Model):
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
