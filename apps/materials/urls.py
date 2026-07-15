from django.urls import path

from . import views

app_name = "materials"
urlpatterns = [
    path("courses/<uuid:course_id>/materials/", views.material_list, name="list"),
    path("courses/<uuid:course_id>/materials/new/", views.material_new, name="new"),
    path(
        "courses/<uuid:course_id>/materials/<uuid:material_id>/versions/new/",
        views.material_version_new,
        name="version_new",
    ),
    path(
        "courses/<uuid:course_id>/materials/<uuid:material_id>/versions/<uuid:version_id>/download/",
        views.material_download,
        name="download",
    ),
]
