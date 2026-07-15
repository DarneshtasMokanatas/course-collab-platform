import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower

from .managers import UserManager


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = "STUDENT", "Student"
        INSTRUCTOR = "INSTRUCTOR", "Instructor"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    role = models.CharField(max_length=10, choices=Role.choices)
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
