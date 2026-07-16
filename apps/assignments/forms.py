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
        widgets = {"due_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}

    def clean_allowed_extensions(self):
        extensions = self.cleaned_data["allowed_extensions"]
        return list(
            dict.fromkeys(extension.strip().lower() for extension in extensions)
        )


class SubmissionForm(forms.Form):
    file = forms.FileField()


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
        widget=forms.Textarea,
    )

    def __init__(self, *args, submission, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["submission_version"].queryset = submission.versions.order_by(
            "version_number"
        )
