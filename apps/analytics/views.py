from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Exists, Max, OuterRef, Q, Subquery
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.assignments.models import (
    Assignment,
    GradeRevision,
    Submission,
    SubmissionVersion,
)
from apps.courses.models import Course, Enrolment


@login_required
def course_analytics(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if request.user.role != request.user.Role.INSTRUCTOR or (
        course.instructor_id != request.user.id
    ):
        raise Http404

    try:
        inactive_days = int(request.GET.get("inactive_days", 14))
    except (TypeError, ValueError):
        inactive_days = 14
    inactive_days = min(max(inactive_days, 1), 365)
    inactive_cutoff = timezone.now() - timedelta(days=inactive_days)
    tracked_statuses = [Assignment.Status.PUBLISHED, Assignment.Status.CLOSED]
    assignment_count = Assignment.objects.filter(
        course=course,
        status__in=tracked_statuses,
    ).count()

    enrolments = (
        Enrolment.objects.filter(course=course, status=Enrolment.Status.ACTIVE)
        .select_related("student")
        .annotate(
            latest_activity=Max(
                "student__activity_events__occurred_at",
                filter=Q(student__activity_events__course=course),
            )
        )
        .order_by("student__display_name", "student__username")
    )
    inactive_filter = Q(latest_activity__isnull=True) | Q(
        latest_activity__lt=inactive_cutoff
    )
    active_enrolment_count = enrolments.count()
    inactive_student_count = enrolments.filter(inactive_filter).count()
    page = Paginator(enrolments, 25).get_page(request.GET.get("page"))
    student_ids = [enrolment.student_id for enrolment in page.object_list]

    latest_was_late = SubmissionVersion.objects.filter(
        submission_id=OuterRef("pk")
    ).order_by("-version_number")
    released_grade_exists = GradeRevision.objects.filter(
        submission_id=OuterRef("pk"),
        released_at__isnull=False,
    )
    submissions = list(
        Submission.objects.filter(
            assignment__course=course,
            assignment__status__in=tracked_statuses,
            student_id__in=student_ids,
        )
        .select_related("assignment", "student")
        .annotate(
            latest_was_late=Subquery(latest_was_late.values("was_late")[:1]),
            has_released_grade=Exists(released_grade_exists),
        )
    )

    metrics = defaultdict(
        lambda: {
            "submitted": 0,
            "late": 0,
            "graded": 0,
            "released_scores": [],
        }
    )
    for submission in submissions:
        student_metrics = metrics[submission.student_id]
        student_metrics["submitted"] += 1
        student_metrics["late"] += int(bool(submission.latest_was_late))
        student_metrics["graded"] += int(submission.has_released_grade)

    submission_ids = [submission.id for submission in submissions]
    released_revisions = (
        GradeRevision.objects.filter(
            submission_id__in=submission_ids,
            released_at__isnull=False,
        )
        .select_related("submission")
        .order_by("submission_id", "-revision_number")
        .distinct("submission_id")
    )
    for revision in released_revisions:
        metrics[revision.submission.student_id]["released_scores"].append(
            revision.score
        )

    rows = []
    for enrolment in page.object_list:
        student_metrics = metrics[enrolment.student_id]
        scores = student_metrics["released_scores"]
        released_total = sum(scores, Decimal("0.00"))
        rows.append(
            {
                "student": enrolment.student,
                "latest_activity": enrolment.latest_activity,
                "is_inactive": (
                    enrolment.latest_activity is None
                    or enrolment.latest_activity < inactive_cutoff
                ),
                "submitted": student_metrics["submitted"],
                "missing": max(
                    assignment_count - student_metrics["submitted"],
                    0,
                ),
                "late": student_metrics["late"],
                "graded": student_metrics["graded"],
                "released_total": released_total,
                "released_average": (released_total / len(scores) if scores else None),
            }
        )

    return render(
        request,
        "analytics/course.html",
        {
            "course": course,
            "active_enrolment_count": active_enrolment_count,
            "assignment_count": assignment_count,
            "inactive_days": inactive_days,
            "inactive_student_count": inactive_student_count,
            "page": page,
            "rows": rows,
        },
    )
