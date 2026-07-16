from django import forms

from .models import Announcement


class AnnouncementForm(forms.ModelForm):
    publish_now = forms.BooleanField(
        required=False,
        help_text="Publish immediately. Leave unchecked to save a draft.",
    )

    class Meta:
        model = Announcement
        fields = ("title", "body", "is_pinned")
        widgets = {"body": forms.Textarea(attrs={"rows": 8})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields[
            "is_pinned"
        ].help_text = "Pinned announcements stay above the chronological feed."


class AnnouncementEditForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ("title", "body", "is_pinned")
        widgets = {"body": forms.Textarea(attrs={"rows": 8})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields[
            "is_pinned"
        ].help_text = "Pinned announcements stay above the chronological feed."
