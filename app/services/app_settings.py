"""User-editable settings (API keys) stored in the database, falling back to built-in defaults.

The defaults come from Django settings / environment variables (in the Android app: keys baked in at build time).
"""

from asgiref.sync import sync_to_async
from django.conf import settings

from app.models import AppSetting

EDITABLE_KEYS = {
    "GROQ_API_KEY": "Groq API key",
    "COHERE_API_KEY": "Cohere API key",
}


def get_default(name: str) -> str:
    """Return the built-in value of a setting."""
    return getattr(settings, name, None) or ""


def get_override(name: str) -> str:
    """Return the value saved by the user, or an empty string."""
    return AppSetting.objects.filter(key=name).values_list("value", flat=True).first() or ""


def get_value(name: str) -> str:
    """Return the effective value: the user's value if set, else the built-in default."""
    return get_override(name) or get_default(name)


aget_value = sync_to_async(get_value, thread_sensitive=True)


def set_override(name: str, value: str) -> None:
    """Save (or clear, with an empty value) the user's value for a setting."""
    value = value.strip()
    if value:
        AppSetting.objects.update_or_create(key=name, defaults={"value": value})
    else:
        AppSetting.objects.filter(key=name).delete()
