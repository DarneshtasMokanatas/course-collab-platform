from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import Course, CourseSection


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ("code", "title", "description", "syllabus", "enrolment_mode")

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class CourseSectionForm(forms.ModelForm):
    class Meta:
        model = CourseSection
        fields = ("title", "description")


class BaseCourseSectionFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        positions = []
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            position = form.cleaned_data.get("ORDER")
            if position is None or position < 1:
                raise forms.ValidationError(
                    "Each section needs an order of 1 or greater."
                )
            positions.append(position)
        if len(positions) != len(set(positions)):
            raise forms.ValidationError("Each section order must be unique.")


CourseSectionFormSet = inlineformset_factory(
    Course,
    CourseSection,
    form=CourseSectionForm,
    formset=BaseCourseSectionFormSet,
    extra=1,
    can_delete=True,
    can_order=True,
)
