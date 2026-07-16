from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.debug import sensitive_post_parameters

from .forms import IdentityAuthenticationForm, RegistrationForm


@sensitive_post_parameters("password1", "password2")
def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
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
    context = {}
    if request.user.role == request.user.Role.STUDENT:
        from apps.announcements.models import Announcement, AnnouncementRead
        from apps.courses.models import Enrolment

        active_course_ids = Enrolment.objects.filter(
            student=request.user,
            status=Enrolment.Status.ACTIVE,
        ).values("course_id")
        announcements = (
            Announcement.objects.filter(
                course_id__in=active_course_ids,
                status=Announcement.Status.PUBLISHED,
            )
            .select_related("course")
            .annotate(
                is_read=Exists(
                    AnnouncementRead.objects.filter(
                        announcement_id=OuterRef("pk"),
                        student=request.user,
                    )
                )
            )
            .order_by("-published_at")
        )
        context["unread_announcement_count"] = announcements.filter(
            is_read=False
        ).count()
        context["recent_announcements"] = announcements[:5]
    return render(request, "accounts/dashboard.html", context)
