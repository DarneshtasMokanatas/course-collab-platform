import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
PROCESS_ENV_KEYS = frozenset(os.environ)
DOTENV_PATH = BASE_DIR / ".env"


def load_dotenv(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_bool(name, default=False):
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ImproperlyConfigured(f"{name} must be a boolean value")
    return value in {"true", "1", "yes"}


def database_config(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("DATABASE_URL must use PostgreSQL")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": parsed.port or 5432,
        "CONN_MAX_AGE": 60,
    }


load_dotenv(DOTENV_PATH)

environment_value = os.getenv("DJANGO_ENVIRONMENT")
ENVIRONMENT = (
    environment_value.strip().lower()
    if environment_value
    else ("local" if DOTENV_PATH.exists() else "production")
)
if ENVIRONMENT not in {"local", "test", "production"}:
    raise ImproperlyConfigured("DJANGO_ENVIRONMENT must be local, test, or production")
IS_PRODUCTION = ENVIRONMENT == "production"

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is required")

DEBUG = env_bool("DJANGO_DEBUG", False)
if ENVIRONMENT != "local" and DEBUG:
    raise ImproperlyConfigured("DJANGO_DEBUG may be true only in local development")
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]
if IS_PRODUCTION and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS is required in production")
if IS_PRODUCTION and "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS cannot contain a wildcard in production"
    )

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.courses",
    "apps.announcements",
    "apps.materials",
    "apps.assignments",
    "apps.analytics",
    "apps.audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

database_url = os.getenv("DATABASE_URL")
if IS_PRODUCTION and "DATABASE_URL" not in PROCESS_ENV_KEYS:
    raise ImproperlyConfigured(
        "Production DATABASE_URL must be supplied by the process environment"
    )
if not database_url:
    database_url = "postgresql://course_app:course_app@127.0.0.1:5432/course_app"
DATABASES = {"default": database_config(database_url)}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"  # noqa: E501
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.UsernameOrEmailBackend",
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "home"

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "Asia/Kuala_Lumpur")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "media"))
if IS_PRODUCTION and ("MEDIA_ROOT" not in os.environ or not MEDIA_ROOT.is_absolute()):
    raise ImproperlyConfigured(
        "Production MEDIA_ROOT must be an explicit absolute path"
    )

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", IS_PRODUCTION)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", IS_PRODUCTION)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", IS_PRODUCTION)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = int(
    os.getenv("DJANGO_SECURE_HSTS_SECONDS", "31536000" if IS_PRODUCTION else "0")
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", IS_PRODUCTION
)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
if env_bool("DJANGO_TRUST_PROXY_HEADERS", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if IS_PRODUCTION:
    insecure_settings = [
        name
        for name, enabled in (
            ("DJANGO_SECURE_SSL_REDIRECT", SECURE_SSL_REDIRECT),
            ("DJANGO_SESSION_COOKIE_SECURE", SESSION_COOKIE_SECURE),
            ("DJANGO_CSRF_COOKIE_SECURE", CSRF_COOKIE_SECURE),
            (
                "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
                SECURE_HSTS_INCLUDE_SUBDOMAINS,
            ),
        )
        if not enabled
    ]
    if SECURE_HSTS_SECONDS <= 0:
        insecure_settings.append("DJANGO_SECURE_HSTS_SECONDS")
    if insecure_settings:
        raise ImproperlyConfigured(
            "Production requires secure settings: " + ", ".join(insecure_settings)
        )
