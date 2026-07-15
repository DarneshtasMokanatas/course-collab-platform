import uuid

from django.conf import settings
from django.db import models

from apps.courses.models import Course


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_id = models.UUIDField()
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_auditevent"
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(
                fields=["course", "-occurred_at"], name="audit_course_time_idx"
            ),
            models.Index(
                fields=["object_type", "object_id"], name="audit_object_lookup_idx"
            ),
        ]

    def __str__(self):
        return f"{self.action} {self.object_type}:{self.object_id}"
