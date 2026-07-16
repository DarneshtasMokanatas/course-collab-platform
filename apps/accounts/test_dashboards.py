from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.analytics.models import ActivityEvent
from apps.announcements.models import Announcement
from apps.assignments.models import (
    Assignment,
    GradeRevision,
    Submission,
    SubmissionVersion,
)
from apps.courses.models import Course, Enrolment


class RoleDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.instructor = user_model.objects.create_user(
            username="dashboard.teacher",
            email="dashboard.teacher@example.test",
            display_name="Dashboard Teacher",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        cls.student = user_model.objects.create_user(
            username="dashboard.student",
            email="dashboard.student@example.test",
            display_name="Dashboard Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        cls.missing_student = user_model.objects.create_user(
            username="dashboard.missing",
            email="dashboard.missing@example.test",
            display_name="Missing Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        cls.withdrawn_student = user_model.objects.create_user(
            username="dashboard.withdrawn",
            email="dashboard.withdrawn@example.test",
            display_name="Withdrawn Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        cls.course = Course.objects.create(
            code="DSH101",
            slug="dsh101",
            title="Dashboard Course",
            description="Dashboard coverage",
            instructor=cls.instructor,
            status=Course.Status.PUBLISHED,
        )
        Enrolment.objects.create(course=cls.course, student=cls.student)
        Enrolment.objects.create(course=cls.course, student=cls.missing_student)
        Enrolment.objects.create(
            course=cls.course,
            student=cls.withdrawn_student,
            status=Enrolment.Status.WITHDRAWN,
            withdrawn_at=timezone.now(),
        )
        cls.assignment = Assignment.objects.create(
            course=cls.course,
            title="Upcoming dashboard work",
            instructions="Submit.",
            due_at=timezone.now() + timedelta(days=2),
            max_score=Decimal("100.00"),
            max_upload_bytes=1024,
            allowed_extensions=["pdf"],
            status=Assignment.Status.PUBLISHED,
            published_at=timezone.now(),
            created_by=cls.instructor,
        )
        cls.submission = Submission.objects.create(
            assignment=cls.assignment,
            student=cls.student,
        )
        cls.version = SubmissionVersion.objects.create(
            submission=cls.submission,
            version_number=1,
            storage_key="dashboard/submission",
            original_filename="dashboard.pdf",
            content_type="application/pdf",
            size_bytes=10,
            sha256="a" * 64,
            was_late=True,
        )
        GradeRevision.objects.create(
            submission=cls.submission,
            submission_version=cls.version,
            revision_number=1,
            score=Decimal("75.00"),
            feedback="Released dashboard result.",
            graded_by=cls.instructor,
            released_at=timezone.now(),
        )
        GradeRevision.objects.create(
            submission=cls.submission,
            submission_version=cls.version,
            revision_number=2,
            score=Decimal("82.00"),
            feedback="Latest released dashboard result.",
            graded_by=cls.instructor,
            released_at=timezone.now() + timedelta(minutes=1),
        )
        withdrawn_submission = Submission.objects.create(
            assignment=cls.assignment,
            student=cls.withdrawn_student,
        )
        SubmissionVersion.objects.create(
            submission=withdrawn_submission,
            version_number=1,
            storage_key="dashboard/withdrawn",
            original_filename="withdrawn.pdf",
            content_type="application/pdf",
            size_bytes=10,
            sha256="b" * 64,
            was_late=False,
        )
        cls.closed_assignment = Assignment.objects.create(
            course=cls.course,
            title="Closed dashboard work",
            instructions="Closed.",
            due_at=timezone.now() - timedelta(days=2),
            max_score=Decimal("100.00"),
            max_upload_bytes=1024,
            allowed_extensions=["pdf"],
            status=Assignment.Status.CLOSED,
            published_at=timezone.now() - timedelta(days=5),
            created_by=cls.instructor,
        )
        Announcement.objects.create(
            course=cls.course,
            author=cls.instructor,
            title="Dashboard announcement",
            body="Dashboard body",
            status=Announcement.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        ActivityEvent.objects.create(
            course=cls.course,
            user=cls.student,
            event_type=ActivityEvent.EventType.COURSE_VIEWED,
            object_type="Course",
            object_id=cls.course.id,
        )

    def test_student_dashboard_uses_authoritative_course_work_and_grade_data(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard Course")
        self.assertContains(response, "Upcoming dashboard work")
        self.assertContains(response, "GRADED")
        self.assertContains(response, "Closed dashboard work")
        self.assertContains(response, "NOT_SUBMITTED")
        self.assertContains(response, "Dashboard announcement")
        self.assertContains(response, "82.00 / 100.00")
        self.assertNotContains(response, "75.00 / 100.00")
        self.assertContains(response, "Due in")

    def test_instructor_dashboard_reports_workload_and_inactivity(self):
        self.client.force_login(self.instructor)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard Course")
        self.assertContains(response, "2 active enrolments")
        self.assertContains(response, "3 missing")
        self.assertContains(response, "1 late")
        self.assertContains(response, "1 recently inactive")
        self.assertContains(response, "not a measure of physical attendance")

    def test_dashboard_query_counts_are_bounded(self):
        for user, maximum in ((self.student, 12), (self.instructor, 7)):
            self.client.force_login(user)
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse("dashboard"))
                self.assertEqual(response.status_code, 200)
            self.assertLessEqual(len(queries), maximum)
