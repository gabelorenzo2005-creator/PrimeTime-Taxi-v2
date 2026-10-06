"""Transport is always mocked; these tests never contact Apple."""
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from io import StringIO
from unittest.mock import Mock, patch
from uuid import uuid4
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from .test_mobile import MobileFixture
from .models import Trip, NotificationEvent, PushDevice, PushDelivery, PushAttempt, SafetyAlert
from .apns_delivery import process_event, prepare_deliveries, claim_attempt, finish_attempt
from .apns_transport import APNsTransport, APNsResult

TOPIC = 'com.primetimetaxi.app'

@override_settings(APNS_ALLOWED_TOPICS=[TOPIC], APNS_MAX_ATTEMPTS=3, APNS_EVENT_TTL_SECONDS=3600, APNS_LEASE_SECONDS=120)
class DeliveryTests(MobileFixture):
    def setUp(self):
        self.now = timezone.now()
        trip = Trip.objects.create(driver=self.driver, vehicle=self.vehicle, status='ASSIGNED', pick_up_location='Pickup', drop_off_location='Dropoff', pickup_time=self.now)
        self.event = NotificationEvent.objects.create(recipient=self.driver_user, kind='TRIP_ASSIGNED', trip=trip)
        self.device = PushDevice.objects.create(user=self.driver_user, **self.registration())
        self.transport = Mock()
        self.transport.send.return_value = APNsResult(200, apns_id=str(uuid4()))
        self.now = timezone.now() + timedelta(seconds=1)

    def run_event(self, now=None):
        return process_event(self.event.pk, self.transport, now=now or self.now)

    def test_acceptance_not_device_delivery_and_idempotent_rerun(self):
        self.assertEqual(self.run_event(), 'ACCEPTED_BY_APNS')
        self.assertEqual(self.run_event(), 'ACCEPTED_BY_APNS')
        self.assertEqual(self.transport.send.call_count, 1)
        self.assertEqual(PushAttempt.objects.get().status, 'ACCEPTED_BY_APNS')
        self.assertEqual(PushDelivery.objects.get().device_revision, self.device.revision)
        payload = self.transport.send.call_args.kwargs['payload']
        self.assertNotIn('Pickup', str(payload))
        self.assertEqual(payload['event_id'], str(self.event.pk))

    def test_multiple_devices_and_partial_result_owner_only(self):
        PushDevice.objects.create(user=self.driver_user, **self.registration(apns_token='cd' * 32))
        PushDevice.objects.create(user=self.other_user, **self.registration(apns_token='ef' * 32))
        self.transport.send.side_effect = [APNsResult(200), APNsResult(400, 'BadDeviceToken')]
        self.assertEqual(self.run_event(), 'PARTIAL')
        self.assertEqual(PushDelivery.objects.count(), 2)
        self.assertEqual(PushDevice.objects.filter(is_active=True).count(), 2)

    def test_network_retry_keeps_same_apns_identity_and_waits_until_due(self):
        self.transport.send.side_effect = RuntimeError('secret/token should never persist')
        self.assertEqual(self.run_event(), 'RETRY')
        delivery = PushDelivery.objects.get()
        apns_id = delivery.apns_id
        self.run_event(self.now + timedelta(seconds=30))
        self.assertEqual(self.transport.send.call_count, 1)
        self.transport.send.side_effect = None
        self.transport.send.return_value = APNsResult(200)
        self.assertEqual(self.run_event(self.now + timedelta(seconds=61)), 'ACCEPTED_BY_APNS')
        delivery.refresh_from_db()
        self.assertEqual(delivery.apns_id, apns_id)
        self.assertEqual(delivery.attempt_count, 2)
        self.assertEqual(PushAttempt.objects.first().reason, 'TransportError')

    def test_retry_after_and_server_backoff_exhaustion(self):
        self.transport.send.return_value = APNsResult(503, 'ServiceUnavailable', retry_after=1200)
        self.run_event()
        self.assertEqual(PushDelivery.objects.get().next_attempt_at, self.now + timedelta(seconds=1200))
        self.run_event(self.now + timedelta(seconds=1201))
        self.assertEqual(self.run_event(self.now + timedelta(seconds=2402)), 'FAILED')
        self.assertEqual(PushAttempt.objects.count(), 3)

    def test_lease_blocks_duplicate_worker_and_late_response(self):
        pk = prepare_deliveries(self.event.pk, self.now)[0]
        delivery, attempt = claim_attempt(pk, self.now)
        self.assertIsNone(claim_attempt(pk, self.now))
        new_delivery, new_attempt = claim_attempt(pk, self.now + timedelta(seconds=121))
        finish_attempt(pk, attempt.pk, APNsResult(200), self.now + timedelta(seconds=122))
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'SENDING')
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'UNKNOWN')
        finish_attempt(pk, new_attempt.pk, APNsResult(200), self.now + timedelta(seconds=123))
        self.assertEqual(PushAttempt.objects.get(pk=new_attempt.pk).status, 'ACCEPTED_BY_APNS')

    def test_invalid_timestamp_does_not_disable_newer_registration(self):
        self.transport.send.return_value = APNsResult(410, 'Unregistered', invalid_since_ms=int((self.device.last_registered_at - timedelta(seconds=1)).timestamp() * 1000))
        self.assertEqual(self.run_event(), 'FAILED')
        self.device.refresh_from_db()
        self.assertTrue(self.device.is_active)

    def test_invalid_token_disables_only_sent_revision(self):
        pk = prepare_deliveries(self.event.pk, self.now)[0]
        delivery, attempt = claim_attempt(pk, self.now)
        PushDevice.objects.filter(pk=self.device.pk).update(revision=2, apns_token='cd' * 32)
        finish_attempt(pk, attempt.pk, APNsResult(400, 'BadDeviceToken'), self.now)
        self.device.refresh_from_db()
        self.assertTrue(self.device.is_active)
        self.assertEqual(self.device.revision, 2)

    def test_expired_and_cancelled_events_never_send(self):
        self.assertEqual(self.run_event(self.now + timedelta(hours=2)), 'EXPIRED')
        self.transport.send.assert_not_called()

    def test_assignment_no_longer_owned_is_skipped(self):
        Trip.objects.filter(pk=self.event.trip_id).update(driver=self.driver2)
        self.assertEqual(self.run_event(), 'SKIPPED')
        self.transport.send.assert_not_called()

    def test_unregistered_device_and_password_change_stop_delivery(self):
        self.device.is_active = False
        self.device.save()
        self.assertEqual(self.run_event(), 'WAITING_FOR_DEVICES')
        self.driver_user.profile.must_change_password = True
        self.driver_user.profile.save()
        self.assertEqual(self.run_event(), 'SKIPPED')
        self.transport.send.assert_not_called()

    def test_safety_alert_operator_event_uses_same_provider(self):
        alert = SafetyAlert.objects.create(driver=self.driver, kind='PANIC', notes='Help')
        event = NotificationEvent.objects.create(recipient=self.admin, kind='SAFETY_ALERT', safety_alert=alert)
        PushDevice.objects.create(user=self.admin, **self.registration(apns_token='ef' * 32))
        self.assertEqual(process_event(event.pk, self.transport, now=timezone.now() + timedelta(seconds=1)), 'ACCEPTED_BY_APNS')
        self.assertEqual(self.transport.send.call_args.kwargs['payload']['kind'], 'SAFETY_ALERT')

    @override_settings(APNS_ENABLED=True)
    def test_batch_does_not_starve_new_events_behind_future_retries(self):
        self.transport.send.return_value = APNsResult(503, 'ServiceUnavailable')
        self.run_event()
        alert = SafetyAlert.objects.create(driver=self.driver, kind='PANIC')
        newer = NotificationEvent.objects.create(recipient=self.admin, kind='SAFETY_ALERT', safety_alert=alert)
        PushDevice.objects.create(user=self.admin, **self.registration(apns_token='ef' * 32))
        self.transport.send.return_value = APNsResult(200)
        with patch('core.management.commands.send_apns_notifications.APNsTransport', return_value=self.transport):
            call_command('send_apns_notifications', limit=1, stdout=StringIO())
        newer.refresh_from_db()
        self.assertEqual(newer.status, 'ACCEPTED_BY_APNS')

    def test_unregistered_timestamp_disables_old_registration(self):
        self.transport.send.return_value = APNsResult(410, 'Unregistered', invalid_since_ms=int(self.now.timestamp() * 1000))
        self.run_event()
        self.device.refresh_from_db()
        self.assertFalse(self.device.is_active)
        self.assertEqual(self.device.revision, 2)

    @override_settings(APNS_ENABLED=False)
    def test_disabled_worker_does_not_mutate_events(self):
        with self.assertRaises(CommandError):
            call_command('send_apns_notifications')
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, 'PENDING_APNS_INTEGRATION')

