from django import forms

from .models import Material


class MaterialForm(forms.ModelForm):
    file = forms.FileField()

    class Meta:
        model = Material
        fields = ("section", "title", "description", "status")


class MaterialVersionForm(forms.Form):
    file = forms.FileField(label="New file version")
