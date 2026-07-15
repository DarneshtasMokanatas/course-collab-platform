import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.courses.models import Course, CourseSection


class Material(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        ARCHIVED = "ARCHIVED", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(
        Course, on_delete=models.PROTECT, related_name="materials"
    )
    section = models.ForeignKey(
        CourseSection,
        on_delete=models.PROTECT,
        related_name="materials",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_materials",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "materials_material"
        indexes = [
            models.Index(
                fields=["course", "status", "section", "created_at"],
                name="material_course_feed_idx",
            )
        ]

    def clean(self):
        super().clean()
        if self.section_id and self.section.course_id != self.course_id:
            raise ValidationError({"section": "Section must belong to this course."})

    def __str__(self):
        return self.title


class MaterialVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    material = models.ForeignKey(
        Material, on_delete=models.PROTECT, related_name="versions"
    )
    version_number = models.PositiveIntegerField()
    storage_key = models.CharField(max_length=500, unique=True)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="material_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "materials_materialversion"
        ordering = ["material", "version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["material", "version_number"],
                name="material_version_number_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(version_number__gte=1),
                name="material_version_number_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(size_bytes__gt=0), name="material_size_bytes_gt_0"
            ),
        ]

    def __str__(self):
        return f"{self.material} v{self.version_number}"
