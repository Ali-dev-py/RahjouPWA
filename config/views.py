"""Small project-level delivery views required by the PWA shell."""

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


@never_cache
@require_safe
def web_app_manifest(request: HttpRequest) -> HttpResponse:
    """Serve the canonical manifest at the origin root with its PWA MIME type."""
    manifest_path = settings.BASE_DIR / "static" / "manifest.json"
    return FileResponse(
        manifest_path.open("rb"),
        content_type="application/manifest+json; charset=utf-8",
    )


@never_cache
@require_safe
def service_worker(request: HttpRequest) -> HttpResponse:
    """Serve the worker at the site root so it can control every app route."""
    worker_path = settings.BASE_DIR / "static" / "serviceworker.js"
    response = FileResponse(
        worker_path.open("rb"),
        content_type="application/javascript; charset=utf-8",
    )
    response["Service-Worker-Allowed"] = "/"
    return response
