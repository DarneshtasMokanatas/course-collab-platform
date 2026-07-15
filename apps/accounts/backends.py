from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class UsernameOrEmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        identity = username or kwargs.get("email")
        if not identity or password is None:
            return None
        user_model = get_user_model()
        try:
            user = user_model.objects.get(
                Q(username__iexact=identity.strip()) | Q(email__iexact=identity.strip())
            )
        except (user_model.DoesNotExist, user_model.MultipleObjectsReturned):
            user_model().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
