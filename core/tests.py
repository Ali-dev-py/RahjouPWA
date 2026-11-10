"""Tests for routes, SaleRequest views, templates, context keys, and PWA delivery."""

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase
from django.urls import NoReverseMatch, reverse

from core.views import (
    CustomersView,
    DashboardView,
    SaleRequestCreateView,
    SaleRequestDetailView,
    SaleRequestListView,
    SaleRequestPDFView,
)


def _attach_authenticated_session(request, user_id="USER-GUID-001"):
    """Attach an in-memory session and fallback message storage to a request."""
    request.session = {"user_id": user_id}
    setattr(request, "_messages", FallbackStorage(request))
    return request


def _mock_active_user(user_id="USER-GUID-001"):
    return SimpleNamespace(
        gucode=user_id,
        uid="ali",
        uname="علی",
        utitle="کاربر فروش",
        uactive=True,
        isadmin=False,
    )


class RouteAndPWASmokeTests(SimpleTestCase):
    """Confirm named routes, removed legacy routes, redirects, and PWA assets."""

    def test_sale_request_named_urls_resolve(self) -> None:
        self.assertEqual(reverse("core:sale_request_list"), "/sale-requests/")
        self.assertEqual(
            reverse("core:sale_request_detail"),
            "/sale-requests/detail/",
        )
        self.assertEqual(
            reverse("core:sale_request_detail", kwargs={"pk": "SR-GUID-1"}),
            "/sale-requests/detail/SR-GUID-1/",
        )
        self.assertEqual(
            reverse("core:sale_request_pdf", kwargs={"pk": "SR-GUID-1"}),
            "/sale-requests/SR-GUID-1/pdf/",
        )
        self.assertEqual(
            reverse("core:sale_request_create"),
            "/sale-requests/new/",
        )

    def test_legacy_factor_route_names_are_removed(self) -> None:
        for legacy_name in (
            "core:factor_list",
            "core:factor_detail",
            "core:factor_create",
            "core:factor_pdf",
        ):
            with self.subTest(route=legacy_name):
                with self.assertRaises(NoReverseMatch):
                    reverse(legacy_name)

    def test_public_pages_render(self) -> None:
        public_pages = {
            "core:splash": "core/splash.html",
            "core:login": "core/login.html",
        }
        for route_name, template_name in public_pages.items():
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template_name)
                self.assertTemplateUsed(response, "base.html")
                self.assertContains(response, reverse("web_app_manifest"))

    def test_protected_sale_request_routes_redirect_when_anonymous(self) -> None:
        protected_urls = [
            reverse("core:dashboard"),
            reverse("core:sale_request_list"),
            reverse("core:sale_request_detail"),
            reverse("core:sale_request_detail", kwargs={"pk": "SR-1"}),
            reverse("core:sale_request_pdf", kwargs={"pk": "SR-1"}),
            reverse("core:sale_request_create"),
        ]
        for url in protected_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("core:login"), response["Location"])

    def test_splash_declares_timed_login_redirect(self) -> None:
        response = self.client.get(reverse("core:splash"))
        self.assertContains(
            response,
            f'data-splash-redirect-url="{reverse("core:login")}"',
        )
        self.assertContains(response, 'data-splash-redirect-delay="2500"')
        self.assertContains(response, 'content="3;url=/login/"')

    def test_service_worker_has_root_scope(self) -> None:
        worker_url = reverse("service_worker")
        response = self.client.get(worker_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertIn("application/javascript", response["Content-Type"])

        head_response = self.client.head(worker_url)
        self.assertEqual(head_response.status_code, 200)
        self.assertEqual(head_response["Service-Worker-Allowed"], "/")

    def test_canonical_manifest_is_installable_and_uses_sale_request_shortcut(
        self,
    ) -> None:
        manifest_url = reverse("web_app_manifest")
        response = self.client.get(manifest_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/manifest+json", response["Content-Type"])

        manifest = json.loads(b"".join(response.streaming_content))
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["scope"], "/")
        self.assertFalse(manifest["prefer_related_applications"])
        self.assertEqual(manifest["screenshots"][0]["form_factor"], "narrow")

        shortcut_urls = [s["url"] for s in manifest["shortcuts"]]
        self.assertIn("/sale-requests/new/?source=pwa-shortcut", shortcut_urls)
        self.assertNotIn("/factors/new/?source=pwa-shortcut", shortcut_urls)

    def test_required_pwa_files_exist(self) -> None:
        static_dir = Path(settings.STATICFILES_DIRS[0])
        required = (
            "manifest.json",
            "serviceworker.js",
            "css/app.css",
            "js/app.js",
            "images/logo.png",
            "icons/icon-192.png",
            "icons/icon-512.png",
            "screenshots/dashboard.png",
        )
        for relative_path in required:
            with self.subTest(path=relative_path):
                self.assertTrue((static_dir / relative_path).is_file())


class SaleRequestViewsAndTemplatesTests(SimpleTestCase):
    """Verify SaleRequest views, context keys, templates, and POST flow."""

    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.user = _mock_active_user()

    @patch("core.views.TuaUser")
    @patch("core.views.Salerequeststatus")
    @patch("core.views.Salerequestmaster")
    @patch("core.views.Tblcustomer")
    @patch("core.views.Salerequestdetail")
    def test_dashboard_uses_sale_request_no_context_key_and_links(
        self,
        mock_detail,
        mock_customer,
        mock_master,
        mock_status,
        mock_user,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        mock_status.objects.using.return_value.all.return_value = [
            SimpleNamespace(
                salerequeststatuscode=1, salerequeststatusname="تایید شده"
            )
        ]

        sample_master = SimpleNamespace(
            gsalerequestmasterid="SR-GUID-100",
            salerequestno="000123",
            salerequestdate="1405/08/18",
            createddate="1405/08/18",
            gcustomerid="CUST-1",
            requestman="",
            salerequeststatuscode=1,
        )
        master_using = mock_master.objects.using.return_value
        master_using.filter.return_value.order_by.return_value = [sample_master]
        master_using.filter.return_value.values_list.return_value = [
            "SR-GUID-100"
        ]
        master_using.filter.return_value.count.return_value = 1

        mock_customer.objects.using.return_value.filter.return_value = [
            SimpleNamespace(gcustomerid="CUST-1", custname="فروشگاه بهار")
        ]
        detail_using = mock_detail.objects.using.return_value
        detail_using.filter.return_value.values.return_value.annotate.return_value = [
            {"gsalerequestmasterid": "SR-GUID-100", "total": Decimal("250000")}
        ]
        detail_using.filter.return_value.aggregate.return_value = {
            "total": Decimal("250000")
        }

        request = _attach_authenticated_session(
            self.factory.get(reverse("core:dashboard"))
        )
        response = DashboardView.as_view()(request)
        response.render()

        self.assertEqual(response.status_code, 200)
        activities = response.context_data["recent_activities"]
        self.assertEqual(len(activities), 1)
        self.assertIn("sale_request_no", activities[0])
        self.assertNotIn("factor_no", activities[0])
        self.assertEqual(activities[0]["sale_request_no"], "000123")

        html = response.content.decode("utf-8")
        self.assertIn(reverse("core:sale_request_list"), html)
        self.assertIn(
            f'{reverse("core:sale_request_detail")}?id=SR-GUID-100', html
        )
        self.assertIn(reverse("core:sale_request_create"), html)

    @patch("core.views.TuaUser")
    @patch("core.views.Salerequeststatus")
    @patch("core.views.Salerequestmaster")
    @patch("core.views.Tblcustomer")
    def test_sale_request_list_view_and_template(
        self,
        mock_customer,
        mock_master,
        mock_status,
        mock_user,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        mock_status.objects.using.return_value.all.return_value.order_by.return_value = [
            SimpleNamespace(
                salerequeststatuscode=1, salerequeststatusname="ثبت شده"
            )
        ]
        mock_master.objects.using.return_value.all.return_value.order_by.return_value = [
            SimpleNamespace(
                gsalerequestmasterid="SR-GUID-200",
                salerequestno="000456",
                salerequestdate="1405/08/18",
                createddate="1405/08/18",
                gcustomerid="CUST-2",
                requestman="",
                salerequeststatuscode=1,
            )
        ]
        mock_customer.objects.using.return_value.filter.return_value = [
            SimpleNamespace(gcustomerid="CUST-2", custname="شرکت امید")
        ]

        request = _attach_authenticated_session(
            self.factory.get(reverse("core:sale_request_list"))
        )
        request.resolver_match = SimpleNamespace(url_name="sale_request_list")
        response = SaleRequestListView.as_view()(request)
        response.render()

        self.assertEqual(response.status_code, 200)
        self.assertIn("sale_requests", response.context_data)
        self.assertNotIn("factors", response.context_data)
        self.assertEqual(len(response.context_data["sale_requests"]), 1)

        html = response.content.decode("utf-8")
        self.assertIn("شرکت امید", html)
        self.assertIn(
            reverse(
                "core:sale_request_detail", kwargs={"pk": "SR-GUID-200"}
            ),
            html,
        )
        self.assertIn("sale-request-card", html)

    @patch("core.views.TuaUser")
    @patch("core.views.Salerequestmaster")
    @patch("core.views.Salerequeststatus")
    @patch("core.views.Tblcustomer")
    @patch("core.views.Salerequestdetail")
    @patch("core.views.Tblkala")
    def test_sale_request_detail_view_found_and_not_found(
        self,
        mock_kala,
        mock_detail,
        mock_customer,
        mock_status,
        mock_master,
        mock_user,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )

        # Case 1: Found
        master_obj = SimpleNamespace(
            gsalerequestmasterid="SR-GUID-300",
            salerequestno="000789",
            salerequestdate="1405/08/18",
            createddate="1405/08/18",
            salerequeststatuscode=1,
            gcustomerid="CUST-3",
            requestman="",
        )
        mock_master.objects.using.return_value.filter.return_value.first.return_value = (
            master_obj
        )
        mock_status.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            salerequeststatusname="تایید شده"
        )
        mock_customer.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            custname="مشتری نمونه",
            economno="1234567890",
            nationalid="",
            mobile="09120000000",
            phone="",
            address="تهران",
        )
        mock_detail.objects.using.return_value.filter.return_value.order_by.return_value = [
            SimpleNamespace(
                gkalaid="KALA-1",
                quantity=Decimal("2"),
                unitprice=Decimal("150000"),
                discount=Decimal("10000"),
                descript="",
            )
        ]
        mock_kala.objects.using.return_value.filter.return_value = [
            SimpleNamespace(
                gkalaid="KALA-1",
                kalaname="کالای تست",
                kalano="K-10",
                vahed1="بسته",
            )
        ]

        url = reverse("core:sale_request_detail", kwargs={"pk": "SR-GUID-300"})
        request = _attach_authenticated_session(self.factory.get(url))
        response = SaleRequestDetailView.as_view()(request, pk="SR-GUID-300")
        response.render()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context_data["sale_request_found"])
        self.assertNotIn("factor_found", response.context_data)
        self.assertEqual(response.context_data["total_payable"], 290000)

        html = response.content.decode("utf-8")
        self.assertIn("btnDownloadSaleRequest", html)
        self.assertIn("btnTopPrintSaleRequest", html)
        self.assertIn("sale-request-pdf-styles", html)
        self.assertIn(
            reverse("core:sale_request_pdf", kwargs={"pk": "SR-GUID-300"}),
            html,
        )

        # Case 2: Not found
        mock_master.objects.using.return_value.filter.return_value.first.return_value = (
            None
        )
        not_found_req = _attach_authenticated_session(self.factory.get(url))
        not_found_resp = SaleRequestDetailView.as_view()(
            not_found_req, pk="MISSING"
        )
        not_found_resp.render()
        self.assertFalse(not_found_resp.context_data["sale_request_found"])
        self.assertIn(
            reverse("core:sale_request_list"),
            not_found_resp.content.decode("utf-8"),
        )

    @patch("core.views.TuaUser")
    @patch("core.views.Tblcustomer")
    @patch("core.views.Branches")
    @patch("core.views.Tblinv")
    @patch("core.views.ViewAllvisitors")
    @patch("core.views.Statementprice")
    @patch("core.views.Tblkala")
    def test_sale_request_create_get_renders_form_and_json(
        self,
        mock_kala,
        mock_sp,
        mock_visitors,
        mock_inv,
        mock_branches,
        mock_customer,
        mock_user,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        mock_customer.objects.using.return_value.values.return_value.order_by.return_value = [
            {
                "gcustomerid": "CUST-1",
                "custname": "مشتری اول",
                "custno": "101",
                "mobile": "09121111111",
                "phone": "",
            }
        ]
        mock_branches.objects.using.return_value.values.return_value.order_by.return_value = [
            {"gbranchid": "BR-1", "branchname": "شعبه مرکزی", "branchcode": "1"}
        ]
        mock_inv.objects.using.return_value.values.return_value.order_by.return_value = [
            {"ginvid": "INV-1", "invname": "انبار اصلی", "invcode": "1"}
        ]
        mock_visitors.objects.using.return_value.filter.return_value.values.return_value.order_by.return_value = [
            {
                "gvisitorid": "VIS-1",
                "vizitorname": "بازاریاب نمونه",
                "personname": "",
                "vizitorcode": "10",
            }
        ]
        mock_sp.objects.using.return_value.filter.return_value.values.return_value.order_by.return_value = [
            {"gkalaid": "KALA-1", "price": Decimal("95000")}
        ]
        mock_kala.objects.using.return_value.values.return_value.order_by.return_value = [
            {
                "gkalaid": "KALA-1",
                "kalaname": "محصول یک",
                "kalano": "P-1",
                "vahed1": "عدد",
                "selprice": Decimal("90000"),
            }
        ]

        request = _attach_authenticated_session(
            self.factory.get(reverse("core:sale_request_create"))
        )
        response = SaleRequestCreateView.as_view()(request)
        response.render()

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('id="saleRequestForm"', html)
        self.assertIn('form="saleRequestForm"', html)
        self.assertIn(f'action="{reverse("core:sale_request_create")}"', html)
        self.assertNotIn("factorForm", html)

    @patch("core.views.transaction.atomic")
    @patch("core.views.TuaUser")
    @patch("core.views.ViewAllvisitors")
    @patch("core.views.Salerequestmaster")
    @patch("core.views.Salerequesttovisitor")
    @patch("core.views.Salerequestdetail")
    def test_sale_request_create_post_redirects_to_sale_request_list(
        self,
        mock_detail,
        mock_srv,
        mock_master,
        mock_visitors,
        mock_user,
        mock_atomic,
    ) -> None:
        mock_atomic.return_value = MagicMock()
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        mock_visitors.objects.using.return_value.filter.return_value.values.return_value.first.return_value = {
            "visitorid": 5,
            "poorsant": Decimal("2.50"),
        }
        mock_master.objects.using.return_value.filter.return_value.order_by.return_value.values.return_value.first.return_value = {
            "salerequestno": "000009"
        }
        mock_master.objects.using.return_value.create.return_value = (
            SimpleNamespace(salerequestmasterid=42)
        )
        mock_srv.objects.using.return_value.aggregate.return_value = {
            "max_id": 10
        }
        mock_srv._meta.get_fields.return_value = [
            SimpleNamespace(name="salerequesttovisitorid"),
            SimpleNamespace(name="gsalerequesttovisitorid"),
            SimpleNamespace(name="gvisitorid"),
            SimpleNamespace(name="porsant"),
            SimpleNamespace(name="gsalerequestid"),
            SimpleNamespace(name="salerequestid"),
            SimpleNamespace(name="visitorid"),
        ]

        request = _attach_authenticated_session(
            self.factory.post(
                reverse("core:sale_request_create"),
                data={
                    "customer_id": "CUST-1",
                    "branch_id": "BR-1",
                    "inv_id": "INV-1",
                    "visitor_id": "VIS-1",
                    "product_id[]": ["KALA-1"],
                    "quantity[]": ["3"],
                    "price[]": ["100000"],
                },
            )
        )
        response = SaleRequestCreateView.as_view()(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("core:sale_request_list"))
        create_kwargs = mock_master.objects.using.return_value.create.call_args.kwargs
        self.assertEqual(create_kwargs["salerequestno"], "000010")
        mock_detail.objects.using.return_value.bulk_create.assert_called_once()

    @patch("core.views.TuaUser")
    @patch("core.views.Salerequestmaster")
    @patch("core.views.Tblcustomer")
    @patch("core.views.Salerequestdetail")
    @patch("core.views.Tblkala")
    def test_sale_request_pdf_view_renders_template_and_404(
        self,
        mock_kala,
        mock_detail,
        mock_customer,
        mock_master,
        mock_user,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        mock_master.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            gsalerequestmasterid="SR-GUID-500",
            salerequestno="000500",
            salerequestdate="1405/08/18",
            createddate="1405/08/18",
            createdtime="12:30:00",
            gcustomerid="CUST-5",
            requestman="",
        )
        mock_customer.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            custname="خریدار تست",
            mobile="09123456789",
            phone="",
            address="خیابان ولیعصر",
        )
        mock_detail.objects.using.return_value.filter.return_value.order_by.return_value = [
            SimpleNamespace(
                gkalaid="KALA-1",
                quantity=Decimal("1"),
                unitprice=Decimal("500000"),
                discount=Decimal("0"),
                descript="",
            )
        ]
        mock_kala.objects.using.return_value.filter.return_value = [
            SimpleNamespace(
                gkalaid="KALA-1", kalaname="کالای پی‌دی‌اف", vahed1="عدد"
            )
        ]

        url = reverse("core:sale_request_pdf", kwargs={"pk": "SR-GUID-500"})
        request = _attach_authenticated_session(self.factory.get(url))
        response = SaleRequestPDFView.as_view()(request, pk="SR-GUID-500")

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('id="sale-request-pdf-styles"', html)
        self.assertNotIn('id="factor-pdf-styles"', html)
        self.assertIn("درخواست فروش خریدار تست شماره 000500.pdf", html)
        self.assertIn("</html>", html)

        # Missing SaleRequest raises Http404
        mock_master.objects.using.return_value.filter.return_value.first.return_value = (
            None
        )
        missing_req = _attach_authenticated_session(self.factory.get(url))
        with self.assertRaises(Http404):
            SaleRequestPDFView.as_view()(missing_req, pk="MISSING")

    @patch("core.views.TuaUser")
    @patch("core.views.ViewAllvisitors")
    @patch("core.views.Visitortocustomer")
    @patch("core.views.Tblsanadrad")
    @patch("core.views.Tblcustomer")
    def test_customers_view_assigns_statuses_and_visitor_names(
        self,
        mock_customer,
        mock_sanadrad,
        mock_v2c,
        mock_visitors,
        mock_user,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        mock_sanadrad.objects.using.return_value.values.return_value.annotate.return_value = [
            {
                "gsubdetailid": "sub-debtor",
                "total_debit": Decimal("500000"),
                "total_credit": Decimal("100000"),
            },
            {
                "gsubdetailid": "sub-creditor",
                "total_debit": Decimal("100000"),
                "total_credit": Decimal("350000"),
            },
            {
                "gsubdetailid": "sub-settled",
                "total_debit": Decimal("200000"),
                "total_credit": Decimal("200000"),
            },
        ]
        mock_v2c.objects.using.return_value.filter.return_value.values.return_value = [
            {"gcustomerid": "cust-guid-1", "gvisitorid": "vis-guid-1"},
            {"gcustomerid": "CUST-GUID-2", "gvisitorid": "VIS-GUID-2"},
        ]
        mock_visitors.objects.using.return_value.values.return_value = [
            {
                "gvisitorid": "VIS-GUID-1",
                "vizitorname": "رضا محمدی",
                "personname": "",
            },
            {
                "gvisitorid": "vis-guid-2",
                "vizitorname": "",
                "personname": "سارا احمدی",
            },
        ]
        mock_customer.objects.using.return_value.all.return_value.order_by.return_value = [
            SimpleNamespace(
                gcustomerid="CUST-GUID-1",
                custname="مشتری بدهکار",
                gsubdetailid="SUB-DEBTOR",
                mobile="09120000001",
                phone="",
            ),
            SimpleNamespace(
                gcustomerid="cust-guid-2",
                custname="مشتری بستانکار",
                gsubdetailid="SUB-CREDITOR",
                mobile="09120000002",
                phone="",
            ),
            SimpleNamespace(
                gcustomerid="CUST-GUID-3",
                custname="مشتری تسویه",
                gsubdetailid="SUB-SETTLED",
                mobile="09120000003",
                phone="",
            ),
        ]

        url = reverse("core:customers")
        request = _attach_authenticated_session(self.factory.get(url))
        request.resolver_match = SimpleNamespace(url_name="customers")
        response = CustomersView.as_view()(request)
        response.render()

        self.assertEqual(response.status_code, 200)
        statuses = response.context_data["statuses"]
        self.assertEqual(
            [s["name"] for s in statuses],
            ["بدهکار", "بستانکار", "تسویه"],
        )
        customers = response.context_data["customers"]
        self.assertEqual(
            [
                (
                    c.custname,
                    c.status_code,
                    c.status_name,
                    c.visitor_code,
                    c.visitor_name,
                )
                for c in customers
            ],
            [
                (
                    "مشتری بدهکار",
                    "debtor",
                    "بدهکار",
                    "vis-guid-1",
                    "رضا محمدی",
                ),
                (
                    "مشتری بستانکار",
                    "creditor",
                    "بستانکار",
                    "vis-guid-2",
                    "سارا احمدی",
                ),
                (
                    "مشتری تسویه",
                    "settled",
                    "تسویه",
                    "none",
                    "بدون ویزیتور",
                ),
            ],
        )
        visitors = response.context_data["visitors"]
        self.assertEqual(
            visitors,
            [
                {"code": "vis-guid-1", "name": "رضا محمدی"},
                {"code": "vis-guid-2", "name": "سارا احمدی"},
            ],
        )
        self.assertEqual(response.context_data["current_visitor"], "all")
        self.assertEqual(response.context_data["visible_customers_count"], 3)

        html = response.content.decode("utf-8")
        self.assertIn("رضا محمدی", html)
        self.assertIn("سارا احمدی", html)
        self.assertIn("بدون ویزیتور", html)
        self.assertNotIn("نامشخص", html)
        self.assertIn('id="customerVisitorFilter"', html)
        self.assertIn('value="none"', html)
        self.assertIn('value="vis-guid-1"', html)
        self.assertIn('value="vis-guid-2"', html)
        self.assertIn('data-visitor="vis-guid-1"', html)
        self.assertIn('data-visitor="vis-guid-2"', html)
        self.assertIn('data-visitor="none"', html)
        self.assertIn('data-status-filter="all"', html)
        self.assertIn('data-status-filter="debtor"', html)
        self.assertIn('data-status-filter="creditor"', html)
        self.assertIn('data-status-filter="settled"', html)
        self.assertIn('data-status="debtor"', html)
        self.assertIn('data-status="creditor"', html)
        self.assertIn('data-status="settled"', html)

        # Verify initial ?status=creditor hides non-creditors on server render
        def _build_customers(*_args, **_kwargs):
            return [
                SimpleNamespace(
                    gcustomerid="CUST-GUID-1",
                    custname="مشتری بدهکار",
                    gsubdetailid="SUB-DEBTOR",
                    mobile="09120000001",
                    phone="",
                ),
                SimpleNamespace(
                    gcustomerid="CUST-GUID-2",
                    custname="مشتری بستانکار",
                    gsubdetailid="SUB-CREDITOR",
                    mobile="09120000002",
                    phone="",
                ),
                SimpleNamespace(
                    gcustomerid="CUST-GUID-3",
                    custname="مشتری تسویه",
                    gsubdetailid="SUB-SETTLED",
                    mobile="09120000003",
                    phone="",
                ),
            ]

        mock_customer.objects.using.return_value.all.return_value.order_by.side_effect = (
            _build_customers
        )
        filtered_req = _attach_authenticated_session(
            self.factory.get(f"{url}?status=creditor")
        )
        filtered_req.resolver_match = SimpleNamespace(url_name="customers")
        filtered_resp = CustomersView.as_view()(filtered_req)
        filtered_resp.render()
        self.assertEqual(
            filtered_resp.context_data["current_status"], "creditor"
        )
        self.assertEqual(
            filtered_resp.context_data["visible_customers_count"], 1
        )

        # Verify ?visitor=vis-guid-1 filters to only that visitor's customers
        vis_req = _attach_authenticated_session(
            self.factory.get(f"{url}?visitor=VIS-GUID-1")
        )
        vis_req.resolver_match = SimpleNamespace(url_name="customers")
        vis_resp = CustomersView.as_view()(vis_req)
        vis_resp.render()
        self.assertEqual(
            vis_resp.context_data["current_visitor"], "vis-guid-1"
        )
        self.assertEqual(
            vis_resp.context_data["visible_customers_count"], 1
        )
        self.assertEqual(
            [
                c.custname
                for c in vis_resp.context_data["customers"]
                if c.is_initially_visible
            ],
            ["مشتری بدهکار"],
        )

        # Verify ?visitor=none filters to unassigned (بدون ویزیتور) customers
        none_req = _attach_authenticated_session(
            self.factory.get(f"{url}?visitor=none")
        )
        none_req.resolver_match = SimpleNamespace(url_name="customers")
        none_resp = CustomersView.as_view()(none_req)
        none_resp.render()
        self.assertEqual(none_resp.context_data["current_visitor"], "none")
        self.assertEqual(
            [
                c.custname
                for c in none_resp.context_data["customers"]
                if c.is_initially_visible
            ],
            ["مشتری تسویه"],
        )
