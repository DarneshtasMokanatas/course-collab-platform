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
    path(
        "courses/<uuid:course_id>/assignments/<uuid:assignment_id>/submissions/",
        views.assignment_submissions,
        name="submission_list",
    ),
    path(
        "courses/<uuid:course_id>/assignments/<uuid:assignment_id>/"
        "submissions/<uuid:submission_id>/",
        views.submission_detail,
        name="submission_detail",
    ),
    path(
        "courses/<uuid:course_id>/assignments/<uuid:assignment_id>/"
        "submissions/<uuid:submission_id>/grade/",
        views.grade_submission,
        name="grade",
    ),
    path(
        "courses/<uuid:course_id>/assignments/<uuid:assignment_id>/"
        "submissions/<uuid:submission_id>/release-grade/",
        views.release_grade,
        name="release_grade",
    ),
    path(
        "courses/<uuid:course_id>/assignments/<uuid:assignment_id>/"
        "submissions/<uuid:submission_id>/withdraw-grade/",
        views.withdraw_grade_release,
        name="withdraw_grade",
    ),
    path(
        "courses/<uuid:course_id>/assignments/<uuid:assignment_id>/"
        "submissions/<uuid:submission_id>/versions/<uuid:version_id>/download/",
        views.submission_version_download,
        name="submission_version_download",
    ),
]
