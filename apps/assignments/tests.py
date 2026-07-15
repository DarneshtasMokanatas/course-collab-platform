from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.courses.models import Course

from .models import Assignment, GradeRevision, Submission, SubmissionVersion


class AssignmentConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.instructor = user_model.objects.create_user(
            username="assignment.instructor",
            email="assignment.instructor@tests.example",
            display_name="Assignment Instructor",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        cls.student = user_model.objects.create_user(
            username="assignment.student",
            email="assignment.student@tests.example",
            display_name="Assignment Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        cls.course = Course.objects.create(
            code="ASG101",
            slug="asg101",
            title="Assignments",
            description="Assignment tests",
            instructor=cls.instructor,
        )
        cls.assignment = Assignment.objects.create(
            course=cls.course,
            title="Report",
            instructions="Submit",
            due_at=timezone.now() + timedelta(days=1),
            max_score=Decimal("100.00"),
            max_upload_bytes=1024,
            allowed_extensions=["pdf"],
            created_by=cls.instructor,
        )

    def test_submission_version_and_grade_revision_are_unique(self):
        submission = Submission.objects.create(
            assignment=self.assignment, student=self.student
        )
        version = SubmissionVersion.objects.create(
            submission=submission,
            version_number=1,
            storage_key="tests/submission/v1",
            original_filename="report.pdf",
            content_type="application/pdf",
            size_bytes=100,
            sha256="a" * 64,
            was_late=False,
        )
        GradeRevision.objects.create(
            submission=submission,
            submission_version=version,
            revision_number=1,
            score=Decimal("80.00"),
            graded_by=self.instructor,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            SubmissionVersion.objects.create(
                submission=submission,
                version_number=1,
                storage_key="tests/submission/duplicate",
                original_filename="duplicate.pdf",
                content_type="application/pdf",
                size_bytes=100,
                sha256="b" * 64,
                was_late=False,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            GradeRevision.objects.create(
                submission=submission,
                submission_version=version,
                revision_number=1,
                score=Decimal("90.00"),
                graded_by=self.instructor,
            )

    def test_positive_database_checks(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Assignment.objects.create(
                course=self.course,
                title="Invalid",
                instructions="Invalid",
                due_at=timezone.now(),
                max_score=Decimal("0.00"),
                max_upload_bytes=0,
                allowed_extensions=["pdf"],
                created_by=self.instructor,
            )
