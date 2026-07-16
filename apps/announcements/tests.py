from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.analytics.models import ActivityEvent
from apps.audit.models import AuditEvent
from apps.courses.models import Course, Enrolment

from .models import Announcement, AnnouncementRead
from .services import (
    archive_announcement,
    create_announcement,
    edit_announcement,
    mark_announcement_read,
    publish_announcement,
)


class AnnouncementWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.instructor = user_model.objects.create_user(
            username="announce.teacher",
            email="announce.teacher@example.test",
            display_name="Announcement Teacher",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        cls.other_instructor = user_model.objects.create_user(
            username="announce.other.teacher",
            email="announce.other.teacher@example.test",
            display_name="Other Teacher",
            role=user_model.Role.INSTRUCTOR,
            password="SafeTestPassword!2026",
        )
        cls.student = user_model.objects.create_user(
            username="announce.student",
            email="announce.student@example.test",
            display_name="Announcement Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        cls.unenrolled = user_model.objects.create_user(
            username="announce.unenrolled",
            email="announce.unenrolled@example.test",
            display_name="Unenrolled Student",
            role=user_model.Role.STUDENT,
            password="SafeTestPassword!2026",
        )
        cls.staff = user_model.objects.create_user(
            username="announce.staff",
            email="announce.staff@example.test",
            display_name="Announcement Staff",
            role=user_model.Role.INSTRUCTOR,
            is_staff=True,
            password="SafeTestPassword!2026",
        )
        cls.course = Course.objects.create(
            code="ANN101",
            slug="ann101",
            title="Announcements",
            description="Announcement tests",
            instructor=cls.instructor,
            status=Course.Status.PUBLISHED,
            enrolment_mode=Course.EnrolmentMode.OPEN,
        )
        Enrolment.objects.create(course=cls.course, student=cls.student)

    def test_owner_can_create_publish_edit_pin_and_archive_with_audit(self):
        announcement = create_announcement(
            actor=self.instructor,
            course=self.course,
            data={"title": "Draft", "body": "Body", "is_pinned": False},
        )
        self.assertEqual(announcement.status, Announcement.Status.DRAFT)
        publish_announcement(actor=self.instructor, announcement=announcement)
        announcement.refresh_from_db()
        self.assertIsNotNone(announcement.published_at)
        edit_announcement(
            actor=self.instructor,
            announcement=announcement,
            data={"title": "Updated", "body": "New body", "is_pinned": True},
        )
        announcement.refresh_from_db()
        self.assertTrue(announcement.is_pinned)
        archive_announcement(actor=self.instructor, announcement=announcement)
        announcement.refresh_from_db()
        self.assertEqual(announcement.status, Announcement.Status.ARCHIVED)
        self.assertFalse(announcement.is_pinned)
        self.assertEqual(
            list(
                AuditEvent.objects.filter(object_id=announcement.id)
                .order_by("occurred_at")
                .values_list("action", flat=True)
            ),
            [
                "ANNOUNCEMENT_PUBLISHED",
                "ANNOUNCEMENT_EDITED",
                "ANNOUNCEMENT_ARCHIVED",
            ],
        )

    def test_wrong_role_or_owner_cannot_manage_announcements(self):
        announcement = create_announcement(
            actor=self.instructor,
            course=self.course,
            data={"title": "Draft", "body": "Body", "is_pinned": False},
        )
        with self.assertRaises(PermissionDenied):
            create_announcement(
                actor=self.student,
                course=self.course,
                data={"title": "No", "body": "No", "is_pinned": False},
            )
        with self.assertRaises(PermissionDenied):
            publish_announcement(actor=self.other_instructor, announcement=announcement)

    def test_published_edit_is_audited_and_archived_edit_is_rejected(self):
        draft = create_announcement(
            actor=self.instructor,
            course=self.course,
            data={"title": "Draft", "body": "Body", "is_pinned": False},
        )
        edit_announcement(
            actor=self.instructor,
            announcement=draft,
            data={"title": "Edited draft", "body": "Body", "is_pinned": False},
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                action="ANNOUNCEMENT_EDITED", object_id=draft.id
            ).exists()
        )
        announcement = create_announcement(
            actor=self.instructor,
            course=self.course,
            data={"title": "Published", "body": "Body", "is_pinned": False},
            publish_now=True,
        )
        archive_announcement(actor=self.instructor, announcement=announcement)
        with self.assertRaisesMessage(ValidationError, "cannot be edited"):
            edit_announcement(
                actor=self.instructor,
                announcement=announcement,
                data={"title": "No", "body": "No", "is_pinned": False},
            )

    def test_student_feed_shows_only_published_pinned_first_and_read_state(self):
        older = create_announcement(
            actor=self.instructor,
            course=self.course,
            data={"title": "Older", "body": "Body", "is_pinned": False},
            publish_now=True,
        )
        pinned = create_announcement(
            actor=self.instructor,
            course=self.course,
            data={"title": "Pinned", "body": "Body", "is_pinned": True},
            publish_now=True,
        )
        create_announcement(
            actor=self.instructor,
            course=self.course,
            data={"title": "Draft hidden", "body": "Body", "is_pinned": False},
        )
        Announcement.objects.filter(pk=older.pk).update(
            published_at=timezone.now() - timedelta(days=1)
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse("announcements:list", args=[self.course.id]))
        self.assertContains(response, "Pinned")
        self.assertContains(response, "Older")
        self.assertNotContains(response, "Draft hidden")
        self.assertLess(
            response.content.index(b"Pinned"), response.content.index(b"Older")
        )
        self.assertContains(response, "Unread", count=2)

        detail_url = reverse("announcements:detail", args=[self.course.id, pinned.id])
        self.client.get(detail_url)
        self.client.get(detail_url)
        self.assertEqual(
            AnnouncementRead.objects.filter(
                announcement=pinned, student=self.student
            ).count(),
            1,
        )
        self.assertEqual(
            ActivityEvent.objects.filter(
                event_type=ActivityEvent.EventType.ANNOUNCEMENT_VIEWED,
                object_id=pinned.id,
                user=self.student,
            ).count(),
            1,
        )
        response = self.client.get(reverse("announcements:list", args=[self.course.id]))
        self.assertContains(response, "Read")

    def test_unenrolled_student_and_other_instructor_receive_404(self):
        announcement = create_announcement(
            actor=self.instructor,
            course=self.course,
            data={"title": "Published", "body": "Body", "is_pinned": False},
            publish_now=True,
        )
        for user in (self.unenrolled, self.other_instructor):
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(
                    reverse("announcements:list", args=[self.course.id])
                ).status_code,
                404,
            )
            self.assertEqual(
                self.client.get(
                    reverse(
                        "announcements:detail",
                        args=[self.course.id, announcement.id],
                    )
                ).status_code,
                404,
            )

    def test_staff_admin_can_read_and_manage_course_announcements(self):
        announcement = create_announcement(
            actor=self.instructor,
            course=self.course,
            data={"title": "Draft", "body": "Body", "is_pinned": False},
        )
        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.get(
                reverse("announcements:list", args=[self.course.id])
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                reverse(
                    "announcements:publish",
                    args=[self.course.id, announcement.id],
                )
            ).status_code,
            302,
        )
        announcement.refresh_from_db()
        self.assertEqual(announcement.status, Announcement.Status.PUBLISHED)

    def test_management_views_are_post_only_and_owner_scoped(self):
        announcement = create_announcement(
            actor=self.instructor,
            course=self.course,
            data={"title": "Draft", "body": "Body", "is_pinned": False},
        )
        self.client.force_login(self.student)
        self.assertEqual(
            self.client.get(
                reverse("announcements:new", args=[self.course.id])
            ).status_code,
            404,
        )
        self.client.force_login(self.instructor)
        publish_url = reverse(
            "announcements:publish", args=[self.course.id, announcement.id]
        )
        archive_url = reverse(
            "announcements:archive", args=[self.course.id, announcement.id]
        )
        self.assertEqual(self.client.get(publish_url).status_code, 404)
        self.assertEqual(self.client.get(archive_url).status_code, 404)
        self.assertEqual(self.client.post(publish_url).status_code, 302)
        self.assertEqual(self.client.post(archive_url).status_code, 302)

    def test_mark_read_is_idempotent_and_database_constraint_is_unique(self):
        announcement = create_announcement(
            actor=self.instructor,
            course=self.course,
            data={"title": "Published", "body": "Body", "is_pinned": False},
            publish_now=True,
        )
        first = mark_announcement_read(student=self.student, announcement=announcement)
        second = mark_announcement_read(student=self.student, announcement=announcement)
        self.assertEqual(first.id, second.id)
        with self.assertRaises(PermissionDenied):
            mark_announcement_read(student=self.unenrolled, announcement=announcement)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AnnouncementRead.objects.create(
                announcement=announcement, student=self.student
            )

    def test_published_announcement_requires_published_timestamp(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Announcement.objects.create(
                course=self.course,
                author=self.instructor,
                title="Invalid published row",
                body="Missing timestamp",
                status=Announcement.Status.PUBLISHED,
            )

    def test_dashboard_recent_and_unread_state_uses_active_published_feed(self):
        announcements = []
        for number in range(6):
            announcement = create_announcement(
                actor=self.instructor,
                course=self.course,
                data={
                    "title": f"Recent {number}",
                    "body": "Body",
                    "is_pinned": False,
                },
                publish_now=True,
            )
            Announcement.objects.filter(pk=announcement.pk).update(
                published_at=timezone.now() - timedelta(minutes=number)
            )
            announcements.append(announcement)
        create_announcement(
            actor=self.instructor,
            course=self.course,
            data={"title": "Draft hidden", "body": "Body", "is_pinned": False},
        )

        self.client.force_login(self.student)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["unread_announcement_count"], 6)
        self.assertEqual(len(response.context["recent_announcements"]), 5)
        self.assertEqual(response.context["recent_announcements"][0].title, "Recent 0")
        self.assertNotContains(response, "Recent 5")
        self.assertNotContains(response, "Draft hidden")

        self.client.get(
            reverse(
                "announcements:detail",
                args=[self.course.id, announcements[0].id],
            )
        )
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["unread_announcement_count"], 5)

        enrolment = Enrolment.objects.get(course=self.course, student=self.student)
        enrolment.status = Enrolment.Status.WITHDRAWN
        enrolment.withdrawn_at = timezone.now()
        enrolment.save(update_fields=["status", "withdrawn_at"])
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["unread_announcement_count"], 0)
        self.assertEqual(len(response.context["recent_announcements"]), 0)
