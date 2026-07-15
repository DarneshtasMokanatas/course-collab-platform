import hashlib
from pathlib import Path

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from apps.analytics.models import ActivityEvent
from apps.audit.models import AuditEvent
from apps.courses.models import Course, Enrolment

from .models import Assignment, Submission, SubmissionVersion


def _require_owner(actor, course):
    if actor.role != actor.Role.INSTRUCTOR or course.instructor_id != actor.id:
        raise PermissionDenied("You do not manage this course.")


def create_assignment(*, actor, course, data):
    _require_owner(actor, course)
    if data.get("section") and data["section"].course_id != course.id:
        raise ValidationError("Section must belong to this course.")
    if data["due_at"] <= timezone.now():
        raise ValidationError({"due_at": "Deadline must be in the future."})
    with transaction.atomic():
        assignment = Assignment(
            course=course,
            created_by=actor,
            status=Assignment.Status.DRAFT,
            **data,
        )
        assignment.full_clean()
        assignment.save()
        AuditEvent.objects.create(
            actor=actor,
            action="ASSIGNMENT_CREATED",
            object_type="Assignment",
            object_id=assignment.id,
            course=course,
        )
    return assignment


def publish_assignment(*, actor, assignment):
    _require_owner(actor, assignment.course)
    with transaction.atomic():
        assignment = (
            Assignment.objects.select_for_update()
            .select_related("course")
            .get(pk=assignment.pk)
        )
        _require_owner(actor, assignment.course)
        if assignment.status == Assignment.Status.ARCHIVED:
            raise ValidationError("Archived assignments cannot be published.")
        if assignment.status == Assignment.Status.CLOSED:
            raise ValidationError("Closed assignments cannot be published.")
        if assignment.status == Assignment.Status.PUBLISHED:
            return assignment
        if assignment.course.status != Course.Status.PUBLISHED:
            raise ValidationError("Publish the course before publishing assignments.")
        if assignment.due_at <= timezone.now():
            raise ValidationError("The assignment deadline must be in the future.")
        assignment.status = Assignment.Status.PUBLISHED
        assignment.published_at = timezone.now()
        assignment.full_clean()
        assignment.save(update_fields=["status", "published_at", "updated_at"])
        AuditEvent.objects.create(
            actor=actor,
            action="ASSIGNMENT_PUBLISHED",
            object_type="Assignment",
            object_id=assignment.id,
            course=assignment.course,
        )
    return assignment


def _file_metadata(assignment, upload):
    filename = Path(upload.name).name
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in assignment.allowed_extensions:
        raise ValidationError("This file type is not allowed for the assignment.")
    if upload.size <= 0 or upload.size > assignment.max_upload_bytes:
        raise ValidationError("This file does not meet the assignment size limit.")
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return (
        filename,
        upload.content_type or "application/octet-stream",
        upload.size,
        digest.hexdigest(),
    )


def submit_first_version(*, actor, assignment, upload):
    if actor.role != actor.Role.STUDENT:
        raise PermissionDenied("Student access is required.")
    filename, content_type, size, sha256 = _file_metadata(assignment, upload)
    saved_key = None
    try:
        with transaction.atomic():
            assignment = (
                Assignment.objects.select_for_update()
                .select_related("course")
                .get(pk=assignment.pk)
            )
            if assignment.status != Assignment.Status.PUBLISHED:
                raise ValidationError("This assignment is not accepting submissions.")
            if not Enrolment.objects.filter(
                course=assignment.course,
                student=actor,
                status=Enrolment.Status.ACTIVE,
            ).exists():
                raise PermissionDenied("Active enrolment is required.")
            if Submission.objects.filter(assignment=assignment, student=actor).exists():
                raise ValidationError("A submission already exists.")
            now = timezone.now()
            if now > assignment.due_at and not assignment.allow_late_submissions:
                raise ValidationError("The submission deadline has passed.")
            submission = Submission.objects.create(assignment=assignment, student=actor)
            version = SubmissionVersion(
                submission=submission,
                version_number=1,
                original_filename=filename,
                content_type=content_type,
                size_bytes=size,
                sha256=sha256,
                was_late=now > assignment.due_at,
            )
            version.storage_key = (
                f"courses/{assignment.course_id}/assignments/{assignment.id}/"
                f"submissions/{submission.id}/{version.id}"
            )
            saved_key = default_storage.save(version.storage_key, upload)
            version.storage_key = saved_key
            version.full_clean()
            version.save()
            ActivityEvent.objects.create(
                course=assignment.course,
                user=actor,
                event_type=ActivityEvent.EventType.SUBMISSION_CREATED,
                object_type="SubmissionVersion",
                object_id=version.id,
                metadata={"version_number": 1, "was_late": version.was_late},
            )
            AuditEvent.objects.create(
                actor=actor,
                action="SUBMISSION_CREATED",
                object_type="SubmissionVersion",
                object_id=version.id,
                course=assignment.course,
                metadata={
                    "assignment_id": str(assignment.id),
                    "submission_id": str(submission.id),
                    "version_number": 1,
                    "was_late": version.was_late,
                },
            )
    except Exception:
        if saved_key:
            default_storage.delete(saved_key)
        raise
    return version
