from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.materials.models import Material

from .models import Course, CourseSection
from .services import SectionData, update_course_and_sections


class CourseSectionServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.instructor = user_model.objects.create_user(
            username="service.teacher",
            email="service.teacher@example.test",
            display_name="Service Teacher",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )

    def course_data(self, course):
        return {
            "code": course.code,
            "title": course.title,
            "description": course.description,
            "syllabus": course.syllabus,
            "enrolment_mode": course.enrolment_mode,
        }

    def test_reordering_existing_sections_uses_a_safe_temporary_range(self):
        course = Course.objects.create(
            code="REORDER",
            slug="reorder",
            title="Reorder",
            description="Reorder sections",
            instructor=self.instructor,
        )
        first = CourseSection.objects.create(course=course, title="First", position=1)
        second = CourseSection.objects.create(
            course=course, title="Second", position=1000001
        )

        update_course_and_sections(
            actor=self.instructor,
            course=course,
            data=self.course_data(course),
            sections=[
                SectionData(second.id, "Second", "", 1),
                SectionData(first.id, "First", "", 2),
            ],
        )

        self.assertEqual(
            list(course.sections.order_by("position").values_list("title", flat=True)),
            ["Second", "First"],
        )

    def test_referenced_section_cannot_be_removed_and_update_rolls_back(self):
        course = Course.objects.create(
            code="PROTECT",
            slug="protect",
            title="Protect",
            description="Protect sections",
            instructor=self.instructor,
        )
        section = CourseSection.objects.create(
            course=course, title="Referenced", position=1
        )
        Material.objects.create(
            course=course, section=section, title="Slides", created_by=self.instructor
        )

        with self.assertRaisesMessage(ValidationError, "cannot be removed"):
            update_course_and_sections(
                actor=self.instructor,
                course=course,
                data=self.course_data(course),
                sections=[],
            )
        self.assertTrue(CourseSection.objects.filter(pk=section.pk).exists())
