from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from apps.accounts.views import dashboard

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("dashboard/", dashboard, name="dashboard"),
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
]
