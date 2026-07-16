from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.audit.models import AuditEvent

from .models import Course, CourseSection


class CourseMutationPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(
            username="owner",
            email="owner@example.test",
            display_name="Owner",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        cls.other = user_model.objects.create_user(
            username="other-owner",
            email="other-owner@example.test",
            display_name="Other",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        cls.student = user_model.objects.create_user(
            username="learner",
            email="learner@example.test",
            display_name="Learner",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        cls.staff = user_model.objects.create_user(
            username="course-staff",
            email="course-staff@example.test",
            display_name="Course Staff",
            role=user_model.Role.INSTRUCTOR,
            is_staff=True,
            password="SafeTestPassword!2026",
        )
        cls.course = Course.objects.create(
            code="PERM",
            slug="perm",
            title="Permissions",
            description="Permissions",
            instructor=cls.owner,
        )
        CourseSection.objects.create(course=cls.course, title="Week one", position=1)

    def edit_data(self):
        return {
            "code": "PERM",
            "title": "Changed",
            "description": "Permissions",
            "syllabus": "",
            "enrolment_mode": Course.EnrolmentMode.CLOSED,
            "sections-TOTAL_FORMS": "1",
            "sections-INITIAL_FORMS": "1",
            "sections-MIN_NUM_FORMS": "0",
            "sections-MAX_NUM_FORMS": "1000",
            "sections-0-id": str(self.course.sections.get().id),
            "sections-0-title": "Week one",
            "sections-0-description": "",
            "sections-0-ORDER": "1",
        }

    def test_anonymous_and_nonowners_cannot_mutate_course(self):
        edit_url = reverse("courses:edit", args=[self.course.id])
        publish_url = reverse("courses:publish", args=[self.course.id])
        self.assertEqual(self.client.post(edit_url, self.edit_data()).status_code, 302)
        self.assertEqual(self.client.post(publish_url).status_code, 302)
        for user, status in ((self.student, 404), (self.other, 404)):
            self.client.force_login(user)
            self.assertEqual(
                self.client.post(edit_url, self.edit_data()).status_code, status
            )
            self.assertEqual(self.client.post(publish_url).status_code, status)
        self.course.refresh_from_db()
        self.assertEqual(self.course.title, "Permissions")
        self.assertFalse(
            AuditEvent.objects.filter(
                course=self.course, action="COURSE_PUBLISHED"
            ).exists()
        )

    def test_staff_can_access_course_management_and_csrf_is_enforced(self):
        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.get(reverse("courses:edit", args=[self.course.id])).status_code,
            200,
        )
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(
            csrf_client.post(
                reverse("courses:publish", args=[self.course.id])
            ).status_code,
            403,
        )
