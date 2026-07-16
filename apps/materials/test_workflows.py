import hashlib
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.courses.models import Course, Enrolment

from .models import Material, MaterialVersion
from .services import add_material_version, create_material

PDF_HEADER = b"%PDF-1.4\n"


class MaterialWorkflowTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings_override.enable()
        user_model = get_user_model()
        self.instructor = user_model.objects.create_user(
            username="materials.teacher",
            email="materials.teacher@example.test",
            display_name="Materials Teacher",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        self.student = user_model.objects.create_user(
            username="materials.student",
            email="materials.student@example.test",
            display_name="Materials Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        self.other_student = user_model.objects.create_user(
            username="materials.other",
            email="materials.other@example.test",
            display_name="Other Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        self.staff = user_model.objects.create_user(
            username="materials.staff",
            email="materials.staff@example.test",
            display_name="Materials Staff",
            role=user_model.Role.INSTRUCTOR,
            is_staff=True,
            password="SafeTestPassword!2026",
        )
        self.course = Course.objects.create(
            code="MATFLOW",
            slug="matflow",
            title="Materials",
            description="Materials",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
            enrolment_mode=Course.EnrolmentMode.OPEN,
        )
        Enrolment.objects.create(course=self.course, student=self.student)

    def tearDown(self):
        self.settings_override.disable()
        self.media_root.cleanup()

    def upload(self, name="slides.pdf", content=b"slide bytes"):
        if name.lower().endswith(".pdf") and not content.startswith(PDF_HEADER):
            content = PDF_HEADER + content
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    def test_owner_creates_immutable_versions_with_hash_metadata(self):
        material = create_material(
            actor=self.instructor,
            course=self.course,
            data={
                "section": None,
                "title": "Slides",
                "description": "Week one",
                "status": Material.Status.PUBLISHED,
            },
            upload=self.upload(),
        )
        version_two = add_material_version(
            actor=self.instructor,
            material=material,
            upload=self.upload("slides-v2.pdf", b"revised"),
        )
        versions = list(material.versions.order_by("version_number"))
        self.assertEqual([version.version_number for version in versions], [1, 2])
        self.assertEqual(
            version_two.sha256,
            hashlib.sha256(PDF_HEADER + b"revised").hexdigest(),
        )
        self.assertTrue(
            version_two.storage_key.startswith(f"courses/{self.course.id}/materials/")
        )

    def test_protected_download_allows_enrolled_student_only_for_published_material(
        self,
    ):
        material = create_material(
            actor=self.instructor,
            course=self.course,
            data={
                "section": None,
                "title": "Slides",
                "description": "Week one",
                "status": Material.Status.PUBLISHED,
            },
            upload=self.upload(),
        )
        version = material.versions.get()
        url = reverse(
            "materials:download", args=[self.course.id, material.id, version.id]
        )
        self.client.force_login(self.student)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.client.force_login(self.other_student)
        self.assertEqual(self.client.get(url).status_code, 404)
        material.status = Material.Status.DRAFT
        material.save(update_fields=["status"])
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_upload_rejects_unapproved_extension(self):
        with self.assertRaisesMessage(Exception, "not allowed"):
            create_material(
                actor=self.instructor,
                course=self.course,
                data={
                    "section": None,
                    "title": "Unsafe",
                    "description": "",
                    "status": Material.Status.DRAFT,
                },
                upload=self.upload("unsafe.exe"),
            )

    def test_upload_validates_content_size_and_sanitizes_filename(self):
        data = {
            "section": None,
            "title": "Validated",
            "description": "",
            "status": Material.Status.DRAFT,
        }
        with self.assertRaisesMessage(ValidationError, "content does not match"):
            create_material(
                actor=self.instructor,
                course=self.course,
                data=data,
                upload=SimpleUploadedFile(
                    "spoofed.pdf",
                    b"not a pdf",
                    content_type="application/pdf",
                ),
            )
        with patch("apps.materials.services.MAX_UPLOAD_BYTES", 4):
            with self.assertRaisesMessage(ValidationError, "size limit"):
                create_material(
                    actor=self.instructor,
                    course=self.course,
                    data=data,
                    upload=self.upload(content=b"too large"),
                )
        material = create_material(
            actor=self.instructor,
            course=self.course,
            data=data,
            upload=self.upload("C:\\private\\unsafe name.pdf"),
        )
        version = material.versions.get()
        self.assertEqual(version.original_filename, "unsafe_name.pdf")
        self.assertEqual(version.content_type, "application/pdf")
        self.assertEqual(version.size_bytes, len(PDF_HEADER + b"slide bytes"))

    def test_failed_material_metadata_write_removes_saved_file(self):
        with (
            patch(
                "apps.materials.services.MaterialVersion.save",
                side_effect=IntegrityError("forced failure"),
            ),
            patch("apps.materials.services.default_storage.delete") as delete_mock,
        ):
            with self.assertRaises(IntegrityError):
                create_material(
                    actor=self.instructor,
                    course=self.course,
                    data={
                        "section": None,
                        "title": "Rollback",
                        "description": "",
                        "status": Material.Status.DRAFT,
                    },
                    upload=self.upload(),
                )
        delete_mock.assert_called_once()
        self.assertFalse(Material.objects.filter(title="Rollback").exists())

    def test_staff_can_manage_and_download_protected_material(self):
        material = create_material(
            actor=self.staff,
            course=self.course,
            data={
                "section": None,
                "title": "Staff material",
                "description": "",
                "status": Material.Status.PUBLISHED,
            },
            upload=self.upload(),
        )
        version = material.versions.get()
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse(
                "materials:download",
                args=[self.course.id, material.id, version.id],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

        material.status = Material.Status.DRAFT
        material.save(update_fields=["status"])
        self.assertEqual(
            self.client.get(
                reverse(
                    "materials:download",
                    args=[self.course.id, material.id, version.id],
                )
            ).status_code,
            200,
        )
        self.client.force_login(self.student)
        self.assertEqual(
            self.client.get(
                reverse(
                    "materials:download",
                    args=[self.course.id, material.id, version.id],
                )
            ).status_code,
            404,
        )

    def test_missing_storage_file_returns_404(self):
        material = create_material(
            actor=self.instructor,
            course=self.course,
            data={
                "section": None,
                "title": "Missing file",
                "description": "",
                "status": Material.Status.PUBLISHED,
            },
            upload=self.upload(),
        )
        version = material.versions.get()
        self.client.force_login(self.student)
        with patch(
            "apps.materials.views.default_storage.open",
            side_effect=OSError("storage unavailable"),
        ):
            response = self.client.get(
                reverse(
                    "materials:download",
                    args=[self.course.id, material.id, version.id],
                )
            )
        self.assertEqual(response.status_code, 404)

    def test_material_history_query_count_is_bounded_and_paginated(self):
        materials = [
            Material.objects.create(
                course=self.course,
                title=f"Material {number:02d}",
                description="Query test",
                status=Material.Status.PUBLISHED,
                created_by=self.instructor,
            )
            for number in range(25)
        ]
        MaterialVersion.objects.bulk_create(
            [
                MaterialVersion(
                    material=material,
                    version_number=1,
                    storage_key=f"query/material/{material.id}",
                    original_filename="material.pdf",
                    content_type="application/pdf",
                    size_bytes=10,
                    sha256="a" * 64,
                    uploaded_by=self.instructor,
                )
                for material in materials
            ]
        )
        self.client.force_login(self.student)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("materials:list", args=[self.course.id]))
            self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["page"].object_list), 20)
        self.assertLessEqual(len(queries), 7)
