from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.core.exceptions import ValidationError

from apps.audit.models import AuditEvent

from .models import Skill, StudentCollaborationProfile, StudentProfileSkill, User


class UserRoleAdminForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"

    def clean_role(self):
        role = self.cleaned_data["role"]
        if not self.instance.pk:
            return role
        original_role = (
            User.objects.filter(pk=self.instance.pk)
            .values_list("role", flat=True)
            .first()
        )
        if original_role == role:
            return role
        if self.instance.owned_courses.exists() or self.instance.enrolments.exists():
            raise ValidationError(
                "Resolve owned courses or enrolments before changing this role."
            )
        return role


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = UserRoleAdminForm
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Application role",
            {"fields": ("role", "membership_status", "display_name")},
        ),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (
            "Application role",
            {"fields": ("email", "role", "display_name")},
        ),
    )
    list_display = (
        "username",
        "email",
        "display_name",
        "role",
        "membership_status",
        "is_active",
    )
    list_filter = ("role", "membership_status", "is_active", "is_staff")
    search_fields = ("username", "email", "display_name")

    def save_model(self, request, obj, form, change):
        previous_role = None
        previous_membership = None
        if change:
            previous = (
                User.objects.filter(pk=obj.pk)
                .values("role", "membership_status")
                .first()
            )
            if previous:
                previous_role = previous["role"]
                previous_membership = previous["membership_status"]
        super().save_model(request, obj, form, change)
        if obj.role == User.Role.STUDENT:
            StudentCollaborationProfile.objects.get_or_create(user=obj)
        elif previous_role == User.Role.STUDENT:
            StudentCollaborationProfile.objects.filter(user=obj).delete()
        if previous_role and previous_role != obj.role:
            AuditEvent.objects.create(
                actor=request.user,
                action="USER_ROLE_CHANGED",
                object_type="User",
                object_id=obj.id,
                metadata={"from": previous_role, "to": obj.role},
            )
        if previous_membership and previous_membership != obj.membership_status:
            AuditEvent.objects.create(
                actor=request.user,
                action="USER_MEMBERSHIP_CHANGED",
                object_type="User",
                object_id=obj.id,
                metadata={
                    "from": previous_membership,
                    "to": obj.membership_status,
                },
            )


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at", "updated_at")
    search_fields = ("name",)


class StudentProfileSkillInline(admin.TabularInline):
    model = StudentProfileSkill
    extra = 0


@admin.register(StudentCollaborationProfile)
class StudentCollaborationProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "collaboration_mode", "availability", "updated_at")
    list_filter = ("collaboration_mode",)
    search_fields = ("user__display_name", "user__username")
    readonly_fields = ("user", "created_at", "updated_at")
    inlines = (StudentProfileSkillInline,)

    def has_delete_permission(self, request, obj=None):
        return False
