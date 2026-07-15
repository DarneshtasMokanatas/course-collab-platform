from django.urls import path

from . import views

app_name = "courses"

urlpatterns = [
    path("", views.course_list, name="list"),
    path("new/", views.course_new, name="new"),
    path("<uuid:course_id>/", views.course_detail, name="detail"),
    path("<uuid:course_id>/edit/", views.course_edit, name="edit"),
    path("<uuid:course_id>/publish/", views.course_publish, name="publish"),
]
