"""Context processors for the app."""

from yt_navigator import __version__


def version_context(request):
    """Add version information to the template context.

    Args:
        request: The HTTP request object

    Returns:
        dict: A dictionary containing the application version
    """
    return {"app_version": __version__}


def single_user_context(request):
    """Tell templates whether accounts are disabled (Android app)."""
    from django.conf import settings

    return {"single_user_mode": settings.SINGLE_USER_MODE}
