import uuid

from django.conf import settings
from django.db import models

from apps.courses.models import Course


class Announcement(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        ARCHIVED = "ARCHIVED", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="announcements"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="announcements"
    )
    title = models.CharField(max_length=200)
    body = models.TextField()
    is_pinned = models.BooleanField(default=False)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "announcements_announcement"
        indexes = [
            models.Index(
                fields=["course", "status", "-published_at"],
                name="announce_feed_idx",
            ),
            models.Index(
                fields=["course", "is_pinned", "-published_at"],
                name="announce_pinned_idx",
            ),
        ]

    def __str__(self):
        return self.title


class AnnouncementRead(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    announcement = models.ForeignKey(
        Announcement, on_delete=models.CASCADE, related_name="reads"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="announcement_reads",
    )
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "announcements_announcementread"
        constraints = [
            models.UniqueConstraint(
                fields=["announcement", "student"],
                name="announcement_student_read_uniq",
            )
        ]

    def __str__(self):
        return f"{self.student} read {self.announcement}"
