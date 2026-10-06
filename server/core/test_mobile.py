"""Synthetic coordinates/tokens exist only in the isolated test database."""
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from .models import (
    Driver, DriverLocation, NotificationEvent, PushDevice, Role,
    SafetyAlert, Shift, Trip, Vehicle, VehicleOwner,
)
from .notifications import prepare_safety_alert, prepare_trip_assignment
from .services import create_account


class MobileFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner = VehicleOwner.objects.create(name='Test owner')
        cls.vehicle = Vehicle.objects.create(car_number='101', license_plate_number='TEST001', owner=owner)
        cls.vehicle2 = Vehicle.objects.create(car_number='102', license_plate_number='TEST002', owner=owner)
        cls.driver = Driver.objects.create(first_name='Test', last_name='Driver', call_number='D101', hack_license_number='H101', phone_number='111', email='one@example.com')
        cls.driver2 = Driver.objects.create(first_name='Second', last_name='Driver', call_number='D102', hack_license_number='H102', phone_number='222', email='two@example.com')
        cls.driver_user, _ = create_account('Test', 'Driver', 'test-mobile-password', Role.DRIVER, cls.driver)
        cls.other_user, _ = create_account('Second', 'Driver', 'test-mobile-password', Role.DRIVER, cls.driver2)
        cls.admin, _ = create_account('Test', 'Admin', 'test-mobile-password', Role.ADMIN)
        cls.dispatcher, _ = create_account('Test', 'Dispatch', 'test-mobile-password', Role.DISPATCHER)
        cls.it, _ = create_account('Test', 'IT', 'test-mobile-password', Role.IT)

    def client_for(self, user):
        client = APIClient()
        token, _ = Token.objects.get_or_create(user=user)
        client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        return client

    def start(self, driver=None, vehicle=None):
        shift = Shift.objects.create(driver=driver or self.driver, vehicle=vehicle or self.vehicle)
        # Fix timestamps are always relative to an explicitly earlier shift start.
        Shift.objects.filter(pk=shift.pk).update(start_time=timezone.now() - timedelta(hours=1))
        shift.refresh_from_db()
        return shift

    def gps(self, shift, **overrides):
        return {'shift_id': shift.pk, 'latitude': 40.0, 'longitude': -73.0, 'accuracy': 5.0, 'timestamp': timezone.now().isoformat(), **overrides}

    def registration(self, **overrides):
        return {'installation_id': str(uuid4()), 'apns_token': 'ab' * 32, 'environment': 'sandbox', 'topic': 'com.primetimetaxi.app', **overrides}


