from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Exists, F, OuterRef, Prefetch, Q, Subquery
from django.utils import timezone

from apps.analytics.models import ActivityEvent
from apps.announcements.models import Announcement, AnnouncementRead
from apps.assignments.models import (
    Assignment,
    GradeRevision,
    Submission,
    SubmissionVersion,
)
from apps.courses.models import Course, Enrolment

TRACKED_ASSIGNMENT_STATUSES = [
    Assignment.Status.PUBLISHED,
    Assignment.Status.CLOSED,
]


def student_dashboard_context(user):
    now = timezone.now()
    active_enrolments_queryset = (
        Enrolment.objects.filter(student=user, status=Enrolment.Status.ACTIVE)
        .select_related("course")
        .order_by("course__code")
    )
    active_course_ids = list(
        active_enrolments_queryset.values_list("course_id", flat=True)
    )
    displayed_enrolments = list(active_enrolments_queryset[:7])
    active_enrolments = displayed_enrolments[:6]

    announcements = (
        Announcement.objects.filter(
            course_id__in=active_course_ids,
            status=Announcement.Status.PUBLISHED,
        )
        .select_related("course")
        .annotate(
            is_read=Exists(
                AnnouncementRead.objects.filter(
                    announcement_id=OuterRef("pk"),
                    student=user,
                )
            )
        )
        .order_by("-published_at")
    )
    unread_announcement_count = announcements.filter(is_read=False).count()
    recent_announcements = list(announcements[:5])

    student_submissions = Submission.objects.filter(student=user).prefetch_related(
        Prefetch(
            "versions",
            queryset=SubmissionVersion.objects.order_by("version_number"),
            to_attr="dashboard_versions",
        ),
        Prefetch(
            "grade_revisions",
            queryset=GradeRevision.objects.filter(released_at__isnull=False).order_by(
                "revision_number"
            ),
            to_attr="dashboard_released_grades",
        ),
    )
    upcoming_assignments = list(
        Assignment.objects.filter(
            course_id__in=active_course_ids,
            status=Assignment.Status.PUBLISHED,
            due_at__gte=now,
        )
        .select_related("course")
        .order_by("due_at")[:10]
    )
    state_assignments = list(
        Assignment.objects.filter(
            course_id__in=active_course_ids,
            status__in=TRACKED_ASSIGNMENT_STATUSES,
        )
        .select_related("course")
        .prefetch_related(
            Prefetch(
                "submissions",
                queryset=student_submissions,
                to_attr="dashboard_submissions",
            )
        )
        .order_by("-due_at")[:10]
    )
    submission_rows = []
    for assignment in state_assignments:
        submission = (
            assignment.dashboard_submissions[0]
            if assignment.dashboard_submissions
            else None
        )
        status = "NOT_SUBMITTED"
        if submission:
            latest_version = submission.dashboard_versions[-1]
            if submission.dashboard_released_grades:
                status = "GRADED"
            elif latest_version.was_late:
                status = "LATE"
            else:
                status = "SUBMITTED"
        submission_rows.append({"assignment": assignment, "status": status})

    latest_released_id = (
        GradeRevision.objects.filter(
            submission_id=OuterRef("submission_id"),
            released_at__isnull=False,
        )
        .order_by("-revision_number")
        .values("id")[:1]
    )
    released_grades = list(
        GradeRevision.objects.filter(
            submission__student=user,
            submission__assignment__course_id__in=active_course_ids,
            released_at__isnull=False,
            pk=Subquery(latest_released_id),
        )
        .select_related("submission__assignment__course")
        .order_by("-released_at")[:10]
    )

    return {
        "now": now,
        "active_enrolments": active_enrolments,
        "has_more_enrolments": len(displayed_enrolments) > 6,
        "unread_announcement_count": unread_announcement_count,
        "recent_announcements": recent_announcements,
        "upcoming_assignments": upcoming_assignments,
        "submission_rows": submission_rows,
        "released_grades": released_grades,
    }


def instructor_dashboard_context(user):
    tracked_filter = Q(assignments__status__in=TRACKED_ASSIGNMENT_STATUSES)
    courses = list(
        Course.objects.filter(instructor=user)
        .annotate(
            active_enrolment_count=Count(
                "enrolments",
                filter=Q(enrolments__status=Enrolment.Status.ACTIVE),
                distinct=True,
            ),
            tracked_assignment_count=Count(
                "assignments",
                filter=tracked_filter,
                distinct=True,
            ),
            needs_grading_count=Count(
                "assignments__submissions",
                filter=tracked_filter
                & Q(assignments__submissions__grade_revisions__isnull=True),
                distinct=True,
            ),
        )
        .order_by("code")
    )
    course_ids = [course.id for course in courses]
    active_received_counts = {
        row["assignment__course_id"]: row["total"]
        for row in (
            Submission.objects.filter(
                assignment__course_id__in=course_ids,
                assignment__status__in=TRACKED_ASSIGNMENT_STATUSES,
                student__enrolments__course_id=F("assignment__course_id"),
                student__enrolments__status=Enrolment.Status.ACTIVE,
            )
            .values("assignment__course_id")
            .annotate(total=Count("pk", distinct=True))
        )
    }

    latest_was_late = SubmissionVersion.objects.filter(
        submission_id=OuterRef("pk")
    ).order_by("-version_number")
    late_counts = {
        row["assignment__course_id"]: row["total"]
        for row in (
            Submission.objects.filter(
                assignment__course_id__in=course_ids,
                assignment__status__in=TRACKED_ASSIGNMENT_STATUSES,
            )
            .annotate(latest_was_late=Subquery(latest_was_late.values("was_late")[:1]))
            .filter(latest_was_late=True)
            .values("assignment__course_id")
            .annotate(total=Count("pk"))
        )
    }

    inactive_cutoff = timezone.now() - timedelta(days=14)
    latest_activity = ActivityEvent.objects.filter(
        course_id=OuterRef("course_id"),
        user_id=OuterRef("student_id"),
    ).order_by("-occurred_at")
    inactive_enrolments = (
        Enrolment.objects.filter(
            course_id__in=course_ids,
            status=Enrolment.Status.ACTIVE,
        )
        .annotate(latest_activity=Subquery(latest_activity.values("occurred_at")[:1]))
        .filter(
            Q(latest_activity__isnull=True) | Q(latest_activity__lt=inactive_cutoff)
        )
    )
    inactive_student_count = inactive_enrolments.values("student_id").distinct().count()
    inactive_counts = {
        row["course_id"]: row["total"]
        for row in inactive_enrolments.values("course_id").annotate(total=Count("pk"))
    }

    course_rows = []
    for course in courses:
        missing_count = max(
            (
                course.active_enrolment_count * course.tracked_assignment_count
                - active_received_counts.get(course.id, 0)
            ),
            0,
        )
        course_rows.append(
            {
                "course": course,
                "late_count": late_counts.get(course.id, 0),
                "missing_count": missing_count,
                "inactive_count": inactive_counts.get(course.id, 0),
            }
        )

    totals = defaultdict(int)
    for row in course_rows:
        course = row["course"]
        totals["active_enrolments"] += course.active_enrolment_count
        totals["needs_grading"] += course.needs_grading_count
        totals["late"] += row["late_count"]
        totals["missing"] += row["missing_count"]
    totals["inactive"] = inactive_student_count

    return {
        "course_rows": course_rows[:10],
        "has_more_owned_courses": len(course_rows) > 10,
        "dashboard_totals": dict(totals),
        "inactive_days": 14,
    }
