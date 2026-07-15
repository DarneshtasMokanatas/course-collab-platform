from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Max
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django.utils.text import slugify

from apps.audit.models import AuditEvent

from .models import Course, CourseSection


@dataclass(frozen=True)
class SectionData:
    section_id: object | None
    title: str
    description: str
    position: int


def _can_manage(actor, course):
    return course.instructor_id == actor.id


def _require_instructor(actor):
    if actor.role != actor.Role.INSTRUCTOR:
        raise PermissionDenied("Instructor access is required.")


def _slug_for(code):
    return slugify(code) or "course"


def _unique_slug(code):
    base = _slug_for(code)
    slug = base
    suffix = 2
    while Course.objects.filter(slug=slug).exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def create_course(*, actor, data):
    _require_instructor(actor)
    with transaction.atomic():
        course = Course(
            code=data["code"],
            slug=_unique_slug(data["code"]),
            title=data["title"],
            description=data["description"],
            syllabus=data["syllabus"],
            enrolment_mode=data["enrolment_mode"],
            instructor=actor,
        )
        course.full_clean()
        course.save()
        AuditEvent.objects.create(
            actor=actor,
            action="COURSE_CREATED",
            object_type="Course",
            object_id=course.id,
            course=course,
        )
    return course


def update_course_and_sections(*, actor, course, data, sections):
    _require_instructor(actor)
    positions = [section.position for section in sections]
    if len(positions) != len(set(positions)) or any(
        position < 1 for position in positions
    ):
        raise ValidationError("Section positions must be unique positive numbers.")

    with transaction.atomic():
        locked_course = Course.objects.select_for_update().get(pk=course.pk)
        if not _can_manage(actor, locked_course):
            raise PermissionDenied("You do not manage this course.")
        if (
            locked_course.status == Course.Status.PUBLISHED
            and data["code"] != locked_course.code
        ):
            raise ValidationError(
                {"code": "Course code cannot change after publication."}
            )

        previous_mode = locked_course.enrolment_mode
        for field in ("code", "title", "description", "syllabus", "enrolment_mode"):
            setattr(locked_course, field, data[field])
        if locked_course.status == Course.Status.DRAFT:
            locked_course.slug = (
                _unique_slug(locked_course.code)
                if locked_course.code != course.code
                else locked_course.slug
            )
        locked_course.full_clean()
        locked_course.save()

        existing = {
            section.id: section
            for section in CourseSection.objects.select_for_update().filter(
                course=locked_course
            )
        }
        submitted_ids = {
            section.section_id for section in sections if section.section_id
        }
        unknown_ids = submitted_ids.difference(existing)
        if unknown_ids:
            raise PermissionDenied("Section does not belong to this course.")
        highest_position = max(
            CourseSection.objects.filter(course=locked_course).aggregate(
                maximum=Max("position")
            )["maximum"]
            or 0,
            max(positions, default=0),
        )
        temporary_offset = highest_position + len(existing) + len(sections) + 1
        CourseSection.objects.filter(course=locked_course).update(
            position=F("position") + temporary_offset
        )
        for section_id, section in existing.items():
            if section_id not in submitted_ids:
                try:
                    section.delete()
                except ProtectedError as error:
                    raise ValidationError(
                        "A section with learning materials or assignments cannot be "
                        "removed."
                    ) from error
        for section_data in sorted(sections, key=lambda item: item.position):
            if section_data.section_id:
                section = existing[section_data.section_id]
                section.title = section_data.title
                section.description = section_data.description
                section.position = section_data.position
                section.full_clean()
                section.save()
            else:
                CourseSection.objects.create(
                    course=locked_course,
                    title=section_data.title,
                    description=section_data.description,
                    position=section_data.position,
                )
        if previous_mode != locked_course.enrolment_mode:
            AuditEvent.objects.create(
                actor=actor,
                action="COURSE_ENROLMENT_MODE_CHANGED",
                object_type="Course",
                object_id=locked_course.id,
                course=locked_course,
                metadata={"from": previous_mode, "to": locked_course.enrolment_mode},
            )
    return locked_course


def publish_course(*, actor, course):
    _require_instructor(actor)
    with transaction.atomic():
        course = Course.objects.select_for_update().get(pk=course.pk)
        if not _can_manage(actor, course):
            raise PermissionDenied("You do not manage this course.")
        if course.status == Course.Status.ARCHIVED:
            raise ValidationError("Archived courses cannot be published.")
        if not CourseSection.objects.filter(course=course).exists():
            raise ValidationError("Add at least one section before publishing.")
        course.status = Course.Status.PUBLISHED
        course.full_clean()
        course.save(update_fields=["status", "updated_at"])
        AuditEvent.objects.create(
            actor=actor,
            action="COURSE_PUBLISHED",
            object_type="Course",
            object_id=course.id,
            course=course,
            metadata={"published_at": timezone.now().isoformat()},
        )
    return course
