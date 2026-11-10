import io
import os
import uuid
import json
import jdatetime
import base64
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.conf import settings
from urllib.parse import quote
from django.contrib.staticfiles import finders
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import DecimalField, F, Sum, Value, Q, Max
from django.db.models.functions import Coalesce
from django.shortcuts import redirect, render, get_object_or_404
from django.db import DatabaseError, transaction
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

            # Batch Calculate Total Price per Sale Request (Single Query)
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
                        "sale_request_no": m.salerequestno,
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

        # Query Tblsanadrad directly without the sanad_qs filter conditions
        balances = (
            Tblsanadrad.objects.using("plus")
            .values("gsubdetailid")
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

        # Batch map GCustomerID -> GVisitorID via Visitortocustomer (No N+1)
        visitor_links = (
            Visitortocustomer.objects.using("plus")
            .filter(gcustomerid__isnull=False, gvisitorid__isnull=False)
            .values("gcustomerid", "gvisitorid")
        )
        customer_to_visitor_map = {}
        for link in visitor_links:
            raw_cust_gid = link.get("gcustomerid")
            raw_vis_gid = link.get("gvisitorid")
            if raw_cust_gid and raw_vis_gid:
                cust_key = str(raw_cust_gid).strip().lower()
                vis_key = str(raw_vis_gid).strip().lower()
                if cust_key and vis_key:
                    customer_to_visitor_map[cust_key] = vis_key

        # Batch map GVisitorID -> Visitor Name via ViewAllvisitors (No N+1)
        visitor_rows = ViewAllvisitors.objects.using("plus").values(
            "gvisitorid", "vizitorname", "personname", "active"
        )
        visitor_name_map = {}
        active_visitor_keys = set()
        for v in visitor_rows:
            raw_vis_gid = v.get("gvisitorid")
            if raw_vis_gid:
                vis_key = str(raw_vis_gid).strip().lower()
                v_name = (
                    v.get("vizitorname") or v.get("personname") or ""
                ).strip()
                if vis_key and v_name:
                    if vis_key not in visitor_name_map:
                        visitor_name_map[vis_key] = v_name
                    if v.get("active") is not False:
                        active_visitor_keys.add(vis_key)

        statuses = [
            {"code": "debtor", "name": "بدهکار"},
            {"code": "creditor", "name": "بستانکار"},
            {"code": "settled", "name": "تسویه"},
        ]
        status_alias_map = {
            "all": "all",
            "debtor": "debtor",
            "creditor": "creditor",
            "settled": "settled",
            "بدهکار": "debtor",
            "بستانکار": "creditor",
            "تسویه": "settled",
        }
        raw_status = self.request.GET.get("status", "all").strip()
        current_status = status_alias_map.get(raw_status, "all")

        assigned_visitor_keys = set()
        for idx, customer in enumerate(customers):
            customer.name_rank = idx
            raw_edit_pk = getattr(customer, "gcustomerid", None) or getattr(
                customer, "customerid", ""
            )
            customer.edit_pk = str(raw_edit_pk).strip()
            if customer.gsubdetailid:
                cust_gid = str(customer.gsubdetailid).strip().lower()
                customer.hesab = balance_map.get(cust_gid, 0)
            else:
                customer.hesab = 0
            customer.hesab_raw = str(customer.hesab)

            if customer.hesab > 0:
                customer.status_code = "debtor"
                customer.status_name = "بدهکار"
            elif customer.hesab < 0:
                customer.status_code = "creditor"
                customer.status_name = "بستانکار"
            else:
                customer.status_code = "settled"
                customer.status_name = "تسویه"

            resolved_visitor_name = ""
            resolved_visitor_code = "none"
            if getattr(customer, "gcustomerid", None):
                cust_id_key = str(customer.gcustomerid).strip().lower()
                linked_vis_key = customer_to_visitor_map.get(cust_id_key)
                if linked_vis_key and linked_vis_key in visitor_name_map:
                    resolved_visitor_name = visitor_name_map[linked_vis_key]
                    resolved_visitor_code = linked_vis_key
                    assigned_visitor_keys.add(linked_vis_key)

            customer.has_visitor = bool(resolved_visitor_name)
            customer.visitor_code = resolved_visitor_code
            customer.visitor_name = resolved_visitor_name or "بدون ویزیتور"

        ordering_options = [
            {"code": "name", "name": "بر اساس نام"},
            {"code": "debt_desc", "name": "بیشترین بدهی"},
            {"code": "debt_asc", "name": "کمترین بدهی"},
        ]
        order_alias_map = {
            "name": "name",
            "default": "name",
            "custname": "name",
            "بر اساس نام": "name",
            "debt_desc": "debt_desc",
            "debt": "debt_desc",
            "-debt": "debt_desc",
            "-hesab": "debt_desc",
            "بیشترین بدهی": "debt_desc",
            "debt_asc": "debt_asc",
            "+debt": "debt_asc",
            "hesab": "debt_asc",
            "کمترین بدهی": "debt_asc",
        }
        raw_order = (
            self.request.GET.get("order")
            or self.request.GET.get("sort")
            or "name"
        ).strip()
        current_order = order_alias_map.get(
            raw_order, order_alias_map.get(raw_order.lower(), "name")
        )

        if current_order == "debt_desc":
            customers.sort(key=lambda c: (-c.hesab, c.name_rank))
        elif current_order == "debt_asc":
            customers.sort(key=lambda c: (c.hesab, c.name_rank))

        filterable_visitor_keys = active_visitor_keys | assigned_visitor_keys
        visitors = sorted(
            [
                {"code": vis_key, "name": visitor_name_map[vis_key]}
                for vis_key in filterable_visitor_keys
                if vis_key in visitor_name_map
            ],
            key=lambda item: item["name"],
        )

        visitor_alias_map = {
            "all": "all",
            "none": "none",
            "بدون ویزیتور": "none",
        }
        for vis_item in visitors:
            visitor_alias_map[vis_item["code"]] = vis_item["code"]
            visitor_alias_map[vis_item["name"]] = vis_item["code"]

        raw_visitor = self.request.GET.get("visitor", "all").strip()
        current_visitor = visitor_alias_map.get(
            raw_visitor, visitor_alias_map.get(raw_visitor.lower(), "all")
        )

        for customer in customers:
            matches_status = (
                current_status == "all"
                or customer.status_code == current_status
            )
            matches_visitor = (
                current_visitor == "all"
                or customer.visitor_code == current_visitor
            )
            customer.is_initially_visible = matches_status and matches_visitor

        visible_customers_count = sum(
            1 for c in customers if c.is_initially_visible
        )

        context["customers"] = customers
        context["statuses"] = statuses
        context["current_status"] = current_status
        context["visitors"] = visitors
        context["current_visitor"] = current_visitor
        context["ordering_options"] = ordering_options
        context["current_order"] = current_order
        context["visible_customers_count"] = visible_customers_count
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


class CustomerEditView(PlusLoginRequiredMixin, View):
    template_name = "core/customer_edit.html"

    def _get_customer(self, pk):
        clean_pk = str(pk or "").strip()
        if not clean_pk:
            raise Http404("مشتری مورد نظر یافت نشد.")

        customer = (
            Tblcustomer.objects.using("plus")
            .filter(gcustomerid__iexact=clean_pk)
            .first()
        )
        if not customer and clean_pk.isdigit():
            customer = (
                Tblcustomer.objects.using("plus")
                .filter(customerid=int(clean_pk))
                .first()
            )
        if not customer:
            raise Http404("مشتری مورد نظر یافت نشد.")
        return customer

    def _get_customer_group_link(self, customer):
        c2g = None
        if getattr(customer, "gcustomerid", None):
            c2g = (
                Customer2Group.objects.using("plus")
                .filter(gcustomerid__iexact=str(customer.gcustomerid).strip())
                .first()
            )
        if not c2g and getattr(customer, "customerid", None):
            c2g = (
                Customer2Group.objects.using("plus")
                .filter(customerid=customer.customerid)
                .first()
            )
        return c2g

    def _resolve_edit_pk(self, customer, fallback_pk):
        raw = (
            getattr(customer, "gcustomerid", None)
            or getattr(customer, "customerid", None)
            or fallback_pk
        )
        return str(raw).strip()

    def get(self, request, pk, *args, **kwargs):
        customer = self._get_customer(pk)
        groups = list(
            Customergroup.objects.using("plus").all().order_by("groupname")
        )
        c2g = self._get_customer_group_link(customer)

        selected_group_id = ""
        if c2g:
            raw_group_gid = (c2g.gcustomergroupid or "").strip().lower()
            for grp in groups:
                grp_gid = (grp.gcustomergroupid or "").strip().lower()
                if (raw_group_gid and grp_gid == raw_group_gid) or (
                    c2g.customergroupid
                    and grp.customergroupid == c2g.customergroupid
                ):
                    selected_group_id = grp.gcustomergroupid
                    break

        initial_phone = (customer.mobile or customer.phone or "").strip()
        initial_address = (customer.address or "").strip()
        edit_pk = self._resolve_edit_pk(customer, pk)
        return_to = request.GET.get("from", "").strip()
        cancel_url = (
            reverse("core:customer_detail", kwargs={"pk": edit_pk})
            if return_to == "detail"
            else reverse("core:customers")
        )

        return render(
            request,
            self.template_name,
            {
                "customer": customer,
                "edit_pk": edit_pk,
                "groups": groups,
                "custname": customer.custname or "",
                "phone": initial_phone,
                "address": initial_address,
                "selected_group_id": selected_group_id,
                "return_to": return_to,
                "cancel_url": cancel_url,
            },
        )

    def post(self, request, pk, *args, **kwargs):
        customer = self._get_customer(pk)
        edit_pk = self._resolve_edit_pk(customer, pk)
        return_to = (
            request.POST.get("return_to") or request.GET.get("from") or ""
        ).strip()
        cancel_url = (
            reverse("core:customer_detail", kwargs={"pk": edit_pk})
            if return_to == "detail"
            else reverse("core:customers")
        )

        custname = request.POST.get("custname", "").strip()
        phone = request.POST.get("phone", "").strip()
        address = request.POST.get("address", "").strip()
        selected_group_id = request.POST.get("customer_group", "").strip()

        groups = list(
            Customergroup.objects.using("plus").all().order_by("groupname")
        )

        errors = []
        if not custname:
            errors.append("نام مشتری الزامی است.")
        if not selected_group_id:
            errors.append("انتخاب گروه مشتری الزامی است.")

        group = None
        if selected_group_id:
            group = (
                Customergroup.objects.using("plus")
                .filter(gcustomergroupid__iexact=selected_group_id)
                .first()
            )
            if not group:
                errors.append("گروه مشتری انتخاب‌شده نامعتبر است.")

        if errors:
            return render(
                request,
                self.template_name,
                {
                    "customer": customer,
                    "edit_pk": edit_pk,
                    "groups": groups,
                    "errors": errors,
                    "custname": custname,
                    "phone": phone,
                    "address": address,
                    "selected_group_id": selected_group_id,
                    "return_to": return_to,
                    "cancel_url": cancel_url,
                },
            )

        try:
            plus_user = getattr(request, "plus_user", None)
            updated_by = getattr(plus_user, "uname", "") if plus_user else ""
            shamsi_date = jdatetime.date.today().strftime("%Y/%m/%d")

            with transaction.atomic(using="plus"):
                update_fields = [
                    "custname",
                    "customername",
                    "phone",
                    "mobile",
                    "address",
                    "lastupdatedby",
                    "lastupdateddate",
                ]
                customer.custname = custname
                customer.customername = custname
                customer.phone = phone
                customer.mobile = phone
                customer.address = address
                customer.lastupdatedby = updated_by
                customer.lastupdateddate = shamsi_date

                if not getattr(customer, "gcustomerid", None):
                    customer.gcustomerid = str(uuid.uuid4()).upper()
                    update_fields.append("gcustomerid")

                customer.save(using="plus", update_fields=update_fields)

                c2g = self._get_customer_group_link(customer)
                if c2g:
                    c2g.customergroupid = group.customergroupid
                    c2g.gcustomergroupid = group.gcustomergroupid
                    if getattr(customer, "customerid", None):
                        c2g.customerid = customer.customerid
                    if (
                        getattr(customer, "gcustomerid", None)
                        and not c2g.gcustomerid
                    ):
                        c2g.gcustomerid = customer.gcustomerid
                    if group.gcompanyid:
                        c2g.gcompanyid = group.gcompanyid
                    c2g.save(
                        using="plus",
                        update_fields=[
                            "customergroupid",
                            "gcustomergroupid",
                            "customerid",
                            "gcustomerid",
                            "gcompanyid",
                        ],
                    )
                else:
                    Customer2Group.objects.using("plus").create(
                        customergroupid=group.customergroupid,
                        customerid=getattr(customer, "customerid", None),
                        gcustomerid=customer.gcustomerid,
                        gcustomergroupid=group.gcustomergroupid,
                        gcustomer2groupid=str(uuid.uuid4()).upper(),
                        gcompanyid=group.gcompanyid,
                    )

            if return_to == "detail":
                final_pk = self._resolve_edit_pk(customer, edit_pk)
                return redirect("core:customer_detail", pk=final_pk)
            return redirect("core:customers")

        except Exception as exc:
            return render(
                request,
                self.template_name,
                {
                    "customer": customer,
                    "edit_pk": edit_pk,
                    "groups": groups,
                    "errors": [f"خطا در ویرایش اطلاعات: {str(exc)}"],
                    "custname": custname,
                    "phone": phone,
                    "address": address,
                    "selected_group_id": selected_group_id,
                    "return_to": return_to,
                    "cancel_url": cancel_url,
                },
            )


_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


def _normalize_shamsi_date_and_sort_key(raw_date, raw_time=""):
    """Normalize Shamsi date/time strings and build a deterministic chronological sort tuple."""
    clean_date = str(raw_date or "").strip().translate(_DIGIT_TRANSLATION)
    clean_time = str(raw_time or "").strip().translate(_DIGIT_TRANSLATION)

    year, month, day = 0, 0, 0
    display_date = clean_date or "-"

    if clean_date and clean_date != "-":
        sep = "/" if "/" in clean_date else ("-" if "-" in clean_date else None)
        if sep:
            parts = [p.strip() for p in clean_date.split(sep)]
            if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                display_date = f"{year:04d}/{month:02d}/{day:02d}"

    hour, minute = 0, 0
    if clean_time and ":" in clean_time:
        t_parts = [p.strip() for p in clean_time.split(":")]
        if len(t_parts) >= 2 and t_parts[0].isdigit() and t_parts[1].isdigit():
            hour, minute = int(t_parts[0]), int(t_parts[1])

    has_valid_date = (year, month, day) != (0, 0, 0)
    iso_token = (
        f"{year:04d}{month:02d}{day:02d}_{hour:02d}{minute:02d}"
        if has_valid_date
        else ""
    )
    return display_date, has_valid_date, (year, month, day, hour, minute), iso_token


def _extract_raw_sanad_id(rad):
    """Extract raw GSanadID string from Tblsanadrad or mock object without lazy FK queries."""
    if hasattr(rad, "__dict__") and "gsanadid_id" in rad.__dict__:
        val = rad.__dict__.get("gsanadid_id")
        return str(val).strip() if val else ""
    if hasattr(rad, "gsanadid_id"):
        val = getattr(rad, "gsanadid_id", None)
        return str(val).strip() if val else ""
    raw_fk = getattr(rad, "gsanadid", None)
    if isinstance(raw_fk, str):
        return raw_fk.strip()
    if raw_fk is not None and hasattr(raw_fk, "gsanadid"):
        val = getattr(raw_fk, "gsanadid", None)
        return str(val).strip() if val else ""
    return ""


def _resolve_rad_date_and_time(rad, sanad=None):
    """Resolve Shamsi voucher date and time for a Tblsanadrad payment row."""
    raw_date = ""
    raw_time = ""

    if sanad is not None:
        raw_date = (
            getattr(sanad, "sanaddate", None)
            or getattr(sanad, "createddate", None)
            or ""
        ).strip()
        raw_time = (getattr(sanad, "sanadtime", None) or "").strip()

    rad_created = getattr(rad, "createddate", None)
    if not raw_date and rad_created:
        if hasattr(rad_created, "date"):
            greg_date = rad_created.date()
            raw_date = jdatetime.date.fromgregorian(date=greg_date).strftime(
                "%Y/%m/%d"
            )
            if not raw_time and hasattr(rad_created, "strftime"):
                raw_time = rad_created.strftime("%H:%M")
        elif hasattr(rad_created, "year") and hasattr(rad_created, "month"):
            raw_date = jdatetime.date.fromgregorian(date=rad_created).strftime(
                "%Y/%m/%d"
            )
        else:
            raw_date = str(rad_created).strip()[:10]

    return raw_date, raw_time


class CustomerDetailView(PlusLoginRequiredMixin, TemplateView):
    template_name = "core/customer_detail.html"

    def _get_customer(self, pk):
        clean_pk = str(pk or "").strip()
        if not clean_pk:
            raise Http404("مشتری مورد نظر یافت نشد.")

        customer = (
            Tblcustomer.objects.using("plus")
            .filter(gcustomerid__iexact=clean_pk)
            .first()
        )
        if not customer and clean_pk.isdigit():
            customer = (
                Tblcustomer.objects.using("plus")
                .filter(customerid=int(clean_pk))
                .first()
            )
        if not customer:
            raise Http404("مشتری مورد نظر یافت نشد.")
        return customer

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pk = self.kwargs.get("pk")
        customer = self._get_customer(pk)

        raw_pk = (
            getattr(customer, "gcustomerid", None)
            or getattr(customer, "customerid", None)
            or pk
        )
        customer_pk = str(raw_pk).strip()
        clean_cust_gid = str(getattr(customer, "gcustomerid", "") or "").strip()
        clean_sub_id = str(getattr(customer, "gsubdetailid", "") or "").strip()

        # 1. Customer Group & Assigned Visitor (DatabaseError-safe)
        group_name = ""
        try:
            c2g = None
            if clean_cust_gid:
                c2g = (
                    Customer2Group.objects.using("plus")
                    .filter(gcustomerid__iexact=clean_cust_gid)
                    .first()
                )
            if not c2g and getattr(customer, "customerid", None):
                c2g = (
                    Customer2Group.objects.using("plus")
                    .filter(customerid=customer.customerid)
                    .first()
                )
            if c2g:
                grp = None
                if getattr(c2g, "gcustomergroupid", None):
                    grp = (
                        Customergroup.objects.using("plus")
                        .filter(
                            gcustomergroupid__iexact=str(
                                c2g.gcustomergroupid
                            ).strip()
                        )
                        .first()
                    )
                if not grp and getattr(c2g, "customergroupid", None):
                    grp = (
                        Customergroup.objects.using("plus")
                        .filter(customergroupid=c2g.customergroupid)
                        .first()
                    )
                if grp and getattr(grp, "groupname", None):
                    group_name = grp.groupname
        except DatabaseError:
            group_name = ""

        visitor_name = "بدون ویزیتور"
        has_visitor = False
        if clean_cust_gid:
            try:
                vis_link = (
                    Visitortocustomer.objects.using("plus")
                    .filter(
                        gcustomerid__iexact=clean_cust_gid,
                        gvisitorid__isnull=False,
                    )
                    .first()
                )
                if vis_link and getattr(vis_link, "gvisitorid", None):
                    vis_gid = str(vis_link.gvisitorid).strip()
                    vis_obj = (
                        ViewAllvisitors.objects.using("plus")
                        .filter(gvisitorid__iexact=vis_gid)
                        .first()
                    )
                    if vis_obj:
                        resolved_vname = (
                            getattr(vis_obj, "vizitorname", None)
                            or getattr(vis_obj, "personname", None)
                            or ""
                        ).strip()
                        if resolved_vname:
                            visitor_name = resolved_vname
                            has_visitor = True
            except DatabaseError:
                pass

        # 2. Customer Accounting Balance & Pays from Tblsanadrad (+ Tblsanad dates)
        hesab = 0
        pay_rows = []
        if clean_sub_id:
            agg = (
                Tblsanadrad.objects.using("plus")
                .filter(gsubdetailid__iexact=clean_sub_id)
                .aggregate(
                    total_debit=Sum("debit"),
                    total_credit=Sum("credit"),
                )
            )
            total_debit = Decimal(str(agg.get("total_debit") or 0))
            total_credit = Decimal(str(agg.get("total_credit") or 0))
            hesab = int(total_debit - total_credit)

            pay_rows = list(
                Tblsanadrad.objects.using("plus").filter(
                    gsubdetailid__iexact=clean_sub_id,
                    credit__gt=0,
                )
            )

        if hesab > 0:
            status_code = "debtor"
            status_name = "بدهکار"
        elif hesab < 0:
            status_code = "creditor"
            status_name = "بستانکار"
        else:
            status_code = "settled"
            status_name = "تسویه"

        sanad_id_variants = list(
            {
                variant
                for rad in pay_rows
                for raw_sid in [_extract_raw_sanad_id(rad)]
                if raw_sid
                for variant in (raw_sid, raw_sid.upper(), raw_sid.lower())
            }
        )
        sanad_map = {}
        if sanad_id_variants:
            try:
                sanad_objs = Tblsanad.objects.using("plus").filter(
                    gsanadid__in=sanad_id_variants
                )
                sanad_map = {
                    str(s.gsanadid).strip().lower(): s
                    for s in sanad_objs
                    if getattr(s, "gsanadid", None)
                }
            except DatabaseError:
                sanad_map = {}

        pays = []
        total_pays_amount = 0
        for seq_idx, rad in enumerate(pay_rows):
            raw_sid = _extract_raw_sanad_id(rad)
            sanad = sanad_map.get(raw_sid.lower()) if raw_sid else None
            if sanad is None:
                inline_fk = getattr(rad, "gsanadid", None)
                if inline_fk is not None and not isinstance(inline_fk, str):
                    sanad = inline_fk

            raw_date, raw_time = _resolve_rad_date_and_time(rad, sanad)
            display_date, has_date, sort_tuple, iso_token = (
                _normalize_shamsi_date_and_sort_key(raw_date, raw_time)
            )
            amount = int(Decimal(str(getattr(rad, "credit", 0) or 0)))
            total_pays_amount += amount

            sanad_no = ""
            if sanad is not None and getattr(sanad, "sanadno", None):
                sanad_no = str(sanad.sanadno).strip()
            elif getattr(rad, "serialid", None):
                sanad_no = str(rad.serialid).strip()

            desc = (getattr(rad, "description", "") or "").strip()
            if not desc and sanad is not None:
                desc = (getattr(sanad, "sanaddesc", "") or "").strip()

            pays.append(
                {
                    "kind": "pay",
                    "kind_label": "پرداختی مشتری",
                    "id": str(getattr(rad, "gsanadradid", "") or ""),
                    "number": sanad_no,
                    "date": display_date,
                    "time": raw_time,
                    "has_date": has_date,
                    "sort_tuple": sort_tuple,
                    "sort_seq": seq_idx,
                    "sort_token": iso_token,
                    "amount": amount,
                    "description": desc or "ثبت دریافت از مشتری",
                    "status_name": "بستانکار",
                    "chip_class": "status-chip--approved",
                    "dot_class": "status-dot",
                    "detail_url": "",
                }
            )

        # 3. Customer Sale Factors from Salefactormaster + Salefactordetail
        factor_masters = []
        if clean_cust_gid:
            factor_masters = list(
                Salefactormaster.objects.using("plus").filter(
                    gcustomerid__iexact=clean_cust_gid
                )
            )

        factor_status_map = {}
        if factor_masters:
            try:
                sf_statuses = Salefactorstatus.objects.using("plus").all()
                factor_status_map = {
                    s.salefactorstatuscode: s.salefactorstatusname
                    for s in sf_statuses
                }
            except DatabaseError:
                factor_status_map = {}

        master_guid_variants = list(
            {
                variant
                for sf in factor_masters
                if getattr(sf, "gsalefactormasterid", None)
                for raw_gid in [str(sf.gsalefactormasterid).strip()]
                if raw_gid
                for variant in (raw_gid, raw_gid.upper(), raw_gid.lower())
            }
        )
        factor_line_totals = {}
        if master_guid_variants:
            detail_agg = (
                Salefactordetail.objects.using("plus")
                .filter(gsalefactormasterid__in=master_guid_variants)
                .values("gsalefactormasterid")
                .annotate(
                    line_net=Sum(
                        (F("quantity") * F("unitprice"))
                        - Coalesce(F("discount"), Value(0)),
                        output_field=DecimalField(),
                    )
                )
            )
            for row in detail_agg:
                raw_mid = row.get("gsalefactormasterid")
                if raw_mid:
                    mid_key = str(raw_mid).strip().lower()
                    factor_line_totals[mid_key] = factor_line_totals.get(
                        mid_key, Decimal("0")
                    ) + Decimal(str(row.get("line_net") or 0))

        factors = []
        total_factors_amount = 0
        for seq_idx, sf in enumerate(factor_masters):
            sf_guid = str(getattr(sf, "gsalefactormasterid", "") or "").strip()
            sf_key = sf_guid.lower()
            line_net = factor_line_totals.get(sf_key, Decimal("0"))
            master_discount = Decimal(str(getattr(sf, "discount", 0) or 0))
            payable_amount = int(line_net - master_discount)
            total_factors_amount += payable_amount

            raw_fdate = (
                getattr(sf, "salefactordate", None)
                or getattr(sf, "createddate", None)
                or ""
            ).strip()
            raw_ftime = (getattr(sf, "salefactortime", None) or "").strip()
            display_date, has_date, sort_tuple, iso_token = (
                _normalize_shamsi_date_and_sort_key(raw_fdate, raw_ftime)
            )

            sf_status_name = factor_status_map.get(
                getattr(sf, "salefactorstatuscode", None), "ثبت شده"
            )
            style = get_status_style(sf_status_name)
            detail_url = (
                f"{reverse('core:factor_detail', kwargs={'pk': sf_guid})}?from_customer={quote(customer_pk)}"
                if sf_guid
                else ""
            )

            factors.append(
                {
                    "kind": "factor",
                    "kind_label": "فاکتور فروش",
                    "id": sf_guid,
                    "number": str(getattr(sf, "salefactorno", "") or "").strip(),
                    "date": display_date,
                    "time": raw_ftime,
                    "has_date": has_date,
                    "sort_tuple": sort_tuple,
                    "sort_seq": seq_idx,
                    "sort_token": iso_token,
                    "amount": payable_amount,
                    "description": (
                        getattr(sf, "salefactordesc", "") or ""
                    ).strip(),
                    "status_name": sf_status_name,
                    "chip_class": style["chip_class"],
                    "dot_class": style["dot_class"],
                    "detail_url": detail_url,
                }
            )

        # 4. Merge & Order Chronologically by Date
        raw_order = (self.request.GET.get("order") or "date_desc").strip().lower()
        current_order = "date_asc" if raw_order in ("date_asc", "asc", "oldest") else "date_desc"

        raw_type = (self.request.GET.get("type") or "all").strip().lower()
        current_type = raw_type if raw_type in ("all", "factor", "pay") else "all"

        transactions = pays + factors
        if current_order == "date_asc":
            transactions.sort(
                key=lambda item: (
                    0 if item["has_date"] else 1,
                    item["sort_tuple"],
                    0 if item["kind"] == "factor" else 1,
                    item["number"],
                    item["sort_seq"],
                )
            )
        else:
            transactions.sort(
                key=lambda item: (
                    0 if item["has_date"] else 1,
                    tuple(-v for v in item["sort_tuple"]),
                    0 if item["kind"] == "factor" else 1,
                    item["sort_seq"],
                )
            )

        for rank_idx, entry in enumerate(transactions):
            entry["chronological_rank"] = rank_idx
            entry["is_initially_visible"] = (
                current_type == "all" or entry["kind"] == current_type
            )

        visible_transactions_count = sum(
            1 for item in transactions if item["is_initially_visible"]
        )

        context.update(
            {
                "customer": customer,
                "customer_pk": customer_pk,
                "group_name": group_name,
                "visitor_name": visitor_name,
                "has_visitor": has_visitor,
                "hesab": hesab,
                "status_code": status_code,
                "status_name": status_name,
                "transactions": transactions,
                "pays": pays,
                "factors": factors,
                "pays_count": len(pays),
                "factors_count": len(factors),
                "total_transactions_count": len(transactions),
                "visible_transactions_count": visible_transactions_count,
                "total_pays_amount": total_pays_amount,
                "total_factors_amount": total_factors_amount,
                "current_type": current_type,
                "current_order": current_order,
            }
        )
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
    
    
class SaleRequestListView(PlusLoginRequiredMixin, TemplateView):
    template_name = "core/sale_request_list.html"

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
        sale_requests_qs = (
            Salerequestmaster.objects.using("plus")
            .all()
            .order_by("-salerequestdate", "-salerequestno")
        )

        # Filter by selected status tab (if not 'all')
        if status_filter != "all" and status_filter.isdigit():
            sale_requests_qs = sale_requests_qs.filter(
                salerequeststatuscode=int(status_filter)
            )

        # Limit to top 150 records for optimal performance
        sale_requests_list = list(sale_requests_qs[:150])

        # 3. Batch Fetch Customer Names (prevents N+1 query issue)
        customer_ids = [
            sr.gcustomerid for sr in sale_requests_list if sr.gcustomerid
        ]
        customer_map = {}
        if customer_ids:
            customers = Tblcustomer.objects.using("plus").filter(
                gcustomerid__in=customer_ids
            )
            customer_map = {c.gcustomerid: c.custname for c in customers}

        # 4. Construct Final Data List
        sale_requests = []
        for sr in sale_requests_list:
            customer_name = (
                customer_map.get(sr.gcustomerid)
                or sr.requestman
                or "مشتری نامشخص"
            )

            # Search by keyword (Sale Request No or Customer Name)
            if (
                query
                and query not in sr.salerequestno
                and query not in customer_name
            ):
                continue

            status_name = status_map.get(sr.salerequeststatuscode, "نامشخص")
            style = get_status_style(status_name)

            sale_requests.append(
                {
                    "id": sr.gsalerequestmasterid,
                    "number": sr.salerequestno,
                    "date": sr.salerequestdate or sr.createddate or "-",
                    "customer_name": customer_name,
                    "status_code": sr.salerequeststatuscode,
                    "status_name": status_name,
                    "chip_class": style["chip_class"],
                    "dot_class": style["dot_class"],
                }
            )

        context["sale_requests"] = sale_requests
        context["statuses"] = statuses
        context["current_status"] = status_filter
        context["query"] = query
        return context


class SaleRequestDetailView(PlusLoginRequiredMixin, TemplateView):
    template_name = "core/sale_request_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # 1. Retrieve Sale Request ID from URL kwargs or GET parameters
        sale_request_id = self.kwargs.get("pk") or self.request.GET.get("id")

        if sale_request_id:
            master = (
                Salerequestmaster.objects.using("plus")
                .filter(gsalerequestmasterid=str(sale_request_id).strip())
                .first()
            )
        else:
            # Fallback to the latest sale request only if no ID was provided at all
            master = (
                Salerequestmaster.objects.using("plus")
                .order_by("-salerequestdate", "-salerequestno")
                .first()
            )

        if not master:
            context["sale_request_found"] = False
            return context

        context["sale_request_found"] = True
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

        # 4. Fetch Sale Request Line Items & Products
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
    

class SaleRequestCreateView(PlusLoginRequiredMixin, TemplateView):
    template_name = "core/sale_request_create.html"

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

                # Next Sale Request Number
                last_sale_request = (
                    Salerequestmaster.objects.using("plus")
                    .filter(accyear=acc_year)
                    .order_by("-salerequestno")
                    .values("salerequestno")
                    .first()
                )

                last_no = (
                    last_sale_request.get("salerequestno")
                    if last_sale_request
                    else None
                )
                if last_no and str(last_no).isdigit():
                    next_sale_request_no = f"{int(last_no) + 1:06d}"
                else:
                    next_sale_request_no = "000001"

                master_guid = str(uuid.uuid4()).upper()
                current_user_gucode = request.session.get("user_id")

                # A. Create Master Record
                master = Salerequestmaster.objects.using("plus").create(
                    salerequestno=next_sale_request_no,
                    atfno=next_sale_request_no,                # Same as SaleRequestNo
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

            return redirect("core:sale_request_list")

        except Exception as e:
            messages.error(request, f"خطا در ثبت درخواست فروش: {str(e)}")
            return self.get(request, *args, **kwargs)


class OfflineView(PlusLoginRequiredMixin, TemplateView):
    template_name = "core/offline.html"


class SaleRequestPDFView(PlusLoginRequiredMixin, View):
    def get(self, request, pk=None, *args, **kwargs):
        sale_request_id = pk or request.GET.get("id")
        if not sale_request_id:
            raise Http404("درخواست فروش مورد نظر یافت نشد.")

        # 1. Fetch Master Record
        master = (
            Salerequestmaster.objects.using("plus")
            .filter(gsalerequestmasterid=sale_request_id)
            .first()
        )
        if not master:
            raise Http404("درخواست فروش مورد نظر یافت نشد.")

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

        sale_request_no = master.salerequestno or "sale_request"
        cust_name = customer.custname if (customer and customer.custname) else (master.requestman or "")
        filename = f"درخواست فروش {cust_name} شماره {sale_request_no}.pdf".strip()

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
            "pdf_filename": filename,
        }

        # 5. Render Server-Side HTML for jsPDF
        return render(request, "core/sale_request_pdf.html", context)


def _load_logo_base64():
    logo_path = finders.find("images/logo.png")
    if not logo_path:
        alt_path = os.path.join(settings.BASE_DIR, "static", "images", "logo.png")
        if os.path.exists(alt_path):
            logo_path = alt_path

    if logo_path and os.path.exists(logo_path):
        with open(logo_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")
    return ""


class PreFactorListView(PlusLoginRequiredMixin, TemplateView):
    template_name = "core/pre_factor_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        query = self.request.GET.get("q", "").strip()
        status_filter = self.request.GET.get("status", "all").strip()

        # 1. Fetch all available PreFactor statuses from DB (with safe fallback)
        try:
            statuses = list(
                Prefactorstatus.objects.using("plus")
                .all()
                .order_by("prefactorstatuscode")
            )
            status_map = {
                s.prefactorstatuscode: s.prefactorstatusname for s in statuses
            }
        except DatabaseError:
            statuses = []
            status_map = {}

        # 2. Fetch Sale Pre-Factors QuerySet (exclude purchase pre-factors where IsBuy=1)
        pre_factors_qs = (
            Prefactormaster.objects.using("plus")
            .filter(Q(isbuy=False) | Q(isbuy__isnull=True))
            .order_by("-prefactordate", "-prefactorno")
        )

        if status_filter != "all" and status_filter.isdigit():
            pre_factors_qs = pre_factors_qs.filter(
                prefactorstatuscode=int(status_filter)
            )

        pre_factors_list = list(pre_factors_qs[:150])

        # 3. Batch Fetch Customer Names (No N+1)
        customer_ids = list(
            {
                variant
                for pf in pre_factors_list
                if pf.gcustomerid
                for variant in (
                    str(pf.gcustomerid).strip(),
                    str(pf.gcustomerid).strip().upper(),
                    str(pf.gcustomerid).strip().lower(),
                )
            }
        )
        customer_map = {}
        if customer_ids:
            customers = Tblcustomer.objects.using("plus").filter(
                gcustomerid__in=customer_ids
            )
            customer_map = {
                str(c.gcustomerid).strip().lower(): c.custname
                for c in customers
                if c.gcustomerid
            }

        # 4. Construct Final Data List
        pre_factors = []
        for pf in pre_factors_list:
            cust_key = (
                str(pf.gcustomerid).strip().lower() if pf.gcustomerid else ""
            )
            customer_name = (
                customer_map.get(cust_key)
                or pf.requestman
                or "مشتری نامشخص"
            )

            pf_no = pf.prefactorno or ""
            if query and query not in pf_no and query not in customer_name:
                continue

            status_name = status_map.get(pf.prefactorstatuscode, "ثبت شده")
            style = get_status_style(status_name)

            pre_factors.append(
                {
                    "id": pf.gprefactormasterid,
                    "number": pf_no,
                    "date": pf.prefactordate or pf.createddate or "-",
                    "customer_name": customer_name,
                    "status_code": pf.prefactorstatuscode,
                    "status_name": status_name,
                    "chip_class": style["chip_class"],
                    "dot_class": style["dot_class"],
                }
            )

        context["pre_factors"] = pre_factors
        context["statuses"] = statuses
        context["current_status"] = status_filter
        context["query"] = query
        return context


class PreFactorDetailView(PlusLoginRequiredMixin, TemplateView):
    template_name = "core/pre_factor_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        pre_factor_id = self.kwargs.get("pk") or self.request.GET.get("id")

        if pre_factor_id:
            master = (
                Prefactormaster.objects.using("plus")
                .filter(gprefactormasterid__iexact=str(pre_factor_id).strip())
                .first()
            )
        else:
            master = (
                Prefactormaster.objects.using("plus")
                .filter(Q(isbuy=False) | Q(isbuy__isnull=True))
                .order_by("-prefactordate", "-prefactorno")
                .first()
            )

        if not master:
            context["pre_factor_found"] = False
            return context

        context["pre_factor_found"] = True
        context["master"] = master

        # 2. Fetch Status
        status_name = "ثبت شده"
        if master.prefactorstatuscode is not None:
            try:
                status_obj = (
                    Prefactorstatus.objects.using("plus")
                    .filter(prefactorstatuscode=master.prefactorstatuscode)
                    .first()
                )
                if status_obj:
                    status_name = status_obj.prefactorstatusname
            except DatabaseError:
                pass
        context["status_name"] = status_name

        # 3. Fetch Customer Details
        customer = None
        if master.gcustomerid:
            customer = (
                Tblcustomer.objects.using("plus")
                .filter(gcustomerid__iexact=str(master.gcustomerid).strip())
                .first()
            )
        context["customer"] = customer

        # 4. Fetch PreFactor Line Items & Products
        details = list(
            Prefactordetail.objects.using("plus")
            .filter(
                gprefactormasterid__iexact=str(
                    master.gprefactormasterid
                ).strip()
            )
            .order_by("rowid")
        )

        kala_ids = list(
            {
                variant
                for d in details
                if d.gkalaid
                for variant in (
                    str(d.gkalaid).strip(),
                    str(d.gkalaid).strip().upper(),
                    str(d.gkalaid).strip().lower(),
                )
            }
        )
        kala_map = {}
        if kala_ids:
            kalas = Tblkala.objects.using("plus").filter(gkalaid__in=kala_ids)
            kala_map = {
                str(k.gkalaid).strip().lower(): k
                for k in kalas
                if k.gkalaid
            }

        items = []
        subtotal = 0
        total_discount = 0

        for d in details:
            kala_key = str(d.gkalaid).strip().lower() if d.gkalaid else ""
            kala = kala_map.get(kala_key)
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


class PreFactorPDFView(PlusLoginRequiredMixin, View):
    def get(self, request, pk=None, *args, **kwargs):
        pre_factor_id = pk or request.GET.get("id")
        if not pre_factor_id:
            raise Http404("پیش‌فاکتور مورد نظر یافت نشد.")

        master = (
            Prefactormaster.objects.using("plus")
            .filter(gprefactormasterid__iexact=str(pre_factor_id).strip())
            .first()
        )
        if not master:
            raise Http404("پیش‌فاکتور مورد نظر یافت نشد.")

        customer = None
        if master.gcustomerid:
            customer = (
                Tblcustomer.objects.using("plus")
                .filter(gcustomerid__iexact=str(master.gcustomerid).strip())
                .first()
            )

        details = list(
            Prefactordetail.objects.using("plus")
            .filter(
                gprefactormasterid__iexact=str(
                    master.gprefactormasterid
                ).strip()
            )
            .order_by("rowid")
        )

        kala_ids = list(
            {
                variant
                for d in details
                if d.gkalaid
                for variant in (
                    str(d.gkalaid).strip(),
                    str(d.gkalaid).strip().upper(),
                    str(d.gkalaid).strip().lower(),
                )
            }
        )
        kala_map = {}
        if kala_ids:
            kalas = Tblkala.objects.using("plus").filter(gkalaid__in=kala_ids)
            kala_map = {
                str(k.gkalaid).strip().lower(): k
                for k in kalas
                if k.gkalaid
            }

        items = []
        total_quantity = 0
        subtotal = 0
        total_discount = 0

        for idx, d in enumerate(details, start=1):
            kala_key = str(d.gkalaid).strip().lower() if d.gkalaid else ""
            kala = kala_map.get(kala_key)
            qty = float(d.quantity or 0)
            price = float(d.unitprice or 0)
            discount = float(d.discount or 0)
            gross = qty * price
            row_total = gross - discount

            total_quantity += qty
            subtotal += gross
            total_discount += discount

            items.append(
                {
                    "row_no": idx,
                    "name": kala.kalaname
                    if kala
                    else (d.descript or "کالای نامشخص"),
                    "quantity": int(qty) if qty.is_integer() else qty,
                    "unit": kala.vahed1 if (kala and kala.vahed1) else "عدد",
                    "unit_price": int(price),
                    "discount": int(discount),
                    "row_total": int(row_total),
                }
            )

        payable = subtotal - total_discount
        pre_factor_no = master.prefactorno or "pre_factor"
        cust_name = (
            customer.custname
            if (customer and customer.custname)
            else (master.requestman or "")
        )
        filename = f"پیش‌فاکتور {cust_name} شماره {pre_factor_no}.pdf".strip()

        context = {
            "master": master,
            "customer": customer,
            "items": items,
            "total_quantity": int(total_quantity)
            if isinstance(total_quantity, float) and total_quantity.is_integer()
            else total_quantity,
            "subtotal": int(subtotal),
            "total_discount": int(total_discount),
            "payable": int(payable),
            "logo_base64": _load_logo_base64(),
            "seller_name": "رهجو پلاس",
            "seller_phone": "",
            "seller_address": "",
            "bank_card": "۶۲۱۹۸۶۱۰۹۲۳۹۹۴۲۶",
            "bank_sheba": "IR۵۲۰۵۶۰۲۱۳۷۸۰۰۰۵۳۱۱۸۰۰۰۰۱",
            "bank_owner": "خانم سپیده جیحانی",
            "bank_name": "بانک سامان",
            "pdf_filename": filename,
        }

        return render(request, "core/pre_factor_pdf.html", context)


class FactorListView(PlusLoginRequiredMixin, TemplateView):
    template_name = "core/factor_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        query = self.request.GET.get("q", "").strip()
        status_filter = self.request.GET.get("status", "all").strip()

        # 1. Fetch all available SaleFactor statuses from DB (with safe fallback)
        try:
            statuses = list(
                Salefactorstatus.objects.using("plus")
                .all()
                .order_by("salefactorstatuscode")
            )
            status_map = {
                s.salefactorstatuscode: s.salefactorstatusname
                for s in statuses
            }
        except DatabaseError:
            statuses = []
            status_map = {}

        # 2. Fetch Sale Factors QuerySet
        factors_qs = (
            Salefactormaster.objects.using("plus")
            .all()
            .order_by("-salefactordate", "-salefactorno")
        )

        if status_filter != "all" and status_filter.isdigit():
            factors_qs = factors_qs.filter(
                salefactorstatuscode=int(status_filter)
            )

        factors_list = list(factors_qs[:150])

        # 3. Batch Fetch Customer Names (No N+1)
        customer_ids = list(
            {
                variant
                for sf in factors_list
                if sf.gcustomerid
                for variant in (
                    str(sf.gcustomerid).strip(),
                    str(sf.gcustomerid).strip().upper(),
                    str(sf.gcustomerid).strip().lower(),
                )
            }
        )
        customer_map = {}
        if customer_ids:
            customers = Tblcustomer.objects.using("plus").filter(
                gcustomerid__in=customer_ids
            )
            customer_map = {
                str(c.gcustomerid).strip().lower(): c.custname
                for c in customers
                if c.gcustomerid
            }

        # 4. Construct Final Data List
        factors = []
        for sf in factors_list:
            cust_key = (
                str(sf.gcustomerid).strip().lower() if sf.gcustomerid else ""
            )
            customer_name = (
                customer_map.get(cust_key)
                or sf.requestman
                or "مشتری نامشخص"
            )

            sf_no = sf.salefactorno or ""
            if query and query not in sf_no and query not in customer_name:
                continue

            status_name = status_map.get(sf.salefactorstatuscode, "ثبت شده")
            style = get_status_style(status_name)

            factors.append(
                {
                    "id": sf.gsalefactormasterid,
                    "number": sf_no,
                    "date": sf.salefactordate or sf.createddate or "-",
                    "customer_name": customer_name,
                    "status_code": sf.salefactorstatuscode,
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

        from_customer = (self.request.GET.get("from_customer") or "").strip()
        if from_customer:
            context["back_url"] = reverse(
                "core:customer_detail", kwargs={"pk": from_customer}
            )

        factor_id = self.kwargs.get("pk") or self.request.GET.get("id")

        if factor_id:
            master = (
                Salefactormaster.objects.using("plus")
                .filter(gsalefactormasterid__iexact=str(factor_id).strip())
                .first()
            )
        else:
            master = (
                Salefactormaster.objects.using("plus")
                .order_by("-salefactordate", "-salefactorno")
                .first()
            )

        if not master:
            context["factor_found"] = False
            return context

        context["factor_found"] = True
        context["master"] = master

        # 2. Fetch Status
        status_name = "ثبت شده"
        if master.salefactorstatuscode is not None:
            try:
                status_obj = (
                    Salefactorstatus.objects.using("plus")
                    .filter(salefactorstatuscode=master.salefactorstatuscode)
                    .first()
                )
                if status_obj:
                    status_name = status_obj.salefactorstatusname
            except DatabaseError:
                pass
        context["status_name"] = status_name

        # 3. Fetch Customer Details
        customer = None
        if master.gcustomerid:
            customer = (
                Tblcustomer.objects.using("plus")
                .filter(gcustomerid__iexact=str(master.gcustomerid).strip())
                .first()
            )
        context["customer"] = customer

        # 4. Fetch Factor Line Items & Products
        details = list(
            Salefactordetail.objects.using("plus")
            .filter(
                gsalefactormasterid__iexact=str(
                    master.gsalefactormasterid
                ).strip()
            )
            .order_by("rowid")
        )

        kala_ids = list(
            {
                variant
                for d in details
                if d.gkalaid
                for variant in (
                    str(d.gkalaid).strip(),
                    str(d.gkalaid).strip().upper(),
                    str(d.gkalaid).strip().lower(),
                )
            }
        )
        kala_map = {}
        if kala_ids:
            kalas = Tblkala.objects.using("plus").filter(gkalaid__in=kala_ids)
            kala_map = {
                str(k.gkalaid).strip().lower(): k
                for k in kalas
                if k.gkalaid
            }

        items = []
        subtotal = 0
        total_discount = float(getattr(master, "discount", 0) or 0)

        for d in details:
            kala_key = str(d.gkalaid).strip().lower() if d.gkalaid else ""
            kala = kala_map.get(kala_key)
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


class FactorPDFView(PlusLoginRequiredMixin, View):
    def get(self, request, pk=None, *args, **kwargs):
        factor_id = pk or request.GET.get("id")
        if not factor_id:
            raise Http404("فاکتور فروش مورد نظر یافت نشد.")

        master = (
            Salefactormaster.objects.using("plus")
            .filter(gsalefactormasterid__iexact=str(factor_id).strip())
            .first()
        )
        if not master:
            raise Http404("فاکتور فروش مورد نظر یافت نشد.")

        customer = None
        if master.gcustomerid:
            customer = (
                Tblcustomer.objects.using("plus")
                .filter(gcustomerid__iexact=str(master.gcustomerid).strip())
                .first()
            )

        details = list(
            Salefactordetail.objects.using("plus")
            .filter(
                gsalefactormasterid__iexact=str(
                    master.gsalefactormasterid
                ).strip()
            )
            .order_by("rowid")
        )

        kala_ids = list(
            {
                variant
                for d in details
                if d.gkalaid
                for variant in (
                    str(d.gkalaid).strip(),
                    str(d.gkalaid).strip().upper(),
                    str(d.gkalaid).strip().lower(),
                )
            }
        )
        kala_map = {}
        if kala_ids:
            kalas = Tblkala.objects.using("plus").filter(gkalaid__in=kala_ids)
            kala_map = {
                str(k.gkalaid).strip().lower(): k
                for k in kalas
                if k.gkalaid
            }

        items = []
        total_quantity = 0
        subtotal = 0
        total_discount = float(getattr(master, "discount", 0) or 0)

        for idx, d in enumerate(details, start=1):
            kala_key = str(d.gkalaid).strip().lower() if d.gkalaid else ""
            kala = kala_map.get(kala_key)
            qty = float(d.quantity or 0)
            price = float(d.unitprice or 0)
            discount = float(d.discount or 0)
            gross = qty * price
            row_total = gross - discount

            total_quantity += qty
            subtotal += gross
            total_discount += discount

            items.append(
                {
                    "row_no": idx,
                    "name": kala.kalaname
                    if kala
                    else (d.descript or "کالای نامشخص"),
                    "quantity": int(qty) if qty.is_integer() else qty,
                    "unit": kala.vahed1 if (kala and kala.vahed1) else "عدد",
                    "unit_price": int(price),
                    "discount": int(discount),
                    "row_total": int(row_total),
                }
            )

        payable = subtotal - total_discount
        factor_no = master.salefactorno or "factor"
        cust_name = (
            customer.custname
            if (customer and customer.custname)
            else (master.requestman or "")
        )
        filename = f"فاکتور فروش {cust_name} شماره {factor_no}.pdf".strip()

        context = {
            "master": master,
            "customer": customer,
            "items": items,
            "total_quantity": int(total_quantity)
            if isinstance(total_quantity, float) and total_quantity.is_integer()
            else total_quantity,
            "subtotal": int(subtotal),
            "total_discount": int(total_discount),
            "payable": int(payable),
            "logo_base64": _load_logo_base64(),
            "seller_name": "رهجو پلاس",
            "seller_phone": "",
            "seller_address": "",
            "bank_card": "۶۲۱۹۸۶۱۰۹۲۳۹۹۴۲۶",
            "bank_sheba": "IR۵۲۰۵۶۰۲۱۳۷۸۰۰۰۵۳۱۱۸۰۰۰۰۱",
            "bank_owner": "خانم سپیده جیحانی",
            "bank_name": "بانک سامان",
            "pdf_filename": filename,
        }

        return render(request, "core/factor_pdf.html", context)
    
    