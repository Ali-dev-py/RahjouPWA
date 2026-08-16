from django.views.generic import TemplateView
from .models import *


class SplashView(TemplateView):
    template_name = "core/splash.html"


class LoginView(TemplateView):
    template_name = "core/login.html"


class DashboardView(TemplateView):
    template_name = "core/dashboard.html"
    
    
class CustomersView(TemplateView):
    template_name = "core/customers.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["customers"] = Tblcustomer.objects.using('plus').all()
        return context


class FactorListView(TemplateView):
    template_name = "core/factor_list.html"


class FactorDetailView(TemplateView):
    template_name = "core/factor_detail.html"


class FactorCreateView(TemplateView):
    template_name = "core/factor_create.html"


class OfflineView(TemplateView):
    template_name = "core/offline.html"
