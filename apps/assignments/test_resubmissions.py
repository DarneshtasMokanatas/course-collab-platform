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
from .policies import resubmission_policy
from .services import submit_first_version, submit_resubmission

PDF_HEADER = b"%PDF-1.4\n"


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
        if name.lower().endswith(".pdf") and not content.startswith(PDF_HEADER):
            content = PDF_HEADER + content
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
        self.assertEqual(
            first.sha256,
            hashlib.sha256(PDF_HEADER + b"first").hexdigest(),
        )
        self.assertEqual(second.version_number, 2)
        self.assertEqual(second.original_filename, "revised.pdf")
        self.assertEqual(
            second.sha256,
            hashlib.sha256(PDF_HEADER + b"second").hexdigest(),
        )
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

    def test_non_member_initial_submission_is_free_then_two_resubmissions_allowed(self):
        assignment = self.assignment()
        first = submit_first_version(
            actor=self.student,
            assignment=assignment,
            upload=self.upload("first.pdf", b"first"),
        )
        initial_policy = resubmission_policy(
            user=self.student,
            assignment=assignment,
            submission=first.submission,
            now=timezone.now(),
        )
        self.assertEqual(initial_policy.resubmissions_used, 0)
        self.assertEqual(initial_policy.resubmissions_remaining, 2)

        second = submit_resubmission(
            actor=self.student,
            assignment=assignment,
            upload=self.upload("second.pdf", b"second"),
        )
        third = submit_resubmission(
            actor=self.student,
            assignment=assignment,
            upload=self.upload("third.pdf", b"third"),
        )

        self.assertEqual((second.version_number, third.version_number), (2, 3))
        with patch("apps.assignments.services.default_storage.save") as save_mock:
            with self.assertRaisesMessage(ValidationError, "non-member limit"):
                submit_resubmission(
                    actor=self.student,
                    assignment=assignment,
                    upload=self.upload("fourth.pdf", b"fourth"),
                )
        save_mock.assert_not_called()
        self.assertEqual(
            list(
                first.submission.versions.order_by("version_number").values_list(
                    "version_number",
                    flat=True,
                )
            ),
            [1, 2, 3],
        )

    def test_member_can_exceed_three_versions_before_deadline(self):
        self.student.membership_status = self.student.MembershipStatus.MEMBER
        self.student.save(update_fields=["membership_status"])
        assignment = self.assignment()
        first = submit_first_version(
            actor=self.student,
            assignment=assignment,
            upload=self.upload("first.pdf", b"first"),
        )

        versions = [
            submit_resubmission(
                actor=self.student,
                assignment=assignment,
                upload=self.upload(f"version-{number}.pdf", str(number).encode()),
            )
            for number in range(2, 6)
        ]

        self.assertEqual(
            [version.version_number for version in versions],
            [2, 3, 4, 5],
        )
        self.assertEqual(first.submission.versions.count(), 5)

    def test_member_is_still_rejected_at_and_after_deadline(self):
        self.student.membership_status = self.student.MembershipStatus.MEMBER
        self.student.save(update_fields=["membership_status"])
        due_at = timezone.now() + timedelta(hours=1)
        for label, attempted_at in (
            ("exact", due_at),
            ("after", due_at + timedelta(microseconds=1)),
        ):
            assignment = self.assignment(title=label, due_at=due_at)
            submit_first_version(
                actor=self.student,
                assignment=assignment,
                upload=self.upload(f"{label}-first.pdf"),
            )
            with patch(
                "apps.assignments.services.timezone.now",
                return_value=attempted_at,
            ):
                with self.assertRaisesMessage(ValidationError, "before the deadline"):
                    submit_resubmission(
                        actor=self.student,
                        assignment=assignment,
                        upload=self.upload(f"{label}-second.pdf"),
                    )
            self.assertEqual(assignment.submissions.get().versions.count(), 1)

    def test_membership_does_not_bypass_assignment_or_enrolment_rules(self):
        self.student.membership_status = self.student.MembershipStatus.MEMBER
        self.student.save(update_fields=["membership_status"])
        assignment = self.assignment(allow_resubmission=False)
        submit_first_version(
            actor=self.student,
            assignment=assignment,
            upload=self.upload(),
        )
        with self.assertRaisesMessage(ValidationError, "not enabled"):
            submit_resubmission(
                actor=self.student,
                assignment=assignment,
                upload=self.upload("member-disabled.pdf"),
            )

        self.other_student.membership_status = (
            self.other_student.MembershipStatus.MEMBER
        )
        self.other_student.save(update_fields=["membership_status"])
        with self.assertRaisesMessage(ValidationError, "first version"):
            submit_resubmission(
                actor=self.other_student,
                assignment=assignment,
                upload=self.upload("other-students-work.pdf"),
            )
        self.assertEqual(assignment.submissions.get().versions.count(), 1)

        enrolment = Enrolment.objects.get(course=self.course, student=self.student)
        enrolment.status = Enrolment.Status.WITHDRAWN
        enrolment.save(update_fields=["status"])
        with self.assertRaises(PermissionDenied):
            submit_resubmission(
                actor=self.student,
                assignment=assignment,
                upload=self.upload("member-withdrawn.pdf"),
            )

    def test_existing_long_history_stays_immutable_when_member_becomes_non_member(self):
        self.student.membership_status = self.student.MembershipStatus.MEMBER
        self.student.save(update_fields=["membership_status"])
        assignment = self.assignment()
        first = submit_first_version(
            actor=self.student,
            assignment=assignment,
            upload=self.upload("first.pdf", b"first"),
        )
        for number in range(2, 5):
            submit_resubmission(
                actor=self.student,
                assignment=assignment,
                upload=self.upload(f"version-{number}.pdf", str(number).encode()),
            )
        original_ids = list(
            first.submission.versions.order_by("version_number").values_list(
                "id",
                flat=True,
            )
        )
        self.student.membership_status = self.student.MembershipStatus.NON_MEMBER
        self.student.save(update_fields=["membership_status"])

        with self.assertRaisesMessage(ValidationError, "non-member limit"):
            submit_resubmission(
                actor=self.student,
                assignment=assignment,
                upload=self.upload("blocked.pdf"),
            )

        self.assertEqual(
            list(
                first.submission.versions.order_by("version_number").values_list(
                    "id",
                    flat=True,
                )
            ),
            original_ids,
        )

    def test_service_uses_fresh_database_membership_instead_of_stale_actor(self):
        self.student.membership_status = self.student.MembershipStatus.MEMBER
        self.student.save(update_fields=["membership_status"])
        assignment = self.assignment()
        submit_first_version(
            actor=self.student,
            assignment=assignment,
            upload=self.upload("first.pdf"),
        )
        for number in range(2, 4):
            submit_resubmission(
                actor=self.student,
                assignment=assignment,
                upload=self.upload(f"version-{number}.pdf"),
            )

        type(self.student).objects.filter(pk=self.student.pk).update(
            membership_status=self.student.MembershipStatus.NON_MEMBER
        )
        self.assertEqual(
            self.student.membership_status,
            self.student.MembershipStatus.MEMBER,
        )
        with patch("apps.assignments.services.default_storage.save") as save_mock:
            with self.assertRaisesMessage(ValidationError, "non-member limit"):
                submit_resubmission(
                    actor=self.student,
                    assignment=assignment,
                    upload=self.upload("stale-member.pdf"),
                )
        save_mock.assert_not_called()
        self.assertEqual(assignment.submissions.get().versions.count(), 3)

        type(self.student).objects.filter(pk=self.student.pk).update(
            membership_status=self.student.MembershipStatus.MEMBER
        )
        self.student.membership_status = self.student.MembershipStatus.NON_MEMBER
        fourth = submit_resubmission(
            actor=self.student,
            assignment=assignment,
            upload=self.upload("stale-non-member.pdf"),
        )
        self.assertEqual(fourth.version_number, 4)

    def test_post_error_rerender_refreshes_membership_policy(self):
        self.student.membership_status = self.student.MembershipStatus.MEMBER
        self.student.save(update_fields=["membership_status"])
        assignment = self.assignment()
        submit_first_version(
            actor=self.student,
            assignment=assignment,
            upload=self.upload("first.pdf"),
        )
        for number in range(2, 4):
            submit_resubmission(
                actor=self.student,
                assignment=assignment,
                upload=self.upload(f"version-{number}.pdf"),
            )
        self.client.force_login(self.student)
        real_submit_resubmission = submit_resubmission

        def downgrade_then_submit(**kwargs):
            type(self.student).objects.filter(pk=self.student.pk).update(
                membership_status=self.student.MembershipStatus.NON_MEMBER
            )
            return real_submit_resubmission(**kwargs)

        with patch(
            "apps.assignments.views.submit_resubmission",
            side_effect=downgrade_then_submit,
        ):
            response = self.client.post(
                reverse(
                    "assignments:submit",
                    args=[self.course.id, assignment.id],
                ),
                {"file": self.upload("blocked-after-downgrade.pdf")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "non-member limit of 2 resubmissions")
        self.assertContains(response, "2 resubmissions allowed.")
        self.assertNotContains(
            response,
            "Unlimited resubmissions before the deadline.",
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
        with self.assertRaisesMessage(ValidationError, "content"):
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
        self.assertEqual(
            first.sha256,
            hashlib.sha256(PDF_HEADER + b"first").hexdigest(),
        )

    def test_submission_ui_displays_membership_counters_and_limit_message(self):
        assignment = self.assignment()
        submit_first_version(
            actor=self.student,
            assignment=assignment,
            upload=self.upload("first.pdf"),
        )
        submit_resubmission(
            actor=self.student,
            assignment=assignment,
            upload=self.upload("second.pdf"),
        )
        self.client.force_login(self.student)
        detail_url = reverse(
            "assignments:detail",
            args=[self.course.id, assignment.id],
        )

        response = self.client.get(detail_url)
        self.assertContains(response, "2 resubmissions allowed.")
        self.assertContains(response, "1 of 2")
        self.assertContains(response, "Resubmissions remaining")
        self.assertContains(response, "Version 2")

        submit_resubmission(
            actor=self.student,
            assignment=assignment,
            upload=self.upload("third.pdf"),
        )
        response = self.client.get(detail_url)
        self.assertContains(response, "2 of 2")
        self.assertContains(response, "limit has been reached")
        self.assertNotContains(response, ">Submit a new version</a>")

        blocked = self.client.get(
            reverse("assignments:submit", args=[self.course.id, assignment.id]),
            follow=True,
        )
        self.assertContains(blocked, "non-member limit of 2 resubmissions")

    def test_member_ui_says_unlimited_only_before_deadline(self):
        self.student.membership_status = self.student.MembershipStatus.MEMBER
        self.student.save(update_fields=["membership_status"])
        assignment = self.assignment()
        submit_first_version(
            actor=self.student,
            assignment=assignment,
            upload=self.upload(),
        )
        self.client.force_login(self.student)

        for url in (
            reverse(
                "assignments:detail",
                args=[self.course.id, assignment.id],
            ),
            reverse(
                "assignments:submit",
                args=[self.course.id, assignment.id],
            ),
        ):
            response = self.client.get(url)
            self.assertContains(
                response,
                "Unlimited resubmissions before the deadline.",
            )
            self.assertNotContains(response, "Resubmissions remaining")

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
            self.assertEqual(
                b"".join(response.streaming_content),
                PDF_HEADER + b"download me",
            )
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
                "first.pdf",
                PDF_HEADER + b"first",
                content_type="application/pdf",
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
                        PDF_HEADER + content,
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

    def test_concurrent_requests_cannot_bypass_non_member_limit(self):
        submit_resubmission(
            actor=self.student,
            assignment=self.assignment,
            upload=SimpleUploadedFile(
                "second.pdf",
                PDF_HEADER + b"second",
                content_type="application/pdf",
            ),
        )
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
                version = submit_resubmission(
                    actor=self.student,
                    assignment=self.assignment,
                    upload=SimpleUploadedFile(
                        f"{content.decode()}.pdf",
                        PDF_HEADER + content,
                        content_type="application/pdf",
                    ),
                )
                return "accepted", version.version_number
            except ValidationError as error:
                return "rejected", str(error)
            finally:
                connections.close_all()

        with (
            patch(
                "apps.assignments.services._file_metadata",
                side_effect=synchronized_metadata,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            results = list(executor.map(submit, (b"third-a", b"third-b")))

        self.assertEqual(
            sorted(result[0] for result in results),
            ["accepted", "rejected"],
        )
        self.assertIn(
            3,
            [result[1] for result in results if result[0] == "accepted"],
        )
        self.assertIn(
            "non-member limit",
            " ".join(str(result[1]) for result in results if result[0] == "rejected"),
        )
        self.assertEqual(
            list(
                self.assignment.submissions.get()
                .versions.order_by("version_number")
                .values_list("version_number", flat=True)
            ),
            [1, 2, 3],
        )
