from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.assignments.models import (
    Assignment,
    GradeRevision,
    Submission,
    SubmissionVersion,
)
from apps.courses.models import Course, Enrolment

from .models import ActivityEvent
from .services import record_activity


class ActivityAndAnalyticsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(
            username="analytics.owner",
            email="analytics.owner@example.test",
            display_name="Analytics Owner",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        cls.other_instructor = user_model.objects.create_user(
            username="analytics.other",
            email="analytics.other@example.test",
            display_name="Other Instructor",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        cls.students = [
            user_model.objects.create_user(
                username=f"analytics.student{number}",
                email=f"analytics.student{number}@example.test",
                display_name=f"Analytics Student {number}",
                role=user_model.Role.STUDENT,
                password="SafeTestPassword!2026",
            )
            for number in range(1, 31)
        ]
        cls.course = Course.objects.create(
            code="ANA101",
            slug="ana101",
            title="Analytics",
            description="Platform participation analytics",
            instructor=cls.owner,
            status=Course.Status.PUBLISHED,
        )
        Enrolment.objects.bulk_create(
            [Enrolment(course=cls.course, student=student) for student in cls.students]
        )
        cls.assignment = Assignment.objects.create(
            course=cls.course,
            title="Analytics work",
            instructions="Submit.",
            due_at=timezone.now() + timedelta(days=1),
            max_score=Decimal("100.00"),
            max_upload_bytes=1024,
            allowed_extensions=["pdf"],
            status=Assignment.Status.PUBLISHED,
            published_at=timezone.now(),
            created_by=cls.owner,
        )
        cls.late_submission = Submission.objects.create(
            assignment=cls.assignment,
            student=cls.students[0],
        )
        cls.late_version = SubmissionVersion.objects.create(
            submission=cls.late_submission,
            version_number=1,
            storage_key="analytics/late",
            original_filename="late.pdf",
            content_type="application/pdf",
            size_bytes=10,
            sha256="a" * 64,
            was_late=True,
        )
        GradeRevision.objects.create(
            submission=cls.late_submission,
            submission_version=cls.late_version,
            revision_number=1,
            score=Decimal("80.00"),
            feedback="Released.",
            graded_by=cls.owner,
            released_at=timezone.now(),
        )
        record_activity(
            course=cls.course,
            user=cls.students[0],
            event_type=ActivityEvent.EventType.COURSE_VIEWED,
            object_type="Course",
            object_id=cls.course.id,
        )

    def test_view_events_are_rate_limited_but_action_events_are_append_only(self):
        now = timezone.now()
        first = record_activity(
            course=self.course,
            user=self.students[1],
            event_type=ActivityEvent.EventType.ASSIGNMENT_VIEWED,
            object_type="Assignment",
            object_id=self.assignment.id,
        )
        duplicate = record_activity(
            course=self.course,
            user=self.students[1],
            event_type=ActivityEvent.EventType.ASSIGNMENT_VIEWED,
            object_type="Assignment",
            object_id=self.assignment.id,
        )
        ActivityEvent.objects.filter(pk=first.pk).update(
            occurred_at=now - timedelta(minutes=6)
        )
        later = record_activity(
            course=self.course,
            user=self.students[1],
            event_type=ActivityEvent.EventType.ASSIGNMENT_VIEWED,
            object_type="Assignment",
            object_id=self.assignment.id,
        )
        self.assertIsNotNone(first)
        self.assertIsNone(duplicate)
        self.assertIsNotNone(later)

        for _ in range(2):
            record_activity(
                course=self.course,
                user=self.students[1],
                event_type=ActivityEvent.EventType.MATERIAL_DOWNLOADED,
                object_type="MaterialVersion",
                object_id=self.assignment.id,
            )
        self.assertEqual(
            ActivityEvent.objects.filter(
                user=self.students[1],
                event_type=ActivityEvent.EventType.MATERIAL_DOWNLOADED,
            ).count(),
            2,
        )

    def test_analytics_is_owner_only_and_reports_required_states(self):
        url = reverse("analytics:course", args=[self.course.id])
        self.assertEqual(self.client.get(url).status_code, 302)
        for user in (self.other_instructor, self.students[0]):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.owner)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "does not measure physical attendance")
        self.assertContains(
            response,
            "<dt>Active enrolments</dt><dd>30</dd>",
            html=True,
        )
        self.assertContains(response, "Analytics Student 1")
        self.assertContains(response, "Total 80.00")
        self.assertContains(response, "Inactive")
        self.assertEqual(len(response.context["rows"]), 25)

    def test_analytics_query_count_is_bounded_for_paginated_roster(self):
        self.client.force_login(self.owner)
        url = reverse("analytics:course", args=[self.course.id])
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            list(response.context["rows"])
        self.assertLessEqual(len(queries), 10)
