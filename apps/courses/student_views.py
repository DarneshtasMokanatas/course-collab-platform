from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .enrolment_services import enrol_student
from .models import Course, Enrolment


@login_required
def course_portal(request):
    if request.user.role == request.user.Role.STUDENT:
        courses = Course.objects.filter(
            status=Course.Status.PUBLISHED,
            enrolment_mode=Course.EnrolmentMode.OPEN,
        ).order_by("code")
        return render(request, "courses/catalogue.html", {"courses": courses})
    return render(
        request,
        "courses/course_list.html",
        {
            "courses": Course.objects.filter(instructor=request.user).order_by(
                "-updated_at"
            )
        },
    )


@login_required
def course_detail_portal(request, course_id):
    course = get_object_or_404(
        Course.objects.prefetch_related("sections"), pk=course_id
    )
    can_manage = course.instructor_id == request.user.id
    enrolled = (
        request.user.role == request.user.Role.STUDENT
        and Enrolment.objects.filter(
            course=course, student=request.user, status=Enrolment.Status.ACTIVE
        ).exists()
    )
    if not can_manage and not enrolled:
        raise Http404
    return render(
        request,
        "courses/course_detail.html"
        if can_manage
        else "courses/student_course_detail.html",
        {"course": course, "can_manage": can_manage},
    )


@login_required
def course_enrol(request, course_id):
    if request.method != "POST":
        raise Http404
    course = get_object_or_404(Course, pk=course_id)
    try:
        enrol_student(actor=request.user, course=course)
    except PermissionDenied as error:
        raise Http404 from error
    messages.success(request, "You are enrolled in this course.")
    return redirect("courses:detail", course_id=course.id)
