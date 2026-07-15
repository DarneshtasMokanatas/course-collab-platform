from django.contrib import admin

from .models import Announcement, AnnouncementRead


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "status", "is_pinned", "published_at")
    list_filter = ("status", "is_pinned", "course")
    search_fields = ("title", "body", "course__code")


@admin.register(AnnouncementRead)
class AnnouncementReadAdmin(admin.ModelAdmin):
    list_display = ("announcement", "student", "read_at")
    search_fields = ("announcement__title", "student__username")
