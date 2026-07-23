from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.debug import sensitive_post_parameters

from .dashboard_queries import (
    instructor_dashboard_context,
    student_dashboard_context,
)
from .forms import (
    CollaborationProfileForm,
    IdentityAuthenticationForm,
    RegistrationForm,
)
from .models import StudentCollaborationProfile, User
from .services import (
    can_view_collaboration_profile,
    create_student_collaboration_profile,
    update_collaboration_profile,
)


@sensitive_post_parameters("password1", "password2")
def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
                if user.role == User.Role.STUDENT:
                    create_student_collaboration_profile(user=user)
        except IntegrityError:
            form.add_error(None, "An account with that identity already exists.")
        else:
            login(request, user)
            messages.success(request, "Your account is ready.")
            return redirect("dashboard")
    return render(request, "accounts/register.html", {"form": form})


class AccountLoginView(LoginView):
    authentication_form = IdentityAuthenticationForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return self.get_redirect_url() or reverse_lazy("dashboard")


@login_required
def dashboard(request):
    if request.user.role == request.user.Role.STUDENT:
        context = student_dashboard_context(request.user)
    else:
        context = instructor_dashboard_context(request.user)
    return render(request, "accounts/dashboard.html", context)


@login_required
def own_profile(request):
    if request.user.role != User.Role.STUDENT:
        raise Http404
    return redirect("accounts:profile_detail", user_id=request.user.id)


@login_required
def profile_detail(request, user_id):
    target = get_object_or_404(User, pk=user_id, role=User.Role.STUDENT)
    if not can_view_collaboration_profile(actor=request.user, target=target):
        raise Http404
    profile = get_object_or_404(
        StudentCollaborationProfile.objects.select_related("user").prefetch_related(
            "skills"
        ),
        user=target,
    )
    return render(
        request,
        "accounts/profile_detail.html",
        {
            "profile": profile,
            "is_own_profile": request.user.id == target.id,
        },
    )


@login_required
def profile_edit(request):
    if request.user.role != User.Role.STUDENT:
        raise Http404
    profile = get_object_or_404(
        StudentCollaborationProfile.objects.select_related("user").prefetch_related(
            "skills"
        ),
        user=request.user,
    )
    form = CollaborationProfileForm(request.POST or None, profile=profile)
    if request.method == "POST" and form.is_valid():
        try:
            update_collaboration_profile(
                actor=request.user,
                profile=profile,
                collaboration_mode=form.cleaned_data["collaboration_mode"],
                availability=form.cleaned_data["availability"],
                selected_skills=form.cleaned_data["skills"],
                new_skill_names=form.cleaned_data["new_skills"],
            )
        except (IntegrityError, ValidationError) as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Your collaboration profile was updated.")
            return redirect("accounts:profile_detail", user_id=request.user.id)
    return render(
        request,
        "accounts/profile_form.html",
        {"form": form, "profile": profile},
    )
