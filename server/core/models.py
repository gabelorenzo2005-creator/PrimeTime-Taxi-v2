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
