from django.contrib import admin

from .models import Assignment, GradeRevision, Submission, SubmissionVersion


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "status", "due_at", "max_score")
    list_filter = ("status", "allow_late_submissions", "allow_resubmission")
    search_fields = ("title", "course__code")


class SubmissionVersionInline(admin.TabularInline):
    model = SubmissionVersion
    extra = 0
    readonly_fields = ("submitted_at",)


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("student", "assignment", "created_at")
    search_fields = ("student__username", "assignment__title")
    inlines = (SubmissionVersionInline,)


@admin.register(GradeRevision)
class GradeRevisionAdmin(admin.ModelAdmin):
    list_display = ("submission", "revision_number", "score", "released_at")
    readonly_fields = ("created_at",)
