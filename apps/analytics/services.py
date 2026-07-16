from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import ActivityEvent

VIEW_EVENT_TYPES = {
    ActivityEvent.EventType.COURSE_VIEWED,
    ActivityEvent.EventType.MATERIAL_VIEWED,
    ActivityEvent.EventType.ASSIGNMENT_VIEWED,
    ActivityEvent.EventType.ANNOUNCEMENT_VIEWED,
}
VIEW_EVENT_WINDOW = timedelta(minutes=5)
OBJECT_TYPE_BY_EVENT = {
    ActivityEvent.EventType.COURSE_VIEWED: "Course",
    ActivityEvent.EventType.MATERIAL_VIEWED: "Material",
    ActivityEvent.EventType.MATERIAL_DOWNLOADED: "MaterialVersion",
    ActivityEvent.EventType.ASSIGNMENT_VIEWED: "Assignment",
    ActivityEvent.EventType.ANNOUNCEMENT_VIEWED: "Announcement",
    ActivityEvent.EventType.SUBMISSION_CREATED: "SubmissionVersion",
    ActivityEvent.EventType.SUBMISSION_RESUBMITTED: "SubmissionVersion",
}


def record_activity(
    *,
    course,
    user,
    event_type,
    object_type="",
    object_id=None,
    metadata=None,
):
    approved_types = {value for value, _label in ActivityEvent.EventType.choices}
    if event_type not in approved_types:
        raise ValidationError("Activity event type is not approved.")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValidationError("Activity metadata must be an object.")
    if object_type != OBJECT_TYPE_BY_EVENT[event_type] or object_id is None:
        raise ValidationError("Activity object does not match the event type.")

    occurred_at = timezone.now()
    if event_type in VIEW_EVENT_TYPES:
        duplicate_exists = ActivityEvent.objects.filter(
            course=course,
            user=user,
            event_type=event_type,
            object_type=object_type,
            object_id=object_id,
            occurred_at__gte=occurred_at - VIEW_EVENT_WINDOW,
        ).exists()
        if duplicate_exists:
            return None

    return ActivityEvent.objects.create(
        course=course,
        user=user,
        event_type=event_type,
        object_type=object_type,
        object_id=object_id,
        metadata=metadata or {},
    )
