import io
import os
import re
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
from django.db import DatabaseError, connections, transaction
from django.test.testcases import DatabaseOperationForbidden
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


_SAFE_SQL_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CUSTOMER_PERSON_TYPES = [
    {"code": 1, "name": "حقیقی"},
    {"code": 2, "name": "حقوقی"},
    {"code": 3, "name": "مشارکت مدنی"},
    {"code": 4, "name": "اتباع غیرایرانی"},
]
_CUSTOMER_DIGIT_MAP = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


def _normalize_ascii_digits(raw_value):
    return str(raw_value or "").strip().translate(_CUSTOMER_DIGIT_MAP)


def _quote_sql_ident(name):
    clean = str(name or "").strip()
    if not _SAFE_SQL_IDENT_RE.match(clean):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return f"[{clean}]"


def _qualify_sql_table(schema_name, table_name):
    if schema_name:
        return f"{_quote_sql_ident(schema_name)}.{_quote_sql_ident(table_name)}"
    return _quote_sql_ident(table_name)


def _format_guid_value(raw_uuid, use_lowercase=False):
    text = str(raw_uuid).strip()
    return text.lower() if use_lowercase else text.upper()


def _looks_like_guid(value):
    s = str(value or "").strip()
    return len(s) == 36 and s.count("-") == 4


def _discover_subdetail_tables(cursor, vendor):
    """Discover the master SubDetail table (e.g. tblSubDetail) and any SubDetail link tables."""
    tables_with_gsub = []
    if vendor == "sqlite":
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        all_tables = [r[0] for r in cursor.fetchall() if r and r[0]]
        for t_name in all_tables:
            if not _SAFE_SQL_IDENT_RE.match(t_name):
                continue
            cursor.execute(f"PRAGMA table_info({_quote_sql_ident(t_name)})")
            cols = [str(r[1]).lower() for r in cursor.fetchall() if len(r) > 1]
            if "gsubdetailid" in cols:
                tables_with_gsub.append(("", t_name))
    else:
        cursor.execute(
            """
            SELECT DISTINCT t.TABLE_SCHEMA, t.TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES t
            INNER JOIN INFORMATION_SCHEMA.COLUMNS c
                ON c.TABLE_SCHEMA = t.TABLE_SCHEMA AND c.TABLE_NAME = t.TABLE_NAME
            WHERE t.TABLE_TYPE = 'BASE TABLE'
              AND LOWER(c.COLUMN_NAME) = 'gsubdetailid'
            """
        )
        for schema_name, t_name in cursor.fetchall():
            if _SAFE_SQL_IDENT_RE.match(str(schema_name or "")) and _SAFE_SQL_IDENT_RE.match(str(t_name or "")):
                tables_with_gsub.append((str(schema_name), str(t_name)))

    primary = None
    priority_names = (
        "tblsubdetail",
        "subdetail",
        "acc_subdetail",
        "tbl_subdetail",
        "accsubdetail",
    )
    by_lower = {t_name.lower(): (sch, t_name) for sch, t_name in tables_with_gsub}
    for pname in priority_names:
        if pname in by_lower:
            primary = by_lower[pname]
            break

    if primary is None:
        for sch, t_name in tables_with_gsub:
            t_low = t_name.lower()
            if (
                "subdetail" in t_low
                and "2" not in t_low
                and "to" not in t_low
                and "group" not in t_low
            ):
                primary = (sch, t_name)
                break

    link_tables = []
    for sch, t_name in tables_with_gsub:
        if primary and (sch, t_name) == primary:
            continue
        t_low = t_name.lower()
        if "subdetail" in t_low and ("2" in t_low or "to" in t_low):
            link_tables.append((sch, t_name))

    return primary, link_tables


def _inspect_table_columns(cursor, vendor, schema_name, table_name):
    """Return metadata for every column on a SQL Server or SQLite table."""
    if vendor == "sqlite":
        q_table = _quote_sql_ident(table_name)
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = %s",
            [table_name],
        )
        ddl_row = cursor.fetchone()
        ddl_sql = (ddl_row[0] or "").upper() if ddl_row else ""
        has_autoincrement = "AUTOINCREMENT" in ddl_sql

        single_unique_cols = set()
        cursor.execute(f"PRAGMA index_list({q_table})")
        for idx_row in cursor.fetchall():
            idx_name = idx_row[1]
            is_unique = bool(idx_row[2])
            if not is_unique or not _SAFE_SQL_IDENT_RE.match(str(idx_name or "")):
                continue
            cursor.execute(f"PRAGMA index_info({_quote_sql_ident(idx_name)})")
            idx_cols = [r[2] for r in cursor.fetchall() if len(r) > 2]
            if len(idx_cols) == 1:
                single_unique_cols.add(str(idx_cols[0]).lower())

        cursor.execute(f"PRAGMA table_info({q_table})")
        raw_cols = cursor.fetchall()
        pk_cols = [r[1] for r in raw_cols if r[5]]
        if len(pk_cols) == 1:
            single_unique_cols.add(str(pk_cols[0]).lower())

        cols = []
        for cid, col_name, col_type, notnull, dflt_val, pk_flag in raw_cols:
            dtype = str(col_type or "").lower()
            max_len = None
            m = re.search(r"\((\d+)\)", dtype)
            if m:
                max_len = int(m.group(1))
            base_dtype = dtype.split("(")[0].strip()
            is_int_pk = (
                bool(pk_flag)
                and len(pk_cols) == 1
                and "int" in base_dtype
                and has_autoincrement
            )
            cols.append(
                {
                    "name": col_name,
                    "lower": col_name.lower(),
                    "data_type": base_dtype,
                    "max_length": max_len,
                    "is_nullable": not bool(notnull) and not bool(pk_flag),
                    "is_identity": is_int_pk,
                    "is_computed": False,
                    "is_single_unique": col_name.lower() in single_unique_cols,
                }
            )
        return cols

    full_obj = f"{schema_name}.{table_name}" if schema_name else table_name
    cursor.execute(
        """
        SELECT col.name
        FROM sys.indexes idx
        INNER JOIN sys.index_columns ic
            ON ic.object_id = idx.object_id AND ic.index_id = idx.index_id
        INNER JOIN sys.columns col
            ON col.object_id = idx.object_id AND col.column_id = ic.column_id
        WHERE idx.object_id = OBJECT_ID(%s)
          AND idx.is_unique = 1
          AND ic.is_included_column = 0
          AND (
              SELECT COUNT(*)
              FROM sys.index_columns ic2
              WHERE ic2.object_id = idx.object_id
                AND ic2.index_id = idx.index_id
                AND ic2.is_included_column = 0
          ) = 1
        """,
        [full_obj],
    )
    single_unique_cols = {str(r[0]).lower() for r in cursor.fetchall() if r and r[0]}

    cursor.execute(
        """
        SELECT
            c.COLUMN_NAME,
            LOWER(c.DATA_TYPE),
            c.CHARACTER_MAXIMUM_LENGTH,
            CASE WHEN c.IS_NULLABLE = 'YES' THEN 1 ELSE 0 END,
            ISNULL(COLUMNPROPERTY(OBJECT_ID(%s), c.COLUMN_NAME, 'IsIdentity'), 0),
            ISNULL(COLUMNPROPERTY(OBJECT_ID(%s), c.COLUMN_NAME, 'IsComputed'), 0)
        FROM INFORMATION_SCHEMA.COLUMNS c
        WHERE c.TABLE_SCHEMA = %s AND c.TABLE_NAME = %s
        ORDER BY c.ORDINAL_POSITION
        """,
        [full_obj, full_obj, schema_name, table_name],
    )
    cols = []
    for col_name, data_type, max_len, is_null, is_ident, is_comp in cursor.fetchall():
        cols.append(
            {
                "name": col_name,
                "lower": str(col_name).lower(),
                "data_type": str(data_type or "").lower(),
                "max_length": int(max_len) if (max_len is not None and int(max_len) > 0) else None,
                "is_nullable": bool(is_null),
                "is_identity": bool(is_ident),
                "is_computed": bool(is_comp),
                "is_single_unique": str(col_name).lower() in single_unique_cols,
            }
        )
    return cols


def _fetch_one_row_dict(cursor, sql, params=None):
    cursor.execute(sql, params or [])
    row = cursor.fetchone()
    if not row or not cursor.description:
        return None
    col_names = [desc[0] for desc in cursor.description]
    return dict(zip(col_names, row))


def _fetch_all_row_dicts(cursor, sql, params=None):
    cursor.execute(sql, params or [])
    rows = cursor.fetchall()
    if not rows or not cursor.description:
        return []
    col_names = [desc[0] for desc in cursor.description]
    return [dict(zip(col_names, r)) for r in rows]


def _find_reference_desktop_customer(selected_group_gid=""):
    """
    Locate a verified desktop-created Tblcustomer row (preferring one whose GSubDetailID
    genuinely exists in tblSubDetail and belongs to the same CustomerGroup).
    """
    ref_customer = None
    try:
        conn = connections["plus"]
        vendor = conn.vendor
        with conn.cursor() as cursor:
            primary_sd, _ = _discover_subdetail_tables(cursor, vendor)
            if primary_sd:
                sd_sql = _qualify_sql_table(*primary_sd)
                found_cid = None
                if selected_group_gid:
                    if vendor == "sqlite":
                        grp_sql = (
                            f"SELECT c.[CustomerID] FROM [tblCustomer] c "
                            f"INNER JOIN [Customer2Group] c2g ON LOWER(TRIM(c.[GCustomerID])) = LOWER(TRIM(c2g.[GCustomerID])) "
                            f"INNER JOIN {sd_sql} sd ON LOWER(TRIM(c.[GSubDetailID])) = LOWER(TRIM(sd.[GSubDetailID])) "
                            f"WHERE (c.[DeletedBy] IS NULL OR c.[DeletedBy] = '') "
                            f"AND LOWER(TRIM(c2g.[GCustomerGroupID])) = LOWER(TRIM(%s)) "
                            f"ORDER BY c.[CustomerID] DESC LIMIT 1"
                        )
                    else:
                        grp_sql = (
                            f"SELECT TOP 1 c.[CustomerID] FROM [tblCustomer] c "
                            f"INNER JOIN [Customer2Group] c2g ON LOWER(LTRIM(RTRIM(c.[GCustomerID]))) = LOWER(LTRIM(RTRIM(c2g.[GCustomerID]))) "
                            f"INNER JOIN {sd_sql} sd ON LOWER(LTRIM(RTRIM(c.[GSubDetailID]))) = LOWER(LTRIM(RTRIM(sd.[GSubDetailID]))) "
                            f"WHERE (c.[DeletedBy] IS NULL OR c.[DeletedBy] = '') "
                            f"AND LOWER(LTRIM(RTRIM(c2g.[GCustomerGroupID]))) = LOWER(LTRIM(RTRIM(%s))) "
                            f"ORDER BY c.[CustomerID] DESC"
                        )
                    cursor.execute(grp_sql, [selected_group_gid])
                    r = cursor.fetchone()
                    if r:
                        found_cid = r[0]

                if found_cid is None:
                    if vendor == "sqlite":
                        any_sql = (
                            f"SELECT c.[CustomerID] FROM [tblCustomer] c "
                            f"INNER JOIN {sd_sql} sd ON LOWER(TRIM(c.[GSubDetailID])) = LOWER(TRIM(sd.[GSubDetailID])) "
                            f"WHERE (c.[DeletedBy] IS NULL OR c.[DeletedBy] = '') "
                            f"ORDER BY c.[CustomerID] DESC LIMIT 1"
                        )
                    else:
                        any_sql = (
                            f"SELECT TOP 1 c.[CustomerID] FROM [tblCustomer] c "
                            f"INNER JOIN {sd_sql} sd ON LOWER(LTRIM(RTRIM(c.[GSubDetailID]))) = LOWER(LTRIM(RTRIM(sd.[GSubDetailID]))) "
                            f"WHERE (c.[DeletedBy] IS NULL OR c.[DeletedBy] = '') "
                            f"ORDER BY c.[CustomerID] DESC"
                        )
                    cursor.execute(any_sql)
                    r = cursor.fetchone()
                    if r:
                        found_cid = r[0]

                if found_cid is not None:
                    ref_customer = (
                        Tblcustomer.objects.using("plus")
                        .filter(customerid=found_cid)
                        .first()
                    )
    except (DatabaseError, DatabaseOperationForbidden):
        ref_customer = None

    if ref_customer is None:
        try:
            ref_customer = (
                Tblcustomer.objects.using("plus")
                .filter(Q(deletedby__isnull=True) | Q(deletedby=""))
                .order_by("-customerid")
                .first()
            )
        except (DatabaseError, DatabaseOperationForbidden):
            ref_customer = None

    return ref_customer


