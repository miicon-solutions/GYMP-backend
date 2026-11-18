from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)
APP_ENV = env("APP_ENV", default="local").lower()
if APP_ENV not in {"local", "dev", "prod"}:
    raise ImproperlyConfigured("APP_ENV must be local, dev, or prod.")
PRODUCTION = APP_ENV == "prod"
DEBUG = env.bool("DEBUG", default=False)
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="" if PRODUCTION else "local-only-development-secret-change-before-deploy",
)
JWT_SECRET = env("JWT_SECRET", default=SECRET_KEY)
if not SECRET_KEY or len(JWT_SECRET) < 32:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY and a JWT_SECRET of at least 32 characters.")
if PRODUCTION and (
    DEBUG
    or len(SECRET_KEY) < 32
    or SECRET_KEY == "local-only-development-secret-change-before-deploy"
    or JWT_SECRET
    in {
        "local-only-development-secret-change-before-deploy",
        "local-only-development-jwt-secret-change-before-deploy",
    }
):
    raise ImproperlyConfigured("Production requires a private secret and DEBUG=false.")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "testserver"])
DATABASE_URL = env("DATABASE_URL", default="postgres://gyma:gyma@localhost:55432/gyma_django")
if "host.docker.internal" in DATABASE_URL:
    import socket

    try:
        socket.gethostbyname("host.docker.internal")
    except OSError:
        DATABASE_URL = f"sqlite:///{BASE_DIR / 'local_dev.db'}"

db_engine = (
    "django.db.backends.sqlite3"
    if DATABASE_URL.startswith("sqlite")
    else "django.db.backends.postgresql"
)
DATABASES = {"default": env.db_url_config(DATABASE_URL, engine=db_engine)}
DATABASES["default"]["CONN_MAX_AGE"] = 60
INSTALLED_APPS = [
    "accounts.admin_config.OperatorAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "accounts",
    "members",
    "plans",
    "payments",
    "operations",
    "attendance",
    "reporting",
    "biometrics",
    "django_filters",
    "fitness",
    "workouts",
    "schedules",
    "nutrition",
    "journal",
    "music",
]
MIDDLEWARE = [
    "core.middleware.RequestLogMiddleware",
    "core.middleware.TrustedProxyMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "core.middleware.UploadLimitMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
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
TIME_ZONE = "Asia/Dhaka"
USE_TZ = True
LANGUAGE_CODE = "en-us"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = Path(env("MEMBER_PHOTO_DIR", default=str(BASE_DIR / "data/member-photos")))
MEDIA_URL = "/media/member-photos/"
MEDIA_STORAGE = env("MEDIA_STORAGE", default="filesystem").lower()
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
if MEDIA_STORAGE == "s3":
    bucket_name = env("AWS_STORAGE_BUCKET_NAME", default="").strip()
    if not bucket_name:
        raise ImproperlyConfigured("AWS_STORAGE_BUCKET_NAME is required when MEDIA_STORAGE=s3.")
    endpoint_url = env("AWS_S3_ENDPOINT_URL", default="").rstrip("/") or None
    if endpoint_url:
        endpoint = urlparse(endpoint_url)
        if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
            raise ImproperlyConfigured("AWS_S3_ENDPOINT_URL must be an HTTP or HTTPS URL.")
    addressing_style = env("AWS_S3_ADDRESSING_STYLE", default="virtual")
    if addressing_style not in {"path", "virtual", "auto"}:
        raise ImproperlyConfigured("AWS_S3_ADDRESSING_STYLE must be path, virtual, or auto.")
    querystring_expire = env.int("AWS_QUERYSTRING_EXPIRE", default=3600)
    if not 1 <= querystring_expire <= 604800:
        raise ImproperlyConfigured("AWS_QUERYSTRING_EXPIRE must be between 1 and 604800 seconds.")
    S3_SUB_FOLDER = env("S3_SUB_FOLDER", default="").strip().strip("/")
    media_folder = env("AWS_LOCATION", default="media").strip().strip("/")
    for name, prefix in (("S3_SUB_FOLDER", S3_SUB_FOLDER), ("AWS_LOCATION", media_folder)):
        if (
            "\\" in prefix
            or any(ord(char) < 32 or ord(char) == 127 for char in prefix)
            or (prefix and any(part in {"", ".", ".."} for part in prefix.split("/")))
        ):
            raise ImproperlyConfigured(f"{name} must be a relative S3 folder without dot segments.")
    media_location = "/".join(part for part in (S3_SUB_FOLDER, media_folder) if part)
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": bucket_name,
            "access_key": env("AWS_ACCESS_KEY_ID", default="") or None,
            "secret_key": env("AWS_SECRET_ACCESS_KEY", default="") or None,
            "security_token": env("AWS_SESSION_TOKEN", default="") or None,
            "endpoint_url": endpoint_url,
            "region_name": env("AWS_S3_REGION_NAME", default="us-east-1"),
            "addressing_style": addressing_style,
            "location": media_location,
            "signature_version": "s3v4",
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": querystring_expire,
            "custom_domain": None,
            "file_overwrite": False,
        },
    }
