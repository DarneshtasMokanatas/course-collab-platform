from django import forms

from .models import Assignment, SubmissionVersion


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
        widgets = {
            "instructions": forms.Textarea(attrs={"rows": 8}),
            "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "allowed_extensions": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields[
            "max_upload_bytes"
        ].help_text = "Enter the maximum upload size in bytes."
        self.fields[
            "allowed_extensions"
        ].help_text = 'Enter a JSON list such as ["pdf", "docx", "zip"].'
        self.fields[
            "allow_late_submissions"
        ].help_text = "Applies only to a student's first submission after the deadline."
        self.fields["allow_resubmission"].help_text = (
            "New versions are accepted only while the server time is "
            "before the deadline."
        )

    def clean_allowed_extensions(self):
        extensions = self.cleaned_data["allowed_extensions"]
        return list(
            dict.fromkeys(extension.strip().lower() for extension in extensions)
        )


class SubmissionForm(forms.Form):
    file = forms.FileField(
        help_text="Choose one file that matches the assignment rules.",
    )


class GradeRevisionForm(forms.Form):
    submission_version = forms.ModelChoiceField(
        queryset=SubmissionVersion.objects.none(),
        label="Submission version",
    )
    score = forms.DecimalField(
        min_value=0,
        max_digits=8,
        decimal_places=2,
    )
    feedback = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 7}),
    )

    def __init__(self, *args, submission, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["submission_version"].queryset = submission.versions.order_by(
            "version_number"
        )
