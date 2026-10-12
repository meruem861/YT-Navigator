"""Settings page: API keys used by the app."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    redirect,
    render,
)
from django.views.decorators.http import require_http_methods

from app.services.app_settings import (
    EDITABLE_KEYS,
    get_default,
    get_override,
    set_override,
)
from app.services.cohere_client import CohereClient
from app.services.groq_client import GroqClient


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


async def _check_groq() -> tuple[bool, str]:
    try:
        models = await GroqClient().list_models()
    except Exception as e:
        return False, f"Groq key: not working ({e})"
    missing = [m for m in (settings.INSTANT_LLM, settings.POWERFUL_LLM) if m not in models]
    if missing:
        return False, f"Groq key: works, but these models are not available: {', '.join(missing)}"
    return True, "Groq key: works"


async def _check_cohere() -> tuple[bool, str]:
    try:
        await CohereClient().embed(["test"], input_type="search_query")
    except Exception as e:
        return False, f"Cohere key: not working ({e})"
    return True, "Cohere key: works"


@login_required
@require_http_methods(["POST"])
async def test_keys_view(request):
    """Call Groq and Cohere with the current keys and report the result."""
    for ok, message in (await _check_groq(), await _check_cohere()):
        (messages.success if ok else messages.error)(request, message)
    return redirect("app:settings")
