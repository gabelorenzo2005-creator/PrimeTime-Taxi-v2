"""Native client inputs. Identity, shift ownership and APNs topic trust stay server-side."""
import math
import re
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from .models import PushDevice


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError({field: 'Unknown field.' for field in sorted(unknown)})
        return super().to_internal_value(data)


class FiniteFloat(serializers.FloatField):
    def to_internal_value(self, data):
        if isinstance(data, bool):
            raise serializers.ValidationError('Enter a finite number.')
        value = super().to_internal_value(data)
        if not math.isfinite(value):
            raise serializers.ValidationError('Enter a finite number.')
        return value


class AwareTimestamp(serializers.DateTimeField):
    def to_internal_value(self, data):
        try:
            parsed = parse_datetime(data) if isinstance(data, str) else data
        except (ValueError, TypeError):
            parsed = None
        if parsed is None or not hasattr(parsed, 'tzinfo') or timezone.is_naive(parsed):
            raise serializers.ValidationError('Use an ISO 8601 timestamp with Z or a UTC offset.')
        return super().to_internal_value(data)


class GPSReportInput(StrictInput):
    shift_id = serializers.IntegerField(min_value=1)
    latitude = FiniteFloat(min_value=-90, max_value=90)
    longitude = FiniteFloat(min_value=-180, max_value=180)
    accuracy = FiniteFloat(min_value=0)
    heading = FiniteFloat(min_value=0, required=False, allow_null=True)
    speed = FiniteFloat(min_value=0, required=False, allow_null=True)
    timestamp = AwareTimestamp()

    def validate_heading(self, value):
        if value is not None and value >= 360:
            raise serializers.ValidationError('Heading must be less than 360 degrees.')
        return value

    def validate_timestamp(self, value):
        if value > timezone.now() + timedelta(seconds=settings.GPS_MAX_FUTURE_SECONDS):
            raise serializers.ValidationError('The fix timestamp is too far in the future.')
        return value


class DeviceRegistrationInput(StrictInput):
    installation_id = serializers.UUIDField()
    apns_token = serializers.CharField(max_length=512, trim_whitespace=False)
    environment = serializers.ChoiceField(choices=PushDevice.Environment.choices)
    topic = serializers.CharField(max_length=255)

    def validate_apns_token(self, value):
        # Apple tokens are opaque bytes of variable length; do not assume 32 bytes.
        if not re.fullmatch(r'(?:[0-9a-fA-F]{2})+', value):
            raise serializers.ValidationError('Send the APNs token as an even-length hexadecimal string.')
        return value.lower()

    def validate_topic(self, value):
        if value not in settings.APNS_ALLOWED_TOPICS:
            raise serializers.ValidationError('This APNs topic is not configured on the server.')
        return value


class PushDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushDevice
        # Never return raw push tokens through list or registration responses.
        fields = ['id', 'installation_id', 'environment', 'topic', 'is_active', 'revision', 'created_at', 'last_registered_at', 'disabled_at']
        read_only_fields = fields
