from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import IntegrityError, transaction
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
    return render(request, "accounts/dashboard.html")
