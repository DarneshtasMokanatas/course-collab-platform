from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.courses.models import Enrolment

from .models import Announcement, AnnouncementRead


def _require_owner(actor, course):
    if not actor.is_staff and (
        actor.role != actor.Role.INSTRUCTOR or course.instructor_id != actor.id
    ):
        raise PermissionDenied("You do not manage this course.")


def create_announcement(*, actor, course, data, publish_now=False):
    _require_owner(actor, course)
    with transaction.atomic():
        announcement = Announcement(
            course=course,
            author=actor,
            status=Announcement.Status.DRAFT,
            **data,
        )
        announcement.full_clean()
        announcement.save()
        if publish_now:
            announcement = publish_announcement(actor=actor, announcement=announcement)
    return announcement


def publish_announcement(*, actor, announcement):
    _require_owner(actor, announcement.course)
    with transaction.atomic():
        announcement = (
            Announcement.objects.select_for_update()
            .select_related("course")
            .get(pk=announcement.pk)
        )
        _require_owner(actor, announcement.course)
        if announcement.status == Announcement.Status.ARCHIVED:
            raise ValidationError("Archived announcements cannot be published.")
        if announcement.status == Announcement.Status.PUBLISHED:
            return announcement
        announcement.status = Announcement.Status.PUBLISHED
        announcement.published_at = timezone.now()
        announcement.full_clean()
        announcement.save(update_fields=["status", "published_at", "updated_at"])
        AuditEvent.objects.create(
            actor=actor,
            action="ANNOUNCEMENT_PUBLISHED",
            object_type="Announcement",
            object_id=announcement.id,
            course=announcement.course,
        )
    return announcement


def edit_announcement(*, actor, announcement, data):
    _require_owner(actor, announcement.course)
    with transaction.atomic():
        announcement = (
            Announcement.objects.select_for_update()
            .select_related("course")
            .get(pk=announcement.pk)
        )
        _require_owner(actor, announcement.course)
        if announcement.status == Announcement.Status.ARCHIVED:
            raise ValidationError("Archived announcements cannot be edited.")
        changed_fields = [
            field
            for field in ("title", "body", "is_pinned")
            if getattr(announcement, field) != data[field]
        ]
        if not changed_fields:
            return announcement
        for field in changed_fields:
            setattr(announcement, field, data[field])
        announcement.full_clean()
        announcement.save(update_fields=[*changed_fields, "updated_at"])
        AuditEvent.objects.create(
            actor=actor,
            action="ANNOUNCEMENT_EDITED",
            object_type="Announcement",
            object_id=announcement.id,
            course=announcement.course,
            metadata={"changed_fields": changed_fields},
        )
    return announcement


def archive_announcement(*, actor, announcement):
    _require_owner(actor, announcement.course)
    with transaction.atomic():
        announcement = (
            Announcement.objects.select_for_update()
            .select_related("course")
            .get(pk=announcement.pk)
        )
        _require_owner(actor, announcement.course)
        if announcement.status == Announcement.Status.ARCHIVED:
            return announcement
        announcement.status = Announcement.Status.ARCHIVED
        announcement.is_pinned = False
        announcement.full_clean()
        announcement.save(update_fields=["status", "is_pinned", "updated_at"])
        AuditEvent.objects.create(
            actor=actor,
            action="ANNOUNCEMENT_ARCHIVED",
            object_type="Announcement",
            object_id=announcement.id,
            course=announcement.course,
        )
    return announcement


def mark_announcement_read(*, student, announcement):
    if student.role != student.Role.STUDENT:
        raise PermissionDenied("Student access is required.")
    if announcement.status != Announcement.Status.PUBLISHED:
        raise ValidationError("Only published announcements can be marked read.")
    if not Enrolment.objects.filter(
        course=announcement.course,
        student=student,
        status=Enrolment.Status.ACTIVE,
    ).exists():
        raise PermissionDenied("Active enrolment is required.")
    read, _ = AnnouncementRead.objects.get_or_create(
        announcement=announcement,
        student=student,
    )
    return read
