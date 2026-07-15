import uuid

from django.conf import settings
from django.db import models

from apps.courses.models import Course


class ActivityEvent(models.Model):
    class EventType(models.TextChoices):
        COURSE_VIEWED = "COURSE_VIEWED", "Course viewed"
        MATERIAL_VIEWED = "MATERIAL_VIEWED", "Material viewed"
        MATERIAL_DOWNLOADED = "MATERIAL_DOWNLOADED", "Material downloaded"
        ASSIGNMENT_VIEWED = "ASSIGNMENT_VIEWED", "Assignment viewed"
        ANNOUNCEMENT_VIEWED = "ANNOUNCEMENT_VIEWED", "Announcement viewed"
        SUBMISSION_CREATED = "SUBMISSION_CREATED", "Submission created"
        SUBMISSION_RESUBMITTED = "SUBMISSION_RESUBMITTED", "Submission resubmitted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="activity_events"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="activity_events",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    object_type = models.CharField(max_length=50, blank=True)
    object_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "analytics_activityevent"
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(
                fields=["course", "-occurred_at"], name="activity_course_time_idx"
            ),
            models.Index(
                fields=["course", "user", "-occurred_at"],
                name="activity_course_user_idx",
            ),
            models.Index(
                fields=["user", "-occurred_at"], name="activity_user_time_idx"
            ),
        ]

    def __str__(self):
        return f"{self.user}: {self.get_event_type_display()}"
