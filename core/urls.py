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
    path("customers/<str:pk>/", CustomerDetailView.as_view(), name="customer_detail"),
    path("sale-requests/", SaleRequestListView.as_view(), name="sale_request_list"),
    path("sale-requests/detail/", SaleRequestDetailView.as_view(), name="sale_request_detail"),
    path("sale-requests/detail/<str:pk>/", SaleRequestDetailView.as_view(), name="sale_request_detail"),
    path("sale-requests/<str:pk>/edit/", SaleRequestEditView.as_view(), name="sale_request_edit"),
    path("sale-requests/<str:pk>/delete/", SaleRequestDeleteView.as_view(), name="sale_request_delete"),
    path("sale-requests/<str:pk>/shortages/", SaleRequestShortagesView.as_view(), name="sale_request_shortages"),
    path("sale-requests/<str:pk>/pdf/", SaleRequestPDFView.as_view(), name="sale_request_pdf"),
    path("sale-requests/new/", SaleRequestCreateView.as_view(), name="sale_request_create"),
    path("pre-factors/", PreFactorListView.as_view(), name="pre_factor_list"),
    path("pre-factors/detail/", PreFactorDetailView.as_view(), name="pre_factor_detail"),
    path("pre-factors/detail/<str:pk>/", PreFactorDetailView.as_view(), name="pre_factor_detail"),
    path("pre-factors/<str:pk>/pdf/", PreFactorPDFView.as_view(), name="pre_factor_pdf"),
    path("factors/", FactorListView.as_view(), name="factor_list"),
    path("factors/detail/", FactorDetailView.as_view(), name="factor_detail"),
    path("factors/detail/<str:pk>/", FactorDetailView.as_view(), name="factor_detail"),
    path("factors/<str:pk>/pdf/", FactorPDFView.as_view(), name="factor_pdf"),
    path("offline/", OfflineView.as_view(), name="offline"),
]