elif MEDIA_STORAGE != "filesystem":
    raise ImproperlyConfigured("MEDIA_STORAGE must be s3 or filesystem.")
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="http://localhost:8080").rstrip("/")
WEB_APP_BASE_URL = env("WEB_APP_BASE_URL", default="").rstrip("/")
if WEB_APP_BASE_URL:
    web_origin = urlparse(WEB_APP_BASE_URL)
    if (
        web_origin.scheme not in {"http", "https"}
        or not web_origin.netloc
        or web_origin.username
        or web_origin.password
        or web_origin.path
        or web_origin.query
        or web_origin.fragment
        or (PRODUCTION and web_origin.scheme != "https")
    ):
        raise ImproperlyConfigured("WEB_APP_BASE_URL must be a web origin (HTTPS in production).")
CORS_ALLOWED_ORIGINS = env.list("HTTP_ALLOWED_ORIGINS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = PRODUCTION
CSRF_COOKIE_SECURE = PRODUCTION
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=PRODUCTION)
SECURE_REDIRECT_EXEMPT = [r"^health/"]
SECURE_HSTS_SECONDS = 31536000 if PRODUCTION else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = PRODUCTION
SECURE_HSTS_PRELOAD = PRODUCTION
X_FRAME_OPTIONS = "DENY"
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.BearerAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "core.api.Pagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.api.exception_handler",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "UNAUTHENTICATED_USER": None,
}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(seconds=env.int("JWT_ACCESS_TTL_SEC", default=3600)),
    "REFRESH_TOKEN_LIFETIME": timedelta(seconds=env.int("JWT_REFRESH_TTL_SEC", default=2592000)),
    "SIGNING_KEY": JWT_SECRET,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "sub",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "GYMA API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_NAME_OVERRIDES": {
        "DiscountTypeEnum": "plans.models.DISCOUNTS",
        "MusicQueueStatusEnum": "music.models.QUEUE_STATUS_CHOICES",
    },
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
}
JWT_ACCESS_TTL_SEC = env.int("JWT_ACCESS_TTL_SEC", default=3600)
JWT_REFRESH_TTL_SEC = env.int("JWT_REFRESH_TTL_SEC", default=2592000)
OTP_DEV_BYPASS = not PRODUCTION and env.bool("OTP_DEV_BYPASS", default=APP_ENV == "local")
EMAIL_DEV_BYPASS = not PRODUCTION and env.bool("EMAIL_DEV_BYPASS", default=OTP_DEV_BYPASS)
OTP_DEV_MASTER_CODE = env("OTP_DEV_MASTER_CODE", default="000000")
OTP_TTL_SEC = env.int("OTP_TTL_SEC", default=300)
OTP_RESEND_SEC = env.int("OTP_RESEND_SEC", default=24)
MFA_SETUP_TTL_SEC = env.int("MFA_SETUP_TTL_SEC", default=1800)
GOOGLE_LINK_TTL_SEC = env.int("GOOGLE_LINK_TTL_SEC", default=1800)
TOTP_ISSUER = env("TOTP_ISSUER", default="Titanic Gym")
TOTP_ENCRYPTION_KEY = env("TOTP_ENCRYPTION_KEY", default="")
FIREBASE_CREDENTIALS_FILE = env(
    "FIREBASE_CREDENTIALS_FILE", default=env("GOOGLE_APPLICATION_CREDENTIALS", default="")
)
SMS_NET_BD_API_KEY = env("SMS_NET_BD_API_KEY", default="")
SMS_NET_BD_SENDER_ID = env("SMS_NET_BD_SENDER_ID", default="")
SSLCOMMERZ_STORE_ID = env("SSLCOMMERZ_STORE_ID", default="")
SSLCOMMERZ_STORE_PASSWD = env("SSLCOMMERZ_STORE_PASSWD", default="")
SSLCOMMERZ_SANDBOX = not PRODUCTION and env.bool("SSLCOMMERZ_SANDBOX", default=True)
ATTENDANCE_DEVICE_KEY = env("ATTENDANCE_DEVICE_KEY", default="")
ZKTECO_BRIDGE_URL = env("ZKTECO_BRIDGE_URL", default="").rstrip("/")
ZKTECO_BRIDGE_KEY = env("ZKTECO_BRIDGE_KEY", default="")
BIOMETRIC_ENCRYPTION_KEY = env("BIOMETRIC_ENCRYPTION_KEY", default="") or TOTP_ENCRYPTION_KEY
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "loggers": {"httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"}},
    "filters": {"redact": {"()": "core.middleware.RedactFilter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "filters": ["redact"]}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
if PRODUCTION:
    for name in (
        "TOTP_ENCRYPTION_KEY",
        "FIREBASE_CREDENTIALS_FILE",
        "SMS_NET_BD_API_KEY",
        "SSLCOMMERZ_STORE_ID",
        "SSLCOMMERZ_STORE_PASSWD",
        "ATTENDANCE_DEVICE_KEY",
    ):
        if not globals()[name]:
            raise ImproperlyConfigured(f"{name} is required in production.")
    if not PUBLIC_BASE_URL.startswith("https://"):
        raise ImproperlyConfigured("PUBLIC_BASE_URL must use HTTPS in production.")

TRUSTED_PROXY_IPS = env.list("TRUSTED_PROXY_IPS", default=[])
FILE_UPLOAD_HANDLERS = [
    "core.uploads.BoundedUploadHandler",
    "django.core.files.uploadhandler.MemoryFileUploadHandler",
    "django.core.files.uploadhandler.TemporaryFileUploadHandler",
]
DATA_UPLOAD_MAX_NUMBER_FILES = 1
