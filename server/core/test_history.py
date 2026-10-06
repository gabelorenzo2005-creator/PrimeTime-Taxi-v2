from datetime import timedelta
from unittest.mock import patch
from django.utils import timezone
from .test_mobile import MobileFixture
from .models import AuditRecord, VehicleNote, Trip, Shift, NotificationEvent, Role
from .operations import claim_trip


class HistoryTests(MobileFixture):
    def trip(self, **kwargs):
        return Trip.objects.create(pick_up_location='Airport', drop_off_location='Hotel', pickup_time=timezone.now(), **kwargs)

    def test_history_is_paginated_and_driver_scoped(self):
        own = self.trip(driver=self.driver, status=Trip.Status.COMPLETED)
        foreign = self.trip(driver=self.driver2, status=Trip.Status.COMPLETED)
        response = self.client_for(self.driver_user).get('/api/history/trips/?q=Airport&page_size=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], own.pk)
        self.assertEqual(self.client_for(self.driver_user).get(f'/api/history/trips/{foreign.pk}/').status_code, 404)
        self.assertEqual(self.client_for(self.admin).get('/api/history/trips/').data['count'], 2)

    def test_history_is_not_limited_to_workspace_100(self):
        for _ in range(105):
            self.trip(driver=self.driver, status=Trip.Status.COMPLETED)
        result = self.client_for(self.driver_user).get('/api/history/trips/?page_size=100&page=2')
        self.assertEqual(result.data['count'], 105)
        self.assertEqual(len(result.data['results']), 5)

    def test_filters_validation_and_reservation_visibility(self):
        trip = self.trip()
        trip.pickup_time = timezone.now() + timedelta(days=1)
        trip.save()
        for role_user in [self.admin, self.dispatcher, self.it]:
            response = self.client_for(role_user).get('/api/reservations/')
            self.assertEqual(response.data['count'], 1)
        self.assertEqual(self.client_for(self.driver_user).get('/api/reservations/').status_code, 403)
        for query in ['page=0', 'page_size=101', 'status=invalid', 'since=bad', 'driver=-1']:
            self.assertEqual(self.client_for(self.admin).get('/api/history/trips/?' + query).status_code, 400)

    def test_shift_history_ownership(self):
        shift = Shift.objects.create(driver=self.driver2, vehicle=self.vehicle)
        self.assertEqual(self.client_for(self.driver_user).get(f'/api/history/shifts/{shift.pk}/').status_code, 404)
        self.assertEqual(self.client_for(self.driver_user).get('/api/history/shifts/').data['count'], 0)

    def test_notes_are_append_only_and_record_edit_roles_only(self):
        endpoint = f'/api/vehicles/{self.vehicle.pk}/notes/'
        for user in [self.driver_user, self.dispatcher]:
            self.assertEqual(self.client_for(user).post(endpoint, {'text': 'Concern'}).status_code, 403)
            self.assertEqual(self.client_for(user).get(endpoint).status_code, 403)
        client = self.client_for(self.it)
        self.assertEqual(client.post(endpoint, {'text': ''}).status_code, 400)
        response = client.post(endpoint, {'text': 'Check tire', 'author': self.driver_user.pk}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['author'], self.it.pk)
        self.assertEqual(client.get(endpoint).data['count'], 1)
        self.assertEqual(client.patch(endpoint, {'text': 'overwrite'}).status_code, 405)
        self.assertEqual(AuditRecord.objects.get().action, 'vehicle.note_added')

    def test_note_and_audit_rollback_together(self):
        with patch('core.history_api.record', side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):
                self.client_for(self.admin).post(f'/api/vehicles/{self.vehicle.pk}/notes/', {'text': 'Concern'})
        self.assertFalse(VehicleNote.objects.exists())

    def test_turn_in_review_history_preserves_existing_permissions(self):
        shift = Shift.objects.create(driver=self.driver, vehicle=self.vehicle, end_time=timezone.now(), turn_in_amount=10)
        for action, actor in [('approve', self.admin), ('reject', self.it)]:
            response = self.client_for(actor).post(f'/api/shifts/{shift.pk}/{action}/', {})
            self.assertEqual(response.status_code, 200)
        records = list(AuditRecord.objects.order_by('pk'))
        self.assertEqual([r.action for r in records], ['turn_in.approve', 'turn_in.reject'])
        self.assertTrue(records[1].details['before']['cleared'])
        self.assertFalse(records[1].details['after']['cleared'])
        self.assertEqual(self.client_for(self.dispatcher).post(f'/api/shifts/{shift.pk}/approve/', {}).status_code, 403)
        self.assertEqual(AuditRecord.objects.count(), 2)
        self.assertEqual(self.client_for(self.driver_user).get(f'/api/history/shifts/{shift.pk}/turn-in/').data['count'], 2)
        self.assertEqual(self.client_for(self.other_user).get(f'/api/history/shifts/{shift.pk}/turn-in/').status_code, 404)

    def test_assignment_event_audit_and_trip_rollback_together(self):
        Shift.objects.create(driver=self.driver, vehicle=self.vehicle)
        trip = self.trip()
        with patch('core.operations.record', side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):
                claim_trip(self.driver_user, trip.pk)
        trip.refresh_from_db()
        self.assertEqual(trip.status, Trip.Status.OPEN)
        self.assertFalse(NotificationEvent.objects.exists())
        claim_trip(self.driver_user, trip.pk)
        self.assertEqual(NotificationEvent.objects.count(), 1)
        self.assertEqual(AuditRecord.objects.get().action, 'trip.assigned')

    def test_audit_is_restricted_and_read_only(self):
        for user in [self.driver_user, self.dispatcher]:
            self.assertEqual(self.client_for(user).get('/api/audit/').status_code, 403)
        self.assertEqual(self.client_for(self.admin).get('/api/audit/').status_code, 200)
        self.assertEqual(self.client_for(self.it).post('/api/audit/', {}).status_code, 405)
