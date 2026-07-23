from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.courses.models import Course, Enrolment

from .forms import CollaborationProfileForm
from .models import Skill, StudentCollaborationProfile, StudentProfileSkill


class CollaborationProfileTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.instructor = user_model.objects.create_user(
            username="profile.instructor",
            email="profile.instructor@example.test",
            display_name="Profile Instructor",
            role=user_model.Role.INSTRUCTOR,
            password="StrongPass!2026",
        )
        self.other_instructor = user_model.objects.create_user(
            username="other.profile.instructor",
            email="other.profile.instructor@example.test",
            display_name="Other Instructor",
            role=user_model.Role.INSTRUCTOR,
            password="StrongPass!2026",
        )
        self.student = user_model.objects.create_user(
            username="profile.student",
            email="private.student@example.test",
            display_name="Profile Student",
            role=user_model.Role.STUDENT,
            password="StrongPass!2026",
        )
        self.classmate = user_model.objects.create_user(
            username="profile.classmate",
            email="private.classmate@example.test",
            display_name="Profile Classmate",
            role=user_model.Role.STUDENT,
            password="StrongPass!2026",
        )
        self.unrelated = user_model.objects.create_user(
            username="profile.unrelated",
            email="private.unrelated@example.test",
            display_name="Unrelated Student",
            role=user_model.Role.STUDENT,
            password="StrongPass!2026",
        )
        self.staff = user_model.objects.create_user(
            username="profile.staff",
            email="profile.staff@example.test",
            display_name="Profile Staff",
            role=user_model.Role.INSTRUCTOR,
            is_staff=True,
            password="StrongPass!2026",
        )
        self.student_profile = self.student.collaboration_profile
        self.classmate_profile = self.classmate.collaboration_profile
        self.unrelated_profile = self.unrelated.collaboration_profile
        self.course = Course.objects.create(
            code="PROF101",
            slug="profile-course",
            title="Profile Course",
            description="A course for profile visibility tests.",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
            enrolment_mode=Course.EnrolmentMode.OPEN,
        )
        self.student_enrolment = Enrolment.objects.create(
            course=self.course,
            student=self.student,
            status=Enrolment.Status.ACTIVE,
        )
        self.classmate_enrolment = Enrolment.objects.create(
            course=self.course,
            student=self.classmate,
            status=Enrolment.Status.ACTIVE,
        )

    def test_student_can_edit_own_collaboration_profile_and_add_skills(self):
        python = Skill.objects.create(name="Python")
        self.client.force_login(self.student)

        response = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "collaboration_mode": "OFFLINE",
                "availability": "  Saturday mornings  ",
                "skills": [str(python.id)],
                "new_skills": " Academic   writing, python ",
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:profile_detail", args=[self.student.id]),
        )
        self.student_profile.refresh_from_db()
        self.assertEqual(
            self.student_profile.collaboration_mode,
            StudentCollaborationProfile.CollaborationMode.OFFLINE,
        )
        self.assertEqual(self.student_profile.availability, "Saturday mornings")
        self.assertEqual(
            set(self.student_profile.skills.values_list("name", flat=True)),
            {"Python", "Academic writing"},
        )

    def test_profile_form_rejects_unsupported_mode_and_long_availability(self):
        form = CollaborationProfileForm(
            {
                "collaboration_mode": "HYBRID",
                "availability": "x" * 301,
                "new_skills": "",
            },
            profile=self.student_profile,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("collaboration_mode", form.errors)
        self.assertIn("availability", form.errors)

    def test_skill_names_are_normalized_and_case_insensitively_unique(self):
        skill = Skill.objects.create(name="  Data   Science  ")
        self.assertEqual(skill.name, "Data Science")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Skill.objects.create(name="data science")

    def test_duplicate_profile_skill_is_prevented(self):
        skill = Skill.objects.create(name="Research")
        StudentProfileSkill.objects.create(
            profile=self.student_profile,
            skill=skill,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentProfileSkill.objects.create(
                profile=self.student_profile,
                skill=skill,
            )

    def test_collaboration_mode_model_accepts_only_supported_values(self):
        self.student_profile.collaboration_mode = "HYBRID"
        with self.assertRaises(ValidationError):
            self.student_profile.full_clean()

        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentCollaborationProfile.objects.filter(
                pk=self.student_profile.pk
            ).update(collaboration_mode="HYBRID")

    def test_student_cannot_edit_another_students_profile(self):
        self.client.force_login(self.classmate)

        response = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "user": str(self.student.id),
                "collaboration_mode": "OFFLINE",
                "availability": "Attempted overwrite",
                "new_skills": "",
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:profile_detail", args=[self.classmate.id]),
        )
        self.student_profile.refresh_from_db()
        self.classmate_profile.refresh_from_db()
        self.assertEqual(self.student_profile.availability, "")
        self.assertEqual(self.classmate_profile.availability, "Attempted overwrite")

    def test_shared_active_course_allows_profile_view_without_private_fields(self):
        self.student_profile.availability = "Weekdays after 6 PM"
        self.student_profile.save()
        self.client.force_login(self.classmate)

        response = self.client.get(
            reverse("accounts:profile_detail", args=[self.student.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Profile Student")
        self.assertContains(response, "Weekdays after 6 PM")
        self.assertNotContains(response, self.student.email)
        self.assertNotContains(response, self.student.username)
        self.assertNotContains(response, "membership")
        self.assertNotContains(response, "is_staff")

    def test_unrelated_or_withdrawn_student_cannot_view_profile(self):
        self.client.force_login(self.unrelated)
        url = reverse("accounts:profile_detail", args=[self.student.id])
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.classmate)
        self.classmate_enrolment.status = Enrolment.Status.WITHDRAWN
        self.classmate_enrolment.save(update_fields=["status"])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_owned_course_instructor_and_staff_can_view_profile(self):
        url = reverse("accounts:profile_detail", args=[self.student.id])
        for viewer in (self.instructor, self.staff):
            with self.subTest(viewer=viewer.username):
                self.client.force_login(viewer)
                self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.other_instructor)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_archived_course_does_not_grant_profile_visibility(self):
        self.course.status = Course.Status.ARCHIVED
        self.course.save(update_fields=["status"])
        url = reverse("accounts:profile_detail", args=[self.student.id])

        for viewer in (self.classmate, self.instructor):
            with self.subTest(viewer=viewer.username):
                self.client.force_login(viewer)
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_own_profile_has_helpful_empty_states(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("accounts:profile"))

        self.assertRedirects(
            response,
            reverse("accounts:profile_detail", args=[self.student.id]),
        )
        detail = self.client.get(response.url)
        self.assertContains(detail, "No availability has been shared yet.")
        self.assertContains(detail, "No skills have been added yet.")

    def test_active_course_participants_page_links_to_profiles(self):
        self.client.force_login(self.student)

        response = self.client.get(
            reverse("courses:participants", args=[self.course.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Profile Student")
        self.assertContains(response, "Profile Classmate")
        self.assertContains(
            response,
            reverse("accounts:profile_detail", args=[self.classmate.id]),
        )

    def test_anonymous_and_unrelated_users_cannot_access_profile_or_participants(self):
        profile_url = reverse(
            "accounts:profile_detail",
            args=[self.student.id],
        )
        participants_url = reverse("courses:participants", args=[self.course.id])
        self.assertRedirects(
            self.client.get(profile_url),
            f"{reverse('accounts:login')}?next={profile_url}",
        )
        self.assertRedirects(
            self.client.get(participants_url),
            f"{reverse('accounts:login')}?next={participants_url}",
        )

        self.client.force_login(self.unrelated)
        self.assertEqual(self.client.get(profile_url).status_code, 404)
        self.assertEqual(self.client.get(participants_url).status_code, 404)

    def test_registration_creates_student_profile_only(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "new.profile.student",
                "email": "new.profile.student@example.test",
                "display_name": "New Profile Student",
                "role": get_user_model().Role.STUDENT,
                "password1": "StrongPass!2026",
                "password2": "StrongPass!2026",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        user = get_user_model().objects.get(username="new.profile.student")
        self.assertTrue(StudentCollaborationProfile.objects.filter(user=user).exists())

    def test_manager_created_student_receives_profile(self):
        user = get_user_model().objects.create_user(
            username="manager.profile.student",
            email="manager.profile.student@example.test",
            display_name="Manager Profile Student",
            role=get_user_model().Role.STUDENT,
            password="StrongPass!2026",
        )

        self.assertTrue(StudentCollaborationProfile.objects.filter(user=user).exists())
