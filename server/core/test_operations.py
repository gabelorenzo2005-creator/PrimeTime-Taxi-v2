from datetime import timedelta
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from .models import Driver, Vehicle, VehicleOwner, Shift, Trip, Role, SafetyAlert
from .services import create_account


class OperationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = VehicleOwner.objects.create(name='Company')
        cls.car = Vehicle.objects.create(car_number='1', license_plate_number='TEST001', owner=cls.owner)
        cls.car2 = Vehicle.objects.create(car_number='2', license_plate_number='TEST002', owner=cls.owner)
        cls.driver = Driver.objects.create(first_name='Jamie', last_name='Driver', call_number='D1', hack_license_number='H1', phone_number='111', email='one@example.com')
        cls.driver2 = Driver.objects.create(first_name='Other', last_name='Driver', call_number='D2', hack_license_number='H2', phone_number='222', email='two@example.com')
        cls.user, _ = create_account('Jamie', 'Driver', 'development-test-password', Role.DRIVER, cls.driver)
        cls.other, _ = create_account('Other', 'Driver', 'development-test-password', Role.DRIVER, cls.driver2)
        cls.admin, _ = create_account('Alex', 'Admin', 'development-test-password', Role.ADMIN)
        cls.dispatcher, _ = create_account('Alex', 'Dispatch', 'development-test-password', Role.DISPATCHER)
        cls.it, _ = create_account('Alex', 'IT', 'development-test-password', Role.IT)

    def client_for(self, user):
        client = APIClient()
        token, _ = Token.objects.get_or_create(user=user)
        client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        return client

    def create_trip(self, **kwargs):
        return Trip.objects.create(pick_up_location='Pickup', drop_off_location='Dropoff', pickup_time=timezone.now(), **kwargs)

    def test_operations_require_authentication(self):
        self.assertEqual(APIClient().get('/api/workspace/').status_code, 401)
        self.assertEqual(APIClient().post('/api/trips/', {}).status_code, 401)

    def test_end_to_end_dispatch_shift_and_payment(self):
        driver = self.client_for(self.user)
        dispatch = self.client_for(self.dispatcher)
        response = driver.post('/api/shifts/', {'vehicle_id': self.car.pk}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        shift_id = response.data['id']
        response = dispatch.post('/api/trips/', {'pick_up_location': 'Airport', 'drop_off_location': 'Hotel'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        trip_id = response.data['id']
        response = dispatch.post(f'/api/trips/{trip_id}/assign/', {'driver_id': self.driver.pk}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(driver.post(f'/api/shifts/{shift_id}/end/', {'amount': '10.00'}, format='json').status_code, 400)
        self.assertEqual(driver.post(f'/api/trips/{trip_id}/pickup/', {}, format='json').status_code, 200)
        response = driver.post(f'/api/trips/{trip_id}/complete/', {'amount': '25.50'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['fare_amount'], '25.50')
        self.assertEqual(driver.post(f'/api/shifts/{shift_id}/end/', {'amount': '10.00'}, format='json').status_code, 200)
        self.assertEqual(dispatch.post(f'/api/shifts/{shift_id}/approve/', {}, format='json').status_code, 403)
        response = self.client_for(self.admin).post(f'/api/shifts/{shift_id}/approve/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['turn_in_cleared'])
        self.assertTrue(response.data['turn_in_paid'])

    def test_vehicle_and_driver_cannot_double_clock_in(self):
        Shift.objects.create(driver=self.driver, vehicle=self.car)
        self.assertEqual(self.client_for(self.other).post('/api/shifts/', {'vehicle_id': self.car.pk}, format='json').status_code, 400)
        self.assertEqual(self.client_for(self.user).post('/api/shifts/', {'vehicle_id': self.car2.pk}, format='json').status_code, 400)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Shift.objects.create(driver=self.driver, vehicle=self.car2)

    def test_first_acceptance_cannot_be_overwritten(self):
        Shift.objects.create(driver=self.driver, vehicle=self.car)
        Shift.objects.create(driver=self.driver2, vehicle=self.car2)
        trip = self.create_trip()
        self.assertEqual(self.client_for(self.user).post(f'/api/trips/{trip.pk}/accept/', {}, format='json').status_code, 200)
        self.assertEqual(self.client_for(self.other).post(f'/api/trips/{trip.pk}/accept/', {}, format='json').status_code, 400)
        trip.refresh_from_db()
        self.assertEqual(trip.driver, self.driver)

    def test_driver_cannot_take_two_active_trips(self):
        Shift.objects.create(driver=self.driver, vehicle=self.car)
        first, second = self.create_trip(), self.create_trip()
        client = self.client_for(self.user)
        self.assertEqual(client.post(f'/api/trips/{first.pk}/accept/', {}, format='json').status_code, 200)
        self.assertEqual(client.post(f'/api/trips/{second.pk}/accept/', {}, format='json').status_code, 400)

    def test_driver_cannot_modify_other_driver_trip_or_shift(self):
        shift = Shift.objects.create(driver=self.driver2, vehicle=self.car)
        trip = self.create_trip(driver=self.driver2, shift=shift, vehicle=self.car, status='ASSIGNED')
        client = self.client_for(self.user)
        self.assertEqual(client.post(f'/api/trips/{trip.pk}/pickup/', {}, format='json').status_code, 403)
        self.assertEqual(client.post(f'/api/shifts/{shift.pk}/end/', {'amount': '0'}, format='json').status_code, 404)

    def test_reservations_are_hidden_from_other_drivers_until_due(self):
        reservation = Trip.objects.create(pick_up_location='Airport', drop_off_location='Home', pickup_time=timezone.now() + timedelta(days=1))
        client = self.client_for(self.user)
        response = client.get('/api/workspace/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn(reservation.pk, [t['id'] for t in response.data['trips']])
        Shift.objects.create(driver=self.driver, vehicle=self.car)
        self.assertEqual(client.post(f'/api/trips/{reservation.pk}/accept/', {}, format='json').status_code, 400)
        self.assertIn(reservation.pk, [t['id'] for t in self.client_for(self.dispatcher).get('/api/workspace/').data['trips']])

    def test_workspace_does_not_leak_other_driver_history(self):
        mine = self.create_trip(driver=self.driver, status='COMPLETED')
        theirs = self.create_trip(driver=self.driver2, status='COMPLETED')
        data = self.client_for(self.user).get('/api/workspace/').data
        self.assertIn(mine.pk, [t['id'] for t in data['trips']])
        self.assertNotIn(theirs.pk, [t['id'] for t in data['trips']])
        self.assertEqual([d['id'] for d in data['drivers']], [self.driver.pk])

    def test_driver_cannot_create_calls_or_edit_fleet(self):
        client = self.client_for(self.user)
        self.assertEqual(client.post('/api/trips/', {}, format='json').status_code, 403)
        self.assertEqual(client.post('/api/records/owners/', {'name': 'New'}, format='json').status_code, 403)

    def test_bad_money_and_transition_are_rejected(self):
        shift = Shift.objects.create(driver=self.driver, vehicle=self.car)
        trip = self.create_trip(driver=self.driver, shift=shift, status='ASSIGNED')
        client = self.client_for(self.user)
        self.assertEqual(client.post(f'/api/trips/{trip.pk}/complete/', {'amount': '20'}, format='json').status_code, 400)
        self.assertEqual(client.post(f'/api/shifts/{shift.pk}/end/', {'amount': '-1'}, format='json').status_code, 400)
        self.assertEqual(client.post(f'/api/trips/{trip.pk}/cancel/', {}, format='json').status_code, 400)

    def test_alert_acknowledgement_and_resolution(self):
        response = self.client_for(self.user).post('/api/alerts/', {'kind': 'BREAKDOWN', 'notes': 'Flat tire'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        pk = response.data['id']
        self.assertEqual(self.client_for(self.user).post(f'/api/alerts/{pk}/resolve/', {}, format='json').status_code, 403)
        self.assertEqual(self.client_for(self.dispatcher).post(f'/api/alerts/{pk}/acknowledge/', {}, format='json').status_code, 200)
        response = self.client_for(self.it).post(f'/api/alerts/{pk}/resolve/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data['resolved_at'])
        alert = SafetyAlert.objects.get(pk=pk)
        self.assertEqual(alert.acknowledged_by, self.dispatcher)
        self.assertEqual(alert.resolved_by, self.it)

    def test_required_password_change_blocks_operations_and_rotates_token(self):
        self.user.profile.must_change_password = True
        self.user.profile.save()
        client = self.client_for(self.user)
        old = Token.objects.get(user=self.user).key
        self.assertEqual(client.get('/api/workspace/').status_code, 403)
        self.assertEqual(client.post('/api/password/', {'current_password': 'wrong', 'new_password': 'SomethingNew!2026'}, format='json').status_code, 400)
        response = client.post('/api/password/', {'current_password': 'development-test-password', 'new_password': 'SomethingNew!2026'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(old, response.data['token'])
        self.assertEqual(client.get('/api/workspace/').status_code, 401)
        client.credentials(HTTP_AUTHORIZATION=f"Token {response.data['token']}")
        self.assertEqual(client.get('/api/workspace/').status_code, 200)

    def test_logout_and_expiry_invalidate_access(self):
        client = self.client_for(self.user)
        token = Token.objects.get(user=self.user)
        Token.objects.filter(pk=token.pk).update(created=timezone.now() - timedelta(hours=13))
        self.assertEqual(client.get('/api/workspace/').status_code, 401)
        Token.objects.filter(pk=token.pk).update(created=timezone.now())
        self.assertEqual(client.post('/api/logout/', {}, format='json').status_code, 204)
        self.assertEqual(client.get('/api/workspace/').status_code, 401)

    def test_admin_can_edit_company_records(self):
        client = self.client_for(self.admin)
        response = client.patch(f'/api/records/drivers/{self.driver.pk}/', {'notes': 'Updated'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.notes, 'Updated')
