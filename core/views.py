import uuid
import json
import jdatetime
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import DecimalField, F, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import redirect, render
from django.db import transaction
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from .models import *


# MIXINS
class PlusLoginRequiredMixin:
    """Ensures user is authenticated and attaches the full TuaUser model instance to request.plus_user"""

    def dispatch(self, request, *args, **kwargs):
        user_gucode = request.session.get("user_id")

        if not user_gucode:
            login_url = reverse("core:login")
            # Avoid loop if current path is already login
            if request.path == login_url:
                return super().dispatch(request, *args, **kwargs)
            return redirect(f"{login_url}?next={request.path}")

        # Fetch the complete user object from 'plus' database
        user = (
            TuaUser.objects.using("plus")
            .filter(gucode=user_gucode, uactive=True)
            .first()
        )

        if not user:
            request.session.flush()
            return redirect("core:login")

        # Attach the full TuaUser object to the request
        request.plus_user = user
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Automatically pass current_user to all template contexts"""
        context = super().get_context_data(**kwargs)
        context["current_user"] = getattr(self.request, "plus_user", None)
        return context


# CBV VIEWS
class SplashView(TemplateView):
    template_name = "core/splash.html"


class LoginView(View):
    template_name = "core/login.html"

    def get(self, request, *args, **kwargs):
        # If user is already logged in, redirect to dashboard
        if request.session.get("user_id"):
            return redirect("core:dashboard")
        return render(request, self.template_name)

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        if not username or not password:
            messages.error(request, "لطفاً نام کاربری و رمز عبور را وارد کنید.")
            return render(
                request, self.template_name, {"entered_username": username}
            )

        # Query TuaUser on 'plus' database
        user = (
            TuaUser.objects.using("plus")
            .filter(uid=username, uactive=True)
            .first()
        )

        # Check credentials (uid and pluspass)
        if user and user.pluspass == password:
            # Store essential user data in the session
            request.session["user_id"] = str(user.gucode)
            request.session["user_uid"] = user.uid
            request.session["user_name"] = (
                user.uname or user.utitle or user.uid
            )
            request.session["is_admin"] = bool(user.isadmin)

            # Redirect to 'next' url or dashboard
            next_url = request.GET.get("next") or "core:dashboard"
            return redirect(next_url)
        else:
            messages.error(request, "نام کاربری یا رمز عبور اشتباه است.")
            return render(
                request, self.template_name, {"entered_username": username}
            )


class LogoutView(PlusLoginRequiredMixin, View):

    def get(self, request, *args, **kwargs):
        request.session.flush()  # Clear all session data
        return redirect("core:login")


class DashboardView(PlusLoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # 1. Get logged-in user's gucode
        user_gucode = self.request.session.get("user_id")
        if not user_gucode and hasattr(self.request, "plus_user"):
            user_gucode = str(self.request.plus_user.gucode)

        if not user_gucode:
            context["recent_activities"] = []
            return context

        # 2. Fetch Status Map for styling and text
        statuses = Salerequeststatus.objects.using("plus").all()
        status_map = {
            s.salerequeststatuscode: s.salerequeststatusname for s in statuses
        }

        # 3. Query Last 10 Sale Requests for the current user
        recent_masters = list(
            Salerequestmaster.objects.using("plus")
            .filter(gcreatedby=user_gucode)
            .order_by("-salerequestdate", "-salerequestno")[:10]
        )

        recent_activities = []
        if recent_masters:
            master_guids = [m.gsalerequestmasterid for m in recent_masters]
            customer_guids = [
                m.gcustomerid for m in recent_masters if m.gcustomerid
            ]

            # Batch Fetch Customers (Single Query - No N+1)
            customer_map = {}
            if customer_guids:
                customers = Tblcustomer.objects.using("plus").filter(
                    gcustomerid__in=customer_guids
                )
                customer_map = {c.gcustomerid: c.custname for c in customers}

            # Batch Calculate Total Price per Factor (Single Query)
            # Total = (Quantity * UnitPrice) - Discount
            details_agg = (
                Salerequestdetail.objects.using("plus")
                .filter(gsalerequestmasterid__in=master_guids)
                .values("gsalerequestmasterid")
                .annotate(
                    total=Sum(
                        (F("quantity") * F("unitprice"))
                        - Coalesce(F("discount"), Value(0)),
                        output_field=DecimalField(),
                    )
                )
            )
            totals_map = {
                d["gsalerequestmasterid"]: int(d["total"] or 0)
                for d in details_agg
            }

            # Build list
            for m in recent_masters:
                customer_name = (
                    customer_map.get(m.gcustomerid)
                    or m.requestman
                    or "مشتری نامشخص"
                )
                status_name = status_map.get(
                    m.salerequeststatuscode, "ثبت شده"
                )
                style = get_status_style(status_name)

                recent_activities.append(
                    {
                        "id": m.gsalerequestmasterid,
                        "factor_no": m.salerequestno,
                        "date": m.salerequestdate or m.createddate or "-",
                        "customer_name": customer_name,
                        "total_amount": totals_map.get(
                            m.gsalerequestmasterid, 0
                        ),
                        "status_name": status_name,
                        "chip_class": style["chip_class"],
                        "dot_class": style["dot_class"],
                    }
                )

        context["recent_activities"] = recent_activities

        # -------------------------------------------------------------
        # 4. Calculate Top Summary Cards Data
        # -------------------------------------------------------------
        today_jalali = jdatetime.date.today().strftime("%Y/%m/%d")

        # Today's masters by this user
        today_master_guids = list(
            Salerequestmaster.objects.using("plus")
            .filter(gcreatedby=user_gucode, salerequestdate=today_jalali)
            .values_list("gsalerequestmasterid", flat=True)
        )

        today_total_sum = 0
        if today_master_guids:
            sum_agg = Salerequestdetail.objects.using("plus").filter(
                gsalerequestmasterid__in=today_master_guids
            ).aggregate(
                total=Sum(
                    (F("quantity") * F("unitprice"))
                    - Coalesce(F("discount"), Value(0)),
                    output_field=DecimalField(),
                )
            )[
                "total"
            ] or Decimal(
                "0"
            )
            today_total_sum = int(sum_agg)

        context["today_sales_total"] = today_total_sum
        context["pending_count"] = (
            Salerequestmaster.objects.using("plus")
            .filter(gcreatedby=user_gucode, salerequeststatuscode=1)
            .count()
        )
        context["total_requests_count"] = (
            Salerequestmaster.objects.using("plus")
            .filter(gcreatedby=user_gucode)
            .count()
        )

        return context
    
    
class CustomersView(PlusLoginRequiredMixin, TemplateView):
    template_name = "core/customers.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        sanad_qs = Tblsanadrad.objects.using("plus").filter(
            gsubdetailid__isnull=False,
            createddate__gte=datetime(2026, 3, 21)
        )
        
        balances = (
            sanad_qs.values("gsubdetailid")
            .annotate(
                total_debit=Sum("debit"),
                total_credit=Sum("credit"),
            )
        )

        balance_map = {}
        for row in balances:
            raw_gid = row["gsubdetailid"]
            if raw_gid:
                gid = str(raw_gid).strip().lower()
                debit = row["total_debit"] or 0
                credit = row["total_credit"] or 0
                balance_map[gid] = debit - credit

        customers = list(
            Tblcustomer.objects.using("plus")
            .all()
            .order_by("custname")
        )

        for customer in customers:
            if customer.gsubdetailid:
                cust_gid = str(customer.gsubdetailid).strip().lower()
                customer.hesab = balance_map.get(cust_gid, 0)
            else:
                customer.hesab = 0

        context["customers"] = customers
        return context


def get_status_style(status_name):
    """Maps status names to visual styles."""
    if not status_name:
        return {"chip_class": "status-chip--pending", "dot_class": "status-dot"}

    if any(kw in status_name for kw in ["تایید", "ثبت", "موفق"]):
        return {
            "chip_class": "status-chip--approved",
            "dot_class": "status-dot",
        }
    elif any(kw in status_name for kw in ["پرداخت", "تسویه"]):
        return {"chip_class": "status-chip--paid", "dot_class": ""}
    elif any(kw in status_name for kw in ["ابطال", "رد", "حذف"]):
        return {"chip_class": "status-chip--rejected", "dot_class": ""}
    else:
        return {"chip_class": "status-chip--pending", "dot_class": "status-dot"}
    
    
class FactorListView(PlusLoginRequiredMixin, TemplateView):
    template_name = "core/factor_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        query = self.request.GET.get("q", "").strip()
        status_filter = self.request.GET.get("status", "all").strip()

        # 1. Fetch all available statuses from DB
        statuses = (
            Salerequeststatus.objects.using("plus")
            .all()
            .order_by("salerequeststatuscode")
        )
        status_map = {
            s.salerequeststatuscode: s.salerequeststatusname for s in statuses
        }

        # 2. Fetch Sale Requests QuerySet
        factors_qs = (
            Salerequestmaster.objects.using("plus")
            .all()
            .order_by("-salerequestdate", "-salerequestno")
        )

        # Filter by selected status tab (if not 'all')
        if status_filter != "all" and status_filter.isdigit():
            factors_qs = factors_qs.filter(
                salerequeststatuscode=int(status_filter)
            )

        # Limit to top 150 records for optimal performance
        factors_list = list(factors_qs[:150])

        # 3. Batch Fetch Customer Names (prevents N+1 query issue)
        customer_ids = [f.gcustomerid for f in factors_list if f.gcustomerid]
        customer_map = {}
        if customer_ids:
            customers = Tblcustomer.objects.using("plus").filter(
                gcustomerid__in=customer_ids
            )
            customer_map = {c.gcustomerid: c.custname for c in customers}

        # 4. Construct Final Data List
        factors = []
        for f in factors_list:
            customer_name = (
                customer_map.get(f.gcustomerid)
                or f.requestman
                or "مشتری نامشخص"
            )

            # Search by keyword (Factor No or Customer Name)
            if (
                query
                and query not in f.salerequestno
                and query not in customer_name
            ):
                continue

            status_name = status_map.get(f.salerequeststatuscode, "نامشخص")
            style = get_status_style(status_name)

            factors.append(
                {
                    "id": f.gsalerequestmasterid,
                    "number": f.salerequestno,
                    "date": f.salerequestdate or f.createddate or "-",
                    "customer_name": customer_name,
                    "status_code": f.salerequeststatuscode,
                    "status_name": status_name,
                    "chip_class": style["chip_class"],
                    "dot_class": style["dot_class"],
                }
            )

        context["factors"] = factors
        context["statuses"] = statuses
        context["current_status"] = status_filter
        context["query"] = query
        return context


class FactorDetailView(PlusLoginRequiredMixin, TemplateView):
    template_name = "core/factor_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # 1. Retrieve Factor ID from URL kwargs or GET parameters
        factor_id = self.kwargs.get("pk") or self.request.GET.get("id")

        if factor_id:
            master = (
                Salerequestmaster.objects.using("plus")
                .filter(gsalerequestmasterid=factor_id)
                .first()
            )
        else:
            # Fallback to the latest factor if no ID is passed
            master = (
                Salerequestmaster.objects.using("plus")
                .order_by("-salerequestdate", "-salerequestno")
                .first()
            )

        if not master:
            context["factor_found"] = False
            return context

        context["factor_found"] = True
        context["master"] = master

        # 2. Fetch Status
        status_obj = (
            Salerequeststatus.objects.using("plus")
            .filter(salerequeststatuscode=master.salerequeststatuscode)
            .first()
        )
        context["status_name"] = (
            status_obj.salerequeststatusname if status_obj else "ثبت شده"
        )

        # 3. Fetch Customer Details
        customer = None
        if master.gcustomerid:
            customer = (
                Tblcustomer.objects.using("plus")
                .filter(gcustomerid=master.gcustomerid)
                .first()
            )
        context["customer"] = customer

        # 4. Fetch Factor Line Items & Products
        details = (
            Salerequestdetail.objects.using("plus")
            .filter(gsalerequestmasterid=master.gsalerequestmasterid)
            .order_by("rowid")
        )

        # Batch query Tblkala to prevent N+1 query issue
        kala_ids = [d.gkalaid for d in details if d.gkalaid]
        kala_map = {}
        if kala_ids:
            kalas = Tblkala.objects.using("plus").filter(gkalaid__in=kala_ids)
            kala_map = {k.gkalaid: k for k in kalas}

        items = []
        subtotal = 0
        total_discount = 0

        for d in details:
            kala = kala_map.get(d.gkalaid)
            qty = float(d.quantity or 0)
            price = float(d.unitprice or 0)
            discount = float(d.discount or 0)
            row_total = (qty * price) - discount

            subtotal += qty * price
            total_discount += discount

            items.append(
                {
                    "name": kala.kalaname
                    if kala
                    else (d.descript or "کالای نامشخص"),
                    "code": kala.kalano if kala else "",
                    "unit": kala.vahed1
                    if (kala and kala.vahed1)
                    else (d.descript or "عدد"),
                    "quantity": int(qty) if qty.is_integer() else qty,
                    "unit_price": int(price),
                    "discount": int(discount),
                    "row_total": int(row_total),
                }
            )

        context["items"] = items
        context["subtotal"] = int(subtotal)
        context["total_discount"] = int(total_discount)
        context["total_payable"] = int(subtotal - total_discount)

        return context
    

class FactorCreateView(PlusLoginRequiredMixin, TemplateView):
    template_name = "core/factor_create.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # 1. Fetch Customers
        customers_queryset = (
            Tblcustomer.objects.using("plus")
            .values("gcustomerid", "custname", "custno", "mobile", "phone")
            .order_by("custname")
        )
        customers_list = [
            {
                "id": str(c["gcustomerid"]),
                "name": c["custname"] or "",
                "code": c["custno"] or "",
                "phone": c["mobile"] or c["phone"] or "",
            }
            for c in customers_queryset
        ]

        # 2. Fetch Prices from Statementprice mapped by gkalaid
        statement_prices_qs = (
            Statementprice.objects.using("plus")
            .filter(gkalaid__isnull=False)
            .values("gkalaid", "price")
            .order_by("-statementpriceid")
        )

        statement_price_map = {}
        for sp in statement_prices_qs:
            gid = str(sp["gkalaid"])
            if (
                gid
                and (gid not in statement_price_map)
                and sp["price"] is not None
            ):
                statement_price_map[gid] = int(sp["price"])

        # 3. Fetch Products (Tblkala) & apply StatementPrice
        products_queryset = (
            Tblkala.objects.using("plus")
            .values("gkalaid", "kalaname", "kalano", "vahed1", "selprice")
            .order_by("kalaname")
        )

        products_list = []
        for p in products_queryset:
            gid = str(p["gkalaid"])

            if gid in statement_price_map:
                final_price = statement_price_map[gid]
            elif p["selprice"] is not None:
                final_price = int(p["selprice"])
            else:
                final_price = 0

            products_list.append(
                {
                    "id": gid,
                    "name": p["kalaname"] or "",
                    "code": p["kalano"] or "",
                    "unit": p["vahed1"] or "عدد",
                    "price": final_price,
                }
            )

        context["customers_json"] = json.dumps(
            customers_list, cls=DjangoJSONEncoder
        )
        context["products_json"] = json.dumps(
            products_list, cls=DjangoJSONEncoder
        )
        return context

    def post(self, request, *args, **kwargs):
        customer_id = request.POST.get("customer_id", "").strip()
        product_ids = request.POST.getlist("product_id[]")
        quantities = request.POST.getlist("quantity[]")
        prices = request.POST.getlist("price[]")

        # 1. Validation
        if not customer_id:
            messages.error(request, "لطفاً مشتری را انتخاب کنید.")
            return self.get(request, *args, **kwargs)

        valid_items = []
        for p_id, qty, prc in zip(product_ids, quantities, prices):
            p_id = p_id.strip()
            if not p_id:
                continue

            try:
                dec_qty = Decimal(str(qty))
                dec_price = Decimal(str(prc))
                if dec_qty <= 0:
                    continue
                valid_items.append(
                    {
                        "product_id": p_id,
                        "quantity": dec_qty,
                        "price": dec_price,
                    }
                )
            except (InvalidOperation, ValueError):
                continue

        if not valid_items:
            messages.error(
                request, "حداقل باید یک کالا با تعداد معتبر انتخاب شود."
            )
            return self.get(request, *args, **kwargs)

        # 2. Database Insertion with Atomic Transaction
        try:
            with transaction.atomic(using="plus"):
                today_jalali = jdatetime.date.today()
                jalali_date_str = today_jalali.strftime("%Y/%m/%d")
                acc_year = today_jalali.year

                # SaleRequestNo formatting (e.g., 00001, 00002)
                last_factor = (
                    Salerequestmaster.objects.using("plus")
                    .filter(accyear=acc_year)
                    .order_by("-salerequestno")
                    .first()
                )

                if (
                    last_factor
                    and last_factor.salerequestno
                    and last_factor.salerequestno.isdigit()
                ):
                    next_factor_no = (
                        f"{int(last_factor.salerequestno) + 1:05d}"
                    )
                else:
                    next_factor_no = "00001"

                master_guid = str(uuid.uuid4()).upper()
                current_user_gucode = request.session.get("user_id")

                # Create Master (Notice: salerequestmasterid is omitted, SQL Server Identity generates it)
                master = Salerequestmaster.objects.using("plus").create(
                    salerequestno=next_factor_no,
                    salerequestdate=jalali_date_str,
                    createddate=jalali_date_str,
                    accyear=acc_year,
                    gsalerequestmasterid=master_guid,
                    gcustomerid=customer_id,
                    gcreatedby=current_user_gucode,
                    forcevat=True,
                    salerequesttypecode=1,
                    salerequeststatuscode=1,
                    currencyrate=Decimal("1.0000"),
                )

                # Get the generated auto-increment ID from the master record
                generated_master_id = master.salerequestmasterid

                # Create Detail Line Items
                detail_instances = []
                for index, item in enumerate(valid_items, start=1):
                    detail_guid = str(uuid.uuid4()).upper()
                    unique_id = str(uuid.uuid4()).upper()

                    # salerequestdetailid is omitted; SQL Server handles its identity
                    detail = Salerequestdetail(
                        salerequestmasterid=generated_master_id,
                        gsalerequestmasterid=master_guid,
                        gsalerequestdetailid=detail_guid,
                        uniqueid=unique_id,
                        gkalaid=item["product_id"],
                        quantity=item["quantity"],
                        unitprice=item["price"],
                        salerequestdetailstatuscode=1,
                        canchangeaward=False,
                        currencyrate=Decimal("1.0000"),
                        currencyprice=item["price"],
                        rowid=index,
                        kalamojodi=Decimal("0"),
                    )
                    detail_instances.append(detail)

                # Bulk insert items
                Salerequestdetail.objects.using("plus").bulk_create(
                    detail_instances
                )

            messages.success(
                request, f"درخواست فروش شماره {next_factor_no} با موفقیت ثبت شد."
            )
            return redirect("core:factor_list")

        except Exception as e:
            messages.error(request, f"خطا در ثبت درخواست فروش: {str(e)}")
            return self.get(request, *args, **kwargs)


class OfflineView(PlusLoginRequiredMixin, TemplateView):
    template_name = "core/offline.html"
