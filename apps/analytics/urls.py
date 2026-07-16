from django.urls import path

from . import views

app_name = "analytics"
urlpatterns = [
    path(
        "courses/<uuid:course_id>/analytics/",
        views.course_analytics,
        name="course",
    ),
]
