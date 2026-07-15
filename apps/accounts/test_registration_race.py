from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse


class RegistrationRaceTests(TestCase):
    def test_uniqueness_race_returns_a_form_error(self):
        data = {
            "username": "racing.user",
            "email": "racing@example.test",
            "display_name": "Racing User",
            "role": get_user_model().Role.STUDENT,
            "password1": "SafeTestPassword!2026",
            "password2": "SafeTestPassword!2026",
        }
        with patch(
            "apps.accounts.views.RegistrationForm.save",
            side_effect=IntegrityError("simulated uniqueness race"),
        ):
            response = self.client.post(reverse("accounts:register"), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "account with that identity already exists")
        self.assertEqual(get_user_model().objects.count(), 0)
