import io
import os
import uuid
import json
import jdatetime
import base64
from datetime import datetime
from decimal import Decimal, InvalidOperation
from playwright.sync_api import sync_playwright

from django.contrib import messages
from django.conf import settings
from urllib.parse import quote
from django.contrib.staticfiles import finders
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import DecimalField, F, Sum, Value, Q, Max
from django.db.models.functions import Coalesce
from django.shortcuts import redirect, render, get_object_or_404
from django.db import transaction
from django.urls import reverse
from django.http import HttpResponse, Http404
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
from django.template.loader import render_to_string

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


class CustomerCreateView(PlusLoginRequiredMixin, View):
    template_name = "core/customer_create.html"

    def get(self, request, *args, **kwargs):
        groups = Customergroup.objects.using("plus").all().order_by("groupname")
        return render(request, self.template_name, {"groups": groups})

    def post(self, request, *args, **kwargs):
        custname = request.POST.get("custname", "").strip()
        phone = request.POST.get("phone", "").strip()
        address = request.POST.get("address", "").strip()
        selected_group_id = request.POST.get("customer_group", "").strip()

        groups = Customergroup.objects.using("plus").all().order_by("groupname")

        # Validation (only custname and customer_group are required)
        errors = []
        if not custname:
            errors.append("نام مشتری الزامی است.")
        if not selected_group_id:
            errors.append("انتخاب گروه مشتری الزامی است.")

        group = (
            Customergroup.objects.using("plus")
            .filter(gcustomergroupid=selected_group_id)
            .first()
        )

        if selected_group_id and not group:
            errors.append("گروه مشتری انتخاب‌شده نامعتبر است.")

        if errors:
            return render(
                request,
                self.template_name,
                {
                    "groups": groups,
                    "errors": errors,
                    "custname": custname,
                    "phone": phone,
                    "address": address,
                    "selected_group_id": selected_group_id,
                },
            )

        try:
            # 1. Retrieve current user's username via plus_user
            plus_user = getattr(request, "plus_user", None)
            created_by = getattr(plus_user, "uname", "") if plus_user else ""

            # 2. Calculate next CustNo strictly lower than 1900
            existing_custnos = (
                Tblcustomer.objects.using("plus")
                .exclude(custno__isnull=True)
                .exclude(custno="")
                .values_list("custno", flat=True)
            )

            max_custno = 0
            for val in existing_custnos:
                clean_val = str(val).strip()
                if clean_val.isdigit():
                    num = int(clean_val)
                    if num < 1900 and num > max_custno:
                        max_custno = num

            next_custno_int = (max_custno + 1) if max_custno > 0 else 1

            if next_custno_int >= 1900:
                return render(
                    request,
                    self.template_name,
                    {
                        "groups": groups,
                        "errors": ["کد مشتری نمی‌تواند بیشتر یا مساوی ۱۹۰۰ باشد. سقف شماره مشتری پر شده است."],
                        "custname": custname,
                        "phone": phone,
                        "address": address,
                        "selected_group_id": selected_group_id,
                    },
                )

            next_custno = str(next_custno_int)

            # 3. Generate UUIDs and Shamsi date
            new_gcustomerid = str(uuid.uuid4()).upper()
            new_gsubdetailid = str(uuid.uuid4()).upper()  # New UUID for GSubDetailID
            new_gc2g_id = str(uuid.uuid4()).upper()
            shamsi_date = jdatetime.date.today().strftime("%Y/%m/%d")

            with transaction.atomic(using="plus"):
                # 4. Insert customer using Django ORM
                new_customer = Tblcustomer.objects.using("plus").create(
                    custno=next_custno,
                    custname=custname,
                    customername=custname,
                    phone=phone,
                    mobile=phone,
                    address=address,
                    status="1",
                    salestatus=1,
                    credit=0,
                    debit=0,
                    visitpriod=0,
                    customertypecode=2,
                    customertaxtype=3,
                    gprovinceid= 'ECB49B7B-30FC-472C-A1AA-45E00F329135',
                    gcityid='A8218140-B1D0-42DB-B4AD-1D5EAF501EC2',
                    registerdate=timezone.now(),
                    createddate=shamsi_date,
                    createdby=created_by,
                    gsubdetailid=new_gsubdetailid,  # Stored here
                    gcustomerid=new_gcustomerid,
                    gcompanyid=group.gcompanyid,
                )

                # 5. Insert into Customer2Group
                Customer2Group.objects.using("plus").create(
                    customergroupid=group.customergroupid,
                    customerid=new_customer.customerid,
                    gcustomerid=new_gcustomerid,
                    gcustomergroupid=group.gcustomergroupid,
                    gcustomer2groupid=new_gc2g_id,
                    gcompanyid=group.gcompanyid,
                )

            # messages.success(request, f"مشتری «{custname}» با موفقیت افزوده شد.")
            return redirect("core:customers")

        except Exception as exc:
            return render(
                request,
                self.template_name,
                {
                    "groups": groups,
                    "errors": [f"خطا در ثبت اطلاعات: {str(exc)}"],
                    "custname": custname,
                    "phone": phone,
                    "address": address,
                    "selected_group_id": selected_group_id,
                },
            )


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

        # 2. Fetch Branches
        branches = (
            Branches.objects.using("plus")
            .values("gbranchid", "branchname", "branchcode")
            .order_by("branchname")
        )

        # 3. Fetch Inventories
        inventories = (
            Tblinv.objects.using("plus")
            .values("ginvid", "invname", "invcode")
            .order_by("invname")
        )

        # 4. Fetch Visitors (Deduplicated by GVisitorID)
        visitors_queryset = (
            ViewAllvisitors.objects.using("plus")
            .filter(Q(active=True) | Q(active__isnull=True))
            .values("gvisitorid", "vizitorname", "personname", "vizitorcode")
            .order_by("vizitorname", "personname")
        )
        visitors_list = []
        seen_visitors = set()
        for v in visitors_queryset:
            gid = str(v["gvisitorid"])
            if gid and gid not in seen_visitors:
                seen_visitors.add(gid)
                visitors_list.append(
                    {
                        "id": gid,
                        "name": v["vizitorname"]
                        or v["personname"]
                        or "بدون نام",
                        "code": v["vizitorcode"] or "",
                    }
                )

        # 5. Fetch Prices from Statementprice mapped by gkalaid
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

        # 6. Fetch Products (Tblkala) & apply StatementPrice
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
        context["branches"] = branches
        context["inventories"] = inventories
        context["visitors"] = visitors_list
        return context

    def post(self, request, *args, **kwargs):
        customer_id = request.POST.get("customer_id", "").strip()
        branch_id = request.POST.get("branch_id", "").strip()
        inv_id = request.POST.get("inv_id", "").strip()
        visitor_id = request.POST.get("visitor_id", "").strip()
        product_ids = request.POST.getlist("product_id[]")
        quantities = request.POST.getlist("quantity[]")
        prices = request.POST.getlist("price[]")

        # 1. Validation
        if not customer_id:
            messages.error(request, "لطفاً مشتری را انتخاب کنید.")
            return self.get(request, *args, **kwargs)

        if not branch_id:
            messages.error(request, "لطفاً شعبه را انتخاب کنید.")
            return self.get(request, *args, **kwargs)

        if not inv_id:
            messages.error(request, "لطفاً انبار را انتخاب کنید.")
            return self.get(request, *args, **kwargs)

        if not visitor_id:
            messages.error(request, "لطفاً ویزیتور را انتخاب کنید.")
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
                current_time_str = datetime.now().strftime("%H:%M:%S")

                # Fetch visitor details safely using .values()
                visitor_data = (
                    ViewAllvisitors.objects.using("plus")
                    .filter(gvisitorid=visitor_id)
                    .values("visitorid", "poorsant")
                    .first()
                )

                visitor_int_id = (
                    visitor_data.get("visitorid") if visitor_data else None
                )
                visitor_poorsant = (
                    visitor_data.get("poorsant")
                    if (
                        visitor_data
                        and visitor_data.get("poorsant") is not None
                    )
                    else Decimal("0.00")
                )

                # Next Factor Number
                last_factor = (
                    Salerequestmaster.objects.using("plus")
                    .filter(accyear=acc_year)
                    .order_by("-salerequestno")
                    .values("salerequestno")
                    .first()
                )

                last_no = last_factor.get("salerequestno") if last_factor else None
                if last_no and str(last_no).isdigit():
                    next_factor_no = f"{int(last_no) + 1:06d}"
                else:
                    next_factor_no = "000001"

                master_guid = str(uuid.uuid4()).upper()
                current_user_gucode = request.session.get("user_id")

                # A. Create Master Record
                master = Salerequestmaster.objects.using("plus").create(
                    salerequestno=next_factor_no,
                    atfno=next_factor_no,                      # Same as SaleRequestNo
                    receipttypecode=1,                         # 1
                    typesalecode=7,                            # 7
                    transferlocationcode=3,                    # 3
                    ispersonal=False,                          # 0 (False for bit/boolean)
                    salerequestdate=jalali_date_str,
                    createddate=jalali_date_str,
                    createdtime=current_time_str,
                    tahvildate=jalali_date_str,
                    accyear=acc_year,
                    gsalerequestmasterid=master_guid,
                    gcustomerid=customer_id,
                    gbranchid=branch_id,
                    ginvid=inv_id,
                    visitorid=visitor_int_id,
                    gcreatedby=current_user_gucode,
                    forcevat=True,
                    salerequesttypecode=1,
                    salerequeststatuscode=1,
                    currencyrate=Decimal("1.0000"),
                )

                generated_master_id = master.salerequestmasterid

                # B. Create SaleRequestToVisitor Record
                max_visitor_rel_id = (
                    Salerequesttovisitor.objects.using("plus").aggregate(
                        max_id=Max("salerequesttovisitorid")
                    )["max_id"]
                    or 0
                )
                next_visitor_rel_id = max_visitor_rel_id + 1
                srv_guid = str(uuid.uuid4()).upper()

                srv_fields = {f.name for f in Salerequesttovisitor._meta.get_fields()}
                srv_kwargs = {
                    "salerequesttovisitorid": next_visitor_rel_id,
                    "gsalerequesttovisitorid": srv_guid,
                    "gvisitorid": visitor_id,
                    "porsant": visitor_poorsant,
                }

                if "gsalerequestmasterid" in srv_fields:
                    srv_kwargs["gsalerequestmasterid"] = master_guid
                if "gsalerequestid" in srv_fields:
                    srv_kwargs["gsalerequestid"] = master_guid

                if "salerequestmasterid" in srv_fields:
                    srv_kwargs["salerequestmasterid"] = generated_master_id
                if "salerequestid" in srv_fields:
                    srv_kwargs["salerequestid"] = generated_master_id

                if "visitorid" in srv_fields and visitor_int_id:
                    srv_kwargs["visitorid"] = visitor_int_id

                Salerequesttovisitor.objects.using("plus").create(**srv_kwargs)

                # C. Create Detail Line Items
                detail_instances = []
                for index, item in enumerate(valid_items, start=1):
                    detail_guid = str(uuid.uuid4()).upper()
                    unique_id = str(uuid.uuid4()).upper()

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

            return redirect("core:factor_list")

        except Exception as e:
            messages.error(request, f"خطا در ثبت درخواست فروش: {str(e)}")
            return self.get(request, *args, **kwargs)


