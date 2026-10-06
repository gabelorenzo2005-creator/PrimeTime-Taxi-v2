"""Editable company records and explicit account role assignments."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from .models import AccountProfile, Driver, Shift, Trip, Vehicle, VehicleOwner, SafetyAlert


class AccountProfileInline(admin.StackedInline):
    model = AccountProfile
    extra = 1
    max_num = 1


admin.site.unregister(User)


@admin.register(User)
class CompanyUserAdmin(UserAdmin):
    inlines = [AccountProfileInline]


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ("call_number", "first_name", "last_name", "user")
    search_fields = ("call_number", "first_name", "last_name")


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("car_number", "license_plate_number", "owner")
    search_fields = ("car_number", "license_plate_number")


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("shift_number", "driver", "vehicle", "start_time", "end_time", "turn_in_paid", "turn_in_cleared")
    list_filter = ("turn_in_paid", "turn_in_cleared")


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ("id", "driver", "vehicle", "pick_up_location", "drop_off_location", "pickup_time", "fare_amount")
    search_fields = ("pick_up_location", "drop_off_location")


admin.site.register(VehicleOwner)

admin.site.register(SafetyAlert)