@override_settings(APNS_ENABLED=True, APNS_TEAM_ID='TESTTEAM', APNS_KEY_ID='TESTKEY', APNS_ALLOWED_TOPICS=[TOPIC])
class TransportTests(SimpleTestCase):
    def test_mock_http2_transport_hosts_jwt_headers_and_invalid_result(self):
        private = ec.generate_private_key(ec.SECP256R1())
        with TemporaryDirectory() as directory:
            key = Path(directory) / 'test.p8'
            key.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            requests = []
            def handler(request):
                requests.append(request)
                return httpx.Response(410, json={'reason': 'Unregistered', 'timestamp': 123}, headers={'apns-id':'provider-id'}, extensions={'http_version':b'HTTP/2'})
            with override_settings(APNS_PRIVATE_KEY_PATH=str(key)), httpx.Client(transport=httpx.MockTransport(handler)) as client:
                provider = APNsTransport(client)
                kwargs = dict(token='ab'*32, topic=TOPIC, apns_id=uuid4(), event_id=1, payload={'aps':{'alert':'test'}}, expires_at=1234)
                result = provider.send(environment='sandbox', **kwargs)
                provider.send(environment='production', **kwargs)
                self.assertEqual(result, APNsResult(410, 'Unregistered', 'provider-id', 123))
                self.assertEqual(requests[0].url.host, 'api.sandbox.push.apple.com')
                self.assertEqual(requests[1].url.host, 'api.push.apple.com')
                token = requests[0].headers['authorization'].split(' ')[1]
                self.assertEqual(jwt.decode(token, private.public_key(), algorithms=['ES256'])['iss'], 'TESTTEAM')
                self.assertEqual(jwt.get_unverified_header(token)['kid'], 'TESTKEY')
                self.assertEqual(requests[0].headers['apns-push-type'], 'alert')
                self.assertEqual(requests[0].headers['apns-id'], requests[1].headers['apns-id'])
                self.assertEqual(provider.send(environment='wrong', **kwargs).status, 400)

    def test_credentials_are_required_and_keys_inside_checkout_rejected(self):
        from django.conf import settings
        with override_settings(APNS_PRIVATE_KEY_PATH=''):
            with self.assertRaises(ImproperlyConfigured):
                APNsTransport(Mock())
        with override_settings(APNS_PRIVATE_KEY_PATH=str(settings.BASE_DIR / 'never-read.p8')):
            with self.assertRaises(ImproperlyConfigured):
                APNsTransport(Mock())

    def test_http1_is_not_reported_as_acceptance(self):
        private = ec.generate_private_key(ec.SECP256R1())
        with TemporaryDirectory() as directory:
            key = Path(directory) / 'test.p8'
            key.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            handler = lambda request: httpx.Response(200, extensions={'http_version': b'HTTP/1.1'})
            with override_settings(APNS_PRIVATE_KEY_PATH=str(key)), httpx.Client(transport=httpx.MockTransport(handler)) as client:
                provider = APNsTransport(client)
                result = provider.send(token='ab'*32, topic=TOPIC, environment='sandbox', apns_id=uuid4(), event_id=1, payload={}, expires_at=0)
                self.assertEqual(result, APNsResult(503, 'HTTP2Required'))
