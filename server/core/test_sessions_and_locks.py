from datetime import timedelta
from unittest.mock import patch
from django.test import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from .test_operations import OperationsTests
from .models import Shift, PushDevice, NotificationEvent
from .operations import start_shift, claim_trip
from uuid import uuid4

class SessionsAndLocksTests(OperationsTests):
    # Inherits existing operations regressions as well as testing the new rules.
    def pending(self):
        return Shift.objects.create(driver=self.driver, vehicle=self.car, end_time=timezone.now(), turn_in_amount=0)

    def test_pending_driver_still_logs_in_and_reads_workspace(self):
        self.pending()
        response = APIClient().post('/api/login/', {'username': self.user.username, 'password': 'development-test-password'}, format='json')
        self.assertEqual(response.status_code, 200)
        data = self.client_for(self.user).get('/api/workspace/').data
        self.assertTrue(data['turn_in_lock']['blocked'])
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.client_for(self.user).get('/api/session/').status_code, 200)

    def test_lock_blocks_start_accept_and_operator_assignment(self):
        self.pending()
        # Legacy/current open work must still obey the central turn-in lock.
        Shift.objects.create(driver=self.driver, vehicle=self.car2)
        trip = self.create_trip()
        client = self.client_for(self.user)
        self.assertEqual(client.post('/api/shifts/', {'vehicle_id': self.car.pk}, format='json').data['code'], 'TURN_IN_REQUIRED')
        for user, action, body in [(self.user, 'accept', {}), (self.dispatcher, 'assign', {'driver_id': self.driver.pk}), (self.admin, 'assign', {'driver_id': self.driver.pk})]:
            response = self.client_for(user).post(f'/api/trips/{trip.pk}/{action}/', body, format='json')
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data['code'], 'TURN_IN_REQUIRED')
        self.assertFalse(NotificationEvent.objects.exists())
        for function, args in [(start_shift, (self.user, self.car.pk)), (claim_trip, (self.user, trip.pk))]:
            from rest_framework.exceptions import ValidationError
            with self.assertRaises(ValidationError): function(*args)

    def test_clear_reject_permissions_and_any_older_pending_shift(self):
        pending = self.pending()
        for user in [self.user, self.dispatcher]:
            for action in ['approve', 'reject']:
                self.assertEqual(self.client_for(user).post(f'/api/shifts/{pending.pk}/{action}/', {}, format='json').status_code, 403)
        for user in [self.it, self.admin]:
            client = self.client_for(user)
            self.assertEqual(client.post(f'/api/shifts/{pending.pk}/approve/', {}, format='json').status_code, 200)
            self.assertFalse(self.client_for(self.user).get('/api/workspace/').data['turn_in_lock']['blocked'])
            self.assertEqual(client.post(f'/api/shifts/{pending.pk}/reject/', {}, format='json').status_code, 200)
            self.assertTrue(self.client_for(self.user).get('/api/workspace/').data['turn_in_lock']['blocked'])
        self.client_for(self.admin).post(f'/api/shifts/{pending.pk}/approve/', {}, format='json')
        self.assertEqual(self.client_for(self.user).post('/api/shifts/', {'vehicle_id': self.car.pk}, format='json').status_code, 201)

    def test_other_driver_is_not_blocked_and_staff_lock_is_not_driver_lock(self):
        self.pending()
        self.assertEqual(self.client_for(self.other).post('/api/shifts/', {'vehicle_id': self.car.pk}, format='json').status_code, 201)
        self.assertIsNone(self.client_for(self.admin).get('/api/workspace/').data['turn_in_lock'])

    def test_session_validates_expiry_revocation_deactivation_and_password_flag(self):
        client = self.client_for(self.user)
        self.assertEqual(client.get('/api/session/').data['username'], self.user.username)
        self.user.profile.must_change_password = True
        self.user.profile.save()
        self.assertTrue(client.get('/api/session/').data['must_change_password'])
        self.assertEqual(client.get('/api/workspace/').status_code, 403)
        token = Token.objects.get(user=self.user)
        Token.objects.filter(pk=token.pk).update(created=timezone.now() - timedelta(hours=13))
        self.assertEqual(client.get('/api/session/').status_code, 401)
        # Expired token can clean up but cannot restore operations.
        self.assertEqual(client.post('/api/logout/', {}, format='json').status_code, 204)
        self.assertEqual(client.get('/api/session/').status_code, 401)
        client = self.client_for(self.user)
        self.user.is_active = False
        self.user.save()
        self.assertEqual(client.get('/api/session/').status_code, 401)

    def test_logout_deactivates_only_owned_current_device_and_revokes_session(self):
        mine = PushDevice.objects.create(user=self.user, installation_id=uuid4(), apns_token='ab'*32, environment='sandbox', topic='test.app')
        other = PushDevice.objects.create(user=self.other, installation_id=uuid4(), apns_token='cd'*32, environment='sandbox', topic='test.app')
        another = PushDevice.objects.create(user=self.user, installation_id=uuid4(), apns_token='ef'*32, environment='sandbox', topic='test.app')
        client = self.client_for(self.user)
        self.assertEqual(client.post('/api/logout/', {'device_id': mine.pk}, format='json').status_code, 204)
        mine.refresh_from_db(); other.refresh_from_db(); another.refresh_from_db()
        self.assertFalse(mine.is_active)
        self.assertEqual(mine.revision, 2)
        self.assertTrue(other.is_active)
        self.assertTrue(another.is_active)
        self.assertFalse(Token.objects.filter(user=self.user).exists())
        self.assertEqual(client.get('/api/workspace/').status_code, 401)
        client = self.client_for(self.user)
        self.assertEqual(client.post('/api/logout/', {'device_id': other.pk}, format='json').status_code, 204)
        other.refresh_from_db(); self.assertTrue(other.is_active)

    @override_settings(APNS_ENABLED=False, APNS_TEAM_ID='', APNS_KEY_ID='', APNS_PRIVATE_KEY_PATH='')
    def test_credentials_absent_do_not_break_session_or_workspace(self):
        self.assertEqual(self.client_for(self.user).get('/api/session/').status_code, 200)
        self.assertEqual(self.client_for(self.user).get('/api/workspace/').status_code, 200)
