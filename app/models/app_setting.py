"""Key/value settings editable from the app (e.g. API keys)."""

from django.db import models


class AppSetting(models.Model):
    """A setting saved by the user, overriding the built-in default.

    Attributes:
        key: Setting name, e.g. "GROQ_API_KEY".
        value: Setting value.
    """

    key = models.CharField(max_length=100, primary_key=True)
    value = models.TextField()

    def __str__(self):
        """Return the setting name (values may be secrets)."""
        return self.key
