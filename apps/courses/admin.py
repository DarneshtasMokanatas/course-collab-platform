from django.contrib import admin

from .models import Course, CourseSection, Enrolment


class CourseSectionInline(admin.TabularInline):
    model = CourseSection
    extra = 0
    can_delete = False
    readonly_fields = ("title", "description", "position", "created_at", "updated_at")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "instructor", "status", "enrolment_mode")
    list_filter = ("status", "enrolment_mode")
    search_fields = ("code", "title", "instructor__display_name")
    inlines = (CourseSectionInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Enrolment)
class EnrolmentAdmin(admin.ModelAdmin):
    list_display = ("student", "course", "status", "enrolled_at")
    list_filter = ("status", "course")
    search_fields = ("student__username", "student__email", "course__code")
    readonly_fields = (
        "course",
        "student",
        "status",
        "enrolled_at",
        "withdrawn_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
