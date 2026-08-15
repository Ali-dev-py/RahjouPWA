"""Smoke tests for routes, templates, and PWA delivery."""

import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse


class PageSmokeTests(SimpleTestCase):
    """Confirm every placeholder page renders through its named route."""

    pages = {
        "core:splash": "core/splash.html",
        "core:login": "core/login.html",
        "core:dashboard": "core/dashboard.html",
        "core:factor_list": "core/factor_list.html",
        "core:factor_detail": "core/factor_detail.html",
        "core:factor_create": "core/factor_create.html",
        "core:offline": "core/offline.html",
    }

    def test_placeholder_pages_render(self) -> None:
        """All converted pages should return HTML without database access."""
        for route_name, template_name in self.pages.items():
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template_name)
                self.assertTemplateUsed(response, "base.html")
                self.assertContains(response, reverse("web_app_manifest"))

    def test_splash_declares_timed_login_redirect(self) -> None:
        """The splash screen should hand off to login after its short delay."""
        response = self.client.get(reverse("core:splash"))
        self.assertContains(
            response,
            f'data-splash-redirect-url="{reverse("core:login")}"',
        )
        self.assertContains(response, 'data-splash-redirect-delay="2500"')
        self.assertContains(response, 'content="3;url=/login/"')

    def test_service_worker_has_root_scope(self) -> None:
        """The worker is JavaScript served at root with an explicit scope."""
        worker_url = reverse("service_worker")
        response = self.client.get(worker_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertIn("application/javascript", response["Content-Type"])

        head_response = self.client.head(worker_url)
        self.assertEqual(head_response.status_code, 200)
        self.assertEqual(head_response["Service-Worker-Allowed"], "/")

    def test_canonical_manifest_is_installable(self) -> None:
        """The root manifest exposes the members Chromium install checks need."""
        manifest_url = reverse("web_app_manifest")
        response = self.client.get(manifest_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/manifest+json", response["Content-Type"])

        manifest = json.loads(b"".join(response.streaming_content))
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["scope"], "/")
        self.assertFalse(manifest["prefer_related_applications"])
        icon_sizes = {icon["sizes"] for icon in manifest["icons"]}
        self.assertTrue({"192x192", "512x512"}.issubset(icon_sizes))
        icon_purposes = {icon["purpose"] for icon in manifest["icons"]}
        self.assertTrue({"any", "maskable"}.issubset(icon_purposes))

    def test_required_pwa_files_exist(self) -> None:
        """The manifest, worker, fallback assets, and install art exist."""
        static_dir = Path(settings.STATICFILES_DIRS[0])
        required = (
            "manifest.json",
            "serviceworker.js",
            "css/app.css",
            "js/app.js",
            "icons/apple-touch-icon.png",
            "icons/icon-192.png",
            "icons/icon-512.png",
            "icons/icon-maskable-192.png",
            "icons/icon-maskable-512.png",
            "screenshots/dashboard.png",
        )
        for relative_path in required:
            with self.subTest(path=relative_path):
                self.assertTrue((static_dir / relative_path).is_file())
