from django.urls import path

from . import views

app_name = "assignments"
urlpatterns = [
    path("courses/<uuid:course_id>/assignments/", views.assignment_list, name="list"),
    path("courses/<uuid:course_id>/assignments/new/", views.assignment_new, name="new"),
    path(
        "courses/<uuid:course_id>/assignments/<uuid:assignment_id>/publish/",
        views.assignment_publish,
        name="publish",
    ),
    path(
        "courses/<uuid:course_id>/assignments/<uuid:assignment_id>/",
        views.assignment_detail,
        name="detail",
    ),
    path(
        "courses/<uuid:course_id>/assignments/<uuid:assignment_id>/submit/",
        views.assignment_submit,
        name="submit",
    ),
]
