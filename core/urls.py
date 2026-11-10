from django.urls import path
from .views import *

app_name = "core"

urlpatterns = [
    path("", SplashView.as_view(), name="splash"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("customers/", CustomersView.as_view(), name="customers"),
    path("customers/create/", CustomerCreateView.as_view(), name="customer_create"),
    path("customers/<str:pk>/edit/", CustomerEditView.as_view(), name="customer_edit"),
    path("sale-requests/", SaleRequestListView.as_view(), name="sale_request_list"),
    path("sale-requests/detail/", SaleRequestDetailView.as_view(), name="sale_request_detail"),
    path("sale-requests/detail/<str:pk>/", SaleRequestDetailView.as_view(), name="sale_request_detail"),
    path("sale-requests/<str:pk>/pdf/", SaleRequestPDFView.as_view(), name="sale_request_pdf"),
    path("sale-requests/new/", SaleRequestCreateView.as_view(), name="sale_request_create"),
    path("offline/", OfflineView.as_view(), name="offline"),
]
