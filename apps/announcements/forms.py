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


class AnnouncementEditForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ("title", "body", "is_pinned")
