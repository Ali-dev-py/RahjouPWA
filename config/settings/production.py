"""Production settings configured through environment variables."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

if SECRET_KEY == "django-insecure-development-only-change-me":  # noqa: F405
    raise ImproperlyConfigured(
        "Set DJANGO_SECRET_KEY before using production settings."
    )

if not ALLOWED_HOSTS:  # noqa: F405
    raise ImproperlyConfigured(
        "Set DJANGO_ALLOWED_HOSTS before using production settings."
    )

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
