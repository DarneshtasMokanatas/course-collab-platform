from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.announcements.models import Announcement
from apps.assignments.models import Assignment, GradeRevision, Submission
from apps.materials.models import MaterialVersion

from .models import Course, CourseSection, Enrolment


class CourseConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.instructor = user_model.objects.create_user(
            username="instructor",
            email="instructor@tests.example",
            display_name="Instructor",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        cls.student = user_model.objects.create_user(
            username="student",
            email="student@tests.example",
            display_name="Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )

    def create_course(self, code="TEST101"):
        return Course.objects.create(
            code=code,
            slug=code.lower(),
            title="Test Course",
            description="Test description",
            instructor=self.instructor,
        )

    def test_course_code_is_normalized_and_unique(self):
        course = self.create_course(" test101 ")
        self.assertEqual(course.code, "TEST101")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_course("test101")

    def test_section_position_and_enrolment_are_unique(self):
        course = self.create_course()
        CourseSection.objects.create(course=course, title="One", position=1)
        Enrolment.objects.create(course=course, student=self.student)

        with self.assertRaises(IntegrityError), transaction.atomic():
            CourseSection.objects.create(course=course, title="Duplicate", position=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrolment.objects.create(course=course, student=self.student)


class SeedDemoTests(TestCase):
    def test_seed_demo_is_idempotent_and_complete(self):
        call_command("seed_demo", verbosity=0)
        call_command("seed_demo", verbosity=0)

        self.assertEqual(Course.objects.filter(code="DEMO101").count(), 1)
        course = Course.objects.get(code="DEMO101")
        self.assertEqual(course.sections.count(), 2)
        self.assertEqual(
            course.enrolments.filter(status=Enrolment.Status.ACTIVE).count(), 2
        )
        self.assertEqual(
            MaterialVersion.objects.filter(material__course=course).count(), 2
        )
        self.assertEqual(Announcement.objects.filter(course=course).count(), 2)
        self.assertEqual(Assignment.objects.filter(course=course).count(), 2)
        self.assertEqual(
            Submission.objects.filter(assignment__course=course).count(), 2
        )
        self.assertEqual(
            GradeRevision.objects.filter(submission__assignment__course=course).count(),
            1,
        )
