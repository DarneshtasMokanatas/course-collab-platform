from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class UsernameOrEmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        identity = username or kwargs.get("email")
        if not identity or password is None:
            return None
        user_model = get_user_model()
        candidates = list(
            user_model.objects.filter(
                Q(username__iexact=identity.strip()) | Q(email__iexact=identity.strip())
            )
        )
        if not candidates:
            user_model().set_password(password)
            return None
        authenticated = [
            user
            for user in candidates
            if user.check_password(password) and self.user_can_authenticate(user)
        ]
        if len(authenticated) == 1:
            return authenticated[0]
        return None
