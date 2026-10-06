"""Validation and JSON records, kept separate from business rules."""
from rest_framework import serializers
from .models import Driver, Vehicle, VehicleOwner, Shift, Trip, SafetyAlert


class DriverSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    username = serializers.CharField(source='user.username', read_only=True, default=None)
    def get_name(self, obj):
        return f'{obj.first_name} {obj.last_name}'.strip()
    class Meta:
        model = Driver
        fields = ['id', 'name', 'first_name', 'last_name', 'call_number', 'hack_license_number', 'hack_license_expiration_date', 'phone_number', 'email', 'notes', 'username']


class OwnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleOwner
        fields = ['id', 'name']


class VehicleSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source='owner.name', read_only=True)
    class Meta:
        model = Vehicle
        fields = ['id', 'car_number', 'license_plate_number', 'owner', 'owner_name']


class ShiftSerializer(serializers.ModelSerializer):
    driver_name = serializers.SerializerMethodField()
    call_number = serializers.CharField(source='driver.call_number')
    car_number = serializers.CharField(source='vehicle.car_number')
    def get_driver_name(self, obj):
        return f'{obj.driver.first_name} {obj.driver.last_name}'.strip()
    class Meta:
        model = Shift
        fields = ['id', 'shift_number', 'driver', 'driver_name', 'call_number', 'vehicle', 'car_number', 'start_time', 'end_time', 'turn_in_amount', 'turn_in_paid', 'turn_in_cleared']


class TripSerializer(serializers.ModelSerializer):
    driver_name = serializers.SerializerMethodField()
    call_number = serializers.CharField(source='driver.call_number', default=None)
    car_number = serializers.CharField(source='vehicle.car_number', default=None)
    def get_driver_name(self, obj):
        return f'{obj.driver.first_name} {obj.driver.last_name}'.strip() if obj.driver else None
    class Meta:
        model = Trip
        fields = ['id', 'status', 'driver', 'driver_name', 'call_number', 'vehicle', 'car_number', 'shift', 'pick_up_location', 'drop_off_location', 'pickup_time', 'picked_up_at', 'drop_off_time', 'fare_amount', 'trip_notes', 'cancellation_reason', 'created_at']


class TripInput(serializers.Serializer):
    pick_up_location = serializers.CharField(max_length=255)
    drop_off_location = serializers.CharField(max_length=255)
    pickup_time = serializers.DateTimeField(required=False)
    trip_notes = serializers.CharField(required=False, allow_blank=True, max_length=5000)


class MoneyInput(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)


class IdInput(serializers.Serializer):
    id = serializers.IntegerField(min_value=1)


class AlertInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=SafetyAlert.Kind.choices)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=5000)


class AlertSerializer(serializers.ModelSerializer):
    driver_name = serializers.SerializerMethodField()
    call_number = serializers.CharField(source='driver.call_number')
    def get_driver_name(self, obj):
        return f'{obj.driver.first_name} {obj.driver.last_name}'.strip()
    class Meta:
        model = SafetyAlert
        fields = ['id', 'driver', 'driver_name', 'call_number', 'kind', 'notes', 'created_at', 'acknowledged_at', 'resolved_at']
