from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from apps.analytics.models import ActivityEvent
from apps.analytics.services import record_activity
from apps.courses.models import Course

from .forms import MaterialForm, MaterialVersionForm
from .models import Material, MaterialVersion
from .services import add_material_version, can_download, create_material


def _owner_course(user, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if not user.is_staff and (
        user.role != user.Role.INSTRUCTOR or course.instructor_id != user.id
    ):
        raise Http404
    return course


@login_required
def material_list(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    owner = request.user.is_staff or (
        request.user.role == request.user.Role.INSTRUCTOR
        and course.instructor_id == request.user.id
    )
    if not owner and not can_download(request.user, Material(course=course)):
        raise Http404
    materials = (
        course.materials.filter(status=Material.Status.PUBLISHED)
        if not owner
        else course.materials.all()
    )
    return render(
        request,
        "materials/history_list.html",
        {"course": course, "materials": materials, "owner": owner},
    )


@login_required
def material_new(request, course_id):
    course = _owner_course(request.user, course_id)
    form = MaterialForm(request.POST or None, request.FILES or None)
    form.fields["section"].queryset = course.sections.all()
    if request.method == "POST" and form.is_valid():
        try:
            create_material(
                actor=request.user,
                course=course,
                data={
                    key: form.cleaned_data[key]
                    for key in ("section", "title", "description", "status")
                },
                upload=form.cleaned_data["file"],
            )
        except (PermissionDenied, ValidationError) as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Material and version 1 uploaded.")
            return redirect("materials:list", course_id=course.id)
    return render(request, "materials/new.html", {"course": course, "form": form})


@login_required
def material_version_new(request, course_id, material_id):
    course = _owner_course(request.user, course_id)
    material = get_object_or_404(Material, pk=material_id, course=course)
    form = MaterialVersionForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            add_material_version(
                actor=request.user, material=material, upload=form.cleaned_data["file"]
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "New material version uploaded.")
            return redirect("materials:list", course_id=course.id)
    return render(
        request,
        "materials/version_new.html",
        {"course": course, "material": material, "form": form},
    )


@login_required
def material_download(request, course_id, material_id, version_id):
    material = get_object_or_404(
        Material.objects.select_related("course"), pk=material_id, course_id=course_id
    )
    version = get_object_or_404(MaterialVersion, pk=version_id, material=material)
    if material.status != Material.Status.PUBLISHED or not can_download(
        request.user, material
    ):
        raise Http404
    try:
        stored_file = default_storage.open(version.storage_key, "rb")
    except (FileNotFoundError, OSError):
        raise Http404 from None
    record_activity(
        course=material.course,
        user=request.user,
        event_type=ActivityEvent.EventType.MATERIAL_VIEWED,
        object_type="Material",
        object_id=material.id,
    )
    record_activity(
        course=material.course,
        user=request.user,
        event_type=ActivityEvent.EventType.MATERIAL_DOWNLOADED,
        object_type="MaterialVersion",
        object_id=version.id,
    )
    response = FileResponse(
        stored_file,
        as_attachment=True,
        filename=version.original_filename,
        content_type="application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response
