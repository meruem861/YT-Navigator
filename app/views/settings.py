"""Settings page: API keys used by the app."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    redirect,
    render,
)

from app.services.app_settings import (
    EDITABLE_KEYS,
    get_default,
    get_override,
    set_override,
)


def _key_status(name: str) -> dict:
    """Describe where the effective value of a key comes from, without revealing it."""
    override = get_override(name)
    if override:
        status = f"Using your key (ending in …{override[-4:]})"
    elif get_default(name):
        status = "Using the built-in key"
    else:
        status = "Not set"
    return {"name": name, "label": EDITABLE_KEYS[name], "status": status, "has_override": bool(override)}


@login_required
def settings_view(request):
    """Show and update the API keys."""
    if request.method == "POST":
        reset = request.POST.get("reset")
        if reset in EDITABLE_KEYS:
            set_override(reset, "")
            messages.success(request, f"{EDITABLE_KEYS[reset]} reset to the built-in key.")
        else:
            changed = [label for name, label in EDITABLE_KEYS.items() if request.POST.get(name, "").strip()]
            for name in EDITABLE_KEYS:
                value = request.POST.get(name, "").strip()
                if value:
                    set_override(name, value)
            messages.success(request, f"Saved: {', '.join(changed)}." if changed else "Nothing to save.")
        return redirect("app:settings")

    return render(request, "settings.html", {"keys": [_key_status(name) for name in EDITABLE_KEYS]})
