from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.analytics.models import ActivityEvent
from apps.analytics.services import record_activity
from apps.audit.models import AuditEvent
from apps.courses.models import Course, Enrolment
from apps.upload_validation import validated_upload_metadata

from .models import Assignment, GradeRevision, Submission, SubmissionVersion
from .policies import NON_MEMBER_MAX_VERSION


def _require_owner(actor, course):
    if not actor.is_staff and (
        actor.role != actor.Role.INSTRUCTOR or course.instructor_id != actor.id
    ):
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
    try:
        return validated_upload_metadata(
            upload=upload,
            allowed_extensions=set(assignment.allowed_extensions),
            max_upload_bytes=assignment.max_upload_bytes,
        )
    except ValidationError as error:
        if "file type is not allowed" in str(error):
            raise ValidationError(
                "This file type is not allowed for the assignment."
            ) from error
        raise


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
                submitted_at=now,
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
            record_activity(
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


def submit_resubmission(*, actor, assignment, upload):
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
            submission = (
                Submission.objects.select_for_update()
                .filter(assignment=assignment, student=actor)
                .first()
            )
            if submission is None:
                raise ValidationError("Submit a first version before resubmitting.")
            if not assignment.allow_resubmission:
                raise ValidationError(
                    "Resubmission is not enabled for this assignment."
                )
            now = timezone.now()
            if now >= assignment.due_at:
                raise ValidationError(
                    "Resubmissions must be received before the deadline."
                )
            latest_version_number = (
                submission.versions.order_by("-version_number")
                .values_list("version_number", flat=True)
                .first()
            )
            if latest_version_number is None:
                raise ValidationError("Submit a first version before resubmitting.")
            membership_status = (
                User.objects.select_for_update()
                .values_list("membership_status", flat=True)
                .get(pk=actor.pk)
            )
            if (
                membership_status == User.MembershipStatus.NON_MEMBER
                and latest_version_number >= NON_MEMBER_MAX_VERSION
            ):
                raise ValidationError(
                    "You have reached the non-member limit of 2 resubmissions.",
                    code="resubmission_limit",
                )
            version = SubmissionVersion(
                submission=submission,
                version_number=latest_version_number + 1,
                original_filename=filename,
                content_type=content_type,
                size_bytes=size,
                sha256=sha256,
                submitted_at=now,
                was_late=False,
            )
            version.storage_key = (
                f"courses/{assignment.course_id}/assignments/{assignment.id}/"
                f"submissions/{submission.id}/{version.id}"
            )
            saved_key = default_storage.save(version.storage_key, upload)
            version.storage_key = saved_key
            version.full_clean()
            version.save()
            record_activity(
                course=assignment.course,
                user=actor,
                event_type=ActivityEvent.EventType.SUBMISSION_RESUBMITTED,
                object_type="SubmissionVersion",
                object_id=version.id,
                metadata={
                    "version_number": version.version_number,
                    "was_late": False,
                },
            )
            AuditEvent.objects.create(
                actor=actor,
                action="SUBMISSION_RESUBMITTED",
                object_type="SubmissionVersion",
                object_id=version.id,
                course=assignment.course,
                metadata={
                    "assignment_id": str(assignment.id),
                    "submission_id": str(submission.id),
                    "version_number": version.version_number,
                    "was_late": False,
                },
            )
    except Exception:
        if saved_key:
            default_storage.delete(saved_key)
        raise
    return version


def create_grade_revision(
    *,
    actor,
    submission,
    submission_version,
    score,
    feedback,
):
    with transaction.atomic():
        submission = (
            Submission.objects.select_for_update()
            .select_related("assignment__course")
            .get(pk=submission.pk)
        )
        _require_owner(actor, submission.assignment.course)
        submission_version = SubmissionVersion.objects.filter(
            pk=submission_version.pk,
            submission=submission,
        ).first()
        if submission_version is None:
            raise ValidationError(
                {"submission_version": "Version must belong to this submission."}
            )
        latest_revision_number = (
            submission.grade_revisions.order_by("-revision_number")
            .values_list("revision_number", flat=True)
            .first()
            or 0
        )
        revision = GradeRevision(
            submission=submission,
            submission_version=submission_version,
            revision_number=latest_revision_number + 1,
            score=score,
            feedback=feedback,
            graded_by=actor,
        )
        revision.full_clean()
        revision.save()
        AuditEvent.objects.create(
            actor=actor,
            action="GRADE_REVISION_CREATED",
            object_type="GradeRevision",
            object_id=revision.id,
            course=submission.assignment.course,
            metadata={
                "assignment_id": str(submission.assignment_id),
                "submission_id": str(submission.id),
                "submission_version_id": str(submission_version.id),
                "revision_number": revision.revision_number,
            },
        )
    return revision


def release_latest_grade(*, actor, submission):
    with transaction.atomic():
        submission = (
            Submission.objects.select_for_update()
            .select_related("assignment__course")
            .get(pk=submission.pk)
        )
        _require_owner(actor, submission.assignment.course)
        revision = submission.grade_revisions.order_by("-revision_number").first()
        if revision is None:
            raise ValidationError("Create a grade revision before releasing it.")
        if revision.released_at is not None:
            return revision
        revision.released_at = timezone.now()
        revision.save(update_fields=["released_at"])
        AuditEvent.objects.create(
            actor=actor,
            action="GRADE_RELEASED",
            object_type="GradeRevision",
            object_id=revision.id,
            course=submission.assignment.course,
            metadata={
                "assignment_id": str(submission.assignment_id),
                "submission_id": str(submission.id),
                "revision_number": revision.revision_number,
            },
        )
    return revision


def withdraw_latest_grade_release(*, actor, submission):
    with transaction.atomic():
        submission = (
            Submission.objects.select_for_update()
            .select_related("assignment__course")
            .get(pk=submission.pk)
        )
        _require_owner(actor, submission.assignment.course)
        revision = (
            submission.grade_revisions.filter(released_at__isnull=False)
            .order_by("-revision_number")
            .first()
        )
        if revision is None:
            raise ValidationError("No released grade is available to withdraw.")
        revision.released_at = None
        revision.save(update_fields=["released_at"])
        AuditEvent.objects.create(
            actor=actor,
            action="GRADE_RELEASE_WITHDRAWN",
            object_type="GradeRevision",
            object_id=revision.id,
            course=submission.assignment.course,
            metadata={
                "assignment_id": str(submission.assignment_id),
                "submission_id": str(submission.id),
                "revision_number": revision.revision_number,
            },
        )
    return revision
