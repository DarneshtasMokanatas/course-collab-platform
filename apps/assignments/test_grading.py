import tempfile
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.courses.models import Course, Enrolment

from .models import Assignment, GradeRevision
from .services import (
    create_grade_revision,
    release_latest_grade,
    submit_first_version,
    submit_resubmission,
    withdraw_latest_grade_release,
)

PDF_HEADER = b"%PDF-1.4\n"


class GradingWorkflowTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings_override.enable()
        user_model = get_user_model()
        self.instructor = user_model.objects.create_user(
            username="grade.teacher",
            email="grade.teacher@example.test",
            display_name="Grade Teacher",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        self.other_instructor = user_model.objects.create_user(
            username="grade.other.teacher",
            email="grade.other.teacher@example.test",
            display_name="Other Grade Teacher",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        self.student = user_model.objects.create_user(
            username="grade.student",
            email="grade.student@example.test",
            display_name="Grade Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        self.other_student = user_model.objects.create_user(
            username="grade.other.student",
            email="grade.other.student@example.test",
            display_name="Other Grade Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        self.staff = user_model.objects.create_user(
            username="grade.staff",
            email="grade.staff@example.test",
            display_name="Grade Staff",
            role=user_model.Role.INSTRUCTOR,
            is_staff=True,
            password="SafeTestPassword!2026",
        )
        self.course = Course.objects.create(
            code="GRD101",
            slug="grd101",
            title="Grading",
            description="Grading tests",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        Enrolment.objects.create(course=self.course, student=self.student)
        Enrolment.objects.create(course=self.course, student=self.other_student)
        self.assignment = Assignment.objects.create(
            course=self.course,
            title="Graded work",
            instructions="Upload a PDF.",
            due_at=timezone.now() + timedelta(days=1),
            max_score=Decimal("100.00"),
            max_upload_bytes=1024,
            allowed_extensions=["pdf"],
            allow_late_submissions=True,
            allow_resubmission=True,
            status=Assignment.Status.PUBLISHED,
            published_at=timezone.now(),
            created_by=self.instructor,
        )
        self.version = submit_first_version(
            actor=self.student,
            assignment=self.assignment,
            upload=self.upload("first.pdf", b"first"),
        )

    def tearDown(self):
        self.settings_override.disable()
        self.media_root.cleanup()

    def upload(self, name="work.pdf", content=b"work"):
        if name.lower().endswith(".pdf") and not content.startswith(PDF_HEADER):
            content = PDF_HEADER + content
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    def test_grade_revisions_are_append_only_version_specific_and_audited(self):
        second_version = submit_resubmission(
            actor=self.student,
            assignment=self.assignment,
            upload=self.upload("second.pdf", b"second"),
        )
        first_revision = create_grade_revision(
            actor=self.instructor,
            submission=self.version.submission,
            submission_version=self.version,
            score=Decimal("72.00"),
            feedback="First assessment.",
        )
        second_revision = create_grade_revision(
            actor=self.instructor,
            submission=self.version.submission,
            submission_version=second_version,
            score=Decimal("81.50"),
            feedback="Improved revision.",
        )
        first_revision.refresh_from_db()
        self.assertEqual(first_revision.revision_number, 1)
        self.assertEqual(first_revision.score, Decimal("72.00"))
        self.assertIsNone(first_revision.released_at)
        self.assertEqual(second_revision.revision_number, 2)
        self.assertEqual(second_revision.submission_version, second_version)
        self.assertEqual(
            AuditEvent.objects.filter(
                action="GRADE_REVISION_CREATED",
                object_type="GradeRevision",
                course=self.course,
            ).count(),
            2,
        )
        audit_metadata = AuditEvent.objects.get(
            action="GRADE_REVISION_CREATED",
            object_id=first_revision.id,
        ).metadata
        self.assertEqual(
            set(audit_metadata),
            {
                "assignment_id",
                "submission_id",
                "submission_version_id",
                "revision_number",
            },
        )

    def test_grade_validation_enforces_owner_version_and_assignment_maximum(self):
        with self.assertRaises(PermissionDenied):
            create_grade_revision(
                actor=self.other_instructor,
                submission=self.version.submission,
                submission_version=self.version,
                score=Decimal("50.00"),
                feedback="No",
            )
        with self.assertRaises(PermissionDenied):
            create_grade_revision(
                actor=self.student,
                submission=self.version.submission,
                submission_version=self.version,
                score=Decimal("50.00"),
                feedback="No",
            )
        with self.assertRaisesMessage(ValidationError, "maximum"):
            create_grade_revision(
                actor=self.instructor,
                submission=self.version.submission,
                submission_version=self.version,
                score=Decimal("100.01"),
                feedback="Too high",
            )

        other_version = submit_first_version(
            actor=self.other_student,
            assignment=self.assignment,
            upload=self.upload("other.pdf", b"other"),
        )
        with self.assertRaisesMessage(ValidationError, "belong"):
            create_grade_revision(
                actor=self.instructor,
                submission=self.version.submission,
                submission_version=other_version,
                score=Decimal("50.00"),
                feedback="Wrong version",
            )

    def test_grade_stays_private_until_release_and_student_sees_latest_released(self):
        first_revision = create_grade_revision(
            actor=self.instructor,
            submission=self.version.submission,
            submission_version=self.version,
            score=Decimal("70.00"),
            feedback="First released feedback.",
        )
        self.client.force_login(self.student)
        detail_url = reverse(
            "assignments:detail", args=[self.course.id, self.assignment.id]
        )
        response = self.client.get(detail_url)
        self.assertContains(response, "No grade has been released")
        self.assertNotContains(response, "First released feedback")

        released_at = timezone.now() + timedelta(minutes=1)
        with patch(
            "apps.assignments.services.timezone.now",
            return_value=released_at,
        ):
            release_latest_grade(
                actor=self.instructor,
                submission=self.version.submission,
            )
        response = self.client.get(detail_url)
        self.assertContains(response, "70.00 / 100.00")
        self.assertContains(response, "First released feedback")

        second_revision = create_grade_revision(
            actor=self.instructor,
            submission=self.version.submission,
            submission_version=self.version,
            score=Decimal("84.00"),
            feedback="New private feedback.",
        )
        response = self.client.get(detail_url)
        self.assertContains(response, "First released feedback")
        self.assertNotContains(response, "New private feedback")

        release_latest_grade(
            actor=self.instructor,
            submission=self.version.submission,
        )
        response = self.client.get(detail_url)
        self.assertContains(response, "84.00 / 100.00")
        self.assertContains(response, "New private feedback")
        self.assertNotContains(response, "First released feedback")

        withdrawn = withdraw_latest_grade_release(
            actor=self.instructor,
            submission=self.version.submission,
        )
        self.assertEqual(withdrawn.id, second_revision.id)
        response = self.client.get(detail_url)
        self.assertContains(response, "70.00 / 100.00")
        self.assertContains(response, "First released feedback")
        first_revision.refresh_from_db()
        self.assertEqual(first_revision.released_at, released_at)
        self.assertEqual(
            AuditEvent.objects.filter(
                object_type="GradeRevision",
                action="GRADE_RELEASED",
            ).count(),
            2,
        )
        self.assertEqual(
            AuditEvent.objects.filter(
                object_type="GradeRevision",
                action="GRADE_RELEASE_WITHDRAWN",
            ).count(),
            1,
        )

    def test_grade_views_are_owner_scoped_post_only_and_validate_score(self):
        grade_url = reverse(
            "assignments:grade",
            args=[
                self.course.id,
                self.assignment.id,
                self.version.submission_id,
            ],
        )
        release_url = reverse(
            "assignments:release_grade",
            args=[
                self.course.id,
                self.assignment.id,
                self.version.submission_id,
            ],
        )
        withdraw_url = reverse(
            "assignments:withdraw_grade",
            args=[
                self.course.id,
                self.assignment.id,
                self.version.submission_id,
            ],
        )
        for user in (self.student, self.other_instructor):
            self.client.force_login(user)
            self.assertEqual(self.client.get(grade_url).status_code, 404)
        self.client.force_login(self.instructor)
        self.assertEqual(self.client.get(release_url).status_code, 404)
        self.assertEqual(self.client.get(withdraw_url).status_code, 404)
        response = self.client.post(
            grade_url,
            {
                "submission_version": str(self.version.id),
                "score": "101.00",
                "feedback": "Too high",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot exceed")
        self.assertEqual(GradeRevision.objects.count(), 0)

        response = self.client.post(
            grade_url,
            {
                "submission_version": str(self.version.id),
                "score": "88.00",
                "feedback": "Ready after review.",
            },
        )
        self.assertEqual(response.status_code, 302)
        revision = GradeRevision.objects.get()
        self.assertIsNone(revision.released_at)
        self.assertEqual(self.client.post(release_url).status_code, 302)
        revision.refresh_from_db()
        self.assertIsNotNone(revision.released_at)
        self.assertEqual(self.client.post(withdraw_url).status_code, 302)
        revision.refresh_from_db()
        self.assertIsNone(revision.released_at)

        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(grade_url).status_code, 200)

    def test_submission_list_separates_missing_submitted_late_and_graded(self):
        user_model = get_user_model()
        late_student = user_model.objects.create_user(
            username="grade.late",
            email="grade.late@example.test",
            display_name="Late Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        missing_student = user_model.objects.create_user(
            username="grade.missing",
            email="grade.missing@example.test",
            display_name="Missing Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        Enrolment.objects.create(course=self.course, student=late_student)
        Enrolment.objects.create(course=self.course, student=missing_student)
        with patch(
            "apps.assignments.services.timezone.now",
            return_value=self.assignment.due_at + timedelta(seconds=1),
        ):
            submit_first_version(
                actor=late_student,
                assignment=self.assignment,
                upload=self.upload("late.pdf", b"late"),
            )
        create_grade_revision(
            actor=self.instructor,
            submission=self.version.submission,
            submission_version=self.version,
            score=Decimal("90.00"),
            feedback="Released.",
        )
        release_latest_grade(
            actor=self.instructor,
            submission=self.version.submission,
        )
        submit_first_version(
            actor=self.other_student,
            assignment=self.assignment,
            upload=self.upload("submitted.pdf", b"submitted"),
        )

        self.client.force_login(self.instructor)
        response = self.client.get(
            reverse(
                "assignments:submission_list",
                args=[self.course.id, self.assignment.id],
            )
        )
        for status in ("GRADED", "SUBMITTED", "LATE", "MISSING"):
            self.assertContains(response, status)
        for display_name in (
            self.student.display_name,
            self.other_student.display_name,
            late_student.display_name,
            missing_student.display_name,
        ):
            self.assertContains(response, display_name)

    def test_database_rejects_negative_grade_score(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            GradeRevision.objects.create(
                submission=self.version.submission,
                submission_version=self.version,
                revision_number=1,
                score=Decimal("-0.01"),
                graded_by=self.instructor,
            )

    def test_submission_roster_is_paginated_with_bounded_query_count(self):
        user_model = get_user_model()
        extra_students = [
            user_model.objects.create_user(
                username=f"grade.page.{number}",
                email=f"grade.page.{number}@example.test",
                display_name=f"Paged Student {number:02d}",
                role=user_model.Role.STUDENT,
            )
            for number in range(30)
        ]
        Enrolment.objects.bulk_create(
            [
                Enrolment(course=self.course, student=student)
                for student in extra_students
            ]
        )
        self.client.force_login(self.instructor)
        url = reverse(
            "assignments:submission_list",
            args=[self.course.id, self.assignment.id],
        )
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page"].paginator.count, 32)
        self.assertEqual(len(response.context["rows"]), 25)
        self.assertTrue(response.context["page"].has_next())
        self.assertLessEqual(len(queries), 12)

        second_page = self.client.get(f"{url}?page=2")
        self.assertEqual(len(second_page.context["rows"]), 7)
