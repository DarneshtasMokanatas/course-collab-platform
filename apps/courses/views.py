from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CourseForm, CourseSectionFormSet
from .models import Course
from .services import (
    SectionData,
    create_course,
    publish_course,
    update_course_and_sections,
)


def _owned_course_or_404(user, course_id):
    course = get_object_or_404(
        Course.objects.prefetch_related("sections"), pk=course_id
    )
    if course.instructor_id != user.id:
        raise Http404
    return course


def _instructor_required(user):
    if user.role != user.Role.INSTRUCTOR:
        raise PermissionDenied


@login_required
def course_list(request):
    _instructor_required(request.user)
    courses = Course.objects.filter(instructor=request.user).order_by("-updated_at")
    return render(request, "courses/course_list.html", {"courses": courses})


@login_required
def course_new(request):
    _instructor_required(request.user)
    form = CourseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            course = create_course(actor=request.user, data=form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(
                request, "Draft course created. Add sections before publishing."
            )
            return redirect("courses:edit", course_id=course.id)
    return render(request, "courses/course_new.html", {"form": form})


@login_required
def course_detail(request, course_id):
    course = _owned_course_or_404(request.user, course_id)
    return render(request, "courses/course_detail.html", {"course": course})


@login_required
def course_edit(request, course_id):
    course = _owned_course_or_404(request.user, course_id)
    form = CourseForm(request.POST or None, instance=course)
    formset = CourseSectionFormSet(
        request.POST or None, instance=course, prefix="sections"
    )
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        sections = [
            SectionData(
                section_id=(
                    None
                    if section_form.instance._state.adding
                    else section_form.instance.pk
                ),
                title=section_form.cleaned_data["title"],
                description=section_form.cleaned_data["description"],
                position=section_form.cleaned_data["ORDER"],
            )
            for section_form in formset.forms
            if section_form.cleaned_data and not section_form.cleaned_data.get("DELETE")
        ]
        try:
            course = update_course_and_sections(
                actor=request.user,
                course=course,
                data=form.cleaned_data,
                sections=sections,
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Course and sections saved.")
            return redirect("courses:detail", course_id=course.id)
    return render(
        request,
        "courses/course_edit.html",
        {"course": course, "form": form, "formset": formset},
    )


@login_required
def course_publish(request, course_id):
    if request.method != "POST":
        raise Http404
    course = _owned_course_or_404(request.user, course_id)
    try:
        publish_course(actor=request.user, course=course)
    except ValidationError as error:
        messages.error(request, error.message)
    else:
        messages.success(request, "Course published.")
    return redirect("courses:detail", course_id=course.id)
