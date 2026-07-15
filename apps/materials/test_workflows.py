import hashlib
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.courses.models import Course, Enrolment

from .models import Material
from .services import add_material_version, create_material


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
        self.assertEqual(version_two.sha256, hashlib.sha256(b"revised").hexdigest())
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