def _resolve_customer_desktop_defaults(
    selected_group_gid="", plus_user=None, group=None
):
    """Build desktop-compatible default values for Tblcustomer and related tables."""
    ref_cust = _find_reference_desktop_customer(selected_group_gid)

    # Resolve active GCompanyID reliably (never leave NULL if any company record exists)
    company_gid = ""
    for candidate in (
        getattr(ref_cust, "gcompanyid", None) if ref_cust else None,
        getattr(plus_user, "gcompanyid", None) if plus_user else None,
        getattr(group, "gcompanyid", None) if group else None,
    ):
        if candidate and str(candidate).strip():
            company_gid = str(candidate).strip()
            break

    if not company_gid:
        try:
            branch_comp = (
                Branches.objects.using("plus")
                .exclude(gcompanyid__isnull=True)
                .exclude(gcompanyid="")
                .values_list("gcompanyid", flat=True)
                .first()
            )
            if branch_comp and str(branch_comp).strip():
                company_gid = str(branch_comp).strip()
        except (DatabaseError, DatabaseOperationForbidden):
            pass

    ref_gcustomerid = str(getattr(ref_cust, "gcustomerid", "") or "").strip()
    guid_lowercase = bool(
        ref_gcustomerid and ref_gcustomerid == ref_gcustomerid.lower() and any(ch.isalpha() for ch in ref_gcustomerid)
    )

    ref_created_by = str(getattr(ref_cust, "createdby", "") or "").strip()
    created_by_uses_guid = _looks_like_guid(ref_created_by)

    ref_custno = str(getattr(ref_cust, "custno", "") or "").strip()
    custno_pad_width = (
        len(ref_custno)
        if (ref_custno.isdigit() and len(ref_custno) > 1 and ref_custno.startswith("0"))
        else 0
    )

    ref_status = str(getattr(ref_cust, "status", "") or "").strip() or "1"
    ref_salestatus = getattr(ref_cust, "salestatus", None)
    ref_custtypecode = getattr(ref_cust, "custtypecode", None)
    ref_customertypecode = getattr(ref_cust, "customertypecode", None)
    ref_customertaxtype = getattr(ref_cust, "customertaxtype", None)

    return {
        "ref_customer": ref_cust,
        "gcompanyid": company_gid or None,
        "guid_lowercase": guid_lowercase,
        "created_by_uses_guid": created_by_uses_guid,
        "custno_pad_width": custno_pad_width,
        "status": ref_status[:1],
        "salestatus": ref_salestatus if ref_salestatus is not None else 1,
        "custtypecode": ref_custtypecode if ref_custtypecode is not None else 1,
        "customertypecode": ref_customertypecode if ref_customertypecode is not None else 1,
        "customertaxtype": ref_customertaxtype if ref_customertaxtype is not None else 3,
        "gprovinceid": (
            str(ref_cust.gprovinceid).strip()
            if (ref_cust and getattr(ref_cust, "gprovinceid", None))
            else "ECB49B7B-30FC-472C-A1AA-45E00F329135"
        ),
        "gcityid": (
            str(ref_cust.gcityid).strip()
            if (ref_cust and getattr(ref_cust, "gcityid", None))
            else "A8218140-B1D0-42DB-B4AD-1D5EAF501EC2"
        ),
        "visitpriod": (
            ref_cust.visitpriod
            if (ref_cust and getattr(ref_cust, "visitpriod", None) is not None)
            else 0
        ),
        "callstatus": (
            ref_cust.callstatus
            if (ref_cust and getattr(ref_cust, "callstatus", None) is not None)
            else 0
        ),
        "ranking": (
            ref_cust.ranking
            if (ref_cust and getattr(ref_cust, "ranking", None) is not None)
            else 0
        ),
        "usercount": (
            ref_cust.usercount
            if (ref_cust and getattr(ref_cust, "usercount", None) is not None)
            else 0
        ),
        "sentstatuscode": (
            ref_cust.sentstatuscode
            if (ref_cust and getattr(ref_cust, "sentstatuscode", None) is not None)
            else 0
        ),
    }


def _calculate_next_custno(existing_custnos, pad_width=0):
    """Compute the next available CustNo strictly below 1900."""
    used_ints = set()
    max_custno = 0
    for val in existing_custnos:
        clean_val = _normalize_ascii_digits(val)
        if clean_val.isdigit():
            num = int(clean_val)
            used_ints.add(num)
            if 0 < num < 1900 and num > max_custno:
                max_custno = num

    candidate_int = (max_custno + 1) if max_custno > 0 else 1
    if candidate_int >= 1900 or candidate_int in used_ints:
        candidate_int = None
        for probe in range(1899, 0, -1):
            if probe not in used_ints:
                candidate_int = probe
                break

    if candidate_int is None or candidate_int >= 1900:
        return None

    if pad_width and pad_width <= 4:
        return str(candidate_int).zfill(pad_width)
    return str(candidate_int)


def _next_unique_subdetail_code(
    cursor,
    sd_sql,
    code_col_name,
    custno,
    ref_customer,
    ref_sd_row,
    company_gid,
    company_col_name,
    max_length,
):
    """Generate a unique SubDetailCode aligned with desktop customer SubDetail numbering."""
    q_code = _quote_sql_ident(code_col_name)
    where_comp = ""
    comp_params = []
    if company_col_name and company_gid:
        where_comp = f" AND LOWER({_quote_sql_ident(company_col_name)}) = LOWER(%s)"
        comp_params = [company_gid]

    def _code_exists(candidate):
        cursor.execute(
            f"SELECT 1 FROM {sd_sql} WHERE {q_code} = %s{where_comp}",
            [candidate] + comp_params,
        )
        return cursor.fetchone() is not None

    ref_code = ""
    if ref_sd_row:
        for k, v in ref_sd_row.items():
            if k.lower() == code_col_name.lower() and v is not None:
                ref_code = str(v).strip()
                break
    ref_custno = str(getattr(ref_customer, "custno", "") or "").strip()

    candidates = []
    clean_custno = str(custno).strip()
    if ref_code and ref_custno:
        if ref_code == ref_custno:
            candidates.append(clean_custno)
        elif ref_code.isdigit() and ref_custno.isdigit():
            if int(ref_code) == int(ref_custno):
                candidates.append(clean_custno.zfill(len(ref_code)))
            elif ref_code.endswith(ref_custno):
                prefix = ref_code[: -len(ref_custno)]
                candidates.append(prefix + clean_custno.zfill(len(ref_custno)))
    candidates.append(clean_custno)

    for cand in candidates:
        trimmed = cand[:max_length] if max_length else cand
        if trimmed and not _code_exists(trimmed):
            return trimmed

    # Fallback: find max numeric SubDetailCode in Customer range (< 1900) or overall + 1
    if company_col_name and company_gid:
        cursor.execute(
            f"SELECT {q_code} FROM {sd_sql} WHERE LOWER({_quote_sql_ident(company_col_name)}) = LOWER(%s)",
            [company_gid],
        )
    else:
        cursor.execute(f"SELECT {q_code} FROM {sd_sql}")

    used_codes = set()
    max_under_1900 = 0
    max_overall = 0
    for (raw_c,) in cursor.fetchall():
        s = str(raw_c or "").strip()
        if not s:
            continue
        used_codes.add(s)
        if s.isdigit():
            n = int(s)
            if n < 1900 and n > max_under_1900:
                max_under_1900 = n
            if n > max_overall:
                max_overall = n

    if max_under_1900 + 1 < 1900:
        cand = str(max_under_1900 + 1)
        if cand not in used_codes:
            return cand[:max_length] if max_length else cand

    probe_num = max(max_overall + 1, 1)
    while str(probe_num) in used_codes:
        probe_num += 1
    result = str(probe_num)
    return result[:max_length] if max_length else result


