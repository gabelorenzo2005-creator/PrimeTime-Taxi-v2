from unittest.mock import patch
from rest_framework.authtoken.models import Token
from .test_mobile import MobileFixture
from .models import AuditRecord, Role, SafetyAlert
from .services import create_account, deactivate_account, reactivate_account, reset_password


class AccountAuditTests(MobileFixture):
    def test_lifecycle_audit_contains_no_credentials(self):
        user, profile = create_account('New', 'Test', 'test-private-password', Role.DISPATCHER, actor=self.it)
        Token.objects.create(user=user)
        deactivate_account(user, actor=self.it)
        self.assertFalse(Token.objects.filter(user=user).exists())
        reactivate_account(user, actor=self.it)
        reset_password(user, 'new-private-password', actor=self.it)
        user.refresh_from_db()
        profile.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password('new-private-password'))
        self.assertTrue(profile.must_change_password)
        records = list(AuditRecord.objects.filter(subject_id=user.pk).order_by('pk'))
        self.assertEqual([r.action for r in records], ['account.created', 'account.deactivated', 'account.reactivated', 'account.password_reset'])
        self.assertTrue(all(r.actor_id == self.it.pk for r in records))
        self.assertEqual([r.details for r in records[1:]], [{}, {}, {}])
        self.assertNotIn('password', str([r.details for r in records]))

    def test_deactivation_and_token_revocation_roll_back_when_audit_fails(self):
        token = Token.objects.create(user=self.driver_user)
        with patch('core.services.record', side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):
                deactivate_account(self.driver_user, actor=self.it)
        self.driver_user.refresh_from_db()
        self.assertTrue(self.driver_user.is_active)
        self.assertTrue(Token.objects.filter(pk=token.pk).exists())

    def test_legacy_callers_remain_supported(self):
        deactivate_account(self.driver_user)
        self.assertFalse(AuditRecord.objects.exists())

    def test_alert_history_is_driver_scoped_and_searchable(self):
        own = SafetyAlert.objects.create(driver=self.driver, kind=SafetyAlert.Kind.OTHER, notes='Tire concern')
        foreign = SafetyAlert.objects.create(driver=self.driver2, kind=SafetyAlert.Kind.OTHER, notes='Tire concern')
        client = self.client_for(self.driver_user)
        result = client.get('/api/history/alerts/?q=Tire&page_size=1')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data['count'], 1)
        self.assertEqual(result.data['results'][0]['id'], own.pk)
        self.assertEqual(client.get(f'/api/history/alerts/{foreign.pk}/').status_code, 404)
        self.assertEqual(self.client_for(self.dispatcher).get('/api/history/alerts/?q=Tire').data['count'], 2)

    def test_logout_audits_without_retaining_token(self):
        client = self.client_for(self.driver_user)
        self.assertEqual(client.post('/api/logout/', {}).status_code, 204)
        self.assertFalse(Token.objects.filter(user=self.driver_user).exists())
        audit = AuditRecord.objects.get()
        self.assertEqual(audit.action, 'account.logged_out')
        self.assertEqual(audit.details, {})

    def test_password_change_api_audits_and_revokes_old_token(self):
        client = self.client_for(self.driver_user)
        old_token = Token.objects.get(user=self.driver_user).key
        response = client.post('/api/password/', {'current_password': 'test-mobile-password',
                              'new_password': 'strong-replacement-password-82'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(Token.objects.filter(pk=old_token).exists())
        audit = AuditRecord.objects.get()
        self.assertEqual(audit.action, 'account.password_changed')
        self.assertEqual(audit.details, {})
