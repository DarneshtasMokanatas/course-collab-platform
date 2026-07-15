from django.contrib import admin

from .models import Course, CourseSection, Enrolment


class CourseSectionInline(admin.TabularInline):
    model = CourseSection
    extra = 0


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "instructor", "status", "enrolment_mode")
    list_filter = ("status", "enrolment_mode")
    search_fields = ("code", "title", "instructor__display_name")
    inlines = (CourseSectionInline,)


@admin.register(Enrolment)
class EnrolmentAdmin(admin.ModelAdmin):
    list_display = ("student", "course", "status", "enrolled_at")
    list_filter = ("status", "course")
    search_fields = ("student__username", "student__email", "course__code")
