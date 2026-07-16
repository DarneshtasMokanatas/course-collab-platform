from django.urls import path

from . import views

app_name = "announcements"
urlpatterns = [
    path(
        "courses/<uuid:course_id>/announcements/",
        views.announcement_list,
        name="list",
    ),
    path(
        "courses/<uuid:course_id>/announcements/new/",
        views.announcement_new,
        name="new",
    ),
    path(
        "courses/<uuid:course_id>/announcements/<uuid:announcement_id>/",
        views.announcement_detail,
        name="detail",
    ),
    path(
        "courses/<uuid:course_id>/announcements/<uuid:announcement_id>/edit/",
        views.announcement_edit,
        name="edit",
    ),
    path(
        "courses/<uuid:course_id>/announcements/<uuid:announcement_id>/publish/",
        views.announcement_publish,
        name="publish",
    ),
    path(
        "courses/<uuid:course_id>/announcements/<uuid:announcement_id>/archive/",
        views.announcement_archive,
        name="archive",
    ),
]
