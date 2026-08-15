"""Presentation-only views for the converted Stitch screens."""

from django.views.generic import TemplateView


class SplashView(TemplateView):
    """Render the placeholder splash screen without application logic."""

    template_name = "core/splash.html"


class LoginView(TemplateView):
    """Render the visual login placeholder; no authentication is performed."""

    template_name = "core/login.html"


class DashboardView(TemplateView):
    """Render the static dashboard design with sample presentation data."""

    template_name = "core/dashboard.html"


class FactorListView(TemplateView):
    """Render the static factor-list scaffold without database queries."""

    template_name = "core/factor_list.html"


class FactorDetailView(TemplateView):
    """Render one static factor-detail example without model access."""

    template_name = "core/factor_detail.html"


class FactorCreateView(TemplateView):
    """Render the factor-entry scaffold without saving or PDF generation."""

    template_name = "core/factor_create.html"


class OfflineView(TemplateView):
    """Render the lightweight fallback used when navigation is offline."""

    template_name = "core/offline.html"
