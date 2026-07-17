from django import forms

from .models import Material
from .services import ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES

ACCEPTED_FILE_LABELS = ", ".join(
    extension.upper() for extension in sorted(ALLOWED_EXTENSIONS)
)
FILE_HELP_TEXT = (
    f"Accepted: {ACCEPTED_FILE_LABELS}. Maximum {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
)


class MaterialForm(forms.ModelForm):
    file = forms.FileField(help_text=FILE_HELP_TEXT)

    class Meta:
        model = Material
        fields = ("section", "title", "description", "status")


class MaterialVersionForm(forms.Form):
    file = forms.FileField(label="New file version", help_text=FILE_HELP_TEXT)
