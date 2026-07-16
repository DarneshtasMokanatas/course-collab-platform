from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from apps.analytics.models import ActivityEvent
from apps.analytics.services import record_activity
from apps.courses.models import Course, Enrolment

from .forms import AnnouncementEditForm, AnnouncementForm
from .models import Announcement, AnnouncementRead
from .services import (
    archive_announcement,
    create_announcement,
    edit_announcement,
    mark_announcement_read,
    publish_announcement,
)


def _course_access(user, course_id):
    course = get_object_or_404(Course, pk=course_id)
    owner = user.is_staff or (
        user.role == user.Role.INSTRUCTOR and course.instructor_id == user.id
    )
    enrolled = (
        user.role == user.Role.STUDENT
        and Enrolment.objects.filter(
            course=course,
            student=user,
            status=Enrolment.Status.ACTIVE,
        ).exists()
    )
    if not owner and not enrolled:
        raise Http404
    return course, owner


def _owner_course(user, course_id):
    course, owner = _course_access(user, course_id)
    if not owner:
        raise Http404
    return course


@login_required
def announcement_list(request, course_id):
    course, owner = _course_access(request.user, course_id)
    announcements = course.announcements.select_related("author")
    if owner:
        announcements = announcements.order_by(
            "-is_pinned", "-published_at", "-created_at"
        )
    else:
        announcements = (
            announcements.filter(status=Announcement.Status.PUBLISHED)
            .annotate(
                is_read=Exists(
                    AnnouncementRead.objects.filter(
                        announcement_id=OuterRef("pk"),
                        student=request.user,
                    )
                )
            )
            .order_by("-is_pinned", "-published_at")
        )
    page = Paginator(announcements, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "announcements/list.html",
        {"course": course, "page": page, "owner": owner},
    )


@login_required
def announcement_new(request, course_id):
    course = _owner_course(request.user, course_id)
    form = AnnouncementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = {
            field: form.cleaned_data[field] for field in ("title", "body", "is_pinned")
        }
        try:
            announcement = create_announcement(
                actor=request.user,
                course=course,
                data=data,
                publish_now=form.cleaned_data["publish_now"],
            )
        except (PermissionDenied, ValidationError) as error:
            form.add_error(None, error)
        else:
            messages.success(
                request,
                "Announcement published."
                if announcement.status == Announcement.Status.PUBLISHED
                else "Draft announcement saved.",
            )
            return redirect(
                "announcements:detail",
                course_id=course.id,
                announcement_id=announcement.id,
            )
    return render(
        request,
        "announcements/form.html",
        {"course": course, "form": form, "heading": "New announcement"},
    )


@login_required
def announcement_detail(request, course_id, announcement_id):
    course, owner = _course_access(request.user, course_id)
    queryset = Announcement.objects.select_related("author")
    if not owner:
        queryset = queryset.filter(status=Announcement.Status.PUBLISHED)
    announcement = get_object_or_404(
        queryset,
        pk=announcement_id,
        course=course,
    )
    if not owner:
        mark_announcement_read(student=request.user, announcement=announcement)
        record_activity(
            course=course,
            user=request.user,
            event_type=ActivityEvent.EventType.ANNOUNCEMENT_VIEWED,
            object_type="Announcement",
            object_id=announcement.id,
        )
    return render(
        request,
        "announcements/detail.html",
        {"course": course, "announcement": announcement, "owner": owner},
    )


@login_required
def announcement_edit(request, course_id, announcement_id):
    course = _owner_course(request.user, course_id)
    announcement = get_object_or_404(Announcement, pk=announcement_id, course=course)
    form = AnnouncementEditForm(request.POST or None, instance=announcement)
    if request.method == "POST" and form.is_valid():
        try:
            announcement = edit_announcement(
                actor=request.user,
                announcement=announcement,
                data=form.cleaned_data,
            )
        except (PermissionDenied, ValidationError) as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Announcement updated.")
            return redirect(
                "announcements:detail",
                course_id=course.id,
                announcement_id=announcement.id,
            )
    return render(
        request,
        "announcements/form.html",
        {"course": course, "form": form, "heading": "Edit announcement"},
    )


@login_required
def announcement_publish(request, course_id, announcement_id):
    if request.method != "POST":
        raise Http404
    course = _owner_course(request.user, course_id)
    announcement = get_object_or_404(Announcement, pk=announcement_id, course=course)
    try:
        publish_announcement(actor=request.user, announcement=announcement)
    except ValidationError as error:
        messages.error(request, error.message)
    else:
        messages.success(request, "Announcement published.")
    return redirect(
        "announcements:detail",
        course_id=course.id,
        announcement_id=announcement.id,
    )


@login_required
def announcement_archive(request, course_id, announcement_id):
    if request.method != "POST":
        raise Http404
    course = _owner_course(request.user, course_id)
    announcement = get_object_or_404(Announcement, pk=announcement_id, course=course)
    archive_announcement(actor=request.user, announcement=announcement)
    messages.success(request, "Announcement archived.")
    return redirect("announcements:list", course_id=course.id)
