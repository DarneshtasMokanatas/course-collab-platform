from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.analytics.models import ActivityEvent
from apps.courses.models import Course, Enrolment

from .forms import AssignmentForm, SubmissionForm
from .models import Assignment, Submission, SubmissionVersion
from .services import (
    create_assignment,
    publish_assignment,
    submit_first_version,
    submit_resubmission,
)


def _owner_course(user, course_id):
    course = get_object_or_404(
        Course.objects.prefetch_related("sections"), pk=course_id
    )
    if not user.is_staff and (
        user.role != user.Role.INSTRUCTOR or course.instructor_id != user.id
    ):
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
    owner = user.is_staff or (
        user.role == user.Role.INSTRUCTOR and course.instructor_id == user.id
    )
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
    owner = request.user.is_staff or (
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
    can_resubmit = False
    if owner:
        submission_count = assignment.submissions.count()
    else:
        student_submission = (
            Submission.objects.filter(assignment=assignment, student=request.user)
            .prefetch_related("versions")
            .first()
        )
        can_resubmit = bool(
            student_submission
            and assignment.status == Assignment.Status.PUBLISHED
            and assignment.allow_resubmission
            and timezone.now() < assignment.due_at
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
            "can_resubmit": can_resubmit,
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
    existing_submission = Submission.objects.filter(
        assignment=assignment,
        student=request.user,
    ).exists()
    if request.method == "GET" and existing_submission:
        if not assignment.allow_resubmission:
            messages.error(request, "Resubmission is not enabled for this assignment.")
            return redirect(
                "assignments:detail",
                course_id=course_id,
                assignment_id=assignment_id,
            )
        if timezone.now() >= assignment.due_at:
            messages.error(
                request,
                "The resubmission deadline has passed.",
            )
            return redirect(
                "assignments:detail",
                course_id=course_id,
                assignment_id=assignment_id,
            )
    form = SubmissionForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            submit_service = (
                submit_resubmission if existing_submission else submit_first_version
            )
            version = submit_service(
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
        request,
        "assignments/submit.html",
        {
            "assignment": assignment,
            "form": form,
            "is_resubmission": existing_submission,
        },
    )


@login_required
def assignment_submissions(request, course_id, assignment_id):
    course = _owner_course(request.user, course_id)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)
    submissions = (
        Submission.objects.filter(assignment=assignment)
        .select_related("student")
        .prefetch_related(
            Prefetch(
                "versions",
                queryset=SubmissionVersion.objects.order_by("version_number"),
                to_attr="ordered_versions",
            )
        )
        .order_by("student__display_name", "student__username")
    )
    page = Paginator(submissions, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "assignments/submission_list.html",
        {"course": course, "assignment": assignment, "page": page},
    )


@login_required
def submission_detail(request, course_id, assignment_id, submission_id):
    course = _owner_course(request.user, course_id)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)
    submission = get_object_or_404(
        Submission.objects.select_related("student").prefetch_related(
            Prefetch(
                "versions",
                queryset=SubmissionVersion.objects.order_by("version_number"),
                to_attr="ordered_versions",
            )
        ),
        pk=submission_id,
        assignment=assignment,
    )
    return render(
        request,
        "assignments/submission_detail.html",
        {
            "course": course,
            "assignment": assignment,
            "submission": submission,
        },
    )


@login_required
def submission_version_download(
    request,
    course_id,
    assignment_id,
    submission_id,
    version_id,
):
    version = get_object_or_404(
        SubmissionVersion.objects.select_related(
            "submission__student",
            "submission__assignment__course",
        ),
        pk=version_id,
        submission_id=submission_id,
        submission__assignment_id=assignment_id,
        submission__assignment__course_id=course_id,
    )
    course = version.submission.assignment.course
    is_owner = (
        request.user.role == request.user.Role.INSTRUCTOR
        and course.instructor_id == request.user.id
    )
    is_student_owner = (
        request.user.role == request.user.Role.STUDENT
        and version.submission.student_id == request.user.id
        and Enrolment.objects.filter(
            course=course,
            student=request.user,
            status=Enrolment.Status.ACTIVE,
        ).exists()
    )
    if not request.user.is_staff and not is_owner and not is_student_owner:
        raise Http404
    try:
        stored_file = default_storage.open(version.storage_key, "rb")
    except (FileNotFoundError, OSError):
        raise Http404 from None
    response = FileResponse(
        stored_file,
        as_attachment=True,
        filename=version.original_filename,
        content_type="application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response
