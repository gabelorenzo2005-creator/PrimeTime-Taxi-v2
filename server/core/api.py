"""Operational API. Role checks remain on the server, regardless of the screen."""
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from .api_access import require_role
from .locations import workspace_locations
from .notifications import prepare_safety_alert
from django.conf import settings
from .models import Role, Driver, Shift, Trip, Vehicle, VehicleOwner, SafetyAlert
from .serializers import (DriverSerializer, VehicleSerializer, OwnerSerializer, ShiftSerializer, TripSerializer, TripInput, MoneyInput, IdInput, AlertInput, AlertSerializer)
from .operations import driver_for, start_shift, end_shift, claim_trip, advance_trip, DISPATCH_ROLES, PAYMENT_ROLES


def validated(cls, data):
    serializer = cls(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def user_data(user):
    return {'username': user.username, 'first_name': user.first_name, 'last_name': user.last_name, 'role': user.profile.role, 'role_display': user.profile.get_role_display(), 'must_change_password': user.profile.must_change_password}


class Logout(APIView):
    allow_password_change = True
    def post(self, request):
        request.auth.delete()
        return Response(status=204)


class PasswordChange(APIView):
    allow_password_change = True
    def post(self, request):
        old = request.data.get('current_password')
        new = request.data.get('new_password')
        if not isinstance(old, str) or not request.user.check_password(old):
            raise ValidationError({'error': 'Current password is incorrect.'})
        if not isinstance(new, str):
            raise ValidationError({'error': 'Enter a new password.'})
        try:
            validate_password(new, request.user)
        except DjangoValidationError as error:
            raise ValidationError({'error': error.messages})
        with transaction.atomic():
            request.user.set_password(new)
            request.user.save(update_fields=['password'])
            request.user.profile.must_change_password = False
            request.user.profile.save(update_fields=['must_change_password'])
            Token.objects.filter(user=request.user).delete()
            token = Token.objects.create(user=request.user)
        return Response({**user_data(request.user), 'token': token.key})


class Workspace(APIView):
    def get(self, request):
        now = timezone.now()
        trips = Trip.objects.select_related('driver', 'vehicle', 'shift')
        shifts = Shift.objects.select_related('driver', 'vehicle')
        alerts = SafetyAlert.objects.select_related('driver')
        drivers = Driver.objects.select_related('user__profile')
        me = None
        if request.user.profile.role == Role.DRIVER:
            me = driver_for(request.user)
            trips = trips.filter(Q(driver=me) | Q(status=Trip.Status.OPEN, pickup_time__lte=now))
            shifts = shifts.filter(driver=me)
            alerts = alerts.filter(driver=me)
            drivers = drivers.filter(pk=me.pk)
        # Active work always appears; only historical records are bounded.
        active = trips.filter(status__in=['OPEN', 'ASSIGNED', 'IN_PROGRESS']).order_by('pickup_time')
        history = trips.filter(status__in=['COMPLETED', 'CANCELLED']).order_by('-id')[:100]
        shift_records = list(shifts.filter(end_time__isnull=True)) + list(shifts.filter(end_time__isnull=False).order_by('-id')[:100])
        alert_records = list(alerts.filter(resolved_at__isnull=True).order_by('-id')) + list(alerts.filter(resolved_at__isnull=False).order_by('-id')[:100])
        driver_records = list(drivers.order_by('call_number'))
        return Response({
            'user': user_data(request.user), 'driver_id': me.pk if me else None, 'server_time': now,
            'trips': TripSerializer(list(active) + list(history), many=True).data,
            'shifts': ShiftSerializer(shift_records, many=True).data,
            'alerts': AlertSerializer(alert_records, many=True).data,
            'driver_locations': workspace_locations(driver_records, now),
            'gps_policy': {'online_seconds': settings.GPS_ONLINE_SECONDS, 'offline_seconds': settings.GPS_OFFLINE_SECONDS},
            'drivers': DriverSerializer(driver_records, many=True).data,
            'vehicles': VehicleSerializer(Vehicle.objects.select_related('owner').order_by('car_number'), many=True).data,
            'owners': OwnerSerializer(VehicleOwner.objects.order_by('name'), many=True).data if not me else [],
        })


class Shifts(APIView):
    def post(self, request):
        data = validated(IdInput, {'id': request.data.get('vehicle_id')})
        try:
            result = start_shift(request.user, data['id'])
        except IntegrityError:
            raise ValidationError({'error': 'The driver or vehicle is already on shift.'})
        return Response(ShiftSerializer(result).data, status=201)


class ShiftAction(APIView):
    def post(self, request, pk, action):
        if action == 'end':
            result = end_shift(request.user, pk, validated(MoneyInput, request.data)['amount'])
        elif action in ['approve', 'reject']:
            require_role(request.user, *PAYMENT_ROLES)
            with transaction.atomic():
                result = get_object_or_404(Shift.objects.select_for_update(), pk=pk)
                if not result.end_time:
                    raise ValidationError({'error': 'The shift must end before reviewing its turn-in.'})
                result.turn_in_paid = action == 'approve'
                result.turn_in_cleared = action == 'approve'
                result.save(update_fields=['turn_in_paid', 'turn_in_cleared'])
        else:
            raise ValidationError({'error': 'Unknown shift action.'})
        return Response(ShiftSerializer(result).data)


class Trips(APIView):
    def post(self, request):
        require_role(request.user, *DISPATCH_ROLES)
        data = validated(TripInput, request.data)
        data.setdefault('pickup_time', timezone.now())
        return Response(TripSerializer(Trip.objects.create(**data)).data, status=201)


class TripAction(APIView):
    def post(self, request, pk, action):
        if action in ['accept', 'assign']:
            driver_id = None
            if action == 'accept':
                require_role(request.user, Role.DRIVER)
            else:
                require_role(request.user, *DISPATCH_ROLES)
                driver_id = validated(IdInput, {'id': request.data.get('driver_id')})['id']
            try:
                result = claim_trip(request.user, pk, driver_id)
            except IntegrityError:
                raise ValidationError({'error': 'The driver already has an active trip.'})
        elif action in ['pickup', 'complete', 'cancel']:
            amount = validated(MoneyInput, request.data)['amount'] if action == 'complete' else None
            reason = request.data.get('reason', '')
            if action == 'cancel' and (not isinstance(reason, str) or not reason.strip() or len(reason) > 5000):
                raise ValidationError({'error': 'Enter a cancellation reason (up to 5000 characters).'})
            result = advance_trip(request.user, pk, action, amount, reason)
        else:
            raise ValidationError({'error': 'Unknown trip action.'})
        return Response(TripSerializer(result).data)


class Alerts(APIView):
    def post(self, request):
        require_role(request.user, Role.DRIVER)
        data = validated(AlertInput, request.data)
        with transaction.atomic():
            result = SafetyAlert.objects.create(driver=driver_for(request.user), **data)
            prepare_safety_alert(result)
        return Response(AlertSerializer(result).data, status=201)


class AlertAction(APIView):
    def post(self, request, pk, action):
        require_role(request.user, Role.DISPATCHER, Role.ADMIN, Role.IT)
        with transaction.atomic():
            result = get_object_or_404(SafetyAlert.objects.select_for_update(), pk=pk)
            if action not in ['acknowledge', 'resolve']:
                raise ValidationError({'error': 'Unknown alert action.'})
            if not result.acknowledged_at:
                result.acknowledged_at = timezone.now()
                result.acknowledged_by = request.user
            if action == 'resolve' and not result.resolved_at:
                result.resolved_at = timezone.now()
                result.resolved_by = request.user
            result.save()
        return Response(AlertSerializer(result).data)


class Records(APIView):
    """Admin/IT can edit records without changing account permissions here."""
    resources = {'drivers': (Driver, DriverSerializer), 'vehicles': (Vehicle, VehicleSerializer), 'owners': (VehicleOwner, OwnerSerializer)}
    def save_record(self, request, resource, pk=None):
        require_role(request.user, Role.ADMIN, Role.IT)
        if resource not in self.resources:
            raise ValidationError({'error': 'Unknown record type.'})
        model, cls = self.resources[resource]
        instance = get_object_or_404(model, pk=pk) if pk else None
        serializer = cls(instance, data=request.data, partial=pk is not None)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=200 if pk else 201)
    def post(self, request, resource):
        return self.save_record(request, resource)
    def patch(self, request, resource, pk):
        return self.save_record(request, resource, pk)
