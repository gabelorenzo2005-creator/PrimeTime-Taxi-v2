"""Bounded, role-scoped history; no dashboard impersonation permissions."""
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from .api_access import require_role
from .models import Role, Trip, Shift, Vehicle, VehicleNote, AuditRecord, SafetyAlert
from .operations import driver_for
from .serializers import TripSerializer, ShiftSerializer, AlertSerializer
from .audit import record


class Query(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=50)
    q = serializers.CharField(max_length=255, required=False)
    driver = serializers.IntegerField(min_value=1, required=False)
    vehicle = serializers.IntegerField(min_value=1, required=False)
    since = serializers.DateTimeField(required=False)
    until = serializers.DateTimeField(required=False)
    status = serializers.ChoiceField(choices=Trip.Status.choices, required=False)


def page(request, queryset, serializer, date_field, searchable=(), filters=()):
    query = Query(data=request.query_params)
    query.is_valid(raise_exception=True)
    data = query.validated_data
    if data.get('since') and data.get('until') and data['since'] > data['until']:
        raise ValidationError({'error': 'since must not be later than until.'})
    for field in filters:
        if field in data:
            queryset = queryset.filter(**{field: data[field]})
    for parameter, comparison in [('since', 'gte'), ('until', 'lte')]:
        if parameter in data:
            queryset = queryset.filter(**{f'{date_field}__{comparison}': data[parameter]})
    if data.get('q') and searchable:
        condition = Q()
        for field in searchable:
            condition |= Q(**{f'{field}__icontains': data['q']})
        queryset = queryset.filter(condition)
    total = queryset.count()
    start = (data['page'] - 1) * data['page_size']
    return Response({'count': total, 'page': data['page'], 'page_size': data['page_size'],
                     'results': serializer(queryset.order_by(f'-{date_field}', '-pk')[start:start + data['page_size']], many=True).data})


class TripHistory(APIView):
    def get(self, request, pk=None):
        trips = Trip.objects.select_related('driver', 'vehicle')
        if request.user.profile.role == Role.DRIVER:
            trips = trips.filter(driver=driver_for(request.user))
        if pk is not None:
            return Response(TripSerializer(get_object_or_404(trips, pk=pk)).data)
        return page(request, trips, TripSerializer, 'pickup_time',
                    ('pick_up_location', 'drop_off_location', 'trip_notes', 'driver__call_number', 'vehicle__car_number'),
                    ('driver', 'vehicle', 'status'))


class Reservations(APIView):
    def get(self, request):
        from django.utils import timezone
        require_role(request.user, Role.DISPATCHER, Role.ADMIN, Role.IT)
        return page(request, Trip.objects.select_related('driver', 'vehicle').filter(
            pickup_time__gt=timezone.now(), status__in=[Trip.Status.OPEN, Trip.Status.ASSIGNED]),
            TripSerializer, 'pickup_time', ('pick_up_location', 'drop_off_location', 'trip_notes'), ('driver', 'vehicle', 'status'))


class ShiftHistory(APIView):
    def get(self, request, pk=None):
        shifts = Shift.objects.select_related('driver', 'vehicle')
        if request.user.profile.role == Role.DRIVER:
            shifts = shifts.filter(driver=driver_for(request.user))
        if pk is not None:
            return Response(ShiftSerializer(get_object_or_404(shifts, pk=pk)).data)
        return page(request, shifts, ShiftSerializer, 'start_time',
                    ('driver__call_number', 'driver__first_name', 'driver__last_name', 'vehicle__car_number'), ('driver', 'vehicle'))


class NoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleNote
        fields = ['id', 'vehicle', 'author', 'text', 'created_at']
        read_only_fields = ['id', 'vehicle', 'author', 'created_at']
    text = serializers.CharField(max_length=5000)


class VehicleNotes(APIView):
    def get(self, request, pk):
        require_role(request.user, Role.ADMIN, Role.IT)
        get_object_or_404(Vehicle, pk=pk)
        return page(request, VehicleNote.objects.filter(vehicle_id=pk), NoteSerializer, 'created_at', ('text',))

    @transaction.atomic
    def post(self, request, pk):
        require_role(request.user, Role.ADMIN, Role.IT)
        vehicle = get_object_or_404(Vehicle, pk=pk)
        serializer = NoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = serializer.save(vehicle=vehicle, author=request.user)
        record(request.user, 'vehicle.note_added', vehicle, {'note_id': note.pk})
        return Response(NoteSerializer(note).data, status=201)


class AuditSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditRecord
        fields = ['id', 'actor', 'action', 'subject_type', 'subject_id', 'details', 'created_at']


class AuditHistory(APIView):
    def get(self, request):
        require_role(request.user, Role.ADMIN, Role.IT)
        return page(request, AuditRecord.objects.all(), AuditSerializer, 'created_at', ('action', 'subject_type'))


class TurnInHistory(APIView):
    def get(self, request, pk):
        shifts = Shift.objects.all()
        if request.user.profile.role == Role.DRIVER:
            shifts = shifts.filter(driver=driver_for(request.user))
        else:
            require_role(request.user, Role.ADMIN, Role.IT)
        shift = get_object_or_404(shifts, pk=pk)
        return page(request, AuditRecord.objects.filter(subject_type='core.shift', subject_id=shift.pk,
                    action__in=['shift.ended', 'turn_in.approve', 'turn_in.reject']), AuditSerializer, 'created_at')


class AlertHistory(APIView):
    def get(self, request, pk=None):
        alerts = SafetyAlert.objects.select_related('driver')
        if request.user.profile.role == Role.DRIVER:
            alerts = alerts.filter(driver=driver_for(request.user))
        if pk is not None:
            return Response(AlertSerializer(get_object_or_404(alerts, pk=pk)).data)
        return page(request, alerts, AlertSerializer, 'created_at',
                    ('notes', 'kind', 'driver__call_number', 'driver__first_name', 'driver__last_name'), ('driver',))
