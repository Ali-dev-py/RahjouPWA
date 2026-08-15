"""Root URL configuration for Rahjou."""

from django.contrib import admin
from django.urls import include, path

from .views import service_worker, web_app_manifest

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "manifest.webmanifest",
        web_app_manifest,
        name="web_app_manifest",
    ),
    path("serviceworker.js", service_worker, name="service_worker"),
    path("", include("core.urls")),
]
