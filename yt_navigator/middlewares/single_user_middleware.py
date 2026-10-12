"""Middleware that logs everyone in as a single local user (Android app mode)."""

from django.conf import settings
from django.contrib.auth import (
    get_user_model,
    login,
)

LOCAL_USERNAME = "me"


class SingleUserMiddleware:
    """When SINGLE_USER_MODE is on, skip registration/login by logging in a local user automatically."""

    def __init__(self, get_response):
        """Initialize the middleware."""
        self.get_response = get_response

    def __call__(self, request):
        """Log the local user in if nobody is logged in."""
        if settings.SINGLE_USER_MODE and not request.user.is_authenticated:
            user, created = get_user_model().objects.get_or_create(username=LOCAL_USERNAME)
            if created:
                user.set_unusable_password()
                user.save()
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return self.get_response(request)