def _ensure_customer_subdetail_in_db(
    *,
    target_gsubdetailid,
    target_gcustomerid,
    custno,
    full_customer_name,
    custdesc,
    company_gid,
    plus_user,
    shamsi_date,
    ref_customer,
    guid_lowercase=False,
):
    """
    Ensure a corresponding accounting floating detail row exists in tblSubDetail
    (and any SubDetail2Group / SubDetailToGroup link table) on SQL Server 'plus'.
    """
    try:
        conn = connections["plus"]
        vendor = conn.vendor
        with conn.cursor() as cursor:
            primary_sd, link_tables = _discover_subdetail_tables(cursor, vendor)
            if not primary_sd:
                return False

            sd_schema, sd_table = primary_sd
            sd_sql = _qualify_sql_table(sd_schema, sd_table)

            # Check if target_gsubdetailid already exists in tblSubDetail
            cursor.execute(
                f"SELECT 1 FROM {sd_sql} WHERE LOWER([GSubDetailID]) = LOWER(%s)",
                [target_gsubdetailid],
            )
            already_exists = cursor.fetchone() is not None

            ref_gsub = str(getattr(ref_customer, "gsubdetailid", "") or "").strip()
            ref_sd_row = None
            if ref_gsub:
                ref_sd_row = _fetch_one_row_dict(
                    cursor,
                    f"SELECT * FROM {sd_sql} WHERE LOWER([GSubDetailID]) = LOWER(%s)",
                    [ref_gsub],
                )
            if ref_sd_row is None:
                fallback_sql = (
                    f"SELECT * FROM {sd_sql} LIMIT 1"
                    if vendor == "sqlite"
                    else f"SELECT TOP 1 * FROM {sd_sql}"
                )
                ref_sd_row = _fetch_one_row_dict(cursor, fallback_sql)

            user_gucode = str(getattr(plus_user, "gucode", "") or "").strip()
            user_name = (
                getattr(plus_user, "uname", None)
                or getattr(plus_user, "uid", None)
                or ""
            ).strip()
            user_uid = str(getattr(plus_user, "uid", "") or "").strip()

            if not already_exists:
                cols = _inspect_table_columns(cursor, vendor, sd_schema, sd_table)
                ref_ci = (
                    {k.lower(): v for k, v in ref_sd_row.items()}
                    if ref_sd_row
                    else {}
                )
                company_col_name = next(
                    (c["name"] for c in cols if c["lower"] == "gcompanyid"), None
                )

                insert_cols = []
                insert_vals = []

                for col in cols:
                    if (
                        col["is_identity"]
                        or col["is_computed"]
                        or col["data_type"] in ("timestamp", "rowversion")
                    ):
                        continue

                    c_name = col["name"]
                    c_low = col["lower"]
                    max_len = col["max_length"]
                    dtype = col["data_type"]
                    base_val = ref_ci.get(c_low)

                    if c_low == "gsubdetailid":
                        val = target_gsubdetailid
                    elif c_low == "gcompanyid":
                        val = company_gid or base_val
                    elif c_low == "gcustomerid":
                        val = target_gcustomerid
                    elif c_low in ("subdetailid", "tafzilid", "id") and "int" in dtype:
                        cursor.execute(
                            f"SELECT COALESCE(MAX({_quote_sql_ident(c_name)}), 0) + 1 FROM {sd_sql}"
                        )
                        val = int(cursor.fetchone()[0] or 1)
                    elif (
                        col["is_single_unique"]
                        and ("char" in dtype or "uniqueidentifier" in dtype or "text" in dtype)
                        and (max_len is None or max_len >= 36)
                    ):
                        val = _format_guid_value(uuid.uuid4(), guid_lowercase)
                    elif c_low in (
                        "subdetailcode",
                        "tafzilcode",
                        "code",
                        "subcode",
                        "detailcode",
                    ):
                        val = _next_unique_subdetail_code(
                            cursor,
                            sd_sql,
                            c_name,
                            custno,
                            ref_customer,
                            ref_sd_row,
                            company_gid,
                            company_col_name,
                            max_len,
                        )
                    elif c_low in (
                        "subdetailname",
                        "tafzilname",
                        "name",
                        "subname",
                        "title",
                        "detailname",
                        "fulltitle",
                    ):
                        val = (
                            full_customer_name[:max_len]
                            if max_len
                            else full_customer_name
                        )
                    elif c_low in (
                        "description",
                        "descript",
                        "subdetaildesc",
                        "comment",
                        "note",
                    ):
                        clean_desc = (custdesc or "").strip()
                        if clean_desc:
                            val = clean_desc[:max_len] if max_len else clean_desc
                        else:
                            val = None if col["is_nullable"] else ""
                    elif c_low in ("deletedby", "deleteddate", "cancelby", "canceldate"):
                        val = None
                    elif c_low == "registerdate":
                        val = timezone.now()
                    elif c_low in ("createddate", "lastupdateddate"):
                        if dtype in ("datetime", "datetime2", "smalldatetime", "date"):
                            val = timezone.now()
                        else:
                            val = shamsi_date[:max_len] if max_len else shamsi_date
                    elif c_low in ("createdby", "lastupdatedby"):
                        chosen = (
                            user_gucode
                            if (_looks_like_guid(base_val) and user_gucode)
                            else (user_name or user_gucode)
                        )
                        val = chosen[:max_len] if max_len else chosen
                    elif c_low == "uid":
                        val = (user_uid[:max_len] if max_len else user_uid) or base_val
                    else:
                        if base_val is not None:
                            val = base_val
                        elif col["is_nullable"]:
                            val = None
                        elif "int" in dtype or dtype in ("decimal", "numeric", "money", "float", "real"):
                            val = 0
                        elif dtype in ("bit", "bool", "boolean"):
                            val = False
                        elif dtype in ("datetime", "datetime2", "smalldatetime", "date"):
                            val = timezone.now()
                        else:
                            val = ""

                    insert_cols.append(_quote_sql_ident(c_name))
                    insert_vals.append(val)

                if insert_cols:
                    placeholders = ", ".join(["%s"] * len(insert_cols))
                    cols_sql = ", ".join(insert_cols)
                    cursor.execute(
                        f"INSERT INTO {sd_sql} ({cols_sql}) VALUES ({placeholders})",
                        insert_vals,
                    )

            # Clone any SubDetail group/level link rows (e.g. SubDetail2Group / SubDetailToGroup)
            if ref_gsub and link_tables:
                for l_schema, l_table in link_tables:
                    l_sql = _qualify_sql_table(l_schema, l_table)
                    cursor.execute(
                        f"SELECT 1 FROM {l_sql} WHERE LOWER([GSubDetailID]) = LOWER(%s)",
                        [target_gsubdetailid],
                    )
                    if cursor.fetchone() is not None:
                        continue
                    ref_links = _fetch_all_row_dicts(
                        cursor,
                        f"SELECT * FROM {l_sql} WHERE LOWER([GSubDetailID]) = LOWER(%s)",
                        [ref_gsub],
                    )
                    if not ref_links:
                        continue
                    l_cols = _inspect_table_columns(cursor, vendor, l_schema, l_table)
                    l_stem_id = f"{l_table.lower().replace('tbl', '')}id"
                    for ref_link in ref_links:
                        link_ci = {k.lower(): v for k, v in ref_link.items()}
                        l_ins_cols = []
                        l_ins_vals = []
                        for col in l_cols:
                            if (
                                col["is_identity"]
                                or col["is_computed"]
                                or col["data_type"] in ("timestamp", "rowversion")
                            ):
                                continue
                            c_name = col["name"]
                            c_low = col["lower"]
                            dtype = col["data_type"]
                            max_len = col["max_length"]
                            base_val = link_ci.get(c_low)

                            if c_low == "gsubdetailid":
                                val = target_gsubdetailid
                            elif c_low == "gcompanyid":
                                val = company_gid or base_val
                            elif c_low in (l_stem_id, "id") and "int" in dtype:
                                cursor.execute(
                                    f"SELECT COALESCE(MAX({_quote_sql_ident(c_name)}), 0) + 1 FROM {l_sql}"
                                )
                                val = int(cursor.fetchone()[0] or 1)
                            elif (
                                col["is_single_unique"]
                                and ("char" in dtype or "uniqueidentifier" in dtype or "text" in dtype)
                                and (max_len is None or max_len >= 36)
                            ):
                                val = _format_guid_value(uuid.uuid4(), guid_lowercase)
                            else:
                                val = base_val

                            l_ins_cols.append(_quote_sql_ident(c_name))
                            l_ins_vals.append(val)

                        if l_ins_cols:
                            placeholders = ", ".join(["%s"] * len(l_ins_cols))
                            cursor.execute(
                                f"INSERT INTO {l_sql} ({', '.join(l_ins_cols)}) VALUES ({placeholders})",
                                l_ins_vals,
                            )
            return True
    except (DatabaseError, DatabaseOperationForbidden):
        return False


def _load_provinces_and_cities_for_form():
    """Dynamically load Province and City lookup lists from 'plus' when tables exist."""
    provinces = []
    cities = []
    try:
        conn = connections["plus"]
        vendor = conn.vendor
        with conn.cursor() as cursor:
            if vendor == "sqlite":
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
                tables = [("", r[0]) for r in cursor.fetchall() if r and r[0]]
            else:
                cursor.execute(
                    "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'"
                )
                tables = [(str(s), str(t)) for s, t in cursor.fetchall() if s and t]

            by_low = {
                t.lower(): (s, t)
                for s, t in tables
                if _SAFE_SQL_IDENT_RE.match(t) and (not s or _SAFE_SQL_IDENT_RE.match(s))
            }
            prov_tbl = (
                by_low.get("tblprovince")
                or by_low.get("province")
                or by_low.get("provinces")
            )
            city_tbl = (
                by_low.get("tblcity")
                or by_low.get("city")
                or by_low.get("cities")
            )

            if prov_tbl:
                p_cols = _inspect_table_columns(cursor, vendor, *prov_tbl)
                gid_col = next((c["name"] for c in p_cols if c["lower"] == "gprovinceid"), None)
                name_col = next(
                    (
                        c["name"]
                        for c in p_cols
                        if c["lower"] in ("provincename", "name", "title", "ostanname")
                    ),
                    None,
                )
                if gid_col and name_col:
                    p_sql = _qualify_sql_table(*prov_tbl)
                    cursor.execute(
                        f"SELECT {_quote_sql_ident(gid_col)}, {_quote_sql_ident(name_col)} "
                        f"FROM {p_sql} ORDER BY {_quote_sql_ident(name_col)}"
                    )
                    for gid, pname in cursor.fetchall():
                        if gid and pname:
                            provinces.append(
                                {"id": str(gid).strip(), "name": str(pname).strip()}
                            )

            if city_tbl:
                c_cols = _inspect_table_columns(cursor, vendor, *city_tbl)
                gid_col = next((c["name"] for c in c_cols if c["lower"] == "gcityid"), None)
                p_fk_col = next((c["name"] for c in c_cols if c["lower"] == "gprovinceid"), None)
                name_col = next(
                    (
                        c["name"]
                        for c in c_cols
                        if c["lower"] in ("cityname", "name", "title", "shahrname")
                    ),
                    None,
                )
                if gid_col and name_col:
                    c_sql = _qualify_sql_table(*city_tbl)
                    select_p = _quote_sql_ident(p_fk_col) if p_fk_col else "''"
                    cursor.execute(
                        f"SELECT {_quote_sql_ident(gid_col)}, {_quote_sql_ident(name_col)}, {select_p} "
                        f"FROM {c_sql} ORDER BY {_quote_sql_ident(name_col)}"
                    )
                    for gid, cname, pgid in cursor.fetchall():
                        if gid and cname:
                            cities.append(
                                {
                                    "id": str(gid).strip(),
                                    "name": str(cname).strip(),
                                    "province_id": str(pgid or "").strip(),
                                }
                            )
    except (DatabaseError, DatabaseOperationForbidden):
        return [], []
    return provinces, cities


