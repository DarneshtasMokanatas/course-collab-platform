from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import (
    AccountLoginView,
    own_profile,
    profile_detail,
    profile_edit,
    register,
)

app_name = "accounts"

urlpatterns = [
    path("register/", register, name="register"),
    path("login/", AccountLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("profile/", own_profile, name="profile"),
    path("profile/edit/", profile_edit, name="profile_edit"),
    path("profiles/<uuid:user_id>/", profile_detail, name="profile_detail"),
]
