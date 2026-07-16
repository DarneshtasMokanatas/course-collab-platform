from django.contrib import admin

from .models import Material, MaterialVersion


class MaterialVersionInline(admin.TabularInline):
    model = MaterialVersion
    extra = 0
    can_delete = False
    readonly_fields = (
        "version_number",
        "storage_key",
        "original_filename",
        "content_type",
        "size_bytes",
        "sha256",
        "uploaded_by",
        "created_at",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "section", "status", "published_at")
    list_filter = ("status", "course")
    search_fields = ("title", "course__code")
    inlines = (MaterialVersionInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MaterialVersion)
class MaterialVersionAdmin(admin.ModelAdmin):
    list_display = ("material", "version_number", "original_filename", "created_at")
    search_fields = ("material__title", "original_filename", "sha256")
    readonly_fields = (
        "material",
        "version_number",
        "storage_key",
        "original_filename",
        "content_type",
        "size_bytes",
        "sha256",
        "uploaded_by",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
