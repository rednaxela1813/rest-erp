"""
Django settings shared across environments.
"""

from pathlib import Path

from decouple import config
import structlog

from config.observability.logging import mask_sensitive


BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY")
DEBUG = config("DJANGO_DEBUG", cast=bool)
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", cast=lambda v: [s.strip() for s in v.split(",")])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "config.users",
    "config.dictionaries",
    "config.orgs",
    "apps.logs_dashboard",
    "config.observability",
    "apps.partners",
    "apps.products",
    "apps.orders",
    "apps.payments",
    "apps.cashier",
    "apps.ops_dashboard",
    "apps.inventory",
    "apps.equipment",
    "apps.accounting",
    "apps.recipes",
]

AUTH_USER_MODEL = "users.User"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "ERP for Burger API",
    "DESCRIPTION": "API documentation for the ERP backend.",
    "VERSION": "1.0.0",
}

DEFAULT_CURRENCY = config("DEFAULT_CURRENCY", default="EUR")
CASHIER_DEVICE_TOKEN = config("CASHIER_DEVICE_TOKEN", default="")
LOGIN_URL = "/cashier/login/"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "config.orgs.middleware.SessionOrgMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "config.observability.middleware.RequestContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"

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

WSGI_APPLICATION = "core.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("POSTGRES_DB"),
        "USER": config("POSTGRES_USER"),
        "PASSWORD": config("POSTGRES_PASSWORD"),
        "HOST": config("POSTGRES_HOST", default="db"),
        "PORT": config("POSTGRES_PORT", default="5432"),
        "CONN_MAX_AGE": 60,
    }
}

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

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://redis:6379/0")
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default="redis://redis:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_ROUTES = {
    "apps.payments.tasks.dispatch_device_commands": {"queue": "device_commands"},
    "apps.payments.tasks.dispatch_device_commands_for_all_orgs": {"queue": "device_commands"},
    "apps.payments.tasks.process_device_commands_mock": {"queue": "device_commands"},
    "apps.payments.tasks.process_device_commands_mock_for_all_orgs": {"queue": "device_commands"},
}

CELERY_BEAT_SCHEDULE = {
    "dispatch-device-commands-all-orgs": {
        "task": "apps.payments.tasks.dispatch_device_commands_for_all_orgs",
        "schedule": 60.0,
        "kwargs": {"limit": 50},
    },
}

DEVICE_COMMANDS_REDIS_URL = config("DEVICE_COMMANDS_REDIS_URL", default=CELERY_BROKER_URL)
DEVICE_COMMANDS_STREAM = config("DEVICE_COMMANDS_STREAM", default="device_commands")
DEVICE_COMMANDS_STREAM_MAXLEN = config("DEVICE_COMMANDS_STREAM_MAXLEN", cast=int, default=10000)
DEVICE_COMMANDS_RETRY_BASE_SECONDS = config(
    "DEVICE_COMMANDS_RETRY_BASE_SECONDS", cast=int, default=10
)
DEVICE_COMMANDS_RETRY_MAX_SECONDS = config(
    "DEVICE_COMMANDS_RETRY_MAX_SECONDS", cast=int, default=300
)

FISCAL_MOCK_ENABLED = config("FISCAL_MOCK_ENABLED", cast=bool, default=False)
FISCAL_MOCK_OFFLINE = config("FISCAL_MOCK_OFFLINE", cast=bool, default=False)

EKASA_BASE_URL = config("EKASA_BASE_URL", default="")
EKASA_API_KEY = config("EKASA_API_KEY", default="")
EKASA_TIMEOUT_S = config("EKASA_TIMEOUT_S", cast=int, default=30)
EKASA_USERNAME = config("EKASA_USERNAME", default="")
EKASA_PASSWORD = config("EKASA_PASSWORD", default="")
EKASA_CASH_REGISTER_CODE = config("EKASA_CASH_REGISTER_CODE", default="")
EKASA_ENABLED = config("EKASA_ENABLED", cast=bool, default=False)
FISCAL_RECONCILE_ENABLED = config("FISCAL_RECONCILE_ENABLED", cast=bool, default=True)
LOG_RETENTION_ENABLED = config("LOG_RETENTION_ENABLED", cast=bool, default=True)
LOG_RETENTION_DAYS = config("LOG_RETENTION_DAYS", cast=int, default=30)

if FISCAL_MOCK_ENABLED and EKASA_ENABLED:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        "FISCAL_MOCK_ENABLED and EKASA_ENABLED cannot both be True. "
        "Mock mode simulates fiscalization locally; eKasa mode calls the real NineDigit API. "
        "Set only one of them to True."
    )

if FISCAL_MOCK_ENABLED:
    CELERY_BEAT_SCHEDULE["mock-device-commands-all-orgs"] = {
        "task": "apps.payments.tasks.process_device_commands_mock_for_all_orgs",
        "schedule": 5.0,
        "kwargs": {"limit": 50},
    }

if EKASA_ENABLED:
    CELERY_BEAT_SCHEDULE["ekasa-device-commands-all-orgs"] = {
        "task": "apps.payments.tasks.process_device_commands_ekasa_for_all_orgs",
        "schedule": 5.0,
        "kwargs": {"limit": 50},
    }

if FISCAL_RECONCILE_ENABLED:
    CELERY_BEAT_SCHEDULE["reconcile-fiscal-status-all-orgs"] = {
        "task": "apps.payments.tasks.reconcile_payment_fiscal_status_for_all_orgs",
        "schedule": 60.0,
        "kwargs": {"limit": 200},
    }

if LOG_RETENTION_ENABLED:
    CELERY_BEAT_SCHEDULE["purge-old-logs"] = {
        "task": "apps.logs_dashboard.tasks.purge_old_logs",
        "schedule": 3600.0,
        "kwargs": {"days": LOG_RETENTION_DAYS},
    }

STATIC_URL = "static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOG_LEVEL = config("LOG_LEVEL", default="INFO")
LOG_DB_ENABLED = config("LOG_DB_ENABLED", cast=bool, default=True)

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.format_exc_info,
        mask_sensitive,
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "apps_only": {
            "()": "config.observability.logging.AppsOnlyFilter",
        },
    },
    "formatters": {
        "json": {
            "()": "structlog.stdlib.ProcessorFormatter",
            "processor": structlog.processors.JSONRenderer(),
            "foreign_pre_chain": [
                structlog.contextvars.merge_contextvars,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.stdlib.add_log_level,
                structlog.processors.format_exc_info,
                mask_sensitive,
            ],
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
        "db": {
            "()": "config.observability.logging.DBLogHandler",
            "level": LOG_LEVEL,
            "filters": ["apps_only"],
        },
    },
    "root": {
        "handlers": ["console"] + (["db"] if LOG_DB_ENABLED else []),
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}