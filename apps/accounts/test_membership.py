from types import SimpleNamespace

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditEvent

from .admin import UserAdmin
from .forms import CollaborationProfileForm, RegistrationForm
from .models import StudentCollaborationProfile, User


class MembershipStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.staff = user_model.objects.create_superuser(
            username="membership.staff",
            email="membership.staff@example.test",
            display_name="Membership Staff",
            role=user_model.Role.INSTRUCTOR,
            password="StrongPass!2026",
        )
        cls.student = user_model.objects.create_user(
            username="membership.student",
            email="membership.student@example.test",
            display_name="Membership Student",
            role=user_model.Role.STUDENT,
            password="StrongPass!2026",
        )

    def test_new_users_default_to_non_member(self):
        self.assertEqual(
            self.student.membership_status,
            User.MembershipStatus.NON_MEMBER,
        )

    def test_membership_choices_have_database_enforcement(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.student.pk).update(membership_status="PREMIUM")

    def test_ordinary_forms_do_not_expose_or_accept_membership(self):
        registration_form = RegistrationForm()
        profile_form = CollaborationProfileForm(
            profile=self.student.collaboration_profile
        )
        self.assertNotIn("membership_status", registration_form.fields)
        self.assertNotIn("membership_status", profile_form.fields)

        self.client.force_login(self.student)
        response = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "membership_status": User.MembershipStatus.MEMBER,
                "collaboration_mode": (
                    StudentCollaborationProfile.CollaborationMode.ONLINE
                ),
                "availability": "Tuesday afternoons",
                "new_skills": "",
            },
        )
        self.assertRedirects(
            response,
            reverse("accounts:profile_detail", args=[self.student.id]),
        )
        self.student.refresh_from_db()
        self.assertEqual(
            self.student.membership_status,
            User.MembershipStatus.NON_MEMBER,
        )

    def test_forged_registration_membership_is_ignored(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "forged.member",
                "email": "forged.member@example.test",
                "display_name": "Forged Member",
                "role": User.Role.STUDENT,
                "membership_status": User.MembershipStatus.MEMBER,
                "password1": "StrongPass!2026",
                "password2": "StrongPass!2026",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        user = User.objects.get(username="forged.member")
        self.assertEqual(
            user.membership_status,
            User.MembershipStatus.NON_MEMBER,
        )

    def test_staff_admin_change_is_audited_without_personal_data(self):
        target = User.objects.get(pk=self.student.pk)
        target.membership_status = User.MembershipStatus.MEMBER
        user_admin = UserAdmin(User, admin.site)

        user_admin.save_model(
            SimpleNamespace(user=self.staff),
            target,
            form=None,
            change=True,
        )

        target.refresh_from_db()
        self.assertEqual(target.membership_status, User.MembershipStatus.MEMBER)
        event = AuditEvent.objects.get(
            action="USER_MEMBERSHIP_CHANGED",
            object_id=target.id,
        )
        self.assertEqual(
            event.metadata,
            {
                "from": User.MembershipStatus.NON_MEMBER,
                "to": User.MembershipStatus.MEMBER,
            },
        )
        self.assertIsNone(event.course_id)
        self.assertNotIn("email", event.metadata)

    def test_admin_add_forces_default_non_member_despite_forged_value(self):
        self.client.force_login(self.staff)
        add_url = reverse("admin:accounts_user_add")
        response = self.client.get(add_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="membership_status"')

        response = self.client.post(
            add_url,
            {
                "username": "admin.created.member",
                "password1": "StrongPass!2026",
                "password2": "StrongPass!2026",
                "email": "admin.created.member@example.test",
                "display_name": "Admin Created Member",
                "role": User.Role.STUDENT,
                "membership_status": User.MembershipStatus.MEMBER,
            },
        )

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="admin.created.member")
        self.assertEqual(
            user.membership_status,
            User.MembershipStatus.NON_MEMBER,
        )
        self.assertFalse(
            AuditEvent.objects.filter(
                action="USER_MEMBERSHIP_CHANGED",
                object_id=user.id,
            ).exists()
        )

    def test_real_admin_change_updates_and_audits_membership(self):
        self.client.force_login(self.staff)
        target = User.objects.get(pk=self.student.pk)
        change_url = reverse("admin:accounts_user_change", args=[target.id])

        response = self.client.post(
            change_url,
            {
                "username": target.username,
                "password": target.password,
                "first_name": target.first_name,
                "last_name": target.last_name,
                "email": target.email,
                "role": target.role,
                "membership_status": User.MembershipStatus.MEMBER,
                "display_name": target.display_name,
                "is_active": "on",
                "date_joined_0": target.date_joined.strftime("%Y-%m-%d"),
                "date_joined_1": target.date_joined.strftime("%H:%M:%S"),
                "_save": "Save",
            },
        )

        self.assertEqual(response.status_code, 302)
        target.refresh_from_db()
        self.assertEqual(target.membership_status, User.MembershipStatus.MEMBER)
        self.assertEqual(
            AuditEvent.objects.filter(
                action="USER_MEMBERSHIP_CHANGED",
                object_id=target.id,
            ).count(),
            1,
        )

    def test_nonstaff_cannot_access_membership_admin(self):
        self.client.force_login(self.student)
        change_url = reverse("admin:accounts_user_change", args=[self.student.id])

        response = self.client.post(
            change_url,
            {"membership_status": User.MembershipStatus.MEMBER},
        )

        self.assertEqual(response.status_code, 302)
        self.student.refresh_from_db()
        self.assertEqual(
            self.student.membership_status,
            User.MembershipStatus.NON_MEMBER,
        )

    def test_unchanged_admin_save_does_not_create_membership_audit(self):
        target = User.objects.get(pk=self.student.pk)
        user_admin = UserAdmin(User, admin.site)

        user_admin.save_model(
            SimpleNamespace(user=self.staff),
            target,
            form=None,
            change=True,
        )

        self.assertFalse(
            AuditEvent.objects.filter(
                action="USER_MEMBERSHIP_CHANGED",
                object_id=target.id,
            ).exists()
        )
