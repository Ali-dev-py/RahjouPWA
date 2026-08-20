from django.urls import path
from .views import *

app_name = "core"

urlpatterns = [
    path("", SplashView.as_view(), name="splash"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("customers/", CustomersView.as_view(), name="customers"),
    path("factors/", FactorListView.as_view(), name="factor_list"),
    path("factors/detail/", FactorDetailView.as_view(), name="factor_detail"),
    path("factors/new/", FactorCreateView.as_view(), name="factor_create"),
    path("offline/", OfflineView.as_view(), name="offline"),
]
