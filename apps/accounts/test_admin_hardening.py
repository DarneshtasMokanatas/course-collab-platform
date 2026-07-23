from types import SimpleNamespace

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.audit.models import AuditEvent
from apps.courses.models import Course, Enrolment

from .admin import UserAdmin, UserRoleAdminForm
from .models import StudentCollaborationProfile, User


class UserRoleAdminHardeningTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.staff = user_model.objects.create_superuser(
            username="role.staff",
            email="role.staff@example.test",
            display_name="Role Staff",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        cls.instructor = user_model.objects.create_user(
            username="role.instructor",
            email="role.instructor@example.test",
            display_name="Role Instructor",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        cls.student = user_model.objects.create_user(
            username="role.student",
            email="role.student@example.test",
            display_name="Role Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        cls.unbound_student = user_model.objects.create_user(
            username="role.unbound",
            email="role.unbound@example.test",
            display_name="Unbound Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        cls.course = Course.objects.create(
            code="ROLE101",
            slug="role101",
            title="Role safeguards",
            description="Role safeguards",
            instructor=cls.instructor,
        )
        Enrolment.objects.create(course=cls.course, student=cls.student)

    def test_role_change_is_rejected_when_academic_relationships_exist(self):
        for user, new_role in (
            (self.instructor, User.Role.STUDENT),
            (self.student, User.Role.INSTRUCTOR),
        ):
            form = UserRoleAdminForm(instance=user)
            form.cleaned_data = {"role": new_role}
            with self.assertRaisesMessage(ValidationError, "Resolve"):
                form.clean_role()

    def test_allowed_role_change_is_audited_without_personal_metadata(self):
        target = User.objects.get(pk=self.unbound_student.pk)
        target.role = User.Role.INSTRUCTOR
        user_admin = UserAdmin(User, admin.site)
        user_admin.save_model(
            SimpleNamespace(user=self.staff),
            target,
            form=None,
            change=True,
        )
        event = AuditEvent.objects.get(
            action="USER_ROLE_CHANGED",
            object_id=target.id,
        )
        self.assertEqual(
            event.metadata,
            {"from": User.Role.STUDENT, "to": User.Role.INSTRUCTOR},
        )
        self.assertFalse(
            StudentCollaborationProfile.objects.filter(user=target).exists()
        )
