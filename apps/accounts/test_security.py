from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AccountSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.user = user_model.objects.create_user(
            username="secure.user",
            email="secure@example.test",
            display_name="Secure User",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )

    def registration_data(self, **overrides):
        data = {
            "username": "new.user",
            "email": "new@example.test",
            "display_name": "New User",
            "role": get_user_model().Role.STUDENT,
            "password1": "SafeTestPassword!2026",
            "password2": "SafeTestPassword!2026",
        }
        data.update(overrides)
        return data

    def test_registration_rejects_cross_field_identity_collisions(self):
        response = self.client.post(
            reverse("accounts:register"),
            self.registration_data(username="SECURE@EXAMPLE.TEST"),
        )
        self.assertContains(response, "identity is already in use")

        get_user_model().objects.create_user(
            username="alias@example.test",
            email="alias-owner@example.test",
            display_name="Alias Owner",
            role=get_user_model().Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        response = self.client.post(
            reverse("accounts:register"),
            self.registration_data(email="ALIAS@EXAMPLE.TEST"),
        )
        self.assertContains(response, "identity is already in use")
        self.assertEqual(get_user_model().objects.count(), 2)

    def test_login_accepts_username_and_rejects_inactive_user_generically(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "SECURE.USER", "password": "SafeTestPassword!2026"},
        )
        self.assertRedirects(response, reverse("dashboard"))

        self.client.logout()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "secure.user", "password": "SafeTestPassword!2026"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Please enter a correct username or email and password"
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_post_logout_clears_session_and_redirects(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("home"))
        self.assertNotIn("_auth_user_id", self.client.session)
