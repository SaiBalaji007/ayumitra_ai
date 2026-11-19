"""AyuMitra AI — Django settings. All environment-specific values come from .env."""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(REPO_ROOT / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    # Local
    "core",
    "accounts",
    "patients",
    "documents",
    "medical_reports",
    "prescriptions",
    "assistant",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database: SQLite
# ---------------------------------------------------------------------------
# One file, no server. SQLITE_PATH lets Docker put it on a volume; the default is backend/db.sqlite3.
# WAL mode lets readers (API requests) proceed while a writer (e.g. a Celery job) commits, and
# IMMEDIATE transactions + a busy timeout avoid "database is locked" errors under light concurrency.
SQLITE_PATH = Path(env("SQLITE_PATH", default=str(BASE_DIR / "db.sqlite3")))

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": SQLITE_PATH,
        "OPTIONS": {
            "timeout": 20,
            "transaction_mode": "IMMEDIATE",
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
        },
        "TEST": {"NAME": None},  # tests use a fast in-memory database
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ---------------------------------------------------------------------------
# Private medical document storage
# ---------------------------------------------------------------------------
# Files live outside any public URL space: there is deliberately no MEDIA_URL route.
# The only way to read a file is the owner-checked /api/documents/{id}/file/ endpoint.
PRIVATE_MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "private_media")))
MEDIA_ROOT = PRIVATE_MEDIA_ROOT
FILE_UPLOAD_PERMISSIONS = 0o600
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o700

DOCUMENT_MAX_UPLOAD_MB = env.int("DOCUMENT_MAX_UPLOAD_MB", default=20)
# Upload size is enforced per file in documents/validators.py (and early via Content-Length).
DATA_UPLOAD_MAX_MEMORY_SIZE = 2_621_440  # non-file fields only (Django default)
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # larger uploads stream to a temp file

# Background processing pipeline (OCR/NLP arrive in Phase 4–5). While False, uploads are
# stored and stay "uploaded" instead of being queued, so nothing pretends to analyse them.
DOCUMENT_PROCESSING_ENABLED = env.bool("DOCUMENT_PROCESSING_ENABLED", default=False)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "uploads": env("UPLOAD_THROTTLE_RATE", default="60/hour"),
        "auth": env("AUTH_THROTTLE_RATE", default="30/min"),
        "assistant": env("ASSISTANT_THROTTLE_RATE", default="30/hour"),
    },
    "EXCEPTION_HANDLER": "core.exceptions.api_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
}

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:5173"])

CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # long OCR/LLM jobs: don't hoard tasks
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_ROUTES = {
    "documents.tasks.*": {"queue": "documents"},
}

# AI service (OCR / NLP / RAG / Qwen) runs as a separate process — Django only calls it.
AI_SERVICE_URL = env("AI_SERVICE_URL", default="http://localhost:8001")
AI_SERVICE_TOKEN = env("AI_SERVICE_TOKEN", default="")
AI_SERVICE_OCR_TIMEOUT = env.float("AI_SERVICE_OCR_TIMEOUT", default=900)  # handwriting is read by a local vision model (≈ 4 min on CPU)
AI_SERVICE_LLM_TIMEOUT = env.float("AI_SERVICE_LLM_TIMEOUT", default=600)

# How queued document jobs run:
#   "db"     - a `manage.py process_documents` worker polls the ProcessingTask table (no Redis needed;
#              the default for local Windows development with SQLite)
#   "celery" - Celery workers via Redis (Docker / production)
DOCUMENT_QUEUE_BACKEND = env("DOCUMENT_QUEUE_BACKEND", default="db")

# ---------------------------------------------------------------------------
# Production hardening (active when DEBUG=False)
# ---------------------------------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # TLS terminates at the reverse proxy
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
    if SECRET_KEY in ("", "change-me") or len(SECRET_KEY) < 40:
        raise RuntimeError("Set a strong DJANGO_SECRET_KEY (40+ random characters) for production.")

# ---------------------------------------------------------------------------
# Logging: one line per event to stdout (collected by Docker / the host). Medical content is
# never logged: no document text, values or questions, only ids, statuses and timings.
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "line": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "line"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {
        "django.request": {"level": "WARNING"},
        "django.db.backends": {"level": "WARNING"},
    },
}


# --- Phase 2: nearby care (OpenStreetMap). Community services: cached, rate-limited, configurable.
GEOCODER_URL = env("GEOCODER_URL", default="https://nominatim.openstreetmap.org/search")
OVERPASS_URLS = env.list("OVERPASS_URLS", default=[
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
])
OSM_USER_AGENT = env("OSM_USER_AGENT", default="AyuMitraAI/1.0 (health-education app; nearby care search)")
