"""Check the built-in API keys (DEFAULT_GROQ_API_KEY / DEFAULT_COHERE_API_KEY) without printing them.

Fails if a key is set but rejected; reports which Groq chat models the app will use.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

SETTINGS = (Path(__file__).resolve().parent.parent / "yt_navigator" / "settings.py").read_text()


def default_setting(name: str) -> str:
    """Return the default value of a setting defined as NAME = os.getenv("NAME", "default")."""
    return re.search(rf'{name} = os.getenv\("{name}", "([^"]*)"\)', SETTINGS).group(1)


def list_setting(name: str) -> list[str]:
    """Return the strings of a list setting defined as NAME = [ "a", "b", ... ]."""
    return re.findall(r'"([^"]+)"', re.search(rf"{name} = \[(.*?)\]", SETTINGS, re.DOTALL).group(1))


def request(url: str, key: str, payload: dict | None = None) -> dict:
    """GET (or POST when a payload is given) a JSON API with a bearer key."""
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=30) as response:
        return json.load(response)


def check_groq(key: str) -> bool:
    """Check the Groq key and report which chat models the app will pick."""
    try:
        models = {m["id"] for m in request("https://api.groq.com/openai/v1/models", key)["data"]}
    except urllib.error.HTTPError as e:
        print(f"Groq key: REJECTED (HTTP {e.code}: {e.read()[:200].decode(errors='replace')})")
        return False
    print("Groq key: valid")
    for kind in ("INSTANT_LLM", "POWERFUL_LLM"):
        candidates = [m for m in [default_setting(kind)] + list_setting(f"{kind}_CANDIDATES") if m]
        chosen = next((m for m in candidates if m in models), None)
        print(f"  {kind}: {chosen or 'no preferred model available (the app will use any chat model)'}")
    return bool(models)


def check_cohere(key: str) -> bool:
    """Check the Cohere key with one tiny embedding request."""
    model = default_setting("EMBEDDING_MODEL")
    payload = {"model": model, "texts": ["test"], "input_type": "search_query", "embedding_types": ["float"]}
    try:
        request("https://api.cohere.com/v2/embed", key, payload)
    except urllib.error.HTTPError as e:
        print(f"Cohere key: REJECTED (HTTP {e.code}: {e.read()[:200].decode(errors='replace')})")
        return False
    print(f"Cohere key: valid ({model} works)")
    return True


def main() -> int:
    """Check each key that is set; exit non-zero if any check fails."""
    results = []
    for name, check in (("DEFAULT_GROQ_API_KEY", check_groq), ("DEFAULT_COHERE_API_KEY", check_cohere)):
        key = os.environ.get(name, "").strip()
        if not key:
            print(f"{name}: not set (users will have to enter a key in Settings)")
            continue
        results.append(check(key))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
