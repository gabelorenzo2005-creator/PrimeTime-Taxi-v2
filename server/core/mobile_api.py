"""Additive native-mobile endpoints; use the existing API authentication and role policy."""
from rest_framework.response import Response
from rest_framework.views import APIView
from .api import validated
from .api_access import require_role
from .models import PushDevice, Role
from .mobile_serializers import GPSReportInput, DeviceRegistrationInput, PushDeviceSerializer
from .locations import report_location, location_data
from .devices import register_device, unregister_device


class DriverGPS(APIView):
    def post(self, request):
        require_role(request.user, Role.DRIVER)
        location, accepted = report_location(request.user, validated(GPSReportInput, request.data))
        return Response({
            'accepted': accepted,
            'reason': 'new_fix' if accepted else 'older_or_duplicate_fix',
            'location': location_data(location),
        })


class Devices(APIView):
    def get(self, request):
        devices = PushDevice.objects.filter(user=request.user).order_by('id')
        return Response({'devices': PushDeviceSerializer(devices, many=True).data})

    def post(self, request):
        device, created = register_device(request.user, validated(DeviceRegistrationInput, request.data))
        return Response(PushDeviceSerializer(device).data, status=201 if created else 200)


class DeviceDetail(APIView):
    # Allow unregistering during a required password change; registration remains blocked.
    allow_password_change = True
    def delete(self, request, pk):
        unregister_device(request.user, pk)
        return Response(status=204)
