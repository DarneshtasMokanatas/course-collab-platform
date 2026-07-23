import uuid

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from .managers import UserManager


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = "STUDENT", "Student"
        INSTRUCTOR = "INSTRUCTOR", "Instructor"

    class MembershipStatus(models.TextChoices):
        NON_MEMBER = "NON_MEMBER", "Non-member"
        MEMBER = "MEMBER", "Member"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    role = models.CharField(max_length=10, choices=Role.choices)
    membership_status = models.CharField(
        max_length=10,
        choices=MembershipStatus.choices,
        default=MembershipStatus.NON_MEMBER,
    )
    display_name = models.CharField(max_length=150)
    REQUIRED_FIELDS = ["email", "display_name", "role"]

    objects = UserManager()

    class Meta:
        db_table = "accounts_user"
        constraints = [
            models.UniqueConstraint(
                Lower("username"), name="accounts_user_username_ci_uniq"
            ),
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_uniq"),
            models.CheckConstraint(
                condition=models.Q(membership_status__in=["NON_MEMBER", "MEMBER"]),
                name="accounts_user_membership_valid",
            ),
        ]

    def clean(self):
        super().clean()
        self.username = self.normalize_username(self.username).strip().lower()
        self.email = self.__class__.objects.normalize_email(self.email).strip().lower()
        self.display_name = self.display_name.strip()

    def save(self, *args, **kwargs):
        self.username = self.normalize_username(self.username).strip().lower()
        self.email = self.__class__.objects.normalize_email(self.email).strip().lower()
        self.display_name = self.display_name.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name


def normalize_skill_name(value):
    return " ".join(value.split())


class Skill(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_skill"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="accounts_skill_name_ci_uniq",
            )
        ]

    def clean(self):
        super().clean()
        self.name = normalize_skill_name(self.name)
        if not self.name:
            raise ValidationError({"name": "Skill name is required."})

    def save(self, *args, **kwargs):
        self.name = normalize_skill_name(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class StudentCollaborationProfile(models.Model):
    class CollaborationMode(models.TextChoices):
        ONLINE = "ONLINE", "Online"
        OFFLINE = "OFFLINE", "Offline"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="collaboration_profile",
    )
    collaboration_mode = models.CharField(
        max_length=7,
        choices=CollaborationMode.choices,
        default=CollaborationMode.ONLINE,
    )
    availability = models.CharField(max_length=300, blank=True)
    skills = models.ManyToManyField(
        Skill,
        through="StudentProfileSkill",
        related_name="student_profiles",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_studentcollaborationprofile"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(collaboration_mode__in=["ONLINE", "OFFLINE"]),
                name="accounts_profile_mode_valid",
            )
        ]

    def clean(self):
        super().clean()
        self.availability = self.availability.strip()
        if self.user_id and self.user.role != User.Role.STUDENT:
            raise ValidationError(
                {"user": "Collaboration profiles belong to students."}
            )

    def save(self, *args, **kwargs):
        self.availability = self.availability.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.display_name}'s collaboration profile"


class StudentProfileSkill(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        StudentCollaborationProfile,
        on_delete=models.CASCADE,
        related_name="skill_links",
    )
    skill = models.ForeignKey(
        Skill,
        on_delete=models.PROTECT,
        related_name="profile_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_studentprofileskill"
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "skill"],
                name="accounts_profile_skill_uniq",
            )
        ]

    def __str__(self):
        return f"{self.profile.user.display_name}: {self.skill.name}"
