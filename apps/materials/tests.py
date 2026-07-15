from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.courses.models import Course

from .models import Material, MaterialVersion


class MaterialConstraintTests(TestCase):
    def test_material_version_number_is_unique(self):
        user_model = get_user_model()
        instructor = user_model.objects.create_user(
            username="material.instructor",
            email="material.instructor@tests.example",
            display_name="Material Instructor",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        course = Course.objects.create(
            code="MAT101",
            slug="mat101",
            title="Materials",
            description="Material tests",
            instructor=instructor,
        )
        material = Material.objects.create(
            course=course, title="Slides", created_by=instructor
        )
        values = {
            "material": material,
            "version_number": 1,
            "original_filename": "slides.pdf",
            "content_type": "application/pdf",
            "size_bytes": 100,
            "sha256": "a" * 64,
            "uploaded_by": instructor,
        }
        MaterialVersion.objects.create(storage_key="tests/material/v1", **values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MaterialVersion.objects.create(
                storage_key="tests/material/v1-copy", **values
            )
