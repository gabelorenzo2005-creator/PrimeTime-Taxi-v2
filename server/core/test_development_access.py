from io import StringIO
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core.management import call_command, CommandError
from django.db import IntegrityError, transaction
from django.test import override_settings
from rest_framework.test import APIClient
from .test_mobile import MobileFixture
from .models import AccountProfile, Driver, Role, Shift


@override_settings(DEBUG=True)
class DevelopmentAccessTests(MobileFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.developer = User.objects.create_user('gabriellorenzo', first_name='Gabriel', last_name='Lorenzo',
            password='development-test-password', is_staff=True, is_superuser=True)
        AccountProfile.objects.create(user=cls.developer, role=Role.IT, development_dashboard_access=True)
        cls.dev_driver = Driver.objects.create(user=cls.developer, first_name='Gabriel', last_name='Lorenzo',
            call_number='DEV-GAB', hack_license_number='DEV-GAB', phone_number='DEV-GABRIEL', email='gabriel.lorenzo@development.invalid')

    def preview(self, user, role):
        return self.client_for(user).get('/api/development/dashboard/', {'role': role})

    def test_all_preview_roles_are_read_only_and_driver_scoped(self):
        for role in Role.values:
            response = self.preview(self.developer, role)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['view_as_role'], role)
            self.assertEqual(response.data['user']['role'], Role.IT)
            self.assertTrue(response.data['user']['development_dashboard_access'])
            if role == Role.DRIVER:
                self.assertEqual(response.data['driver_id'], self.dev_driver.pk)
                self.assertEqual([d['id'] for d in response.data['drivers']], [self.dev_driver.pk])
        self.developer.refresh_from_db()
        self.assertEqual(self.developer.profile.role, Role.IT)
        self.assertEqual(self.client_for(self.developer).post('/api/development/dashboard/', {'role': 'ADMIN'}, format='json').status_code, 405)

    def test_ordinary_accounts_including_same_name_cannot_preview(self):
        self.it.first_name, self.it.last_name = 'Gabriel', 'Lorenzo'
        self.it.is_staff = self.it.is_superuser = True
        self.it.save()
        for user in [self.driver_user, self.other_user, self.admin, self.dispatcher, self.it]:
            for role in Role.values:
                self.assertEqual(self.preview(user, role).status_code, 403)
            self.assertFalse(self.client_for(user).get('/api/session/').data['development_dashboard_access'])
        self.assertEqual(APIClient().get('/api/development/dashboard/', {'role': 'IT'}).status_code, 401)

    @override_settings(DEBUG=False)
    def test_debug_false_disables_every_role_and_capability(self):
        for role in Role.values:
            self.assertEqual(self.preview(self.developer, role).status_code, 403)
        for path in ['/api/session/', '/api/workspace/']:
            self.assertFalse(self.client_for(self.developer).get(path).data['user']['development_dashboard_access'] if path.endswith('workspace/') else self.client_for(self.developer).get(path).data['development_dashboard_access'])
        response = APIClient().post('/api/login/', {'username': self.developer.username, 'password': 'development-test-password'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['development_dashboard_access'])
        self.developer.refresh_from_db()
        self.assertEqual(self.developer.profile.role, Role.IT)

    def test_flag_requires_staff_superuser_and_technician_role(self):
        for changes in [{'is_staff': False}, {'is_superuser': False}]:
            User.objects.filter(pk=self.developer.pk).update(**changes)
            self.assertEqual(self.preview(self.developer, 'ADMIN').status_code, 403)
            User.objects.filter(pk=self.developer.pk).update(is_staff=True, is_superuser=True)
        AccountProfile.objects.filter(user=self.developer).update(role=Role.ADMIN)
        self.assertEqual(self.preview(self.developer, 'ADMIN').status_code, 403)

    def test_password_change_and_bad_preview_role_are_not_bypassed(self):
        self.assertEqual(self.preview(self.developer, 'SUPERUSER').status_code, 400)
        AccountProfile.objects.filter(user=self.developer).update(must_change_password=True)
        self.assertEqual(self.preview(self.developer, 'IT').status_code, 403)
        self.assertFalse(self.client_for(self.developer).get('/api/session/').data['development_dashboard_access'])

    def test_preview_does_not_grant_driver_or_dispatcher_operations(self):
        client = self.client_for(self.developer)
        self.assertEqual(self.preview(self.developer, 'DRIVER').status_code, 200)
        self.assertEqual(client.post('/api/shifts/', {'vehicle_id': self.vehicle.pk}, format='json').status_code, 403)
        self.assertEqual(client.post('/api/gps/', {}, format='json').status_code, 403)
        self.assertEqual(client.post('/api/trips/', {'pick_up_location': 'Test', 'drop_off_location': 'Test'}, format='json').status_code, 403)
        self.assertEqual(client.post('/api/trips/123/accept/', {}, format='json').status_code, 403)
        # Technician permissions still work because the stored role is unchanged.
        self.assertEqual(client.post('/api/records/owners/', {'name': 'Development owner'}, format='json').status_code, 201)

    def test_only_one_account_can_own_flag_and_normal_query_does_not_impersonate(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccountProfile.objects.filter(user=self.it).update(development_dashboard_access=True)
        response = self.client_for(self.it).get('/api/workspace/', {'role': 'DRIVER', 'development_dashboard_access': 'true'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['view_as_role'])
        self.assertEqual(response.data['user']['role'], Role.IT)

    def test_initialization_hashes_password_and_reuses_own_driver(self):
        with patch('core.management.commands.init_developer.getpass', side_effect=['new-development-test-password'] * 2):
            call_command('init_developer', stdout=StringIO())
        self.developer.refresh_from_db()
        self.assertTrue(self.developer.check_password('new-development-test-password'))
        self.assertNotEqual(self.developer.password, 'new-development-test-password')
        self.assertTrue(self.developer.is_staff and self.developer.is_superuser)
        self.assertEqual(self.developer.profile.role, Role.IT)
        self.assertEqual(Driver.objects.filter(user=self.developer).count(), 1)
        self.assertEqual(Driver.objects.get(user=self.developer).pk, self.dev_driver.pk)

    def test_initialization_creates_profile_driver_and_preserves_unrelated_accounts(self):
        self.dev_driver.delete()
        self.developer.delete()
        old = list(User.objects.values_list('pk', 'password', 'is_staff', 'is_superuser'))
        with patch('core.management.commands.init_developer.getpass', side_effect=['new-development-test-password'] * 2):
            call_command('init_developer', stdout=StringIO())
        developer = User.objects.get(username='gabriellorenzo')
        self.assertEqual((developer.first_name, developer.last_name), ('Gabriel', 'Lorenzo'))
        self.assertEqual(developer.profile.role, Role.IT)
        self.assertTrue(developer.profile.development_dashboard_access)
        self.assertEqual(developer.driver_profile.call_number, 'DEV-GAB')
        for pk, password, staff, superuser in old:
            user = User.objects.get(pk=pk)
            self.assertEqual((user.password, user.is_staff, user.is_superuser), (password, staff, superuser))

    @override_settings(DEBUG=False)
    def test_initialization_refuses_production_without_prompt_or_writes(self):
        with patch('core.management.commands.init_developer.getpass') as prompt:
            with self.assertRaises(CommandError): call_command('init_developer', stdout=StringIO())
        prompt.assert_not_called()

    def test_conflicting_driver_identity_rolls_back_initialization(self):
        self.dev_driver.user = None
        self.dev_driver.save()
        password = self.developer.password
        with patch('core.management.commands.init_developer.getpass', side_effect=['new-development-test-password'] * 2):
            with self.assertRaises(CommandError): call_command('init_developer', stdout=StringIO())
        self.developer.refresh_from_db()
        self.assertEqual(self.developer.password, password)
        self.dev_driver.refresh_from_db()
        self.assertIsNone(self.dev_driver.user_id)
