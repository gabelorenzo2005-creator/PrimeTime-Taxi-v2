from django.contrib.auth.models import User
from django.test import TestCase
from .models import AccountProfile, Role
from .services import create_account


class LoginTests(TestCase):
    def login(self, username="testuser", password="development-test-password"):
        return self.client.post("/api/login/", {"username": username, "password": password}, content_type="application/json")

    def test_missing_profile_returns_actionable_error(self):
        User.objects.create_user("testuser", password="development-test-password")
        response = self.login()
        self.assertEqual(response.status_code, 403)
        self.assertIn("role profile", response.json()["error"])

    def test_all_roles_are_returned(self):
        for role in Role.values:
            with self.subTest(role=role):
                user, profile = create_account("Test", role, "development-test-password", role)
                response = self.login(user.username)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["role"], role)

    def test_inactive_account_cannot_login(self):
        user, _ = create_account("Test", "Inactive", "development-test-password", Role.DRIVER)
        user.is_active = False
        user.save()
        self.assertEqual(self.login(user.username).status_code, 401)

    def test_invalid_role_cannot_login(self):
        user = User.objects.create_user("testuser", password="development-test-password")
        AccountProfile.objects.create(user=user, role="UNKNOWN")
        self.assertEqual(self.login().status_code, 403)
