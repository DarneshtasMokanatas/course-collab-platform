from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db.models import Q

from .models import Skill, StudentCollaborationProfile, User, normalize_skill_name


class RegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "display_name", "role")
        widgets = {
            "username": forms.TextInput(attrs={"autocomplete": "username"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "display_name": forms.TextInput(attrs={"autocomplete": "name"}),
            "role": forms.RadioSelect(attrs={"aria-describedby": "id_role_helptext"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = User.Role.choices
        self.fields["role"].help_text = (
            "Students enrol and submit coursework. "
            "Instructors create and manage courses."
        )
        self.fields["password1"].widget.attrs["autocomplete"] = "new-password"
        self.fields["password2"].widget.attrs["autocomplete"] = "new-password"

    def clean_username(self):
        username = self.cleaned_data["username"].strip().lower()
        if User.objects.filter(
            Q(username__iexact=username) | Q(email__iexact=username)
        ).exists():
            raise forms.ValidationError(
                "That username or email identity is already in use."
            )
        return username

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"]).strip().lower()
        if User.objects.filter(
            Q(email__iexact=email) | Q(username__iexact=email)
        ).exists():
            raise forms.ValidationError(
                "That username or email identity is already in use."
            )
        return email

    def clean_display_name(self):
        display_name = self.cleaned_data["display_name"].strip()
        if not display_name:
            raise forms.ValidationError("Display name is required.")
        return display_name


class IdentityAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label="Username or email", max_length=254)
    error_messages = {
        "invalid_login": "Please enter a correct username or email and password.",
        "inactive": "This account is inactive.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs["autocomplete"] = "username"
        self.fields["password"].widget.attrs["autocomplete"] = "current-password"


class CollaborationProfileForm(forms.Form):
    collaboration_mode = forms.ChoiceField(
        choices=StudentCollaborationProfile.CollaborationMode.choices,
        label="Preferred collaboration mode",
        help_text=(
            "Choose whether you generally prefer to collaborate online or offline."
        ),
    )
    availability = forms.CharField(
        required=False,
        max_length=300,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Example: Weekdays after 6 PM",
            }
        ),
        help_text=(
            "Describe when you are usually available in 300 characters or fewer. "
            "For example: Saturday mornings."
        ),
    )
    skills = forms.ModelMultipleChoiceField(
        queryset=Skill.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Existing skills or expertise",
        help_text="Select every existing skill that applies to you.",
    )
    new_skills = forms.CharField(
        required=False,
        max_length=809,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Python, Academic writing, Public speaking",
            }
        ),
        label="Add new skills",
        help_text=(
            "Enter up to 10 skill names separated by commas or new lines. "
            "Each name may contain up to 80 characters."
        ),
    )

    def __init__(self, *args, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile
        self.fields["skills"].queryset = Skill.objects.order_by("name")
        if not self.is_bound:
            self.initial.update(
                {
                    "collaboration_mode": profile.collaboration_mode,
                    "availability": profile.availability,
                    "skills": profile.skills.all(),
                }
            )

    def clean_availability(self):
        return self.cleaned_data["availability"].strip()

    def clean_new_skills(self):
        raw_value = self.cleaned_data["new_skills"].replace("\n", ",")
        names = [normalize_skill_name(value) for value in raw_value.split(",")]
        names = [name for name in names if name]
        if len(names) > 10:
            raise forms.ValidationError("Add no more than 10 new skills at a time.")
        if any(len(name) > 80 for name in names):
            raise forms.ValidationError(
                "Each new skill name must contain 80 characters or fewer."
            )
        deduplicated = {}
        for name in names:
            deduplicated.setdefault(name.casefold(), name)
        return list(deduplicated.values())

    def clean(self):
        cleaned_data = super().clean()
        selected = cleaned_data.get("skills")
        new_skills = cleaned_data.get("new_skills", [])
        if selected is not None and len(selected) + len(new_skills) > 25:
            raise forms.ValidationError(
                "Choose no more than 25 skills for one profile."
            )
        return cleaned_data
