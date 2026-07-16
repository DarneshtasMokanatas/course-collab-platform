import hashlib
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.analytics.models import ActivityEvent
from apps.audit.models import AuditEvent
from apps.courses.models import Course, Enrolment

from .models import Assignment, SubmissionVersion
from .services import submit_first_version, submit_resubmission


class ResubmissionWorkflowTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings_override.enable()
        user_model = get_user_model()
        self.instructor = user_model.objects.create_user(
            username="resubmit.teacher",
            email="resubmit.teacher@example.test",
            display_name="Resubmission Teacher",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        self.other_instructor = user_model.objects.create_user(
            username="resubmit.other.teacher",
            email="resubmit.other.teacher@example.test",
            display_name="Other Teacher",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        self.student = user_model.objects.create_user(
            username="resubmit.student",
            email="resubmit.student@example.test",
            display_name="Resubmission Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        self.other_student = user_model.objects.create_user(
            username="resubmit.other.student",
            email="resubmit.other.student@example.test",
            display_name="Other Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        self.staff = user_model.objects.create_user(
            username="resubmit.staff",
            email="resubmit.staff@example.test",
            display_name="Resubmission Staff",
            role=user_model.Role.INSTRUCTOR,
            is_staff=True,
            password="SafeTestPassword!2026",
        )
        self.course = Course.objects.create(
            code="RES101",
            slug="res101",
            title="Resubmissions",
            description="Resubmission tests",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
            enrolment_mode=Course.EnrolmentMode.OPEN,
        )
        Enrolment.objects.create(course=self.course, student=self.student)
        Enrolment.objects.create(course=self.course, student=self.other_student)

    def tearDown(self):
        self.settings_override.disable()
        self.media_root.cleanup()

    def assignment(self, **overrides):
        data = {
            "course": self.course,
            "title": f"Assignment {Assignment.objects.count() + 1}",
            "instructions": "Upload a PDF.",
            "due_at": timezone.now() + timedelta(days=1),
            "max_score": "100.00",
            "max_upload_bytes": 1024,
            "allowed_extensions": ["pdf"],
            "allow_late_submissions": False,
            "allow_resubmission": True,
            "status": Assignment.Status.PUBLISHED,
            "published_at": timezone.now(),
            "created_by": self.instructor,
        }
        data.update(overrides)
        return Assignment.objects.create(**data)

    def upload(self, name="work.pdf", content=b"submission"):
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    def test_resubmission_creates_immutable_version_metadata_and_events(self):
        assignment = self.assignment()
        first = submit_first_version(
            actor=self.student,
            assignment=assignment,
            upload=self.upload(content=b"first"),
        )
        accepted_at = timezone.now() + timedelta(minutes=1)
        with patch("apps.assignments.services.timezone.now", return_value=accepted_at):
            second = submit_resubmission(
                actor=self.student,
                assignment=assignment,
                upload=self.upload("revised.pdf", b"second"),
            )

        first.refresh_from_db()
        self.assertEqual(first.version_number, 1)
        self.assertEqual(first.original_filename, "work.pdf")
        self.assertEqual(first.sha256, hashlib.sha256(b"first").hexdigest())
        self.assertEqual(second.version_number, 2)
        self.assertEqual(second.original_filename, "revised.pdf")
        self.assertEqual(second.sha256, hashlib.sha256(b"second").hexdigest())
        self.assertEqual(second.submitted_at, accepted_at)
        self.assertFalse(second.was_late)
        self.assertEqual(
            list(second.submission.versions.values_list("version_number", flat=True)),
            [1, 2],
        )
        self.assertTrue(
            ActivityEvent.objects.filter(
                event_type=ActivityEvent.EventType.SUBMISSION_RESUBMITTED,
                object_id=second.id,
            ).exists()
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                action="SUBMISSION_RESUBMITTED", object_id=second.id
            ).exists()
        )

    def test_resubmission_requires_policy_existing_submission_and_active_enrolment(
        self,
    ):
        no_resubmission = self.assignment(allow_resubmission=False)
        submit_first_version(
            actor=self.student,
            assignment=no_resubmission,
            upload=self.upload(),
        )
        with self.assertRaisesMessage(ValidationError, "not enabled"):
            submit_resubmission(
                actor=self.student,
                assignment=no_resubmission,
                upload=self.upload(),
            )

        no_first_version = self.assignment()
        with self.assertRaisesMessage(ValidationError, "first version"):
            submit_resubmission(
                actor=self.student,
                assignment=no_first_version,
                upload=self.upload(),
            )
        with self.assertRaises(PermissionDenied):
            submit_resubmission(
                actor=self.instructor,
                assignment=no_first_version,
                upload=self.upload(),
            )

        enrolment = Enrolment.objects.get(course=self.course, student=self.student)
        enrolment.status = Enrolment.Status.WITHDRAWN
        enrolment.withdrawn_at = timezone.now()
        enrolment.save(update_fields=["status", "withdrawn_at"])
        with self.assertRaises(PermissionDenied):
            submit_resubmission(
                actor=self.student,
                assignment=no_resubmission,
                upload=self.upload(),
            )

    def test_resubmission_deadline_is_strictly_before_due_at(self):
        due_at = timezone.now() + timedelta(hours=1)
        before = due_at - timedelta(microseconds=1)
        exact = due_at
        after = due_at + timedelta(microseconds=1)

        before_assignment = self.assignment(due_at=due_at)
        submit_first_version(
            actor=self.student,
            assignment=before_assignment,
            upload=self.upload(),
        )
        with patch("apps.assignments.services.timezone.now", return_value=before):
            version = submit_resubmission(
                actor=self.student,
                assignment=before_assignment,
                upload=self.upload("before.pdf"),
            )
        self.assertEqual(version.submitted_at, before)

        for title, current_time in (("Exact", exact), ("After", after)):
            assignment = self.assignment(title=title, due_at=due_at)
            submit_first_version(
                actor=self.student,
                assignment=assignment,
                upload=self.upload(),
            )
            with patch(
                "apps.assignments.services.timezone.now", return_value=current_time
            ):
                with self.assertRaisesMessage(ValidationError, "before the deadline"):
                    submit_resubmission(
                        actor=self.student,
                        assignment=assignment,
                        upload=self.upload(f"{title.lower()}.pdf"),
                    )
            self.assertEqual(assignment.submissions.get().versions.count(), 1)

    def test_resubmission_rejects_mime_type_that_does_not_match_extension(self):
        assignment = self.assignment()
        submit_first_version(
            actor=self.student,
            assignment=assignment,
            upload=self.upload(),
        )
        mismatched = SimpleUploadedFile(
            "not-really.pdf",
            b"text",
            content_type="text/plain",
        )
        with self.assertRaisesMessage(ValidationError, "content type"):
            submit_resubmission(
                actor=self.student,
                assignment=assignment,
                upload=mismatched,
            )
        self.assertEqual(assignment.submissions.get().versions.count(), 1)

    def test_submit_view_reuses_endpoint_and_marks_latest_version_current(self):
        assignment = self.assignment()
        first = submit_first_version(
            actor=self.student,
            assignment=assignment,
            upload=self.upload(content=b"first"),
        )
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("assignments:submit", args=[self.course.id, assignment.id]),
            {"file": self.upload("second.pdf", b"second")},
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.get(
            reverse("assignments:detail", args=[self.course.id, assignment.id])
        )
        self.assertContains(response, "Version 1")
        self.assertContains(response, "Version 2 (Current)")
        self.assertContains(response, "Submit a new version")
        first.refresh_from_db()
        self.assertEqual(first.sha256, hashlib.sha256(b"first").hexdigest())

    def test_direct_resubmission_page_redirects_when_policy_or_deadline_blocks_it(self):
        disabled = self.assignment(allow_resubmission=False)
        submit_first_version(
            actor=self.student,
            assignment=disabled,
            upload=self.upload(),
        )
        self.client.force_login(self.student)
        response = self.client.get(
            reverse("assignments:submit", args=[self.course.id, disabled.id]),
            follow=True,
        )
        self.assertRedirects(
            response,
            reverse("assignments:detail", args=[self.course.id, disabled.id]),
        )
        self.assertContains(response, "Resubmission is not enabled")

        expired = self.assignment(due_at=timezone.now() + timedelta(hours=1))
        submit_first_version(
            actor=self.student,
            assignment=expired,
            upload=self.upload(),
        )
        with patch(
            "apps.assignments.views.timezone.now",
            return_value=expired.due_at,
        ):
            response = self.client.get(
                reverse("assignments:submit", args=[self.course.id, expired.id]),
                follow=True,
            )
        self.assertContains(response, "resubmission deadline has passed")

    def test_instructor_can_browse_complete_submission_history(self):
        assignment = self.assignment()
        first = submit_first_version(
            actor=self.student,
            assignment=assignment,
            upload=self.upload(content=b"first"),
        )
        second = submit_resubmission(
            actor=self.student,
            assignment=assignment,
            upload=self.upload("second.pdf", b"second"),
        )
        self.client.force_login(self.instructor)
        list_response = self.client.get(
            reverse(
                "assignments:submission_list",
                args=[self.course.id, assignment.id],
            )
        )
        self.assertContains(list_response, self.student.display_name)
        self.assertContains(list_response, "2 versions retained")
        detail_response = self.client.get(
            reverse(
                "assignments:submission_detail",
                args=[self.course.id, assignment.id, first.submission_id],
            )
        )
        self.assertContains(detail_response, "Version 1")
        self.assertContains(detail_response, "Version 2 (Current)")
        self.assertContains(detail_response, first.original_filename)
        self.assertContains(detail_response, second.original_filename)

        self.client.force_login(self.other_instructor)
        self.assertEqual(
            self.client.get(
                reverse(
                    "assignments:submission_list",
                    args=[self.course.id, assignment.id],
                )
            ).status_code,
            404,
        )
        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.get(
                reverse(
                    "assignments:submission_detail",
                    args=[self.course.id, assignment.id, first.submission_id],
                )
            ).status_code,
            200,
        )

    def test_protected_download_allows_only_student_owner_course_owner_and_staff(self):
        assignment = self.assignment()
        version = submit_first_version(
            actor=self.student,
            assignment=assignment,
            upload=self.upload(content=b"download me"),
        )
        url = reverse(
            "assignments:submission_version_download",
            args=[
                self.course.id,
                assignment.id,
                version.submission_id,
                version.id,
            ],
        )
        for user in (self.student, self.instructor, self.staff):
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), b"download me")
            self.assertIn("attachment", response["Content-Disposition"])
            self.assertEqual(response["Content-Type"], "application/octet-stream")
        for user in (self.other_student, self.other_instructor):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 404)
        enrolment = Enrolment.objects.get(course=self.course, student=self.student)
        enrolment.status = Enrolment.Status.WITHDRAWN
        enrolment.withdrawn_at = timezone.now()
        enrolment.save(update_fields=["status", "withdrawn_at"])
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_failed_resubmission_metadata_write_removes_new_file(self):
        assignment = self.assignment()
        submit_first_version(
            actor=self.student,
            assignment=assignment,
            upload=self.upload(),
        )
        with (
            patch(
                "apps.assignments.services.default_storage.save",
                return_value="tests/orphan-resubmission",
            ),
            patch("apps.assignments.services.default_storage.delete") as delete_mock,
            patch.object(
                SubmissionVersion,
                "save",
                side_effect=RuntimeError("database write failed"),
            ),
        ):
            with self.assertRaisesMessage(RuntimeError, "database write failed"):
                submit_resubmission(
                    actor=self.student,
                    assignment=assignment,
                    upload=self.upload("orphan.pdf"),
                )
        delete_mock.assert_called_once_with("tests/orphan-resubmission")


class ConcurrentResubmissionTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings_override.enable()
        user_model = get_user_model()
        self.instructor = user_model.objects.create_user(
            username="concurrent.teacher",
            email="concurrent.teacher@example.test",
            display_name="Concurrent Teacher",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        self.student = user_model.objects.create_user(
            username="concurrent.student",
            email="concurrent.student@example.test",
            display_name="Concurrent Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        self.course = Course.objects.create(
            code="CONRES",
            slug="conres",
            title="Concurrent Resubmissions",
            description="Concurrency tests",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        Enrolment.objects.create(course=self.course, student=self.student)
        self.assignment = Assignment.objects.create(
            course=self.course,
            title="Concurrent assignment",
            instructions="Upload",
            due_at=timezone.now() + timedelta(days=1),
            max_score="100.00",
            max_upload_bytes=1024,
            allowed_extensions=["pdf"],
            allow_resubmission=True,
            status=Assignment.Status.PUBLISHED,
            published_at=timezone.now(),
            created_by=self.instructor,
        )
        submit_first_version(
            actor=self.student,
            assignment=self.assignment,
            upload=SimpleUploadedFile(
                "first.pdf", b"first", content_type="application/pdf"
            ),
        )

    def tearDown(self):
        self.settings_override.disable()
        self.media_root.cleanup()

    def test_concurrent_resubmissions_allocate_distinct_version_numbers(self):
        barrier = Barrier(2)
        from . import services

        original_file_metadata = services._file_metadata

        def synchronized_metadata(assignment, upload):
            metadata = original_file_metadata(assignment, upload)
            barrier.wait(timeout=5)
            return metadata

        def submit(content):
            connections.close_all()
            try:
                return submit_resubmission(
                    actor=self.student,
                    assignment=self.assignment,
                    upload=SimpleUploadedFile(
                        f"{content.decode()}.pdf",
                        content,
                        content_type="application/pdf",
                    ),
                ).version_number
            finally:
                connections.close_all()

        with (
            patch(
                "apps.assignments.services._file_metadata",
                side_effect=synchronized_metadata,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            version_numbers = sorted(executor.map(submit, (b"second", b"third")))

        self.assertEqual(version_numbers, [2, 3])
        self.assertEqual(
            list(
                self.assignment.submissions.get()
                .versions.order_by("version_number")
                .values_list("version_number", flat=True)
            ),
            [1, 2, 3],
        )