def _load_active_visitors_for_customer_form():
    """Load deduplicated active visitors from ViewAllvisitors for customer assignment."""
    visitors_list = []
    try:
        qs = (
            ViewAllvisitors.objects.using("plus")
            .filter(Q(active=True) | Q(active__isnull=True))
            .values("gvisitorid", "vizitorname", "personname", "vizitorcode")
            .order_by("vizitorname", "personname")
        )
        seen = set()
        for v in qs:
            if not isinstance(v, dict):
                continue
            raw_gid = str(v.get("gvisitorid") or "").strip()
            key = raw_gid.lower()
            if not raw_gid or key in seen:
                continue
            seen.add(key)
            visitors_list.append(
                {
                    "id": raw_gid,
                    "name": (
                        v.get("vizitorname") or v.get("personname") or "بدون نام"
                    ).strip(),
                    "code": str(v.get("vizitorcode") or "").strip(),
                }
            )
    except (DatabaseError, DatabaseOperationForbidden):
        return []
    return visitors_list


class CustomerCreateView(PlusLoginRequiredMixin, View):
    template_name = "core/customer_create.html"

    def _build_form_context(self, form_values=None, errors=None, defaults=None):
        form_values = form_values or {}
        groups = list(
            Customergroup.objects.using("plus").all().order_by("groupname")
        )
        visitors = _load_active_visitors_for_customer_form()
        provinces, cities = _load_provinces_and_cities_for_form()

        if defaults is None:
            defaults = _resolve_customer_desktop_defaults(
                selected_group_gid=form_values.get("selected_group_id", ""),
                plus_user=getattr(self.request, "plus_user", None),
            )

        next_custno_preview = ""
        try:
            existing_custnos = (
                Tblcustomer.objects.using("plus")
                .exclude(custno__isnull=True)
                .exclude(custno="")
                .values_list("custno", flat=True)
            )
            next_custno_preview = (
                _calculate_next_custno(
                    existing_custnos, pad_width=defaults["custno_pad_width"]
                )
                or ""
            )
        except (DatabaseError, DatabaseOperationForbidden):
            next_custno_preview = ""

        selected_province_id = form_values.get("gprovinceid")
        if selected_province_id is None:
            selected_province_id = defaults.get("gprovinceid") or ""

        selected_city_id = form_values.get("gcityid")
        if selected_city_id is None:
            selected_city_id = defaults.get("gcityid") or ""

        selected_person_type = str(
            form_values.get("customertypecode")
            or defaults.get("customertypecode")
            or 1
        )

        return {
            "groups": groups,
            "visitors": visitors,
            "person_types": _CUSTOMER_PERSON_TYPES,
            "provinces": provinces,
            "cities": cities,
            "cities_json": json.dumps(cities, cls=DjangoJSONEncoder),
            "next_custno_preview": next_custno_preview,
            "errors": errors or [],
            "custname": form_values.get("custname", ""),
            "prename": form_values.get("prename", ""),
            "companyname": form_values.get("companyname", ""),
            "selected_group_id": form_values.get("selected_group_id", ""),
            "selected_visitor_id": form_values.get("selected_visitor_id", ""),
            "selected_person_type": selected_person_type,
            "mobile": form_values.get("mobile", ""),
            "phone": form_values.get("phone", ""),
            "citytelcode": form_values.get("citytelcode", ""),
            "nationalid": form_values.get("nationalid", ""),
            "economno": form_values.get("economno", ""),
            "registno": form_values.get("registno", ""),
            "postcode": form_values.get("postcode", ""),
            "credit": form_values.get("credit", ""),
            "address": form_values.get("address", ""),
            "custdesc": form_values.get("custdesc", ""),
            "selected_province_id": selected_province_id,
            "selected_city_id": selected_city_id,
        }

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._build_form_context())

    def post(self, request, *args, **kwargs):
        custname = request.POST.get("custname", "").strip()[:100]
        prename = request.POST.get("prename", "").strip()[:50]
        companyname = request.POST.get("companyname", "").strip()[:50]
        selected_group_id = request.POST.get("customer_group", "").strip()
        selected_visitor_id = request.POST.get("visitor_id", "").strip()
        raw_person_type = _normalize_ascii_digits(
            request.POST.get("customertypecode", "")
        )
        raw_mobile = request.POST.get("mobile", "").strip()[:100]
        raw_phone = request.POST.get("phone", "").strip()[:100]
        citytelcode = request.POST.get("citytelcode", "").strip()[:10]
        nationalid = _normalize_ascii_digits(
            request.POST.get("nationalid", "")
        )[:50]
        economno = _normalize_ascii_digits(
            request.POST.get("economno", "")
        )[:50]
        registno = _normalize_ascii_digits(
            request.POST.get("registno", "")
        )[:50]
        postcode = _normalize_ascii_digits(
            request.POST.get("postcode", "")
        )[:50]
        raw_credit = (
            _normalize_ascii_digits(request.POST.get("credit", ""))
            .replace(",", "")
            .strip()
        )
        address = request.POST.get("address", "").strip()[:250]
        custdesc = request.POST.get("custdesc", "").strip()[:500]
        posted_province_id = request.POST.get("gprovinceid", "").strip()
        posted_city_id = request.POST.get("gcityid", "").strip()

        form_values = {
            "custname": custname,
            "prename": prename,
            "companyname": companyname,
            "selected_group_id": selected_group_id,
            "selected_visitor_id": selected_visitor_id,
            "customertypecode": raw_person_type,
            "mobile": raw_mobile,
            "phone": raw_phone,
            "citytelcode": citytelcode,
            "nationalid": nationalid,
            "economno": economno,
            "registno": registno,
            "postcode": postcode,
            "credit": raw_credit,
            "address": address,
            "custdesc": custdesc,
            "gprovinceid": posted_province_id if "gprovinceid" in request.POST else None,
            "gcityid": posted_city_id if "gcityid" in request.POST else None,
        }

        # Validation (only custname and customer_group are required)
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

        credit_val = Decimal("0")
        if raw_credit:
            try:
                credit_val = Decimal(raw_credit)
                if credit_val < 0:
                    errors.append("سقف اعتبار نمی‌تواند منفی باشد.")
            except (InvalidOperation, ValueError):
                errors.append("مقدار سقف اعتبار واردشده معتبر نیست.")

        plus_user = getattr(request, "plus_user", None)
        defaults = _resolve_customer_desktop_defaults(
            selected_group_gid=selected_group_id,
            plus_user=plus_user,
            group=group,
        )

        if errors:
            return render(
                request,
                self.template_name,
                self._build_form_context(
                    form_values=form_values, errors=errors, defaults=defaults
                ),
            )

        try:
            # 1. Resolve desktop-compatible user & company metadata
            user_gucode = str(getattr(plus_user, "gucode", "") or "").strip()
            user_name = (
                getattr(plus_user, "uname", None)
                or getattr(plus_user, "uid", None)
                or ""
            ).strip()
            user_uid = str(getattr(plus_user, "uid", "") or "").strip()[:10]
            created_by = (
                user_gucode
                if (defaults["created_by_uses_guid"] and user_gucode)
                else (user_name or user_gucode)
            )[:100]

            company_gid = defaults["gcompanyid"]

            # 2. Calculate next CustNo strictly lower than 1900
            existing_custnos = (
                Tblcustomer.objects.using("plus")
                .exclude(custno__isnull=True)
                .exclude(custno="")
                .values_list("custno", flat=True)
            )
            next_custno = _calculate_next_custno(
                existing_custnos, pad_width=defaults["custno_pad_width"]
            )

            if not next_custno:
                return render(
                    request,
                    self.template_name,
                    self._build_form_context(
                        form_values=form_values,
                        errors=[
                            "کد مشتری نمی‌تواند بیشتر یا مساوی ۱۹۰۰ باشد. سقف شماره مشتری پر شده است."
                        ],
                        defaults=defaults,
                    ),
                )

            # 3. Resolve phone/mobile, full CustomerName, person type, and location FKs
            effective_mobile = raw_mobile or raw_phone
            effective_phone = raw_phone or raw_mobile
            full_customer_name = (
                f"{prename} {custname}".strip()[:200] if prename else custname[:200]
            )

            person_type_code = defaults["customertypecode"]
            if raw_person_type.isdigit() and int(raw_person_type) in (1, 2, 3, 4):
                person_type_code = int(raw_person_type)

            final_province_id = posted_province_id or defaults["gprovinceid"]
            final_city_id = posted_city_id or defaults["gcityid"]

            guid_lower = defaults["guid_lowercase"]
            new_gcustomerid = _format_guid_value(uuid.uuid4(), guid_lower)
            new_gsubdetailid = _format_guid_value(uuid.uuid4(), guid_lower)
            new_gc2g_id = _format_guid_value(uuid.uuid4(), guid_lower)
            shamsi_date = jdatetime.date.today().strftime("%Y/%m/%d")

            valid_visitor_gid = ""
            if selected_visitor_id:
                try:
                    vis_row = (
                        ViewAllvisitors.objects.using("plus")
                        .filter(gvisitorid__iexact=selected_visitor_id)
                        .values("gvisitorid")
                        .first()
                    )
                    if vis_row and vis_row.get("gvisitorid"):
                        valid_visitor_gid = str(vis_row["gvisitorid"]).strip()
                except (DatabaseError, DatabaseOperationForbidden):
                    valid_visitor_gid = ""

            with transaction.atomic(using="plus"):
                # 4. Create accounting SubDetail (تفصیلی شناور) in tblSubDetail (+ link tables)
                #    so Rahjou Plus desktop's INNER JOIN on tblSubDetail shows this customer!
                _ensure_customer_subdetail_in_db(
                    target_gsubdetailid=new_gsubdetailid,
                    target_gcustomerid=new_gcustomerid,
                    custno=next_custno,
                    full_customer_name=full_customer_name,
                    custdesc=custdesc,
                    company_gid=company_gid,
                    plus_user=plus_user,
                    shamsi_date=shamsi_date,
                    ref_customer=defaults["ref_customer"],
                    guid_lowercase=guid_lower,
                )

                # 5. Insert desktop-compatible customer row into tblCustomer
                new_customer = Tblcustomer.objects.using("plus").create(
                    custno=next_custno,
                    custname=custname,
                    customername=full_customer_name,
                    prename=prename or None,
                    companyname=companyname or None,
                    phone=effective_phone,
                    mobile=effective_mobile,
                    citytelcode=citytelcode or None,
                    address=address,
                    postcode=postcode or None,
                    nationalid=nationalid or None,
                    economno=economno or None,
                    registno=registno or None,
                    custdesc=custdesc or None,
                    status=defaults["status"],
                    salestatus=defaults["salestatus"],
                    custtypecode=defaults["custtypecode"],
                    customertypecode=person_type_code,
                    customertaxtype=defaults["customertaxtype"],
                    credit=credit_val,
                    creditchkd=Decimal("0"),
                    debit=Decimal("0"),
                    visitpriod=defaults["visitpriod"],
                    callstatus=defaults["callstatus"],
                    ranking=defaults["ranking"],
                    usercount=defaults["usercount"],
                    sentstatuscode=defaults["sentstatuscode"],
                    callwithemailsend=False,
                    callwithtel=False,
                    callwithfax=False,
                    callwithletter=False,
                    gprovinceid=final_province_id,
                    gcityid=final_city_id,
                    registerdate=timezone.now(),
                    createddate=shamsi_date,
                    lastupdateddate=shamsi_date,
                    createdby=created_by,
                    lastupdatedby=created_by,
                    uid=user_uid or None,
                    deletedby=None,
                    deleteddate=None,
                    gsubdetailid=new_gsubdetailid,
                    gcustomerid=new_gcustomerid,
                    gcompanyid=company_gid,
                )

                customer_int_id = getattr(new_customer, "customerid", None)
                if customer_int_id is None:
                    customer_int_id = (
                        Tblcustomer.objects.using("plus")
                        .filter(gcustomerid__iexact=new_gcustomerid)
                        .values_list("customerid", flat=True)
                        .first()
                    )

                # 6. Link customer to CustomerGroup in Customer2Group
                Customer2Group.objects.using("plus").create(
                    customergroupid=group.customergroupid,
                    customerid=customer_int_id,
                    gcustomerid=new_gcustomerid,
                    gcustomergroupid=group.gcustomergroupid,
                    gcustomer2groupid=new_gc2g_id,
                    gcompanyid=company_gid or group.gcompanyid,
                )

                # 7. Link customer to Visitor in VisitorToCustomer (when selected)
                if valid_visitor_gid:
                    Visitortocustomer.objects.using("plus").create(
                        gvisitorid=valid_visitor_gid,
                        gcustomerid=new_gcustomerid,
                        gvisitortocustomerid=_format_guid_value(
                            uuid.uuid4(), guid_lower
                        ),
                        gcompanyid=company_gid,
                    )

            messages.success(
                request,
                f"مشتری «{custname}» با کد {next_custno} با موفقیت ثبت شد.",
                fail_silently=True,
            )
            return redirect("core:customers")

        except Exception as exc:
            return render(
                request,
                self.template_name,
                self._build_form_context(
                    form_values=form_values,
                    errors=[f"خطا در ثبت اطلاعات: {str(exc)}"],
                    defaults=defaults,
                ),
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

                # Repair missing desktop-required fields & tblSubDetail on legacy mobile-created customers
                if getattr(getattr(customer, "_meta", None), "db_table", None) == "tblCustomer":
                    defaults = _resolve_customer_desktop_defaults(
                        selected_group_gid=selected_group_id,
                        plus_user=plus_user,
                        group=group,
                    )
                    if not customer.gsubdetailid:
                        customer.gsubdetailid = _format_guid_value(
                            uuid.uuid4(), defaults["guid_lowercase"]
                        )
                        update_fields.append("gsubdetailid")
                    if not customer.gcompanyid and defaults["gcompanyid"]:
                        customer.gcompanyid = defaults["gcompanyid"]
                        update_fields.append("gcompanyid")
                    if customer.custtypecode is None:
                        customer.custtypecode = defaults["custtypecode"]
                        update_fields.append("custtypecode")

                    _ensure_customer_subdetail_in_db(
                        target_gsubdetailid=customer.gsubdetailid,
                        target_gcustomerid=customer.gcustomerid,
                        custno=customer.custno or "1",
                        full_customer_name=custname[:200],
                        custdesc=customer.custdesc or "",
                        company_gid=customer.gcompanyid or defaults["gcompanyid"],
                        plus_user=plus_user,
                        shamsi_date=shamsi_date,
                        ref_customer=defaults["ref_customer"],
                        guid_lowercase=defaults["guid_lowercase"],
                    )

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


def _normalize_persian_status_text(text):
    """Normalize Persian/Arabic letters, ZWNJ, and whitespace for exact status comparisons."""
    if not text:
        return ""
    cleaned = (
        str(text)
        .strip()
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("ة", "ه")
    )
    for ch in (" ", "\t", "\n", "\r", "\u200c", "\u200b", "\u200d", "\ufeff"):
        cleaned = cleaned.replace(ch, "")
    return cleaned


def _is_sabt_shode_status(status_name):
    """Return True strictly when a Sale Request status represents 'ثبت شده'."""
    return _normalize_persian_status_text(status_name) == "ثبتشده"


def _resolve_sale_request_status(master):
    """Resolve status label and whether the Sale Request can be edited/deleted."""
    status_name = "ثبت شده" if getattr(master, "salerequeststatuscode", None) == 1 else "نامشخص"
    try:
        status_obj = (
            Salerequeststatus.objects.using("plus")
            .filter(salerequeststatuscode=master.salerequeststatuscode)
            .first()
        )
        if status_obj and getattr(status_obj, "salerequeststatusname", None):
            status_name = status_obj.salerequeststatusname
    except DatabaseError:
        pass
    return status_name, _is_sabt_shode_status(status_name)


def _guid_case_variants(values):
    """Return deduplicated stripped/upper/lower GUID strings for SQLite & SQL Server __in."""
    variants = set()
    for val in values:
        if not val:
            continue
        cleaned = str(val).strip()
        if cleaned:
            variants.add(cleaned)
            variants.add(cleaned.upper())
            variants.add(cleaned.lower())
    return list(variants)


def _load_visitor_lookup_maps():
    """Batch-load visitor display names indexed by GVisitorID, VisitorID, and GSubDetailID."""
    by_guid = {}
    by_int = {}
    by_subdetail = {}
    try:
        rows = ViewAllvisitors.objects.using("plus").values(
            "gvisitorid", "visitorid", "gsubdetailid", "vizitorname", "personname"
        )
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = (row.get("vizitorname") or row.get("personname") or "").strip()
            if not name:
                continue
            gvid = str(row.get("gvisitorid") or "").strip().lower()
            if gvid and gvid not in by_guid:
                by_guid[gvid] = name
            vid = row.get("visitorid")
            if vid is not None and vid not in by_int:
                by_int[vid] = name
            gsub = str(row.get("gsubdetailid") or "").strip().lower()
            if gsub and gsub not in by_subdetail:
                by_subdetail[gsub] = name
    except DatabaseError:
        pass
    return by_guid, by_int, by_subdetail


def _resolve_visitor_from_link(gvisitorid, visitorid, by_guid, by_int):
    """Resolve visitor name from a junction row's GUID or integer ID."""
    if gvisitorid:
        key = str(gvisitorid).strip().lower()
        if key in by_guid:
            return by_guid[key]
    if visitorid is not None and visitorid in by_int:
        return by_int[visitorid]
    return ""


def _resolve_sale_request_visitors(masters, visitor_maps=None):
    """Batch-resolve visitor names for Salerequestmaster records (no N+1)."""
    masters = list(masters)
    if not masters:
        return {}

    by_guid, by_int, by_subdetail = visitor_maps or _load_visitor_lookup_maps()
    if not (by_guid or by_int or by_subdetail):
        return {}

    guid_variants = _guid_case_variants(
        getattr(m, "gsalerequestmasterid", None) for m in masters
    )
    int_ids = [
        getattr(m, "salerequestmasterid", None)
        for m in masters
        if getattr(m, "salerequestmasterid", None) is not None
    ]

    link_by_guid = {}
    link_by_int = {}
    try:
        srv_q = Q()
        if guid_variants:
            srv_q |= Q(gsalerequestid__in=guid_variants)
        if int_ids:
            srv_q |= Q(salerequestid__in=int_ids)
        if srv_q:
            links = Salerequesttovisitor.objects.using("plus").filter(srv_q).values(
                "gsalerequestid", "salerequestid", "gvisitorid", "visitorid"
            )
            for row in links:
                if not isinstance(row, dict):
                    continue
                vname = _resolve_visitor_from_link(
                    row.get("gvisitorid"), row.get("visitorid"), by_guid, by_int
                )
                if not vname:
                    continue
                gsrid = str(row.get("gsalerequestid") or "").strip().lower()
                if gsrid and gsrid not in link_by_guid:
                    link_by_guid[gsrid] = vname
                srid = row.get("salerequestid")
                if srid is not None and srid not in link_by_int:
                    link_by_int[srid] = vname
    except DatabaseError:
        pass

    resolved = {}
    for m in masters:
        m_guid = str(getattr(m, "gsalerequestmasterid", "") or "").strip().lower()
        m_int = getattr(m, "salerequestmasterid", None)
        vname = link_by_guid.get(m_guid) or (
            link_by_int.get(m_int) if m_int is not None else ""
        )
        if not vname:
            m_vid = getattr(m, "visitorid", None)
            if m_vid is not None:
                vname = by_int.get(m_vid, "")
        if not vname:
            gsub5 = str(getattr(m, "gsubdetailid5", "") or "").strip().lower()
            if gsub5:
                vname = by_subdetail.get(gsub5, "")
        if m_guid and vname:
            resolved[m_guid] = vname
    return resolved


def _resolve_pre_factor_visitors(masters):
    """Batch-resolve visitor names for Prefactormaster records (no N+1)."""
    masters = list(masters)
    if not masters:
        return {}

    visitor_maps = _load_visitor_lookup_maps()
    by_guid, by_int, by_subdetail = visitor_maps
    if not (by_guid or by_int or by_subdetail):
        return {}

    guid_variants = _guid_case_variants(
        getattr(m, "gprefactormasterid", None) for m in masters
    )
    int_ids = [
        getattr(m, "prefactormasterid", None)
        for m in masters
        if getattr(m, "prefactormasterid", None) is not None
    ]

    link_by_guid = {}
    link_by_int = {}
    try:
        pfv_q = Q()
        if guid_variants:
            pfv_q |= Q(gprefactorid__in=guid_variants)
        if int_ids:
            pfv_q |= Q(prefactorid__in=int_ids)
        if pfv_q:
            links = Prefactortovisitor.objects.using("plus").filter(pfv_q).values(
                "gprefactorid", "prefactorid", "gvisitorid", "visitorid"
            )
            for row in links:
                if not isinstance(row, dict):
                    continue
                vname = _resolve_visitor_from_link(
                    row.get("gvisitorid"), row.get("visitorid"), by_guid, by_int
                )
                if not vname:
                    continue
                gpfid = str(row.get("gprefactorid") or "").strip().lower()
                if gpfid and gpfid not in link_by_guid:
                    link_by_guid[gpfid] = vname
                pfid = row.get("prefactorid")
                if pfid is not None and pfid not in link_by_int:
                    link_by_int[pfid] = vname
    except DatabaseError:
        pass

    # Optional fallback via linked Sale Request GUIDs when PreFactorToVisitor is empty
    sr_link_by_guid = {}
    unresolved_sr_guids = [
        getattr(m, "gsalerequestmasterid", None) or getattr(m, "gsalerequestid", None)
        for m in masters
        if (
            str(getattr(m, "gprefactormasterid", "") or "").strip().lower()
            not in link_by_guid
        )
    ]
    sr_variants = _guid_case_variants(unresolved_sr_guids)
    if sr_variants:
        try:
            sr_links = (
                Salerequesttovisitor.objects.using("plus")
                .filter(gsalerequestid__in=sr_variants)
                .values("gsalerequestid", "gvisitorid", "visitorid")
            )
            for row in sr_links:
                if not isinstance(row, dict):
                    continue
                vname = _resolve_visitor_from_link(
                    row.get("gvisitorid"), row.get("visitorid"), by_guid, by_int
                )
                gsrid = str(row.get("gsalerequestid") or "").strip().lower()
                if gsrid and vname and gsrid not in sr_link_by_guid:
                    sr_link_by_guid[gsrid] = vname
        except DatabaseError:
            pass

    resolved = {}
    for m in masters:
        m_guid = str(getattr(m, "gprefactormasterid", "") or "").strip().lower()
        m_int = getattr(m, "prefactormasterid", None)
        vname = link_by_guid.get(m_guid) or (
            link_by_int.get(m_int) if m_int is not None else ""
        )
        if not vname:
            gsub5 = str(getattr(m, "gsubdetailid5", "") or "").strip().lower()
            if gsub5:
                vname = by_subdetail.get(gsub5, "")
        if not vname:
            sr_guid = (
                str(
                    getattr(m, "gsalerequestmasterid", None)
                    or getattr(m, "gsalerequestid", None)
                    or ""
                )
                .strip()
                .lower()
            )
            if sr_guid:
                vname = sr_link_by_guid.get(sr_guid, "")
        if m_guid and vname:
            resolved[m_guid] = vname
    return resolved


def _resolve_factor_visitors(masters):
    """Batch-resolve visitor names for Salefactormaster records (no N+1)."""
    masters = list(masters)
    if not masters:
        return {}

    by_guid, by_int, by_subdetail = _load_visitor_lookup_maps()
    if not (by_guid or by_int or by_subdetail):
        return {}

    guid_variants = _guid_case_variants(
        getattr(m, "gsalefactormasterid", None) for m in masters
    )
    int_ids = [
        getattr(m, "salefactormasterid", None)
        for m in masters
        if getattr(m, "salefactormasterid", None) is not None
    ]

    link_by_guid = {}
    link_by_int = {}
    try:
        sfv_q = Q()
        if guid_variants:
            sfv_q |= Q(gsalefactorid__in=guid_variants)
        if int_ids:
            sfv_q |= Q(salefactorid__in=int_ids)
        if sfv_q:
            links = Salefactortovisitor.objects.using("plus").filter(sfv_q).values(
                "gsalefactorid", "salefactorid", "gvisitorid", "visitorid"
            )
            for row in links:
                if not isinstance(row, dict):
                    continue
                vname = _resolve_visitor_from_link(
                    row.get("gvisitorid"), row.get("visitorid"), by_guid, by_int
                )
                if not vname:
                    continue
                gsfid = str(row.get("gsalefactorid") or "").strip().lower()
                if gsfid and gsfid not in link_by_guid:
                    link_by_guid[gsfid] = vname
                sfid = row.get("salefactorid")
                if sfid is not None and sfid not in link_by_int:
                    link_by_int[sfid] = vname
    except DatabaseError:
        pass

    resolved = {}
    for m in masters:
        m_guid = str(getattr(m, "gsalefactormasterid", "") or "").strip().lower()
        m_int = getattr(m, "salefactormasterid", None)
        vname = ""
        direct_gvid = str(getattr(m, "gvisitorid", "") or "").strip().lower()
        if direct_gvid:
            vname = by_guid.get(direct_gvid, "")
        if not vname:
            vname = link_by_guid.get(m_guid) or (
                link_by_int.get(m_int) if m_int is not None else ""
            )
        if not vname:
            gsub5 = str(getattr(m, "gsubdetailid5", "") or "").strip().lower()
            if gsub5:
                vname = by_subdetail.get(gsub5, "")
        if m_guid and vname:
            resolved[m_guid] = vname
    return resolved
    
    
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

        # 3. Batch Fetch Customer Names & Visitor Names (prevents N+1 query issue)
        customer_ids = _guid_case_variants(
            sr.gcustomerid for sr in sale_requests_list if sr.gcustomerid
        )
        customer_map = {}
        if customer_ids:
            customers = Tblcustomer.objects.using("plus").filter(
                gcustomerid__in=customer_ids
            )
            customer_map = {
                str(c.gcustomerid).strip().lower(): c.custname
                for c in customers
                if getattr(c, "gcustomerid", None)
            }

        visitor_map = _resolve_sale_request_visitors(sale_requests_list)

        # 4. Construct Final Data List
        sale_requests = []
        for sr in sale_requests_list:
            cust_key = (
                str(sr.gcustomerid).strip().lower() if sr.gcustomerid else ""
            )
            customer_name = (
                customer_map.get(cust_key)
                or sr.requestman
                or "مشتری نامشخص"
            )
            sr_key = (
                str(sr.gsalerequestmasterid).strip().lower()
                if getattr(sr, "gsalerequestmasterid", None)
                else ""
            )
            resolved_visitor = visitor_map.get(sr_key, "")
            visitor_name = resolved_visitor or "بدون ویزیتور"

            sr_no = sr.salerequestno or ""
            # Search by keyword (Sale Request No, Customer Name, or Visitor Name)
            if (
                query
                and query not in sr_no
                and query not in customer_name
                and query not in visitor_name
            ):
                continue

            default_status = (
                "ثبت شده" if sr.salerequeststatuscode == 1 else "نامشخص"
            )
            status_name = status_map.get(
                sr.salerequeststatuscode, default_status
            )
            style = get_status_style(status_name)
            can_modify = _is_sabt_shode_status(status_name)

            sale_requests.append(
                {
                    "id": sr.gsalerequestmasterid,
                    "number": sr_no,
                    "date": sr.salerequestdate or sr.createddate or "-",
                    "customer_name": customer_name,
                    "visitor_name": visitor_name,
                    "has_visitor": bool(resolved_visitor),
                    "status_code": sr.salerequeststatuscode,
                    "status_name": status_name,
                    "can_modify": can_modify,
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
        status_name = (
            status_obj.salerequeststatusname if status_obj else "ثبت شده"
        )
        context["status_name"] = status_name
        context["can_modify"] = _is_sabt_shode_status(status_name)

        # 3. Fetch Customer & Visitor Details
        customer = None
        if master.gcustomerid:
            customer = (
                Tblcustomer.objects.using("plus")
                .filter(gcustomerid=master.gcustomerid)
                .first()
            )
        context["customer"] = customer

        sr_key = (
            str(master.gsalerequestmasterid).strip().lower()
            if getattr(master, "gsalerequestmasterid", None)
            else ""
        )
        resolved_visitor = _resolve_sale_request_visitors([master]).get(
            sr_key, ""
        )
        context["visitor_name"] = resolved_visitor or "بدون ویزیتور"
        context["has_visitor"] = bool(resolved_visitor)

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


def _consolidate_sale_request_items(raw_items):
    """Merge duplicate product rows by summing quantities while preserving order."""
    merged = {}
    ordered_keys = []
    for item in raw_items:
        p_id = str(item["product_id"]).strip()
        key = p_id.lower()
        if key not in merged:
            merged[key] = {
                "product_id": p_id,
                "quantity": item["quantity"],
                "price": item["price"],
            }
            ordered_keys.append(key)
        else:
            merged[key]["quantity"] += item["quantity"]
            merged[key]["price"] = item["price"]
    return [merged[k] for k in ordered_keys]


class SaleRequestEditView(SaleRequestCreateView):
    template_name = "core/sale_request_create.html"

    def _get_master(self, pk):
        clean_pk = str(pk or "").strip()
        if not clean_pk:
            raise Http404("درخواست فروش مورد نظر یافت نشد.")

        master = (
            Salerequestmaster.objects.using("plus")
            .filter(gsalerequestmasterid__iexact=clean_pk)
            .first()
        )
        if not master and clean_pk.isdigit():
            master = (
                Salerequestmaster.objects.using("plus")
                .filter(salerequestmasterid=int(clean_pk))
                .first()
            )
        if not master:
            raise Http404("درخواست فروش مورد نظر یافت نشد.")
        return master

    def _resolve_existing_visitor_guid(self, master):
        master_guid = str(getattr(master, "gsalerequestmasterid", "") or "").strip()
        try:
            if master_guid:
                srv = (
                    Salerequesttovisitor.objects.using("plus")
                    .filter(gsalerequestid__iexact=master_guid)
                    .first()
                )
                if srv and getattr(srv, "gvisitorid", None):
                    return str(srv.gvisitorid).strip()
            if getattr(master, "salerequestmasterid", None):
                srv = (
                    Salerequesttovisitor.objects.using("plus")
                    .filter(salerequestid=master.salerequestmasterid)
                    .first()
                )
                if srv and getattr(srv, "gvisitorid", None):
                    return str(srv.gvisitorid).strip()
        except DatabaseError:
            pass

        if getattr(master, "visitorid", None) is not None:
            try:
                vis_row = (
                    ViewAllvisitors.objects.using("plus")
                    .filter(visitorid=master.visitorid)
                    .values("gvisitorid")
                    .first()
                )
                if vis_row and vis_row.get("gvisitorid"):
                    return str(vis_row["gvisitorid"]).strip()
            except DatabaseError:
                pass
        return ""

    def _match_canonical_id(self, candidate_id, choices, id_key):
        if not candidate_id:
            return ""
        target = str(candidate_id).strip().lower()
        for ch in choices:
            raw_val = ch.get(id_key) if isinstance(ch, dict) else getattr(ch, id_key, "")
            if raw_val and str(raw_val).strip().lower() == target:
                return str(raw_val).strip()
        return str(candidate_id).strip()

    def _build_edit_context(
        self,
        master,
        return_to="",
        submitted_data=None,
    ):
        context = super().get_context_data()
        branches_list = list(context["branches"])
        inventories_list = list(context["inventories"])
        visitors_list = list(context["visitors"])

        if submitted_data is not None:
            raw_branch_id = submitted_data.get("branch_id", "")
            raw_inv_id = submitted_data.get("inv_id", "")
            raw_visitor_id = submitted_data.get("visitor_id", "")
            raw_customer_id = submitted_data.get("customer_id", "")
        else:
            raw_branch_id = getattr(master, "gbranchid", "") or ""
            raw_inv_id = getattr(master, "ginvid", "") or ""
            raw_visitor_id = self._resolve_existing_visitor_guid(master)
            raw_customer_id = getattr(master, "gcustomerid", "") or ""

        # Ensure existing visitor is selectable even if currently inactive
        if raw_visitor_id and not any(
            str(v["id"]).strip().lower() == str(raw_visitor_id).strip().lower()
            for v in visitors_list
        ):
            try:
                extra_vis = (
                    ViewAllvisitors.objects.using("plus")
                    .filter(gvisitorid__iexact=str(raw_visitor_id).strip())
                    .values("gvisitorid", "vizitorname", "personname", "vizitorcode")
                    .first()
                )
                if extra_vis and extra_vis.get("gvisitorid"):
                    visitors_list.append(
                        {
                            "id": str(extra_vis["gvisitorid"]),
                            "name": extra_vis.get("vizitorname")
                            or extra_vis.get("personname")
                            or "بدون نام",
                            "code": extra_vis.get("vizitorcode") or "",
                        }
                    )
            except DatabaseError:
                pass

        selected_branch_id = self._match_canonical_id(
            raw_branch_id, branches_list, "gbranchid"
        )
        selected_inv_id = self._match_canonical_id(
            raw_inv_id, inventories_list, "ginvid"
        )
        selected_visitor_id = self._match_canonical_id(
            raw_visitor_id, visitors_list, "id"
        )

        # Initial Customer payload
        initial_customer = None
        if raw_customer_id:
            cust_obj = (
                Tblcustomer.objects.using("plus")
                .filter(gcustomerid__iexact=str(raw_customer_id).strip())
                .first()
            )
            if cust_obj:
                initial_customer = {
                    "id": str(cust_obj.gcustomerid),
                    "name": cust_obj.custname or "",
                    "code": cust_obj.custno or "",
                    "phone": cust_obj.mobile or cust_obj.phone or "",
                }

        # Initial Product Line Items payload
        initial_items = []
        if submitted_data is not None and "items" in submitted_data:
            submitted_items = submitted_data["items"]
            kala_ids = list(
                {
                    variant
                    for it in submitted_items
                    if it.get("product_id")
                    for variant in (
                        str(it["product_id"]).strip(),
                        str(it["product_id"]).strip().upper(),
                        str(it["product_id"]).strip().lower(),
                    )
                }
            )
            kala_map = {}
            if kala_ids:
                for k in Tblkala.objects.using("plus").filter(gkalaid__in=kala_ids):
                    if k.gkalaid:
                        kala_map[str(k.gkalaid).strip().lower()] = k
            for it in submitted_items:
                pid = str(it["product_id"]).strip()
                kala = kala_map.get(pid.lower())
                qty_val = float(it["quantity"])
                initial_items.append(
                    {
                        "id": str(kala.gkalaid) if kala else pid,
                        "name": kala.kalaname if kala else "",
                        "code": kala.kalano if kala else "",
                        "unit": (kala.vahed1 if (kala and kala.vahed1) else "عدد"),
                        "quantity": int(qty_val) if qty_val.is_integer() else qty_val,
                        "price": int(it["price"]),
                    }
                )
        else:
            master_guid = str(getattr(master, "gsalerequestmasterid", "") or "").strip()
            details = list(
                Salerequestdetail.objects.using("plus")
                .filter(gsalerequestmasterid__iexact=master_guid)
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
                for k in Tblkala.objects.using("plus").filter(gkalaid__in=kala_ids):
                    if k.gkalaid:
                        kala_map[str(k.gkalaid).strip().lower()] = k

            for d in details:
                raw_kid = str(d.gkalaid or "").strip()
                kala = kala_map.get(raw_kid.lower())
                qty_val = float(d.quantity or 0)
                initial_items.append(
                    {
                        "id": str(kala.gkalaid) if kala else raw_kid,
                        "name": kala.kalaname
                        if kala
                        else (d.descript or "کالای نامشخص"),
                        "code": kala.kalano if kala else "",
                        "unit": kala.vahed1 if (kala and kala.vahed1) else "عدد",
                        "quantity": int(qty_val) if qty_val.is_integer() else qty_val,
                        "price": int(d.unitprice or 0),
                    }
                )

        back_url = (
            reverse("core:sale_request_list")
            if return_to == "list"
            else reverse(
                "core:sale_request_detail",
                kwargs={"pk": master.gsalerequestmasterid},
            )
        )

        context.update(
            {
                "is_edit": True,
                "master": master,
                "branches": branches_list,
                "inventories": inventories_list,
                "visitors": visitors_list,
                "selected_branch_id": selected_branch_id,
                "selected_inv_id": selected_inv_id,
                "selected_visitor_id": selected_visitor_id,
                "initial_customer": initial_customer,
                "initial_customer_json": json.dumps(
                    initial_customer, ensure_ascii=False, cls=DjangoJSONEncoder
                ),
                "initial_items_json": json.dumps(
                    initial_items, ensure_ascii=False, cls=DjangoJSONEncoder
                ),
                "return_to": return_to,
                "back_url": back_url,
            }
        )
        return context

    def get(self, request, pk, *args, **kwargs):
        master = self._get_master(pk)
        _, can_modify = _resolve_sale_request_status(master)
        if not can_modify:
            messages.error(
                request,
                "فقط درخواست‌های فروش با وضعیت «ثبت شده» قابل ویرایش هستند.",
            )
            return redirect(
                "core:sale_request_detail", pk=master.gsalerequestmasterid
            )

        return_to = (request.GET.get("from") or "").strip()
        context = self._build_edit_context(master, return_to=return_to)
        return render(request, self.template_name, context)

    def post(self, request, pk, *args, **kwargs):
        master = self._get_master(pk)
        _, can_modify = _resolve_sale_request_status(master)
        if not can_modify:
            messages.error(
                request,
                "فقط درخواست‌های فروش با وضعیت «ثبت شده» قابل ویرایش هستند.",
            )
            return redirect(
                "core:sale_request_detail", pk=master.gsalerequestmasterid
            )

        return_to = (
            request.POST.get("return_to") or request.GET.get("from") or ""
        ).strip()
        customer_id = request.POST.get("customer_id", "").strip()
        branch_id = request.POST.get("branch_id", "").strip()
        inv_id = request.POST.get("inv_id", "").strip()
        visitor_id = request.POST.get("visitor_id", "").strip()
        product_ids = request.POST.getlist("product_id[]")
        quantities = request.POST.getlist("quantity[]")
        prices = request.POST.getlist("price[]")

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

        submitted_snapshot = {
            "customer_id": customer_id,
            "branch_id": branch_id,
            "inv_id": inv_id,
            "visitor_id": visitor_id,
            "items": valid_items,
        }

        validation_error = None
        if not customer_id:
            validation_error = "لطفاً مشتری را انتخاب کنید."
        elif not branch_id:
            validation_error = "لطفاً شعبه را انتخاب کنید."
        elif not inv_id:
            validation_error = "لطفاً انبار را انتخاب کنید."
        elif not visitor_id:
            validation_error = "لطفاً ویزیتور را انتخاب کنید."
        elif not valid_items:
            validation_error = "حداقل باید یک کالا با تعداد معتبر انتخاب شود."

        if validation_error:
            messages.error(request, validation_error)
            context = self._build_edit_context(
                master,
                return_to=return_to,
                submitted_data=submitted_snapshot,
            )
            return render(request, self.template_name, context)

        merged_items = _consolidate_sale_request_items(valid_items)

        try:
            with transaction.atomic(using="plus"):
                today_jalali = jdatetime.date.today()
                jalali_date_str = today_jalali.strftime("%Y/%m/%d")
                current_time_str = datetime.now().strftime("%H:%M:%S")
                current_user_gucode = request.session.get("user_id")

                visitor_data = (
                    ViewAllvisitors.objects.using("plus")
                    .filter(gvisitorid__iexact=visitor_id)
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

                master_guid = str(master.gsalerequestmasterid).strip()
                master_int_id = getattr(master, "salerequestmasterid", None)

                # A. Update Master Record
                master.gcustomerid = customer_id
                master.gbranchid = branch_id
                master.ginvid = inv_id
                master.visitorid = visitor_int_id
                master.glastupdatedby = current_user_gucode
                master.lastupdateddate = jalali_date_str
                master.lastupdatedtime = current_time_str
                master.save(
                    using="plus",
                    update_fields=[
                        "gcustomerid",
                        "gbranchid",
                        "ginvid",
                        "visitorid",
                        "glastupdatedby",
                        "lastupdateddate",
                        "lastupdatedtime",
                    ],
                )

                # B. Update or Create SaleRequestToVisitor
                srv_q = Q(gsalerequestid__iexact=master_guid)
                if master_int_id is not None:
                    srv_q |= Q(salerequestid=master_int_id)

                updated_srv_count = (
                    Salerequesttovisitor.objects.using("plus")
                    .filter(srv_q)
                    .update(
                        gvisitorid=visitor_id,
                        visitorid=visitor_int_id,
                        porsant=visitor_poorsant,
                    )
                )
                if not updated_srv_count:
                    Salerequesttovisitor.objects.using("plus").create(
                        gsalerequesttovisitorid=str(uuid.uuid4()).upper(),
                        gsalerequestid=master_guid,
                        salerequestid=master_int_id,
                        gvisitorid=visitor_id,
                        visitorid=visitor_int_id,
                        porsant=visitor_poorsant,
                    )

                # C. Replace SaleRequestDetail Line Items
                detail_q = Q(gsalerequestmasterid__iexact=master_guid)
                if master_int_id is not None:
                    detail_q |= Q(salerequestmasterid=master_int_id)
                Salerequestdetail.objects.using("plus").filter(detail_q).delete()

                detail_instances = []
                for index, item in enumerate(merged_items, start=1):
                    detail_instances.append(
                        Salerequestdetail(
                            salerequestmasterid=master_int_id,
                            gsalerequestmasterid=master_guid,
                            gsalerequestdetailid=str(uuid.uuid4()).upper(),
                            uniqueid=str(uuid.uuid4()).upper(),
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
                    )

                Salerequestdetail.objects.using("plus").bulk_create(
                    detail_instances
                )

            messages.success(
                request,
                f"درخواست فروش شماره {master.salerequestno} با موفقیت ویرایش شد.",
            )
            if return_to == "list":
                return redirect("core:sale_request_list")
            return redirect(
                "core:sale_request_detail", pk=master.gsalerequestmasterid
            )

        except Exception as exc:
            messages.error(request, f"خطا در ویرایش درخواست فروش: {str(exc)}")
            context = self._build_edit_context(
                master,
                return_to=return_to,
                submitted_data=submitted_snapshot,
            )
            return render(request, self.template_name, context)


class SaleRequestDeleteView(PlusLoginRequiredMixin, View):
    def _get_master(self, pk):
        clean_pk = str(pk or "").strip()
        if not clean_pk:
            raise Http404("درخواست فروش مورد نظر یافت نشد.")

        master = (
            Salerequestmaster.objects.using("plus")
            .filter(gsalerequestmasterid__iexact=clean_pk)
            .first()
        )
        if not master and clean_pk.isdigit():
            master = (
                Salerequestmaster.objects.using("plus")
                .filter(salerequestmasterid=int(clean_pk))
                .first()
            )
        if not master:
            raise Http404("درخواست فروش مورد نظر یافت نشد.")
        return master

    def get(self, request, pk, *args, **kwargs):
        return redirect("core:sale_request_detail", pk=pk)

    def post(self, request, pk, *args, **kwargs):
        master = self._get_master(pk)
        _, can_modify = _resolve_sale_request_status(master)
        if not can_modify:
            messages.error(
                request,
                "فقط درخواست‌های فروش با وضعیت «ثبت شده» قابل حذف هستند.",
            )
            return redirect(
                "core:sale_request_detail", pk=master.gsalerequestmasterid
            )

        req_no = master.salerequestno or ""
        master_guid = str(master.gsalerequestmasterid).strip()
        master_int_id = getattr(master, "salerequestmasterid", None)

        try:
            with transaction.atomic(using="plus"):
                detail_q = Q(gsalerequestmasterid__iexact=master_guid)
                if master_int_id is not None:
                    detail_q |= Q(salerequestmasterid=master_int_id)
                Salerequestdetail.objects.using("plus").filter(detail_q).delete()

                srv_q = Q(gsalerequestid__iexact=master_guid)
                if master_int_id is not None:
                    srv_q |= Q(salerequestid=master_int_id)
                Salerequesttovisitor.objects.using("plus").filter(srv_q).delete()

                master.delete(using="plus")

            messages.success(
                request,
                f"درخواست فروش شماره {req_no} با موفقیت حذف شد.",
            )
            return redirect("core:sale_request_list")

        except Exception as exc:
            messages.error(request, f"خطا در حذف درخواست فروش: {str(exc)}")
            return redirect(
                "core:sale_request_detail", pk=master.gsalerequestmasterid
            )


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

        # 1. Fetch all available PreFactor statuses from PreFactorDetailStatus
        try:
            statuses = list(
                Prefactordetailstatus.objects.using("plus")
                .all()
                .order_by("prefactordetailstatuscode")
            )
            status_map = {
                s.prefactordetailstatuscode: s.prefactordetailstatusname
                for s in statuses
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

        if status_filter != "all" and status_filter.lstrip("-").isdigit():
            selected_code = int(status_filter)
            status_q = Q(prefactorstatuscode=selected_code)
            try:
                detail_master_ids = _guid_case_variants(
                    Prefactordetail.objects.using("plus")
                    .filter(prefactordetailstatuscode=selected_code)
                    .values_list("gprefactormasterid", flat=True)
                    .distinct()
                )
                if detail_master_ids:
                    status_q |= Q(gprefactormasterid__in=detail_master_ids)
            except DatabaseError:
                pass
            pre_factors_qs = pre_factors_qs.filter(status_q)

        pre_factors_list = list(pre_factors_qs[:150])

        # 3. Batch Fetch Customer Names, Visitor Names & Totals/Detail Statuses (No N+1)
        customer_ids = _guid_case_variants(
            pf.gcustomerid for pf in pre_factors_list if pf.gcustomerid
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

        visitor_map = _resolve_pre_factor_visitors(pre_factors_list)

        pf_totals_map = {}
        pf_detail_status_map = {}
        pf_master_guids = _guid_case_variants(
            pf.gprefactormasterid
            for pf in pre_factors_list
            if getattr(pf, "gprefactormasterid", None)
        )
        if pf_master_guids:
            try:
                pf_agg_rows = (
                    Prefactordetail.objects.using("plus")
                    .filter(gprefactormasterid__in=pf_master_guids)
                    .values("gprefactormasterid")
                    .annotate(
                        line_net=Sum(
                            (F("quantity") * F("unitprice"))
                            - Coalesce(F("discount"), Value(0)),
                            output_field=DecimalField(),
                        ),
                        detail_status=Max("prefactordetailstatuscode"),
                    )
                )
                for row in pf_agg_rows:
                    if not isinstance(row, dict):
                        continue
                    key = str(row.get("gprefactormasterid") or "").strip().lower()
                    if not key:
                        continue
                    pf_totals_map[key] = pf_totals_map.get(key, Decimal("0")) + Decimal(
                        str(row.get("line_net") or 0)
                    )
                    if row.get("detail_status") is not None and key not in pf_detail_status_map:
                        pf_detail_status_map[key] = row["detail_status"]
            except DatabaseError:
                pass

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
            pf_key = (
                str(pf.gprefactormasterid).strip().lower()
                if getattr(pf, "gprefactormasterid", None)
                else ""
            )
            resolved_visitor = visitor_map.get(pf_key, "")
            visitor_name = resolved_visitor or "بدون ویزیتور"
            total_amount = int(pf_totals_map.get(pf_key, Decimal("0")))

            pf_no = pf.prefactorno or ""
            if (
                query
                and query not in pf_no
                and query not in customer_name
                and query not in visitor_name
            ):
                continue

            master_code = getattr(pf, "prefactorstatuscode", None)
            detail_code = pf_detail_status_map.get(pf_key)
            if master_code is not None and master_code in status_map:
                effective_status_code = master_code
            elif detail_code is not None and detail_code in status_map:
                effective_status_code = detail_code
            else:
                effective_status_code = (
                    master_code if master_code is not None else detail_code
                )

            status_name = status_map.get(effective_status_code, "ثبت شده")
            style = get_status_style(status_name)

            pre_factors.append(
                {
                    "id": pf.gprefactormasterid,
                    "number": pf_no,
                    "date": pf.prefactordate or pf.createddate or "-",
                    "customer_name": customer_name,
                    "visitor_name": visitor_name,
                    "has_visitor": bool(resolved_visitor),
                    "total_amount": total_amount,
                    "status_code": effective_status_code,
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

        # 2. Fetch Customer & Visitor Details
        customer = None
        if master.gcustomerid:
            customer = (
                Tblcustomer.objects.using("plus")
                .filter(gcustomerid__iexact=str(master.gcustomerid).strip())
                .first()
            )
        context["customer"] = customer

        pf_key = (
            str(master.gprefactormasterid).strip().lower()
            if getattr(master, "gprefactormasterid", None)
            else ""
        )
        resolved_visitor = _resolve_pre_factor_visitors([master]).get(
            pf_key, ""
        )
        context["visitor_name"] = resolved_visitor or "بدون ویزیتور"
        context["has_visitor"] = bool(resolved_visitor)

        # 3. Fetch PreFactor Line Items & Products
        details = list(
            Prefactordetail.objects.using("plus")
            .filter(
                gprefactormasterid__iexact=str(
                    master.gprefactormasterid
                ).strip()
            )
            .order_by("rowid")
        )

        # 4. Fetch Status from PreFactorDetailStatus (master code or first detail row code)
        status_name = "ثبت شده"
        candidate_codes = []
        if getattr(master, "prefactorstatuscode", None) is not None:
            candidate_codes.append(master.prefactorstatuscode)
        for d in details:
            d_code = getattr(d, "prefactordetailstatuscode", None)
            if d_code is not None and d_code not in candidate_codes:
                candidate_codes.append(d_code)

        for code in candidate_codes:
            try:
                status_obj = (
                    Prefactordetailstatus.objects.using("plus")
                    .filter(prefactordetailstatuscode=code)
                    .first()
                )
                if status_obj and getattr(
                    status_obj, "prefactordetailstatusname", None
                ):
                    status_name = status_obj.prefactordetailstatusname
                    break
            except DatabaseError:
                break
        context["status_name"] = status_name

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

        # 3. Batch Fetch Customer Names, Visitor Names & Totals (No N+1)
        customer_ids = _guid_case_variants(
            sf.gcustomerid for sf in factors_list if sf.gcustomerid
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

        visitor_map = _resolve_factor_visitors(factors_list)

        sf_totals_map = {}
        sf_master_guids = _guid_case_variants(
            sf.gsalefactormasterid
            for sf in factors_list
            if getattr(sf, "gsalefactormasterid", None)
        )
        if sf_master_guids:
            try:
                sf_agg_rows = (
                    Salefactordetail.objects.using("plus")
                    .filter(gsalefactormasterid__in=sf_master_guids)
                    .values("gsalefactormasterid")
                    .annotate(
                        line_net=Sum(
                            (F("quantity") * F("unitprice"))
                            - Coalesce(F("discount"), Value(0)),
                            output_field=DecimalField(),
                        )
                    )
                )
                for row in sf_agg_rows:
                    if not isinstance(row, dict):
                        continue
                    key = str(row.get("gsalefactormasterid") or "").strip().lower()
                    if not key:
                        continue
                    sf_totals_map[key] = sf_totals_map.get(key, Decimal("0")) + Decimal(
                        str(row.get("line_net") or 0)
                    )
            except DatabaseError:
                pass

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
            sf_key = (
                str(sf.gsalefactormasterid).strip().lower()
                if getattr(sf, "gsalefactormasterid", None)
                else ""
            )
            resolved_visitor = visitor_map.get(sf_key, "")
            visitor_name = resolved_visitor or "بدون ویزیتور"

            line_net = sf_totals_map.get(sf_key, Decimal("0"))
            master_discount = Decimal(str(getattr(sf, "discount", 0) or 0))
            total_amount = int(line_net - master_discount)

            sf_no = sf.salefactorno or ""
            if (
                query
                and query not in sf_no
                and query not in customer_name
                and query not in visitor_name
            ):
                continue

            status_name = status_map.get(sf.salefactorstatuscode, "ثبت شده")
            style = get_status_style(status_name)

            factors.append(
                {
                    "id": sf.gsalefactormasterid,
                    "number": sf_no,
                    "date": sf.salefactordate or sf.createddate or "-",
                    "customer_name": customer_name,
                    "visitor_name": visitor_name,
                    "has_visitor": bool(resolved_visitor),
                    "total_amount": total_amount,
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

        # 3. Fetch Customer & Visitor Details
        customer = None
        if master.gcustomerid:
            customer = (
                Tblcustomer.objects.using("plus")
                .filter(gcustomerid__iexact=str(master.gcustomerid).strip())
                .first()
            )
        context["customer"] = customer

        sf_key = (
            str(master.gsalefactormasterid).strip().lower()
            if getattr(master, "gsalefactormasterid", None)
            else ""
        )
        resolved_visitor = _resolve_factor_visitors([master]).get(sf_key, "")
        context["visitor_name"] = resolved_visitor or "بدون ویزیتور"
        context["has_visitor"] = bool(resolved_visitor)

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
    
    