@override_settings(GPS_ONLINE_SECONDS=60, GPS_OFFLINE_SECONDS=300, GPS_MAX_FUTURE_SECONDS=30)
class GPSTests(MobileFixture):
    def test_authentication_and_role_permissions(self):
        shift = self.start()
        self.assertEqual(APIClient().post('/api/gps/', self.gps(shift), format='json').status_code, 401)
        for user in [self.admin, self.dispatcher, self.it]:
            with self.subTest(role=user.profile.role):
                self.assertEqual(self.client_for(user).post('/api/gps/', self.gps(shift), format='json').status_code, 403)
        self.assertEqual(DriverLocation.objects.count(), 0)

    def test_on_shift_driver_can_report_full_fix(self):
        shift = self.start()
        data = self.gps(shift, heading=180.0, speed=12.5)
        response = self.client_for(self.driver_user).post('/api/gps/', data, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['accepted'])
        fix = DriverLocation.objects.get(shift=shift)
        self.assertEqual((fix.latitude, fix.longitude, fix.accuracy, fix.heading, fix.speed), (40.0, -73.0, 5.0, 180.0, 12.5))
        self.assertGreaterEqual(fix.received_at, fix.timestamp)
        self.assertEqual(response.data['location']['car_number'], '101')

    def test_unavailable_heading_and_speed_are_nullable(self):
        shift = self.start()
        response = self.client_for(self.driver_user).post('/api/gps/', self.gps(shift), format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['location']['heading'])
        self.assertIsNone(response.data['location']['speed'])

    def test_rejects_other_driver_ended_and_nonexistent_shifts(self):
        other = self.start(self.driver2, self.vehicle2)
        mine = self.start()
        mine.end_time = timezone.now()
        mine.save()
        client = self.client_for(self.driver_user)
        for shift_id in [other.pk, mine.pk, 99999]:
            self.assertEqual(client.post('/api/gps/', self.gps(mine, shift_id=shift_id), format='json').status_code, 400)
        self.assertFalse(DriverLocation.objects.exists())

    def test_rejects_invalid_and_nonfinite_coordinates_and_measurements(self):
        shift = self.start()
        client = self.client_for(self.driver_user)
        for field, value in [('latitude', 91), ('latitude', -91), ('longitude', 181), ('longitude', -181), ('accuracy', -1), ('heading', -1), ('heading', 360), ('speed', -1), ('latitude', 'NaN'), ('longitude', 'Infinity'), ('accuracy', 'Infinity'), ('speed', 'NaN'), ('heading', 'NaN'), ('latitude', True)]:
            with self.subTest(field=field, value=value):
                response = client.post('/api/gps/', self.gps(shift, **{field: value}), format='json')
                self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(DriverLocation.objects.exists())

    def test_rejects_bad_naive_future_and_pre_shift_timestamps(self):
        shift = self.start()
        client = self.client_for(self.driver_user)
        for timestamp in ['invalid', timezone.now().replace(tzinfo=None).isoformat(), '2026-99-99T12:00:00Z', (timezone.now() + timedelta(minutes=1)).isoformat(), (shift.start_time - timedelta(seconds=1)).isoformat()]:
            response = client.post('/api/gps/', self.gps(shift, timestamp=timestamp), format='json')
            self.assertEqual(response.status_code, 400, response.data)

    def test_unknown_identity_fields_are_rejected(self):
        shift = self.start()
        response = self.client_for(self.driver_user).post('/api/gps/', self.gps(shift, driver_id=self.driver2.pk), format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(DriverLocation.objects.exists())

    def test_old_and_duplicate_fixes_do_not_replace_or_refresh_presence(self):
        shift = self.start()
        client = self.client_for(self.driver_user)
        data = self.gps(shift)
        self.assertTrue(client.post('/api/gps/', data, format='json').data['accepted'])
        original = DriverLocation.objects.get(shift=shift)
        original_receipt = original.received_at
        for changed in [data, {**data, 'latitude': 41, 'timestamp': (original.timestamp - timedelta(seconds=30)).isoformat()}]:
            response = client.post('/api/gps/', changed, format='json')
            self.assertFalse(response.data['accepted'])
        original.refresh_from_db()
        self.assertEqual(original.latitude, 40)
        self.assertEqual(original.received_at, original_receipt)
        response = client.post('/api/gps/', {**data, 'timestamp': (timezone.now() + timedelta(seconds=1)).isoformat(), 'latitude': 42}, format='json')
        self.assertTrue(response.data['accepted'])
        self.assertEqual(DriverLocation.objects.count(), 1)
        original.refresh_from_db()
        self.assertEqual(original.latitude, 42)

    def test_workspace_all_operator_roles_preserves_call_and_vehicle_labels(self):
        shift = self.start()
        self.client_for(self.driver_user).post('/api/gps/', self.gps(shift), format='json')
        for user in [self.dispatcher, self.admin, self.it]:
            data = self.client_for(user).get('/api/workspace/').data
            row = next(row for row in data['driver_locations'] if row['driver_id'] == self.driver.pk)
            self.assertEqual((row['call_number'], row['car_number'], row['status']), ('D101', '101', 'online'))
            self.assertEqual(row['vehicle_id'], self.vehicle.pk)
            self.assertEqual(row['location']['accuracy'], 5)
            self.assertIn('timestamp', row['location'])
            self.assertIn('received_at', row['location'])
            self.assertEqual(data['gps_policy'], {'online_seconds': 60, 'offline_seconds': 300})
        rows = self.client_for(self.driver_user).get('/api/workspace/').data['driver_locations']
        self.assertEqual([row['driver_id'] for row in rows], [self.driver.pk])

    def test_presence_uses_fix_age_not_just_recent_upload(self):
        shift = self.start()
        client = self.client_for(self.driver_user)
        client.post('/api/gps/', self.gps(shift, timestamp=(timezone.now() - timedelta(seconds=120)).isoformat()), format='json')
        def row():
            return self.client_for(self.admin).get('/api/workspace/').data['driver_locations'][0]
        self.assertEqual(row()['status'], 'stale')
        DriverLocation.objects.filter(shift=shift).update(timestamp=timezone.now() - timedelta(seconds=301))
        self.assertEqual(row()['status'], 'offline')
        DriverLocation.objects.filter(shift=shift).update(timestamp=timezone.now(), received_at=timezone.now() - timedelta(seconds=120))
        self.assertEqual(row()['status'], 'stale')

    def test_no_fix_off_shift_and_new_shift_do_not_invent_online_locations(self):
        client = self.client_for(self.driver_user)
        row = client.get('/api/workspace/').data['driver_locations'][0]
        self.assertEqual(row['status'], 'offline')
        self.assertIsNone(row['location'])
        shift = self.start()
        row = client.get('/api/workspace/').data['driver_locations'][0]
        self.assertEqual(row['status_reason'], 'awaiting_fix')
        self.assertIsNone(row['location'])
        client.post('/api/gps/', self.gps(shift), format='json')
        client.post(f'/api/shifts/{shift.pk}/end/', {'amount': '0'}, format='json')
        row = client.get('/api/workspace/').data['driver_locations'][0]
        self.assertEqual(row['status'], 'offline')
        self.assertIsNone(row['car_number'])
        self.assertEqual(row['location']['car_number'], '101')
        new_shift = self.start(vehicle=self.vehicle2)
        row = client.get('/api/workspace/').data['driver_locations'][0]
        self.assertEqual(row['shift_id'], new_shift.pk)
        self.assertEqual(row['car_number'], '102')
        self.assertIsNone(row['location'])
        self.assertEqual(client.post('/api/gps/', self.gps(shift), format='json').status_code, 400)

    def test_deactivated_driver_is_not_online(self):
        shift = self.start()
        self.client_for(self.driver_user).post('/api/gps/', self.gps(shift), format='json')
        self.driver_user.is_active = False
        self.driver_user.save()
        row = self.client_for(self.admin).get('/api/workspace/').data['driver_locations'][0]
        self.assertEqual(row['status'], 'offline')
        self.assertEqual(row['status_reason'], 'account_unavailable')

    def test_database_rejects_invalid_coordinates_and_duplicate_shift_fix(self):
        shift = self.start()
        data = {'shift': shift, 'latitude': 40, 'longitude': -73, 'accuracy': 1, 'timestamp': timezone.now()}
        with self.assertRaises(IntegrityError), transaction.atomic():
            DriverLocation.objects.create(**{**data, 'latitude': 91})
        DriverLocation.objects.create(**data)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DriverLocation.objects.create(**data)

    def test_password_change_requirement_still_blocks_gps(self):
        shift = self.start()
        self.driver_user.profile.must_change_password = True
        self.driver_user.profile.save()
        response = self.client_for(self.driver_user).post('/api/gps/', self.gps(shift), format='json')
        self.assertEqual(response.status_code, 403)


@override_settings(APNS_ALLOWED_TOPICS=['com.primetimetaxi.app'])
class DeviceTests(MobileFixture):
    def test_authentication_and_all_roles_can_register_only_for_themselves(self):
        self.assertEqual(APIClient().post('/api/devices/', self.registration(), format='json').status_code, 401)
        self.assertEqual(APIClient().get('/api/devices/').status_code, 401)
        self.assertEqual(APIClient().delete('/api/devices/1/').status_code, 401)
        for index, user in enumerate([self.driver_user, self.dispatcher, self.admin, self.it]):
            response = self.client_for(user).post('/api/devices/', self.registration(apns_token=f'{index + 1:02x}' * 32), format='json')
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(PushDevice.objects.get(pk=response.data['id']).user, user)
            self.assertNotIn('apns_token', response.data)

    def test_two_devices_and_token_rotation_preserve_other_registration(self):
        client = self.client_for(self.driver_user)
        first = self.registration()
        second = self.registration(apns_token='cd' * 32)
        first_response = client.post('/api/devices/', first, format='json')
        second_response = client.post('/api/devices/', second, format='json')
        response = client.post('/api/devices/', {**first, 'apns_token': 'ef' * 40}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['id'], first_response.data['id'])
        self.assertEqual(response.data['revision'], 2)
        self.assertEqual(PushDevice.objects.get(pk=second_response.data['id']).apns_token, second['apns_token'])
        self.assertEqual(len(client.get('/api/devices/').data['devices']), 2)

    def test_variable_length_tokens_are_accepted_and_normalized(self):
        client = self.client_for(self.driver_user)
        for length in [32, 64, 128]:
            response = client.post('/api/devices/', self.registration(apns_token='AB' * length), format='json')
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(PushDevice.objects.get(pk=response.data['id']).apns_token, 'ab' * length)

    def test_rejects_invalid_tokens_topics_environments_and_identity_spoofing(self):
        client = self.client_for(self.driver_user)
        for changes in [{'apns_token': 'not-hex'}, {'apns_token': 'abc'}, {'apns_token': ''}, {'apns_token': 'ab' * 257}, {'apns_token': ' AB '}, {'installation_id': 'invalid'}, {'topic': 'com.other.app'}, {'environment': 'development'}, {'user': self.admin.pk}]:
            response = client.post('/api/devices/', self.registration(**changes), format='json')
            self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(PushDevice.objects.exists())

    @override_settings(APNS_ALLOWED_TOPICS=[])
    def test_unconfigured_topic_allowlist_rejects_registration(self):
        response = self.client_for(self.driver_user).post('/api/devices/', self.registration(), format='json')
        self.assertEqual(response.status_code, 400)

    def test_other_account_cannot_claim_active_installation_or_token(self):
        data = self.registration()
        self.client_for(self.driver_user).post('/api/devices/', data, format='json')
        client = self.client_for(self.other_user)
        for changes in [{}, {'apns_token': 'cd' * 32}, {'installation_id': str(uuid4())}]:
            response = client.post('/api/devices/', {**data, **changes}, format='json')
            self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(PushDevice.objects.get().user, self.driver_user)

    def test_same_account_cannot_overwrite_a_different_installation_token(self):
        client = self.client_for(self.driver_user)
        data = self.registration()
        client.post('/api/devices/', data, format='json')
        self.assertEqual(client.post('/api/devices/', {**data, 'installation_id': str(uuid4())}, format='json').status_code, 409)
        self.assertEqual(PushDevice.objects.count(), 1)

    def test_device_list_and_unregister_are_owner_scoped(self):
        owner = self.client_for(self.driver_user)
        device = owner.post('/api/devices/', self.registration(), format='json').data['id']
        other = self.client_for(self.other_user)
        self.assertEqual(other.get('/api/devices/').data, {'devices': []})
        self.assertEqual(other.delete(f'/api/devices/{device}/').status_code, 404)
        self.assertEqual(owner.delete(f'/api/devices/{device}/').status_code, 204)
        self.assertEqual(owner.delete(f'/api/devices/{device}/').status_code, 204)
        row = PushDevice.objects.get(pk=device)
        self.assertFalse(row.is_active)
        self.assertIsNotNone(row.disabled_at)
        self.assertEqual(row.revision, 2)
        self.assertNotIn('apns_token', owner.get('/api/devices/').data['devices'][0])

    def test_account_switch_requires_unregister_and_keeps_old_ownership(self):
        data = self.registration()
        owner = self.client_for(self.driver_user)
        device = owner.post('/api/devices/', data, format='json').data['id']
        owner.delete(f'/api/devices/{device}/')
        response = self.client_for(self.other_user).post('/api/devices/', data, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotEqual(response.data['id'], device)
        self.assertEqual(PushDevice.objects.get(pk=device).user, self.driver_user)
        self.assertEqual(owner.post('/api/devices/', data, format='json').status_code, 409)

    def test_same_owner_can_reactivate_an_unregistered_device(self):
        data = self.registration()
        client = self.client_for(self.driver_user)
        device = client.post('/api/devices/', data, format='json').data['id']
        client.delete(f'/api/devices/{device}/')
        response = client.post('/api/devices/', data, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], device)
        self.assertEqual(response.data['revision'], 3)
        self.assertTrue(response.data['is_active'])
        self.assertIsNone(response.data['disabled_at'])

    def test_environment_scopes_tokens_and_installations(self):
        data = self.registration()
        client = self.client_for(self.driver_user)
        self.assertEqual(client.post('/api/devices/', data, format='json').status_code, 201)
        self.assertEqual(client.post('/api/devices/', {**data, 'environment': 'production'}, format='json').status_code, 201)
        self.assertEqual(PushDevice.objects.count(), 2)

    def test_required_password_change_blocks_registration_but_allows_unregister(self):
        client = self.client_for(self.driver_user)
        data = self.registration()
        device = client.post('/api/devices/', data, format='json').data['id']
        self.driver_user.profile.must_change_password = True
        self.driver_user.profile.save()
        self.assertEqual(client.post('/api/devices/', data, format='json').status_code, 403)
        self.assertEqual(client.delete(f'/api/devices/{device}/').status_code, 204)

    def test_database_enforces_active_token_and_installation_uniqueness(self):
        data = self.registration()
        PushDevice.objects.create(user=self.driver_user, **data)
        for changes in [{'installation_id': uuid4()}, {'apns_token': 'cd' * 32}]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                PushDevice.objects.create(user=self.other_user, **{**data, **changes})


class NotificationTests(MobileFixture):
    def trip(self):
        return Trip.objects.create(pick_up_location='Test pickup', drop_off_location='Test dropoff', pickup_time=timezone.now())

    def test_assignment_creates_one_pending_event_without_needing_a_device(self):
        self.start()
        trip = self.trip()
        response = self.client_for(self.dispatcher).post(f'/api/trips/{trip.pk}/assign/', {'driver_id': self.driver.pk}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        event = NotificationEvent.objects.get()
        self.assertEqual(event.recipient, self.driver_user)
        self.assertEqual(event.trip, trip)
        self.assertEqual(event.kind, 'TRIP_ASSIGNED')
        self.assertEqual(event.status, 'PENDING_APNS_INTEGRATION')
        self.assertFalse(PushDevice.objects.exists())
        trip.refresh_from_db()
        prepare_trip_assignment(trip)
        self.assertEqual(NotificationEvent.objects.count(), 1)

    def test_driver_acceptance_also_prepares_assignment_event(self):
        self.start()
        trip = self.trip()
        response = self.client_for(self.driver_user).post(f'/api/trips/{trip.pk}/accept/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(NotificationEvent.objects.get().recipient, self.driver_user)

    def test_failed_assignment_does_not_create_an_event(self):
        trip = self.trip()
        response = self.client_for(self.dispatcher).post(f'/api/trips/{trip.pk}/assign/', {'driver_id': self.driver.pk}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(NotificationEvent.objects.exists())
        trip.refresh_from_db()
        self.assertEqual(trip.status, 'OPEN')

    def test_assignment_and_event_roll_back_together(self):
        from .operations import claim_trip
        self.start()
        trip = self.trip()
        with patch('core.operations.prepare_trip_assignment', side_effect=RuntimeError('Event write failed')):
            with self.assertRaises(RuntimeError):
                claim_trip(self.driver_user, trip.pk)
        trip.refresh_from_db()
        self.assertEqual(trip.status, 'OPEN')
        self.assertIsNone(trip.driver)
        self.assertFalse(NotificationEvent.objects.exists())

    def test_safety_alert_targets_only_active_operator_accounts_and_is_deduplicated(self):
        inactive, _ = create_account('Inactive', 'Operator', 'test-mobile-password', Role.ADMIN)
        inactive.is_active = False
        inactive.save()
        response = self.client_for(self.driver_user).post('/api/alerts/', {'kind': 'ACCIDENT'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        alert = SafetyAlert.objects.get(pk=response.data['id'])
        events = NotificationEvent.objects.filter(safety_alert=alert)
        self.assertEqual(set(events.values_list('recipient_id', flat=True)), {self.admin.pk, self.dispatcher.pk, self.it.pk})
        self.assertEqual(set(events.values_list('status', flat=True)), {'PENDING_APNS_INTEGRATION'})
        prepare_safety_alert(alert)
        self.assertEqual(events.count(), 3)
        self.assertTrue(all(event.trip_id is None for event in events))

    def test_safety_alert_and_events_roll_back_together(self):
        client = self.client_for(self.driver_user)
        with patch('core.api.prepare_safety_alert', side_effect=RuntimeError('Event write failed')):
            with self.assertRaises(RuntimeError):
                client.post('/api/alerts/', {'kind': 'BREAKDOWN'}, format='json')
        self.assertFalse(SafetyAlert.objects.exists())
        self.assertFalse(NotificationEvent.objects.exists())

    def test_events_do_not_move_to_another_account_when_device_is_re_registered(self):
        self.start()
        trip = self.trip()
        self.client_for(self.driver_user).post(f'/api/trips/{trip.pk}/accept/', {}, format='json')
        data = self.registration()
        with override_settings(APNS_ALLOWED_TOPICS=['com.primetimetaxi.app']):
            owner = self.client_for(self.driver_user)
            pk = owner.post('/api/devices/', data, format='json').data['id']
            owner.delete(f'/api/devices/{pk}/')
            self.client_for(self.other_user).post('/api/devices/', data, format='json')
        self.assertEqual(NotificationEvent.objects.get().recipient, self.driver_user)
        self.assertFalse(NotificationEvent.objects.filter(recipient=self.other_user).exists())

    def test_database_rejects_subject_mismatch_duplicate_and_delivery_claim(self):
        trip = self.trip()
        NotificationEvent.objects.create(recipient=self.driver_user, kind='TRIP_ASSIGNED', trip=trip)
        for changes in [{}, {'kind': 'SAFETY_ALERT'}, {'recipient': self.other_user, 'status': 'DELIVERED'}]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                NotificationEvent.objects.create(**{'recipient': self.driver_user, 'kind': 'TRIP_ASSIGNED', 'trip': trip, **changes})

    def test_multiple_active_devices_do_not_duplicate_the_account_event(self):
        self.start()
        trip = self.trip()
        with override_settings(APNS_ALLOWED_TOPICS=['com.primetimetaxi.app']):
            client = self.client_for(self.driver_user)
            self.assertEqual(client.post('/api/devices/', self.registration(), format='json').status_code, 201)
            self.assertEqual(client.post('/api/devices/', self.registration(apns_token='cd' * 32), format='json').status_code, 201)
            self.assertEqual(client.post(f'/api/trips/{trip.pk}/accept/', {}, format='json').status_code, 200)
        self.assertEqual(PushDevice.objects.filter(user=self.driver_user, is_active=True).count(), 2)
        self.assertEqual(NotificationEvent.objects.filter(recipient=self.driver_user).count(), 1)
        self.assertEqual(NotificationEvent.objects.get().status, 'PENDING_APNS_INTEGRATION')
