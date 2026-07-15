from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Course, Enrolment


class CatalogueAndEnrolmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.instructor = user_model.objects.create_user(
            username="catalogue.teacher",
            email="catalogue.teacher@example.test",
            display_name="Catalogue Teacher",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        cls.student = user_model.objects.create_user(
            username="catalogue.student",
            email="catalogue.student@example.test",
            display_name="Catalogue Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        cls.open_course = Course.objects.create(
            code="OPEN101",
            slug="open101",
            title="Open course",
            description="Open",
            instructor=cls.instructor,
            status=Course.Status.PUBLISHED,
            enrolment_mode=Course.EnrolmentMode.OPEN,
        )
        cls.closed_course = Course.objects.create(
            code="CLOSED101",
            slug="closed101",
            title="Closed course",
            description="Closed",
            instructor=cls.instructor,
            status=Course.Status.PUBLISHED,
            enrolment_mode=Course.EnrolmentMode.CLOSED,
        )
        cls.draft_course = Course.objects.create(
            code="DRAFT101",
            slug="draft101",
            title="Draft course",
            description="Draft",
            instructor=cls.instructor,
        )

    def test_student_catalogue_shows_only_published_open_courses(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("courses:list"))
        self.assertContains(response, "Open course")
        self.assertNotContains(response, "Closed course")
        self.assertNotContains(response, "Draft course")

    def test_enrolment_is_idempotent_and_reactivates_withdrawn_record(self):
        self.client.force_login(self.student)
        url = reverse("courses:enrol", args=[self.open_course.id])
        response = self.client.post(url)
        self.assertRedirects(
            response, reverse("courses:detail", args=[self.open_course.id])
        )
        response = self.client.post(url)
        self.assertRedirects(
            response, reverse("courses:detail", args=[self.open_course.id])
        )
        self.assertEqual(
            Enrolment.objects.filter(
                course=self.open_course, student=self.student
            ).count(),
            1,
        )
        enrolment = Enrolment.objects.get(course=self.open_course, student=self.student)
        enrolment.status = Enrolment.Status.WITHDRAWN
        enrolment.save(update_fields=["status"])
        self.client.post(url)
        enrolment.refresh_from_db()
        self.assertEqual(enrolment.status, Enrolment.Status.ACTIVE)
        self.assertIsNone(enrolment.withdrawn_at)

    def test_enrolment_denies_wrong_role_and_closed_or_draft_course(self):
        self.client.force_login(self.instructor)
        self.assertEqual(
            self.client.post(
                reverse("courses:enrol", args=[self.open_course.id])
            ).status_code,
            404,
        )
        self.client.force_login(self.student)
        self.assertEqual(
            self.client.post(
                reverse("courses:enrol", args=[self.closed_course.id])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("courses:enrol", args=[self.draft_course.id])
            ).status_code,
            404,
        )
