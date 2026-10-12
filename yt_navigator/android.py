"""Entry point used by the Android app (through Chaquopy) to run the server inside the APK.

The app calls ``start()`` once at launch; it prepares the database and serves the site on a free local port,
which the app's WebView then opens.
"""

import os
import socket
import threading
import time
from typing import Optional

_server = None
_port: Optional[int] = None
_lock = threading.Lock()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start(data_dir: str, groq_api_key: str = "", cohere_api_key: str = "", timeout: float = 60.0) -> int:
    """Start the server (once) and return its port.

    Args:
        data_dir: Writable app directory for the databases, logs and secret key.
        groq_api_key: Built-in Groq key (users can replace it in Settings).
        cohere_api_key: Built-in Cohere key (users can replace it in Settings).
        timeout: Seconds to wait for the server to accept connections.

    Returns:
        int: The port the server listens on (127.0.0.1 only).
    """
    global _server, _port

    with _lock:
        if _server is not None and _server.started:
            return _port

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "yt_navigator.settings")
        os.environ["DATA_DIR"] = data_dir
        os.environ["LOGS_DIR"] = os.path.join(data_dir, "logs")
        os.environ["SINGLE_USER_MODE"] = "true"
        os.environ.setdefault("DEBUG", "false")
        os.environ.setdefault("ALLOWED_HOSTS", "127.0.0.1,localhost")
        if groq_api_key:
            os.environ["GROQ_API_KEY"] = groq_api_key
        if cohere_api_key:
            os.environ["COHERE_API_KEY"] = cohere_api_key

        import django
        from django.core.management import call_command

        django.setup()
        call_command("migrate", interactive=False, verbosity=0)

        import uvicorn

        from yt_navigator.asgi import application

        _port = _free_port()
        config = uvicorn.Config(application, host="127.0.0.1", port=_port, lifespan="off", log_level="warning")
        _server = uvicorn.Server(config)
        threading.Thread(target=_server.run, name="yt-navigator-server", daemon=True).start()

        deadline = time.monotonic() + timeout
        while not _server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("The YT Navigator server did not start in time")
            time.sleep(0.1)

        print(f"YT Navigator server listening on 127.0.0.1:{_port}", flush=True)
        return _port
