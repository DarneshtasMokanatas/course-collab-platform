from django.apps import apps
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import transaction


class UserManager(DjangoUserManager):
    def _create_user(self, username, email, password, **extra_fields):
        username = self.model.normalize_username(username).strip().lower()
        email = self.normalize_email(email).strip().lower()
        if not username:
            raise ValueError("The username is required")
        if not email:
            raise ValueError("The email address is required")
        with transaction.atomic(using=self._db):
            user = self.model(username=username, email=email, **extra_fields)
            user.set_password(password)
            user.full_clean()
            user.save(using=self._db)
            if user.role == user.Role.STUDENT:
                profile_model = apps.get_model(
                    "accounts", "StudentCollaborationProfile"
                )
                profile_model.objects.using(self._db).create(user=user)
        return user
