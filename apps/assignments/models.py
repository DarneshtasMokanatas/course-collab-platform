import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.courses.models import Course, CourseSection


def validate_allowed_extensions(value):
    if not isinstance(value, list) or not value:
        raise ValidationError("Allowed extensions must be a non-empty list.")
    if any(
        not isinstance(extension, str)
        or not extension
        or extension != extension.lower()
        or extension.startswith(".")
        for extension in value
    ):
        raise ValidationError("Use lowercase extensions without a leading dot.")


class Assignment(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        CLOSED = "CLOSED", "Closed"
        ARCHIVED = "ARCHIVED", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="assignments"
    )
    section = models.ForeignKey(
        CourseSection,
        on_delete=models.PROTECT,
        related_name="assignments",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=200)
    instructions = models.TextField()
    due_at = models.DateTimeField()
    max_score = models.DecimalField(max_digits=8, decimal_places=2)
    max_upload_bytes = models.BigIntegerField(default=10 * 1024 * 1024)
    allowed_extensions = models.JSONField(
        default=list, validators=[validate_allowed_extensions]
    )
    allow_late_submissions = models.BooleanField(default=False)
    allow_resubmission = models.BooleanField(default=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_assignments",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "assignments_assignment"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_score__gt=0), name="assignment_max_score_gt_0"
            ),
            models.CheckConstraint(
                condition=models.Q(max_upload_bytes__gt=0),
                name="assignment_max_upload_gt_0",
            ),
        ]
        indexes = [
            models.Index(
                fields=["course", "status", "due_at"],
                name="assignment_course_due_idx",
            ),
            models.Index(fields=["status", "due_at"], name="assignment_status_due_idx"),
        ]

    def clean(self):
        super().clean()
        if self.section_id and self.section.course_id != self.course_id:
            raise ValidationError({"section": "Section must belong to this course."})

    def __str__(self):
        return self.title


class Submission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assignment = models.ForeignKey(
        Assignment, on_delete=models.PROTECT, related_name="submissions"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="submissions"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assignments_submission"
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "student"],
                name="assignment_student_submission_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=["student", "created_at"], name="submission_student_idx"
            ),
            models.Index(
                fields=["assignment", "created_at"], name="submission_assignment_idx"
            ),
        ]

    def __str__(self):
        return f"{self.student} - {self.assignment}"


class SubmissionVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(
        Submission, on_delete=models.PROTECT, related_name="versions"
    )
    version_number = models.PositiveIntegerField()
    storage_key = models.CharField(max_length=500, unique=True)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    submitted_at = models.DateTimeField(auto_now_add=True)
    was_late = models.BooleanField()

    class Meta:
        db_table = "assignments_submissionversion"
        ordering = ["submission", "version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "version_number"],
                name="submission_version_number_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(version_number__gte=1),
                name="submission_version_number_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(size_bytes__gt=0), name="submission_size_bytes_gt_0"
            ),
        ]

    def __str__(self):
        return f"{self.submission} v{self.version_number}"


class GradeRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(
        Submission, on_delete=models.PROTECT, related_name="grade_revisions"
    )
    submission_version = models.ForeignKey(
        SubmissionVersion, on_delete=models.PROTECT, related_name="grade_revisions"
    )
    revision_number = models.PositiveIntegerField()
    score = models.DecimalField(max_digits=8, decimal_places=2)
    feedback = models.TextField(blank=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="grade_revisions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "assignments_graderevision"
        ordering = ["submission", "revision_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "revision_number"],
                name="grade_revision_number_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(revision_number__gte=1),
                name="grade_revision_number_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(score__gte=0), name="grade_score_gte_0"
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.submission_version_id
            and self.submission_version.submission_id != self.submission_id
        ):
            raise ValidationError(
                {"submission_version": "Version must belong to this submission."}
            )
        if self.submission_id and self.score > self.submission.assignment.max_score:
            raise ValidationError(
                {"score": "Score cannot exceed the assignment maximum."}
            )

    def __str__(self):
        return f"{self.submission} grade r{self.revision_number}"
