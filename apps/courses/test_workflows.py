from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditEvent

from .models import Course, CourseSection


class CourseWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.instructor = user_model.objects.create_user(
            username="teacher",
            email="teacher@example.test",
            display_name="Teacher",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        cls.other_instructor = user_model.objects.create_user(
            username="other",
            email="other@example.test",
            display_name="Other",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        cls.student = user_model.objects.create_user(
            username="student2",
            email="student2@example.test",
            display_name="Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )

    def course_data(self, **overrides):
        data = {
            "code": "CS101",
            "title": "Course Setup",
            "description": "A complete course description.",
            "syllabus": "Weekly topics",
            "enrolment_mode": Course.EnrolmentMode.CLOSED,
        }
        data.update(overrides)
        return data

    def formset_data(self, sections):
        data = {
            "sections-TOTAL_FORMS": str(len(sections)),
            "sections-INITIAL_FORMS": "0",
            "sections-MIN_NUM_FORMS": "0",
            "sections-MAX_NUM_FORMS": "1000",
        }
        for index, (title, description, order) in enumerate(sections):
            data.update(
                {
                    f"sections-{index}-title": title,
                    f"sections-{index}-description": description,
                    f"sections-{index}-ORDER": str(order),
                }
            )
        return data

    def test_instructor_creates_edits_orders_and_publishes_course(self):
        self.client.force_login(self.instructor)
        response = self.client.post(
            reverse("courses:new"), self.course_data(code=" cs101 ")
        )
        course = Course.objects.get()
        self.assertRedirects(response, reverse("courses:edit", args=[course.id]))
        self.assertEqual(course.code, "CS101")
        data = self.course_data(enrolment_mode=Course.EnrolmentMode.OPEN)
        data.update(
            self.formset_data([("Week two", "Second", 2), ("Week one", "First", 1)])
        )
        response = self.client.post(reverse("courses:edit", args=[course.id]), data)
        self.assertRedirects(response, reverse("courses:detail", args=[course.id]))
        self.assertEqual(
            list(course.sections.order_by("position").values_list("title", flat=True)),
            ["Week one", "Week two"],
        )
        response = self.client.post(reverse("courses:publish", args=[course.id]))
        self.assertRedirects(response, reverse("courses:detail", args=[course.id]))
        course.refresh_from_db()
        self.assertEqual(course.status, Course.Status.PUBLISHED)
        self.assertTrue(
            AuditEvent.objects.filter(course=course, action="COURSE_PUBLISHED").exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                course=course, action="COURSE_ENROLMENT_MODE_CHANGED"
            ).exists()
        )

    def test_publication_requires_a_section_and_permissions_are_enforced(self):
        course = Course.objects.create(
            code="EMPTY",
            slug="empty",
            title="Empty",
            description="No sections",
            instructor=self.instructor,
        )
        self.client.force_login(self.instructor)
        response = self.client.post(
            reverse("courses:publish", args=[course.id]), follow=True
        )
        self.assertContains(response, "Add at least one section")
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("courses:new")).status_code, 403)
        self.client.force_login(self.other_instructor)
        self.assertEqual(
            self.client.get(reverse("courses:detail", args=[course.id])).status_code,
            404,
        )

    def test_duplicate_section_order_is_rejected(self):
        course = Course.objects.create(
            code="ORDER",
            slug="order",
            title="Order",
            description="Ordered",
            instructor=self.instructor,
        )
        self.client.force_login(self.instructor)
        data = self.course_data(code="ORDER")
        data.update(self.formset_data([("One", "", 1), ("Two", "", 1)]))
        response = self.client.post(reverse("courses:edit", args=[course.id]), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Each section order must be unique")
        self.assertEqual(CourseSection.objects.filter(course=course).count(), 0)
