from django.contrib.auth.models import UserManager as DjangoUserManager


class UserManager(DjangoUserManager):
    def _create_user(self, username, email, password, **extra_fields):
        username = self.model.normalize_username(username).strip().lower()
        email = self.normalize_email(email).strip().lower()
        if not username:
            raise ValueError("The username is required")
        if not email:
            raise ValueError("The email address is required")
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.full_clean()
        user.save(using=self._db)
        return user
