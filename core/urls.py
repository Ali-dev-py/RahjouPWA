"""Named routes for every converted static screen."""

from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.SplashView.as_view(), name="splash"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("factors/", views.FactorListView.as_view(), name="factor_list"),
    path(
        "factors/detail/",
        views.FactorDetailView.as_view(),
        name="factor_detail",
    ),
    path(
        "factors/new/",
        views.FactorCreateView.as_view(),
        name="factor_create",
    ),
    path("offline/", views.OfflineView.as_view(), name="offline"),
]
