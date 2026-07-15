from django import forms

from .models import Assignment


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = (
            "section",
            "title",
            "instructions",
            "due_at",
            "max_score",
            "max_upload_bytes",
            "allowed_extensions",
            "allow_late_submissions",
            "allow_resubmission",
        )
        widgets = {"due_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}

    def clean_allowed_extensions(self):
        extensions = self.cleaned_data["allowed_extensions"]
        return list(
            dict.fromkeys(extension.strip().lower() for extension in extensions)
        )


class SubmissionForm(forms.Form):
    file = forms.FileField()
