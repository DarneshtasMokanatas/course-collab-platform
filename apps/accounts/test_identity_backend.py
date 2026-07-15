from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase


class IdentityBackendCollisionTests(TestCase):
    def create_collision(self, first_password, second_password):
        user_model = get_user_model()
        first = user_model(
            username="shared@example.test",
            email="first@example.test",
            display_name="First",
            role=user_model.Role.STUDENT,
        )
        first.set_password(first_password)
        first.save()
        second = user_model(
            username="second",
            email="shared@example.test",
            display_name="Second",
            role=user_model.Role.STUDENT,
        )
        second.set_password(second_password)
        second.save()
        return first, second

    def test_persisted_cross_field_collision_uses_unique_password_match(self):
        first, second = self.create_collision(
            "FirstPassword!2026", "SecondPassword!2026"
        )

        self.assertEqual(
            authenticate(username="shared@example.test", password="FirstPassword!2026"),
            first,
        )
        self.assertEqual(
            authenticate(
                username="shared@example.test", password="SecondPassword!2026"
            ),
            second,
        )

    def test_ambiguous_password_match_is_denied(self):
        self.create_collision("SharedPassword!2026", "SharedPassword!2026")

        self.assertIsNone(
            authenticate(username="shared@example.test", password="SharedPassword!2026")
        )
