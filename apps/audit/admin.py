from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("action", "object_type", "actor", "course", "occurred_at")
    list_filter = ("action", "object_type", "course")
    search_fields = ("action", "object_type")
    readonly_fields = (
        "actor",
        "action",
        "object_type",
        "object_id",
        "course",
        "metadata",
        "occurred_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
