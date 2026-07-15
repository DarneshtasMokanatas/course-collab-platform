from django.contrib import admin

from .models import Material, MaterialVersion


class MaterialVersionInline(admin.TabularInline):
    model = MaterialVersion
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "section", "status", "published_at")
    list_filter = ("status", "course")
    search_fields = ("title", "course__code")
    inlines = (MaterialVersionInline,)


@admin.register(MaterialVersion)
class MaterialVersionAdmin(admin.ModelAdmin):
    list_display = ("material", "version_number", "original_filename", "created_at")
    search_fields = ("material__title", "original_filename", "sha256")
    readonly_fields = ("created_at",)
