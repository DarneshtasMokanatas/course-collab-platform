from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AccountWorkflowTests(TestCase):
    def test_registration_normalizes_identity_logs_in_and_redirects(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "  New.Student  ",
                "email": "New.Student@EXAMPLE.TEST",
                "display_name": "  New Student  ",
                "role": get_user_model().Role.STUDENT,
                "password1": "SafeTestPassword!2026",
                "password2": "SafeTestPassword!2026",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        user = get_user_model().objects.get(username="new.student")
        self.assertEqual(user.email, "new.student@example.test")
        self.assertEqual(user.display_name, "New Student")
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))

    def test_registration_rejects_case_insensitive_duplicate_email(self):
        user_model = get_user_model()
        user_model.objects.create_user(
            username="existing",
            email="shared@example.test",
            display_name="Existing",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )

        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "different",
                "email": "SHARED@EXAMPLE.TEST",
                "display_name": "Different",
                "role": user_model.Role.INSTRUCTOR,
                "password1": "SafeTestPassword!2026",
                "password2": "SafeTestPassword!2026",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "identity is already in use")
        self.assertEqual(user_model.objects.count(), 1)

    def test_login_accepts_email_and_uses_generic_invalid_error(self):
        user_model = get_user_model()
        user_model.objects.create_user(
            username="login.user",
            email="login@example.test",
            display_name="Login User",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "LOGIN@EXAMPLE.TEST", "password": "SafeTestPassword!2026"},
        )
        self.assertRedirects(response, reverse("dashboard"))

        self.client.logout()
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "unknown@example.test", "password": "wrong"},
        )
        self.assertContains(
            response, "Please enter a correct username or email and password"
        )
        self.assertNotContains(response, "account does not exist")

    def test_dashboard_requires_authentication_and_logout_requires_post(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('dashboard')}",
        )
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
