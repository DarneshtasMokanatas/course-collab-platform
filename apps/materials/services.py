from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.courses.models import Enrolment
from apps.upload_validation import validated_upload_metadata

from .models import Material, MaterialVersion

ALLOWED_EXTENSIONS = {"pdf", "docx", "pptx", "xlsx", "zip"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _require_owner(actor, course):
    if not actor.is_staff and (
        actor.role != actor.Role.INSTRUCTOR or course.instructor_id != actor.id
    ):
        raise PermissionDenied


def _file_metadata(upload):
    return validated_upload_metadata(
        upload=upload,
        allowed_extensions=ALLOWED_EXTENSIONS,
        max_upload_bytes=MAX_UPLOAD_BYTES,
    )


def create_material(*, actor, course, data, upload):
    _require_owner(actor, course)
    if data.get("section") and data["section"].course_id != course.id:
        raise ValidationError("Section must belong to this course.")
    filename, content_type, size, sha256 = _file_metadata(upload)
    saved_key = None
    try:
        with transaction.atomic():
            material = Material(course=course, created_by=actor, **data)
            if material.status == Material.Status.PUBLISHED:
                material.published_at = timezone.now()
            material.full_clean()
            material.save()
            version = MaterialVersion(
                material=material,
                version_number=1,
                original_filename=filename,
                content_type=content_type,
                size_bytes=size,
                sha256=sha256,
                uploaded_by=actor,
            )
            version.storage_key = (
                f"courses/{course.id}/materials/{material.id}/{version.id}"
            )
            saved_key = default_storage.save(version.storage_key, upload)
            version.storage_key = saved_key
            version.full_clean()
            version.save()
            AuditEvent.objects.create(
                actor=actor,
                action="MATERIAL_PUBLISHED"
                if material.status == Material.Status.PUBLISHED
                else "MATERIAL_CREATED",
                object_type="Material",
                object_id=material.id,
                course=course,
            )
    except Exception:
        if saved_key:
            default_storage.delete(saved_key)
        raise
    return material


def add_material_version(*, actor, material, upload):
    _require_owner(actor, material.course)
    filename, content_type, size, sha256 = _file_metadata(upload)
    saved_key = None
    try:
        with transaction.atomic():
            material = (
                Material.objects.select_for_update()
                .select_related("course")
                .get(pk=material.pk)
            )
            _require_owner(actor, material.course)
            version = MaterialVersion(
                material=material,
                version_number=material.versions.count() + 1,
                original_filename=filename,
                content_type=content_type,
                size_bytes=size,
                sha256=sha256,
                uploaded_by=actor,
            )
            version.storage_key = (
                f"courses/{material.course_id}/materials/{material.id}/{version.id}"
            )
            saved_key = default_storage.save(version.storage_key, upload)
            version.storage_key = saved_key
            version.full_clean()
            version.save()
            AuditEvent.objects.create(
                actor=actor,
                action="MATERIAL_VERSION_CREATED",
                object_type="MaterialVersion",
                object_id=version.id,
                course=material.course,
                metadata={
                    "material_id": str(material.id),
                    "version_number": version.version_number,
                },
            )
    except Exception:
        if saved_key:
            default_storage.delete(saved_key)
        raise
    return version


def can_download(user, material):
    if user.is_staff:
        return True
    if user.role == user.Role.INSTRUCTOR and material.course.instructor_id == user.id:
        return True
    return (
        user.role == user.Role.STUDENT
        and Enrolment.objects.filter(
            course=material.course, student=user, status=Enrolment.Status.ACTIVE
        ).exists()
    )
