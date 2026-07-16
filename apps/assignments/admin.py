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
    can_delete = False
    readonly_fields = (
        "version_number",
        "storage_key",
        "original_filename",
        "content_type",
        "size_bytes",
        "sha256",
        "submitted_at",
        "was_late",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("student", "assignment", "created_at")
    search_fields = ("student__username", "assignment__title")
    readonly_fields = ("assignment", "student", "created_at")
    inlines = (SubmissionVersionInline,)

    def has_add_permission(self, request):
        return False


@admin.register(GradeRevision)
class GradeRevisionAdmin(admin.ModelAdmin):
    list_display = ("submission", "revision_number", "score", "released_at")
    readonly_fields = ("created_at",)
