from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.analytics.models import ActivityEvent
from apps.courses.models import Course, Enrolment

from .forms import AssignmentForm, SubmissionForm
from .models import Assignment, Submission
from .services import create_assignment, publish_assignment, submit_first_version


def _owner_course(user, course_id):
    course = get_object_or_404(
        Course.objects.prefetch_related("sections"), pk=course_id
    )
    if user.role != user.Role.INSTRUCTOR or course.instructor_id != user.id:
        raise Http404
    return course


def _active_student(user, course):
    return (
        user.role == user.Role.STUDENT
        and Enrolment.objects.filter(
            course=course, student=user, status=Enrolment.Status.ACTIVE
        ).exists()
    )


def _course_access(user, course_id):
    course = get_object_or_404(
        Course.objects.prefetch_related("sections"), pk=course_id
    )
    owner = user.role == user.Role.INSTRUCTOR and course.instructor_id == user.id
    active_student = _active_student(user, course)
    if not owner and not active_student:
        raise Http404
    return course, owner


@login_required
def assignment_list(request, course_id):
    course, owner = _course_access(request.user, course_id)
    assignments = course.assignments.select_related("section").order_by(
        "due_at", "title"
    )
    if not owner:
        assignments = assignments.filter(status=Assignment.Status.PUBLISHED)
    return render(
        request,
        "assignments/list.html",
        {"course": course, "assignments": assignments, "owner": owner},
    )


@login_required
def assignment_new(request, course_id):
    course = _owner_course(request.user, course_id)
    form = AssignmentForm(
        request.POST or None,
        instance=Assignment(course=course, created_by=request.user),
    )
    form.fields["section"].queryset = course.sections.all()
    if request.method == "POST" and form.is_valid():
        try:
            assignment = create_assignment(
                actor=request.user, course=course, data=form.cleaned_data
            )
        except (PermissionDenied, ValidationError) as error:
            form.add_error(None, error)
        else:
            messages.success(
                request, "Draft assignment created. Publish it when ready."
            )
            return redirect(
                "assignments:detail", course_id=course.id, assignment_id=assignment.id
            )
    return render(request, "assignments/new.html", {"form": form, "course": course})


@login_required
def assignment_publish(request, course_id, assignment_id):
    if request.method != "POST":
        raise Http404
    course = _owner_course(request.user, course_id)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)
    try:
        publish_assignment(actor=request.user, assignment=assignment)
    except ValidationError as error:
        messages.error(request, error.message)
    else:
        messages.success(request, "Assignment published.")
    return redirect(
        "assignments:detail", course_id=course.id, assignment_id=assignment.id
    )


@login_required
def assignment_detail(request, course_id, assignment_id):
    assignment = get_object_or_404(
        Assignment.objects.select_related("course", "section"),
        pk=assignment_id,
        course_id=course_id,
    )
    owner = (
        request.user.role == request.user.Role.INSTRUCTOR
        and assignment.course.instructor_id == request.user.id
    )
    active_student = _active_student(request.user, assignment.course)
    if not owner and not (
        request.user.role == request.user.Role.STUDENT
        and active_student
        and assignment.status == Assignment.Status.PUBLISHED
    ):
        raise Http404
    student_submission = None
    submission_count = None
    if owner:
        submission_count = assignment.submissions.count()
    else:
        student_submission = (
            Submission.objects.filter(assignment=assignment, student=request.user)
            .prefetch_related("versions")
            .first()
        )
        recent_view = ActivityEvent.objects.filter(
            course=assignment.course,
            user=request.user,
            event_type=ActivityEvent.EventType.ASSIGNMENT_VIEWED,
            object_type="Assignment",
            object_id=assignment.id,
            occurred_at__gte=timezone.now() - timedelta(minutes=5),
        ).exists()
        if not recent_view:
            ActivityEvent.objects.create(
                course=assignment.course,
                user=request.user,
                event_type=ActivityEvent.EventType.ASSIGNMENT_VIEWED,
                object_type="Assignment",
                object_id=assignment.id,
            )
    return render(
        request,
        "assignments/detail.html",
        {
            "assignment": assignment,
            "owner": owner,
            "student_submission": student_submission,
            "submission_count": submission_count,
        },
    )


@login_required
def assignment_submit(request, course_id, assignment_id):
    assignment = get_object_or_404(
        Assignment.objects.select_related("course"),
        pk=assignment_id,
        course_id=course_id,
        status=Assignment.Status.PUBLISHED,
    )
    if not _active_student(request.user, assignment.course):
        raise Http404
    form = SubmissionForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            version = submit_first_version(
                actor=request.user,
                assignment=assignment,
                upload=form.cleaned_data["file"],
            )
        except (PermissionDenied, ValidationError) as error:
            form.add_error(None, error)
        else:
            messages.success(
                request,
                "Submission version "
                f"{version.version_number} received at {version.submitted_at}.",
            )
            return redirect(
                "assignments:detail", course_id=course_id, assignment_id=assignment_id
            )
    return render(
        request, "assignments/submit.html", {"assignment": assignment, "form": form}
    )
