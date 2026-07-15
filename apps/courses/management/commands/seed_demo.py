from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.announcements.models import Announcement
from apps.assignments.models import (
    Assignment,
    GradeRevision,
    Submission,
    SubmissionVersion,
)
from apps.courses.models import Course, CourseSection, Enrolment
from apps.materials.models import Material, MaterialVersion

DEMO_PASSWORD = "CourseDemo!2026"


class Command(BaseCommand):
    help = "Create or refresh deterministic, non-production demonstration data."

    @transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()
        user_model = get_user_model()
        instructor = self.upsert_user(
            user_model,
            "demo.instructor",
            "instructor@example.test",
            "Demo Instructor",
            user_model.Role.INSTRUCTOR,
        )
        student_one = self.upsert_user(
            user_model,
            "demo.student1",
            "student1@example.test",
            "Demo Student One",
            user_model.Role.STUDENT,
        )
        student_two = self.upsert_user(
            user_model,
            "demo.student2",
            "student2@example.test",
            "Demo Student Two",
            user_model.Role.STUDENT,
        )

        course, _ = Course.objects.update_or_create(
            code="DEMO101",
            defaults={
                "slug": "demo-course",
                "title": "Introduction to Collaborative Learning",
                "description": "Safe demonstration course for local development.",
                "syllabus": "Foundations, collaboration, and reflective practice.",
                "instructor": instructor,
                "status": Course.Status.PUBLISHED,
                "enrolment_mode": Course.EnrolmentMode.OPEN,
            },
        )
        section_one = self.upsert_section(course, 1, "Foundations")
        self.upsert_section(course, 2, "Collaboration")

        for student in (student_one, student_two):
            Enrolment.objects.update_or_create(
                course=course,
                student=student,
                defaults={"status": Enrolment.Status.ACTIVE, "withdrawn_at": None},
            )

        material, _ = Material.objects.update_or_create(
            course=course,
            title="Week 1 Slides",
            defaults={
                "section": section_one,
                "description": "Two retained demo versions.",
                "status": Material.Status.PUBLISHED,
                "created_by": instructor,
                "published_at": now - timedelta(days=12),
            },
        )
        for version_number in (1, 2):
            MaterialVersion.objects.update_or_create(
                material=material,
                version_number=version_number,
                defaults={
                    "storage_key": f"demo/materials/{material.id}/v{version_number}",
                    "original_filename": f"week-1-v{version_number}.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 1024 * version_number,
                    "sha256": str(version_number) * 64,
                    "uploaded_by": instructor,
                },
            )

        announcements = (
            ("Welcome", "Welcome to the course.", True, now - timedelta(days=10)),
            (
                "Week 1 update",
                "The Week 1 material has been revised.",
                False,
                now - timedelta(days=8),
            ),
        )
        for title, body, is_pinned, published_at in announcements:
            Announcement.objects.update_or_create(
                course=course,
                title=title,
                defaults={
                    "author": instructor,
                    "body": body,
                    "is_pinned": is_pinned,
                    "status": Announcement.Status.PUBLISHED,
                    "published_at": published_at,
                },
            )

        upcoming = self.upsert_assignment(
            course,
            section_one,
            instructor,
            "Upcoming reflection",
            now + timedelta(days=7),
        )
        past = self.upsert_assignment(
            course,
            section_one,
            instructor,
            "Past collaboration report",
            now - timedelta(days=7),
            allow_late=True,
        )

        on_time = self.upsert_submission(
            past, student_one, past.due_at - timedelta(hours=2), False
        )
        self.upsert_submission(
            past, student_two, past.due_at + timedelta(hours=3), True
        )
        version = on_time.versions.get(version_number=1)
        GradeRevision.objects.update_or_create(
            submission=on_time,
            revision_number=1,
            defaults={
                "submission_version": version,
                "score": Decimal("84.00"),
                "feedback": "Clear evidence of collaboration.",
                "graded_by": instructor,
                "released_at": now - timedelta(days=2),
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Demo data ready: 1 instructor, 2 students, 1 course, "
                "2 material versions, 2 announcements, 2 assignments, and "
                "on-time/late/missing/graded scenarios."
            )
        )
        self.stdout.write(f"Demo password: {DEMO_PASSWORD}")
        self.stdout.write(f"Upcoming assignment: {upcoming.title}")

    def upsert_user(self, user_model, username, email, display_name, role):
        user, _ = user_model.objects.update_or_create(
            username=username,
            defaults={"email": email, "display_name": display_name, "role": role},
        )
        user.set_password(DEMO_PASSWORD)
        user.save(update_fields=["password", "email", "display_name", "role"])
        return user

    def upsert_section(self, course, position, title):
        section, _ = CourseSection.objects.update_or_create(
            course=course,
            position=position,
            defaults={"title": title, "description": f"Demo section {position}."},
        )
        return section

    def upsert_assignment(
        self, course, section, instructor, title, due_at, allow_late=False
    ):
        assignment, _ = Assignment.objects.update_or_create(
            course=course,
            title=title,
            defaults={
                "section": section,
                "instructions": "Submit a PDF reflection.",
                "due_at": due_at,
                "max_score": Decimal("100.00"),
                "max_upload_bytes": 10 * 1024 * 1024,
                "allowed_extensions": ["pdf"],
                "allow_late_submissions": allow_late,
                "allow_resubmission": True,
                "status": Assignment.Status.PUBLISHED,
                "published_at": timezone.now() - timedelta(days=14),
                "created_by": instructor,
            },
        )
        return assignment

    def upsert_submission(self, assignment, student, submitted_at, was_late):
        submission, _ = Submission.objects.get_or_create(
            assignment=assignment, student=student
        )
        version, _ = SubmissionVersion.objects.update_or_create(
            submission=submission,
            version_number=1,
            defaults={
                "storage_key": f"demo/submissions/{submission.id}/v1",
                "original_filename": "collaboration-report.pdf",
                "content_type": "application/pdf",
                "size_bytes": 2048,
                "sha256": ("a" if was_late else "b") * 64,
                "was_late": was_late,
            },
        )
        SubmissionVersion.objects.filter(pk=version.pk).update(
            submitted_at=submitted_at
        )
        version.refresh_from_db()
        return submission
