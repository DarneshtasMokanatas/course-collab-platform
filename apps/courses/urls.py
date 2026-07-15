from django.urls import path

from . import student_views, views

app_name = "courses"

urlpatterns = [
    path("", student_views.course_portal, name="list"),
    path("new/", views.course_new, name="new"),
    path("<uuid:course_id>/", student_views.course_detail_portal, name="detail"),
    path("<uuid:course_id>/edit/", views.course_edit, name="edit"),
    path("<uuid:course_id>/publish/", views.course_publish, name="publish"),
    path("<uuid:course_id>/enrol/", student_views.course_enrol, name="enrol"),
]
