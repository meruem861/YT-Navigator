"""Settings page: chat provider and API keys used by the app."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    redirect,
    render,
)
from django.views.decorators.http import require_http_methods

from app.services.app_settings import (
    EDITABLE_KEYS,
    aget_value,
    get_default,
    get_override,
    get_value,
    set_override,
)
from app.services.cohere_client import CohereClient
from app.services.llm_client import (
    CLIENTS,
    PROVIDER_KEYS,
    PROVIDERS,
    get_provider,
)

PROVIDER_DETAILS = {
    "groq": {"note": "Free tier. Fast.", "key_url": "https://console.groq.com/keys"},
    "gemini": {
        "note": "Free tier. Good with Arabic and long answers.",
        "key_url": "https://aistudio.google.com/apikey",
    },
    "claude": {"note": "Paid. Best answer quality.", "key_url": "https://console.anthropic.com/settings/keys"},
}


def _key_status(name: str) -> dict:
    """Describe where the effective value of a key comes from, without revealing it."""
    override = get_override(name)
    if override:
        status = f"Using your key (ending in …{override[-4:]})"
    elif get_default(name):
        status = "Using the built-in key"
    else:
        status = "Not set"
    return {
        "name": name,
        "label": EDITABLE_KEYS[name],
        "status": status,
        "has_override": bool(override),
        "is_set": bool(override or get_default(name)),
    }


@login_required
def settings_view(request):
    """Show and update the chat provider and API keys."""
    if request.method == "POST":
        reset = request.POST.get("reset")
        if reset in EDITABLE_KEYS:
            set_override(reset, "")
            messages.success(request, f"{EDITABLE_KEYS[reset]} reset to the built-in key.")
            return redirect("app:settings")

        saved = []
        provider = request.POST.get("CHAT_PROVIDER")
        if provider in PROVIDERS and provider != get_value("CHAT_PROVIDER"):
            set_override("CHAT_PROVIDER", provider)
            saved.append(f"chat provider: {PROVIDERS[provider]}")
        for name, label in EDITABLE_KEYS.items():
            value = request.POST.get(name, "").strip()
            if value:
                set_override(name, value)
                saved.append(label)
        messages.success(request, f"Saved {', '.join(saved)}." if saved else "Nothing changed.")
        return redirect("app:settings")

    current = get_value("CHAT_PROVIDER") if get_value("CHAT_PROVIDER") in PROVIDERS else "groq"
    keys = {name: _key_status(name) for name in EDITABLE_KEYS}
    providers = [
        {
            "id": provider,
            "name": name,
            "selected": provider == current,
            "key": keys[PROVIDER_KEYS[provider]],
            **PROVIDER_DETAILS[provider],
        }
        for provider, name in PROVIDERS.items()
    ]
    return render(request, "settings.html", {"providers": providers, "cohere": keys["COHERE_API_KEY"]})


async def _check_provider(provider: str) -> tuple[bool, str]:
    client = CLIENTS[provider]()
    name = PROVIDERS[provider]
    try:
        instant, powerful = await client.pick_model("instant"), await client.pick_model("powerful")
    except Exception as e:
        return False, f"{name} key: not working ({e})"
    return True, f"{name} key: works (models: {instant}, {powerful})"


async def _check_cohere() -> tuple[bool, str]:
    try:
        await CohereClient().embed(["test"], input_type="search_query")
    except Exception as e:
        return False, f"Cohere key: not working ({e})"
    return True, "Cohere key: works"


@login_required
@require_http_methods(["POST"])
async def test_keys_view(request):
    """Check the selected chat provider (and any other provider with a key) and Cohere."""
    selected = await get_provider()
    results = [await _check_provider(selected)]
    for provider, key_name in PROVIDER_KEYS.items():
        if provider != selected and await aget_value(key_name):
            results.append(await _check_provider(provider))
    results.append(await _check_cohere())
    for ok, message in results:
        (messages.success if ok else messages.error)(request, message)
    return redirect("app:settings")
