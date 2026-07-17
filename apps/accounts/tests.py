from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse


class UserFoundationTests(TestCase):
    def test_user_identity_is_normalized_and_email_authentication_works(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            username="  Demo.User  ",
            email="Demo.User@EXAMPLE.TEST",
            display_name="  Demo User  ",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )

        self.assertEqual(user.username, "demo.user")
        self.assertEqual(user.email, "demo.user@example.test")
        self.assertEqual(user.display_name, "Demo User")
        self.assertEqual(
            authenticate(
                username="DEMO.USER@EXAMPLE.TEST", password="SafeTestPassword!2026"
            ),
            user,
        )

    def test_email_is_case_insensitively_unique(self):
        user_model = get_user_model()
        user_model.objects.create_user(
            username="first",
            email="shared@example.test",
            display_name="First",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        with self.assertRaises((ValidationError, IntegrityError)), transaction.atomic():
            user_model.objects.create_user(
                username="second",
                email="SHARED@example.test",
                display_name="Second",
                role=user_model.Role.STUDENT,
                password="SafeTestPassword!2026",
            )


class RegistrationPresentationTests(TestCase):
    def test_role_choice_renders_as_a_described_radio_group(self):
        response = self.client.get(reverse("accounts:register"))

        self.assertContains(response, 'id="id_role_group"')
        self.assertContains(response, 'aria-describedby="id_role_helptext"')
        self.assertContains(response, 'type="radio" name="role" value="STUDENT"')
        self.assertContains(response, 'type="radio" name="role" value="INSTRUCTOR"')
        self.assertNotContains(response, 'type="radio" name="role" value=""')

    def test_role_error_summary_targets_the_radio_group(self):
        response = self.client.post(
            reverse("accounts:register"), data={"username": "incomplete"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="#id_role_group"')
        self.assertContains(response, 'id="id_role_group"')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, "id_role_helptext id_role_error")
