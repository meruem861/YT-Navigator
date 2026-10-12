"""Settings for the yt_navigator app."""

import os
import secrets
from pathlib import Path

import structlog
from dotenv import load_dotenv

from yt_navigator.utils.logging import get_log_filename

load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Ensure logs directory exists
logs_dir = os.getenv("LOGS_DIR", os.path.join(BASE_DIR, "logs"))
os.makedirs(logs_dir, exist_ok=True)


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DEBUG", "False").lower() in ("1", "true", "yes")

# The app is meant to run on the phone itself (Termux) and be opened from the WebView app or the browser.
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "app.apps.AppConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "yt_navigator.middlewares.request_logging_middleware.RequestLoggingMiddleware",
    "yt_navigator.middlewares.single_user_middleware.SingleUserMiddleware",
]

# Single-user mode (Android app): no accounts, everyone using the app is logged in as one local user.
SINGLE_USER_MODE = os.getenv("SINGLE_USER_MODE", "False").lower() in ("1", "true", "yes")

ROOT_URLCONF = "yt_navigator.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "app/templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "app.context_processors.version_context",
                "app.context_processors.single_user_context",
            ],
        },
    },
]

WSGI_APPLICATION = "yt_navigator.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

# All data lives in local SQLite files so the whole app can run on a phone.
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
os.makedirs(DATA_DIR, exist_ok=True)


def _load_or_create_secret_key(path: Path) -> str:
    """Return the secret key stored in DATA_DIR, creating it on first run (the phone app has no .env)."""
    if not path.exists():
        path.write_text(secrets.token_urlsafe(50))
    return path.read_text().strip()


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or _load_or_create_secret_key(DATA_DIR / "secret_key")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
        "OPTIONS": {
            # Scans write from several threads; wait for the lock instead of failing.
            "timeout": 30,
            "init_command": "PRAGMA journal_mode=WAL;",
        },
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

AUTH_USER_MODEL = "app.User"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Serve static files straight from the app folders, so no collectstatic step is needed (e.g. inside the APK)
WHITENOISE_USE_FINDERS = True

# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Structlog Configuration
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    context_class=structlog.threadlocal.wrap_dict(dict),
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json_formatter": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.processors.JSONRenderer(),
        },
        "plain_console": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.dev.ConsoleRenderer(),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "plain_console",
        },
        "json_file": {
            "class": "logging.FileHandler",
            "filename": get_log_filename(logs_dir),
            "formatter": "json_formatter",
            "encoding": "utf-8",
        },
    },
    "loggers": {
        "": {
            "handlers": ["console", "json_file"],
            "level": os.getenv("LOG_LEVEL", "INFO"),
            "propagate": True,
        },
        "django": {
            "handlers": ["console", "json_file"],
            "level": os.getenv("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}

# API keys below are the built-in defaults; users can override them from the Settings page.
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = os.getenv("GROQ_API_URL", "https://api.groq.com/openai/v1")

# Cohere (https://dashboard.cohere.com/) provides embeddings and reranking, so no ML model runs on the device
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
COHERE_API_URL = os.getenv("COHERE_API_URL", "https://api.cohere.com/v2")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "embed-v4.0")
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", 96))  # Cohere accepts up to 96 texts per call
RERANKER_MODEL_NAME = os.getenv("RERANKER_MODEL_NAME", "rerank-v3.5")
# Trial keys allow 100k tokens/minute for embeddings; stay below it (raise it for production keys)
COHERE_TOKENS_PER_MINUTE = int(os.getenv("COHERE_TOKENS_PER_MINUTE", 80000))

# Groq retires models regularly, so the app picks, at runtime, the first of these candidates that the key can use
# (and any available chat model as a last resort). INSTANT_LLM / POWERFUL_LLM force a specific model.
INSTANT_LLM = os.getenv("INSTANT_LLM", "")
POWERFUL_LLM = os.getenv("POWERFUL_LLM", "")
# Used without tools and with JSON output: prefer models that never emit spontaneous tool calls (gpt-oss may)
INSTANT_LLM_CANDIDATES = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "moonshotai/kimi-k2-instruct-0905",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
]
# Used with tool calling: keep models that support it
POWERFUL_LLM_CANDIDATES = [
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "moonshotai/kimi-k2-instruct-0905",
    "moonshotai/kimi-k2-instruct",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-20b",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
]

SCRAPER_WORKERS_NUM = int(os.getenv("SCRAPER_WORKERS_NUM", min(os.cpu_count() or 1, 4)))
