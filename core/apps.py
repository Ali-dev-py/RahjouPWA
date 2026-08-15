"""Application configuration for the presentation-only core app."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Configure the core page-scaffolding application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Rahjou core"
