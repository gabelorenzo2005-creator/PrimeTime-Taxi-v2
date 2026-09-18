from django.db import models 


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
    