class OfflineView(PlusLoginRequiredMixin, TemplateView):
    template_name = "core/offline.html"


class FactorPDFView(PlusLoginRequiredMixin, View):    
    def get(self, request, pk=None, *args, **kwargs):
        factor_id = pk or request.GET.get("id")
        if not factor_id:
            raise Http404("فاکتور مورد نظر یافت نشد.")

        # 1. Fetch Master Record
        master = (
            Salerequestmaster.objects.using("plus")
            .filter(gsalerequestmasterid=factor_id)
            .first()
        )
        if not master:
            raise Http404("فاکتور مورد نظر یافت نشد.")

        # 2. Fetch Customer Info
        customer = None
        if master.gcustomerid:
            customer = (
                Tblcustomer.objects.using("plus")
                .filter(gcustomerid=master.gcustomerid)
                .first()
            )

        # 3. Fetch Line Items & Products
        details = (
            Salerequestdetail.objects.using("plus")
            .filter(gsalerequestmasterid=master.gsalerequestmasterid)
            .order_by("rowid")
        )

        kala_ids = [d.gkalaid for d in details if d.gkalaid]
        kala_map = {}
        if kala_ids:
            kalas = Tblkala.objects.using("plus").filter(gkalaid__in=kala_ids)
            kala_map = {k.gkalaid: k for k in kalas}

        items = []
        total_quantity = 0
        subtotal = 0
        total_discount = 0

        for idx, d in enumerate(details, start=1):
            kala = kala_map.get(d.gkalaid)
            qty = float(d.quantity or 0)
            price = float(d.unitprice or 0)
            discount = float(d.discount or 0)
            gross = qty * price
            row_total = gross - discount

            total_quantity += qty
            subtotal += gross
            total_discount += discount

            items.append({
                "row_no": idx,
                "name": kala.kalaname if kala else (d.descript or "کالای نامشخص"),
                "quantity": int(qty) if qty.is_integer() else qty,
                "unit": kala.vahed1 if (kala and kala.vahed1) else "عدد",
                "unit_price": int(price),
                "discount": int(discount),
                "row_total": int(row_total),
            })

        payable = subtotal - total_discount

        # 4. Read & Encode Logo to Base64
        logo_base64 = ""
        logo_path = finders.find("images/logo.png")
        if not logo_path:
            alt_path = os.path.join(settings.BASE_DIR, "static", "images", "logo.png")
            if os.path.exists(alt_path):
                logo_path = alt_path

        if logo_path and os.path.exists(logo_path):
            with open(logo_path, "rb") as image_file:
                logo_base64 = base64.b64encode(image_file.read()).decode("utf-8")

        context = {
            "master": master,
            "customer": customer,
            "items": items,
            "total_quantity": int(total_quantity) if isinstance(total_quantity, float) and total_quantity.is_integer() else total_quantity,
            "subtotal": int(subtotal),
            "total_discount": int(total_discount),
            "payable": int(payable),
            "logo_base64": logo_base64,
            "seller_name": "رهجو پلاس",
            "seller_phone": "",
            "seller_address": "",
            "bank_card": "۶۲۱۹۸۶۱۰۹۲۳۹۹۴۲۶",
            "bank_sheba": "IR۵۲۰۵۶۰۲۱۳۷۸۰۰۰۵۳۱۱۸۰۰۰۰۱",
            "bank_owner": "خانم سپیده جیحانی",
            "bank_name": "بانک سامان",
        }

        # 5. Render HTML to String
        # مطمئن شوید نام فایل در پوشه templates/core برابر factor_pdf.html است
        html_string = render_to_string("core/factor_pdf.html", context, request=request)

        # 6. Generate A5 PDF via Playwright (بخش مفقود شده که باعث ارور می‌شد)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html_string, wait_until="networkidle")
            
            pdf_bytes = page.pdf(
                format="A5",
                print_background=True,
                margin={
                    "top": "6mm",
                    "bottom": "6mm",
                    "left": "7mm",
                    "right": "7mm",
                },
            )
            browser.close()

        # 7. ساخت پاسخ دانلود
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        factor_no = master.salerequestno or "factor"
        filename = f"Factor-{factor_no}.pdf"
        encoded_filename = quote(filename)

        # تنظیم هدر attachment جهت دانلود مستقیم
        response["Content-Disposition"] = (
            f'attachment; filename="{filename}"; filename*=UTF-8\'\'{encoded_filename}'
        )
        return response
    
    