import hashlib
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.analytics.models import ActivityEvent
from apps.audit.models import AuditEvent
from apps.courses.models import Course, CourseSection, Enrolment

from .models import Assignment, Submission, SubmissionVersion
from .services import create_assignment, publish_assignment, submit_first_version

PDF_HEADER = b"%PDF-1.4\n"


class AssignmentWorkflowTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings_override.enable()
        user_model = get_user_model()
        self.instructor = user_model.objects.create_user(
            username="assign.teacher",
            email="assign.teacher@example.test",
            display_name="Assignment Teacher",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        self.other_instructor = user_model.objects.create_user(
            username="assign.other.teacher",
            email="assign.other.teacher@example.test",
            display_name="Other Teacher",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        self.student = user_model.objects.create_user(
            username="assign.student",
            email="assign.student@example.test",
            display_name="Assignment Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        self.other_student = user_model.objects.create_user(
            username="assign.other.student",
            email="assign.other.student@example.test",
            display_name="Other Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        self.course = Course.objects.create(
            code="ASNFLOW",
            slug="asnflow",
            title="Assignments",
            description="Assignments",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
            enrolment_mode=Course.EnrolmentMode.OPEN,
        )
        self.section = CourseSection.objects.create(
            course=self.course, title="Week 1", description="Intro", position=1
        )
        self.other_course = Course.objects.create(
            code="OTHASN",
            slug="othasn",
            title="Other Assignments",
            description="Other Assignments",
            instructor=self.other_instructor,
            status=Course.Status.PUBLISHED,
            enrolment_mode=Course.EnrolmentMode.OPEN,
        )
        self.other_section = CourseSection.objects.create(
            course=self.other_course,
            title="Other Week",
            description="Other",
            position=1,
        )
        Enrolment.objects.create(course=self.course, student=self.student)

    def tearDown(self):
        self.settings_override.disable()
        self.media_root.cleanup()

    def assignment_data(self, **overrides):
        data = {
            "section": self.section,
            "title": "Essay 1",
            "instructions": "Upload your essay.",
            "due_at": timezone.now() + timedelta(days=3),
            "max_score": "100.00",
            "max_upload_bytes": 1024,
            "allowed_extensions": ["pdf", "docx"],
            "allow_late_submissions": False,
            "allow_resubmission": True,
        }
        data.update(overrides)
        return data

    def create_published_assignment(self, **overrides):
        assignment = create_assignment(
            actor=self.instructor,
            course=self.course,
            data=self.assignment_data(**overrides),
        )
        return publish_assignment(actor=self.instructor, assignment=assignment)

    def upload(
        self, name="essay.pdf", content=b"essay bytes", content_type="application/pdf"
    ):
        if name.lower().endswith(".pdf") and not content.startswith(PDF_HEADER):
            content = PDF_HEADER + content
        return SimpleUploadedFile(name, content, content_type=content_type)

    def test_instructor_creates_draft_and_publishes_with_audit_events(self):
        assignment = create_assignment(
            actor=self.instructor, course=self.course, data=self.assignment_data()
        )
        self.assertEqual(assignment.status, Assignment.Status.DRAFT)
        self.assertIsNone(assignment.published_at)
        self.assertTrue(
            AuditEvent.objects.filter(
                action="ASSIGNMENT_CREATED", object_id=assignment.id, course=self.course
            ).exists()
        )

        published = publish_assignment(actor=self.instructor, assignment=assignment)
        self.assertEqual(published.status, Assignment.Status.PUBLISHED)
        self.assertIsNotNone(published.published_at)
        self.assertTrue(
            AuditEvent.objects.filter(
                action="ASSIGNMENT_PUBLISHED",
                object_id=assignment.id,
                course=self.course,
            ).exists()
        )

    def test_assignment_creation_rejects_wrong_role_wrong_section_and_past_deadline(
        self,
    ):
        with self.assertRaises(PermissionDenied):
            create_assignment(
                actor=self.student, course=self.course, data=self.assignment_data()
            )
        with self.assertRaisesMessage(ValidationError, "Section must belong"):
            create_assignment(
                actor=self.instructor,
                course=self.course,
                data=self.assignment_data(section=self.other_section),
            )
        with self.assertRaisesMessage(ValidationError, "future"):
            create_assignment(
                actor=self.instructor,
                course=self.course,
                data=self.assignment_data(due_at=timezone.now() - timedelta(minutes=1)),
            )

    def test_publish_requires_owner_published_course_and_future_deadline(self):
        draft_course = Course.objects.create(
            code="DRAFTASN",
            slug="draftasn",
            title="Draft Course",
            description="Draft Course",
            instructor=self.instructor,
            status=Course.Status.DRAFT,
            enrolment_mode=Course.EnrolmentMode.OPEN,
        )
        assignment = create_assignment(
            actor=self.instructor,
            course=draft_course,
            data=self.assignment_data(section=None),
        )
        with self.assertRaisesMessage(ValidationError, "Publish the course"):
            publish_assignment(actor=self.instructor, assignment=assignment)
        owned_assignment = create_assignment(
            actor=self.instructor,
            course=self.course,
            data=self.assignment_data(title="Owned"),
        )
        with self.assertRaises(PermissionDenied):
            publish_assignment(actor=self.other_instructor, assignment=owned_assignment)

    def test_student_list_and_detail_hide_drafts_and_require_active_enrolment(self):
        draft = create_assignment(
            actor=self.instructor,
            course=self.course,
            data=self.assignment_data(title="Draft"),
        )
        published = self.create_published_assignment(title="Published")
        self.client.force_login(self.student)
        list_response = self.client.get(
            reverse("assignments:list", args=[self.course.id])
        )
        self.assertContains(list_response, "Published")
        self.assertNotContains(list_response, "Draft")
        self.assertEqual(
            self.client.get(
                reverse("assignments:detail", args=[self.course.id, draft.id])
            ).status_code,
            404,
        )
        self.client.force_login(self.other_student)
        self.assertEqual(
            self.client.get(
                reverse("assignments:detail", args=[self.course.id, published.id])
            ).status_code,
            404,
        )

    def test_post_views_create_publish_and_submit_first_version(self):
        self.client.force_login(self.instructor)
        due_at = timezone.now() + timedelta(days=2)
        response = self.client.post(
            reverse("assignments:new", args=[self.course.id]),
            {
                "section": str(self.section.id),
                "title": "Posted Assignment",
                "instructions": "Upload it.",
                "due_at": due_at.strftime("%Y-%m-%dT%H:%M"),
                "max_score": "20.00",
                "max_upload_bytes": "1024",
                "allowed_extensions": '["pdf"]',
                "allow_resubmission": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        assignment = Assignment.objects.get(title="Posted Assignment")
        self.assertEqual(assignment.status, Assignment.Status.DRAFT)
        self.assertEqual(
            self.client.get(
                reverse("assignments:publish", args=[self.course.id, assignment.id])
            ).status_code,
            404,
        )
        response = self.client.post(
            reverse("assignments:publish", args=[self.course.id, assignment.id])
        )
        self.assertEqual(response.status_code, 302)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, Assignment.Status.PUBLISHED)

        self.client.force_login(self.student)
        response = self.client.post(
            reverse("assignments:submit", args=[self.course.id, assignment.id]),
            {"file": self.upload()},
        )
        self.assertEqual(response.status_code, 302)
        version = SubmissionVersion.objects.get(submission__assignment=assignment)
        self.assertEqual(version.version_number, 1)
        self.assertEqual(
            version.sha256,
            hashlib.sha256(PDF_HEADER + b"essay bytes").hexdigest(),
        )
        self.assertTrue(
            ActivityEvent.objects.filter(
                event_type=ActivityEvent.EventType.SUBMISSION_CREATED,
                object_id=version.id,
            ).exists()
        )

    def test_first_submission_records_metadata_and_rejects_duplicate_or_invalid_file(
        self,
    ):
        assignment = self.create_published_assignment(max_upload_bytes=20)
        version = submit_first_version(
            actor=self.student, assignment=assignment, upload=self.upload()
        )
        self.assertEqual(version.version_number, 1)
        self.assertEqual(version.original_filename, "essay.pdf")
        self.assertEqual(version.content_type, "application/pdf")
        self.assertEqual(version.size_bytes, len(PDF_HEADER + b"essay bytes"))
        self.assertEqual(
            version.sha256,
            hashlib.sha256(PDF_HEADER + b"essay bytes").hexdigest(),
        )
        self.assertTrue(
            version.storage_key.startswith(
                f"courses/{self.course.id}/assignments/{assignment.id}/submissions/"
            )
        )
        with self.assertRaisesMessage(ValidationError, "already exists"):
            submit_first_version(
                actor=self.student, assignment=assignment, upload=self.upload()
            )
        with self.assertRaisesMessage(ValidationError, "not allowed"):
            submit_first_version(
                actor=self.other_student,
                assignment=assignment,
                upload=self.upload("run.exe"),
            )
        self.assertEqual(Submission.objects.filter(assignment=assignment).count(), 1)

    def test_upload_rejects_spoofed_content_and_sanitizes_display_filename(self):
        assignment = self.create_published_assignment(max_upload_bytes=1024)
        with self.assertRaisesMessage(ValidationError, "content does not match"):
            submit_first_version(
                actor=self.student,
                assignment=assignment,
                upload=SimpleUploadedFile(
                    "spoofed.pdf",
                    b"not a pdf",
                    content_type="application/pdf",
                ),
            )
        version = submit_first_version(
            actor=self.student,
            assignment=assignment,
            upload=self.upload("C:\\private\\final report.pdf"),
        )
        self.assertEqual(version.original_filename, "final_report.pdf")

    def test_submit_requires_enrolment_and_published_assignment(
        self,
    ):
        draft = create_assignment(
            actor=self.instructor, course=self.course, data=self.assignment_data()
        )
        with self.assertRaises(PermissionDenied):
            submit_first_version(
                actor=self.instructor, assignment=draft, upload=self.upload()
            )
        with self.assertRaisesMessage(ValidationError, "not accepting"):
            submit_first_version(
                actor=self.student, assignment=draft, upload=self.upload()
            )
        published = self.create_published_assignment(title="Requires Enrolment")
        with self.assertRaises(PermissionDenied):
            submit_first_version(
                actor=self.other_student, assignment=published, upload=self.upload()
            )

    def test_first_submission_deadline_boundaries(self):
        due_at = timezone.now() + timedelta(days=1)
        before = due_at - timedelta(microseconds=1)
        exact = due_at
        after = due_at + timedelta(microseconds=1)

        assignment_before = self.create_published_assignment(
            title="Before", due_at=due_at
        )
        with patch("apps.assignments.services.timezone.now", return_value=before):
            before_version = submit_first_version(
                actor=self.student, assignment=assignment_before, upload=self.upload()
            )
        self.assertFalse(before_version.was_late)

        assignment_exact = self.create_published_assignment(
            title="Exact", due_at=due_at
        )
        with patch("apps.assignments.services.timezone.now", return_value=exact):
            exact_version = submit_first_version(
                actor=self.student, assignment=assignment_exact, upload=self.upload()
            )
        self.assertFalse(exact_version.was_late)

        assignment_after = self.create_published_assignment(
            title="After", due_at=due_at
        )
        with patch("apps.assignments.services.timezone.now", return_value=after):
            with self.assertRaisesMessage(ValidationError, "deadline has passed"):
                submit_first_version(
                    actor=self.student,
                    assignment=assignment_after,
                    upload=self.upload(),
                )

        late_assignment = self.create_published_assignment(
            title="Late", due_at=due_at, allow_late_submissions=True
        )
        with patch("apps.assignments.services.timezone.now", return_value=after):
            late_version = submit_first_version(
                actor=self.student, assignment=late_assignment, upload=self.upload()
            )
        self.assertTrue(late_version.was_late)
