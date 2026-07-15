from django.contrib import admin

from .models import ActivityEvent


@admin.register(ActivityEvent)
class ActivityEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "user", "course", "occurred_at")
    list_filter = ("event_type", "course")
    search_fields = ("user__username", "course__code", "object_type")
    readonly_fields = (
        "course",
        "user",
        "event_type",
        "object_type",
        "object_id",
        "metadata",
        "occurred_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
