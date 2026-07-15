import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Course(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        ARCHIVED = "ARCHIVED", "Archived"

    class EnrolmentMode(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True)
    slug = models.SlugField(max_length=255, unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField()
    syllabus = models.TextField(blank=True)
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_courses"
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT
    )
    enrolment_mode = models.CharField(
        max_length=6, choices=EnrolmentMode.choices, default=EnrolmentMode.CLOSED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "courses_course"
        indexes = [
            models.Index(
                fields=["status", "enrolment_mode"], name="course_status_mode_idx"
            ),
            models.Index(
                fields=["instructor", "status"], name="course_owner_status_idx"
            ),
        ]

    def clean(self):
        super().clean()
        self.code = self.code.strip().upper()
        if (
            self.instructor_id
            and self.instructor.role != self.instructor.Role.INSTRUCTOR
        ):
            raise ValidationError({"instructor": "Course owner must be an instructor."})

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.title}"


class CourseSection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="sections"
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "courses_coursesection"
        ordering = ["course", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "position"], name="course_section_position_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(position__gte=1),
                name="course_section_position_gte_1",
            ),
        ]

    def __str__(self):
        return f"{self.course.code} {self.position}: {self.title}"


class Enrolment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="enrolments"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="enrolments"
    )
    status = models.CharField(
        max_length=9, choices=Status.choices, default=Status.ACTIVE
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "courses_enrolment"
        constraints = [
            models.UniqueConstraint(
                fields=["course", "student"], name="course_student_enrolment_uniq"
            )
        ]
        indexes = [
            models.Index(fields=["student", "status"], name="enrol_student_status_idx"),
            models.Index(fields=["course", "status"], name="enrol_course_status_idx"),
        ]

    def clean(self):
        super().clean()
        if self.student_id and self.student.role != self.student.Role.STUDENT:
            raise ValidationError({"student": "Only students may enrol."})

    def __str__(self):
        return f"{self.student} in {self.course.code}"
