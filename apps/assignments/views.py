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
from apps.analytics.services import record_activity
from apps.courses.models import Course, Enrolment

from .forms import AssignmentForm, GradeRevisionForm, SubmissionForm
from .models import Assignment, GradeRevision, Submission, SubmissionVersion
from .services import (
    create_assignment,
    create_grade_revision,
    publish_assignment,
    release_latest_grade,
    submit_first_version,
    submit_resubmission,
    withdraw_latest_grade_release,
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
    page = Paginator(assignments, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "assignments/list.html",
        {
            "course": course,
            "page": page,
            "owner": owner,
            "now": timezone.now(),
        },
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
    latest_released_grade = None
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
        if student_submission:
            latest_released_grade = (
                student_submission.grade_revisions.filter(released_at__isnull=False)
                .select_related("submission_version")
                .order_by("-revision_number")
                .first()
            )
        record_activity(
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
            "latest_released_grade": latest_released_grade,
            "now": timezone.now(),
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
            "now": timezone.now(),
        },
    )


@login_required
def assignment_submissions(request, course_id, assignment_id):
    course = _owner_course(request.user, course_id)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)
    submissions = Submission.objects.filter(assignment=assignment).prefetch_related(
        Prefetch(
            "versions",
            queryset=SubmissionVersion.objects.order_by("version_number"),
            to_attr="ordered_versions",
        ),
        Prefetch(
            "grade_revisions",
            queryset=GradeRevision.objects.order_by("revision_number"),
            to_attr="ordered_grade_revisions",
        ),
    )
    enrolments = (
        Enrolment.objects.filter(
            course=course,
            status=Enrolment.Status.ACTIVE,
        )
        .select_related("student")
        .prefetch_related(
            Prefetch(
                "student__submissions",
                queryset=submissions,
                to_attr="assignment_submissions",
            )
        )
        .order_by("student__display_name", "student__username")
    )
    page = Paginator(enrolments, 25).get_page(request.GET.get("page"))
    rows = []
    for enrolment in page.object_list:
        student_submissions = enrolment.student.assignment_submissions
        submission = student_submissions[0] if student_submissions else None
        latest_version = None
        status = "MISSING"
        if submission:
            latest_version = submission.ordered_versions[-1]
            released_revisions = [
                revision
                for revision in submission.ordered_grade_revisions
                if revision.released_at is not None
            ]
            if released_revisions:
                status = "GRADED"
            elif latest_version.was_late:
                status = "LATE"
            else:
                status = "SUBMITTED"
        rows.append(
            {
                "student": enrolment.student,
                "submission": submission,
                "latest_version": latest_version,
                "status": status,
            }
        )
    return render(
        request,
        "assignments/submission_list.html",
        {
            "course": course,
            "assignment": assignment,
            "page": page,
            "rows": rows,
        },
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
            ),
            Prefetch(
                "grade_revisions",
                queryset=GradeRevision.objects.select_related(
                    "submission_version", "graded_by"
                ).order_by("revision_number"),
                to_attr="ordered_grade_revisions",
            ),
        ),
        pk=submission_id,
        assignment=assignment,
    )
    latest_revision = (
        submission.ordered_grade_revisions[-1]
        if submission.ordered_grade_revisions
        else None
    )
    has_released_grade = any(
        revision.released_at is not None
        for revision in submission.ordered_grade_revisions
    )
    return render(
        request,
        "assignments/submission_detail.html",
        {
            "course": course,
            "assignment": assignment,
            "submission": submission,
            "latest_revision": latest_revision,
            "has_released_grade": has_released_grade,
        },
    )


@login_required
def grade_submission(request, course_id, assignment_id, submission_id):
    course = _owner_course(request.user, course_id)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)
    submission = get_object_or_404(
        Submission.objects.select_related("student").prefetch_related("versions"),
        pk=submission_id,
        assignment=assignment,
    )
    initial = {}
    latest_revision = submission.grade_revisions.order_by("-revision_number").first()
    if latest_revision:
        initial = {
            "submission_version": latest_revision.submission_version_id,
            "score": latest_revision.score,
            "feedback": latest_revision.feedback,
        }
    elif submission.versions.exists():
        initial["submission_version"] = submission.versions.order_by(
            "-version_number"
        ).first()
    form = GradeRevisionForm(
        request.POST or None,
        submission=submission,
        initial=initial,
    )
    if request.method == "POST" and form.is_valid():
        try:
            revision = create_grade_revision(
                actor=request.user,
                submission=submission,
                submission_version=form.cleaned_data["submission_version"],
                score=form.cleaned_data["score"],
                feedback=form.cleaned_data["feedback"],
            )
        except (PermissionDenied, ValidationError) as error:
            if isinstance(error, ValidationError) and hasattr(error, "message_dict"):
                for field, field_errors in error.message_dict.items():
                    form.add_error(
                        field if field in form.fields else None,
                        field_errors,
                    )
            else:
                form.add_error(None, error)
        else:
            messages.success(
                request,
                f"Grade revision {revision.revision_number} saved as a draft.",
            )
            return redirect(
                "assignments:submission_detail",
                course_id=course.id,
                assignment_id=assignment.id,
                submission_id=submission.id,
            )
    return render(
        request,
        "assignments/grade.html",
        {
            "course": course,
            "assignment": assignment,
            "submission": submission,
            "form": form,
        },
    )


@login_required
def release_grade(request, course_id, assignment_id, submission_id):
    if request.method != "POST":
        raise Http404
    course = _owner_course(request.user, course_id)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)
    submission = get_object_or_404(
        Submission,
        pk=submission_id,
        assignment=assignment,
    )
    try:
        revision = release_latest_grade(actor=request.user, submission=submission)
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(
            request,
            f"Grade revision {revision.revision_number} released to the student.",
        )
    return redirect(
        "assignments:submission_detail",
        course_id=course.id,
        assignment_id=assignment.id,
        submission_id=submission.id,
    )


@login_required
def withdraw_grade_release(request, course_id, assignment_id, submission_id):
    if request.method != "POST":
        raise Http404
    course = _owner_course(request.user, course_id)
    assignment = get_object_or_404(Assignment, pk=assignment_id, course=course)
    submission = get_object_or_404(
        Submission,
        pk=submission_id,
        assignment=assignment,
    )
    try:
        revision = withdraw_latest_grade_release(
            actor=request.user,
            submission=submission,
        )
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(
            request,
            f"Release of grade revision {revision.revision_number} withdrawn.",
        )
    return redirect(
        "assignments:submission_detail",
        course_id=course.id,
        assignment_id=assignment.id,
        submission_id=submission.id,
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
