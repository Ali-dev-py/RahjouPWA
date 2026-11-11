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
    CustomerDetailView,
    CustomerEditView,
    CustomersView,
    DashboardView,
    FactorDetailView,
    FactorListView,
    FactorPDFView,
    PreFactorDetailView,
    PreFactorListView,
    PreFactorPDFView,
    SaleRequestCreateView,
    SaleRequestDeleteView,
    SaleRequestDetailView,
    SaleRequestEditView,
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
            reverse("core:sale_request_edit", kwargs={"pk": "SR-GUID-1"}),
            "/sale-requests/SR-GUID-1/edit/",
        )
        self.assertEqual(
            reverse("core:sale_request_delete", kwargs={"pk": "SR-GUID-1"}),
            "/sale-requests/SR-GUID-1/delete/",
        )
        self.assertEqual(
            reverse("core:sale_request_create"),
            "/sale-requests/new/",
        )
        self.assertEqual(
            reverse("core:customer_edit", kwargs={"pk": "CUST-GUID-1"}),
            "/customers/CUST-GUID-1/edit/",
        )
        self.assertEqual(
            reverse("core:customer_detail", kwargs={"pk": "CUST-GUID-1"}),
            "/customers/CUST-GUID-1/",
        )
        self.assertEqual(reverse("core:pre_factor_list"), "/pre-factors/")
        self.assertEqual(
            reverse("core:pre_factor_detail"),
            "/pre-factors/detail/",
        )
        self.assertEqual(
            reverse("core:pre_factor_detail", kwargs={"pk": "PF-GUID-1"}),
            "/pre-factors/detail/PF-GUID-1/",
        )
        self.assertEqual(
            reverse("core:pre_factor_pdf", kwargs={"pk": "PF-GUID-1"}),
            "/pre-factors/PF-GUID-1/pdf/",
        )
        self.assertEqual(reverse("core:factor_list"), "/factors/")
        self.assertEqual(reverse("core:factor_detail"), "/factors/detail/")
        self.assertEqual(
            reverse("core:factor_detail", kwargs={"pk": "FAC-GUID-1"}),
            "/factors/detail/FAC-GUID-1/",
        )
        self.assertEqual(
            reverse("core:factor_pdf", kwargs={"pk": "FAC-GUID-1"}),
            "/factors/FAC-GUID-1/pdf/",
        )

    def test_pre_factor_and_factor_have_no_create_routes(self) -> None:
        for absent_create_name in (
            "core:pre_factor_create",
            "core:factor_create",
        ):
            with self.subTest(route=absent_create_name):
                with self.assertRaises(NoReverseMatch):
                    reverse(absent_create_name)

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
            reverse("core:sale_request_edit", kwargs={"pk": "SR-1"}),
            reverse("core:sale_request_delete", kwargs={"pk": "SR-1"}),
            reverse("core:sale_request_pdf", kwargs={"pk": "SR-1"}),
            reverse("core:sale_request_create"),
            reverse("core:pre_factor_list"),
            reverse("core:pre_factor_detail"),
            reverse("core:pre_factor_detail", kwargs={"pk": "PF-1"}),
            reverse("core:pre_factor_pdf", kwargs={"pk": "PF-1"}),
            reverse("core:factor_list"),
            reverse("core:factor_detail"),
            reverse("core:factor_detail", kwargs={"pk": "FAC-1"}),
            reverse("core:factor_pdf", kwargs={"pk": "FAC-1"}),
            reverse("core:customer_detail", kwargs={"pk": "CUST-1"}),
            reverse("core:customer_edit", kwargs={"pk": "CUST-1"}),
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
    @patch("core.views.ViewAllvisitors")
    @patch("core.views.Salerequesttovisitor")
    @patch("core.views.Salerequeststatus")
    @patch("core.views.Salerequestmaster")
    @patch("core.views.Tblcustomer")
    def test_sale_request_list_view_and_template(
        self,
        mock_customer,
        mock_master,
        mock_status,
        mock_srv,
        mock_visitors,
        mock_user,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        mock_visitors.objects.using.return_value.values.return_value = []
        mock_srv.objects.using.return_value.filter.return_value.values.return_value = []
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
    @patch("core.views.ViewAllvisitors")
    @patch("core.views.Salerequesttovisitor")
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
        mock_srv,
        mock_visitors,
        mock_user,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        mock_visitors.objects.using.return_value.values.return_value = [
            {
                "gvisitorid": "VIS-300",
                "visitorid": 300,
                "gsubdetailid": None,
                "vizitorname": "نیما علوی",
                "personname": "",
            }
        ]
        mock_srv.objects.using.return_value.filter.return_value.values.return_value = [
            {
                "gsalerequestid": "SR-GUID-300",
                "salerequestid": None,
                "gvisitorid": "VIS-300",
                "visitorid": 300,
            }
        ]

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
        self.assertEqual(response.context_data["visitor_name"], "نیما علوی")

        html = response.content.decode("utf-8")
        self.assertIn("نیما علوی", html)
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
        self.assertIn('id="customerOrderSelect"', html)
        self.assertIn('value="debt_desc"', html)
        self.assertIn('value="debt_asc"', html)
        self.assertIn('data-hesab="400000"', html)
        self.assertIn('data-hesab="-250000"', html)
        self.assertIn('data-hesab="0"', html)
        self.assertEqual(response.context_data["current_order"], "name")

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

        # Verify ?order=debt_desc sorts customers by highest debt first (+400000 -> 0 -> -250000)
        debt_desc_req = _attach_authenticated_session(
            self.factory.get(f"{url}?order=debt_desc")
        )
        debt_desc_req.resolver_match = SimpleNamespace(url_name="customers")
        debt_desc_resp = CustomersView.as_view()(debt_desc_req)
        debt_desc_resp.render()
        self.assertEqual(
            debt_desc_resp.context_data["current_order"], "debt_desc"
        )
        self.assertEqual(
            [c.custname for c in debt_desc_resp.context_data["customers"]],
            ["مشتری بدهکار", "مشتری تسویه", "مشتری بستانکار"],
        )

        # Verify ?order=debt_asc sorts customers by lowest debt / highest credit first (-250000 -> 0 -> +400000)
        debt_asc_req = _attach_authenticated_session(
            self.factory.get(f"{url}?order=debt_asc")
        )
        debt_asc_req.resolver_match = SimpleNamespace(url_name="customers")
        debt_asc_resp = CustomersView.as_view()(debt_asc_req)
        debt_asc_resp.render()
        self.assertEqual(
            debt_asc_resp.context_data["current_order"], "debt_asc"
        )
        self.assertEqual(
            [c.custname for c in debt_asc_resp.context_data["customers"]],
            ["مشتری بستانکار", "مشتری تسویه", "مشتری بدهکار"],
        )
        self.assertIn(
            reverse("core:customer_detail", kwargs={"pk": "CUST-GUID-1"}),
            html,
        )
        self.assertIn(
            reverse("core:customer_edit", kwargs={"pk": "CUST-GUID-1"}),
            html,
        )

    @patch("core.views.TuaUser")
    @patch("core.views.Customer2Group")
    @patch("core.views.Customergroup")
    @patch("core.views.Tblcustomer")
    def test_customer_edit_get_prefills_form_and_404_when_missing(
        self,
        mock_customer,
        mock_group,
        mock_c2g,
        mock_user,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        mock_customer.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            customerid=42,
            gcustomerid="CUST-GUID-42",
            custno="142",
            custname="فروشگاه امید",
            phone="",
            mobile="09123456789",
            address="تهران، خیابان ولیعصر",
        )
        mock_group.objects.using.return_value.all.return_value.order_by.return_value = [
            SimpleNamespace(
                customergroupid=1,
                gcustomergroupid="GRP-GUID-1",
                groupname="عمده‌فروش",
                gcompanyid="COMP-1",
            ),
            SimpleNamespace(
                customergroupid=2,
                gcustomergroupid="GRP-GUID-2",
                groupname="خرده‌فروش",
                gcompanyid="COMP-1",
            ),
        ]
        # Case-insensitive GUID match on group link
        mock_c2g.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            customergroupid=2,
            gcustomergroupid="grp-guid-2",
        )

        url = reverse("core:customer_edit", kwargs={"pk": "CUST-GUID-42"})
        request = _attach_authenticated_session(self.factory.get(url))
        request.resolver_match = SimpleNamespace(url_name="customer_edit")
        response = CustomerEditView.as_view()(request, pk="CUST-GUID-42")

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("ویرایش اطلاعات مشتری", html)
        self.assertIn('value="فروشگاه امید"', html)
        self.assertIn('value="09123456789"', html)
        self.assertIn("تهران، خیابان ولیعصر", html)
        self.assertRegex(
            html,
            r'<option value="GRP-GUID-2"\s+selected>',
        )

        # Missing customer raises Http404
        mock_customer.objects.using.return_value.filter.return_value.first.return_value = (
            None
        )
        missing_req = _attach_authenticated_session(self.factory.get(url))
        with self.assertRaises(Http404):
            CustomerEditView.as_view()(missing_req, pk="MISSING-GUID")

    @patch("core.views.transaction.atomic")
    @patch("core.views.TuaUser")
    @patch("core.views.Customer2Group")
    @patch("core.views.Customergroup")
    @patch("core.views.Tblcustomer")
    def test_customer_edit_post_validates_and_updates_customer_and_group(
        self,
        mock_customer,
        mock_group,
        mock_c2g,
        mock_user,
        mock_atomic,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        mock_atomic.return_value.__enter__.return_value = None
        mock_atomic.return_value.__exit__.return_value = False

        customer_obj = MagicMock(
            customerid=42,
            gcustomerid="CUST-GUID-42",
            custno="142",
            custname="فروشگاه قدیم",
            customername="فروشگاه قدیم",
            phone="02100000000",
            mobile="09120000000",
            address="نشانی قدیم",
        )
        mock_customer.objects.using.return_value.filter.return_value.first.return_value = (
            customer_obj
        )
        groups = [
            SimpleNamespace(
                customergroupid=1,
                gcustomergroupid="GRP-GUID-1",
                groupname="عمده‌فروش",
                gcompanyid="COMP-1",
            ),
            SimpleNamespace(
                customergroupid=2,
                gcustomergroupid="GRP-GUID-2",
                groupname="خرده‌فروش",
                gcompanyid="COMP-1",
            ),
        ]
        mock_group.objects.using.return_value.all.return_value.order_by.return_value = (
            groups
        )

        url = reverse("core:customer_edit", kwargs={"pk": "CUST-GUID-42"})

        # 1. Validation error when custname is empty
        bad_req = _attach_authenticated_session(
            self.factory.post(
                url,
                {
                    "custname": "   ",
                    "customer_group": "GRP-GUID-1",
                    "phone": "09121112233",
                    "address": "نشانی جدید",
                },
            )
        )
        bad_req.resolver_match = SimpleNamespace(url_name="customer_edit")
        bad_resp = CustomerEditView.as_view()(bad_req, pk="CUST-GUID-42")
        self.assertEqual(bad_resp.status_code, 200)
        self.assertIn("نام مشتری الزامی است.", bad_resp.content.decode("utf-8"))
        customer_obj.save.assert_not_called()

        # 2. Valid POST updates customer + existing Customer2Group and redirects
        mock_group.objects.using.return_value.filter.return_value.first.return_value = (
            groups[0]
        )
        c2g_obj = MagicMock(
            customer2groupid=10,
            customergroupid=2,
            customerid=42,
            gcustomerid="CUST-GUID-42",
            gcustomergroupid="GRP-GUID-2",
            gcompanyid="COMP-1",
        )
        mock_c2g.objects.using.return_value.filter.return_value.first.return_value = (
            c2g_obj
        )

        good_req = _attach_authenticated_session(
            self.factory.post(
                url,
                {
                    "custname": "فروشگاه امید نوین",
                    "customer_group": "GRP-GUID-1",
                    "phone": "09129998877",
                    "address": "تهران، میدان ونک",
                },
            )
        )
        good_req.resolver_match = SimpleNamespace(url_name="customer_edit")
        good_resp = CustomerEditView.as_view()(good_req, pk="CUST-GUID-42")

        self.assertEqual(good_resp.status_code, 302)
        self.assertEqual(good_resp["Location"], reverse("core:customers"))
        self.assertEqual(customer_obj.custname, "فروشگاه امید نوین")
        self.assertEqual(customer_obj.customername, "فروشگاه امید نوین")
        self.assertEqual(customer_obj.phone, "09129998877")
        self.assertEqual(customer_obj.mobile, "09129998877")
        self.assertEqual(customer_obj.address, "تهران، میدان ونک")
        self.assertEqual(customer_obj.lastupdatedby, "علی")
        customer_obj.save.assert_called_once()
        self.assertEqual(c2g_obj.customergroupid, 1)
        self.assertEqual(c2g_obj.gcustomergroupid, "GRP-GUID-1")
        c2g_obj.save.assert_called_once()

    @patch("core.views.TuaUser")
    @patch("core.views.ViewAllvisitors")
    @patch("core.views.Prefactortovisitor")
    @patch("core.views.Prefactordetail")
    @patch("core.views.Tblcustomer")
    @patch("core.views.Prefactormaster")
    @patch("core.views.Prefactordetailstatus")
    def test_pre_factor_list_view_and_bottom_nav(
        self,
        mock_pf_status,
        mock_pf_master,
        mock_customer,
        mock_pf_detail,
        mock_pf_visitor,
        mock_visitors,
        mock_user,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        mock_pf_status.objects.using.return_value.all.return_value.order_by.return_value = [
            SimpleNamespace(
                prefactordetailstatuscode=1,
                prefactordetailstatusname="ثبت اولیه",
            ),
            SimpleNamespace(
                prefactordetailstatuscode=2,
                prefactordetailstatusname="تایید شده",
            ),
        ]
        mock_pf_master.objects.using.return_value.filter.return_value.order_by.return_value = [
            SimpleNamespace(
                prefactormasterid=100,
                gprefactormasterid="PF-GUID-100",
                prefactorno="000501",
                prefactordate="1405/02/01",
                createddate="1405/02/01",
                gcustomerid="CUST-GUID-1",
                requestman="",
                prefactorstatuscode=None,
            )
        ]
        mock_pf_detail.objects.using.return_value.filter.return_value.values.return_value.annotate.return_value = [
            {
                "gprefactormasterid": "pf-guid-100",
                "line_net": Decimal("1850000"),
                "detail_status": 2,
            }
        ]
        mock_visitors.objects.using.return_value.values.return_value = [
            {
                "gvisitorid": "VIS-GUID-1",
                "visitorid": 10,
                "gsubdetailid": None,
                "vizitorname": "رضا بازاریاب",
                "personname": "",
            }
        ]
        mock_pf_visitor.objects.using.return_value.filter.return_value.values.return_value = [
            {
                "gprefactorid": "pf-guid-100",
                "prefactorid": 100,
                "gvisitorid": "vis-guid-1",
                "visitorid": 10,
            }
        ]
        mock_customer.objects.using.return_value.filter.return_value = [
            SimpleNamespace(gcustomerid="cust-guid-1", custname="شرکت سپهر")
        ]

        request = _attach_authenticated_session(
            self.factory.get(reverse("core:pre_factor_list"))
        )
        request.resolver_match = SimpleNamespace(url_name="pre_factor_list")
        response = PreFactorListView.as_view()(request)
        response.render()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context_data["pre_factors"]), 1)
        pf_item = response.context_data["pre_factors"][0]
        self.assertEqual(pf_item["customer_name"], "شرکت سپهر")
        self.assertEqual(pf_item["visitor_name"], "رضا بازاریاب")
        self.assertEqual(pf_item["total_amount"], 1850000)
        self.assertEqual(pf_item["status_name"], "تایید شده")
        html = response.content.decode("utf-8")
        self.assertIn(
            reverse("core:pre_factor_detail", kwargs={"pk": "PF-GUID-100"}),
            html,
        )
        self.assertIn("رضا بازاریاب", html)
        self.assertIn("۱,۸۵۰,۰۰۰", html)
        self.assertIn("ثبت اولیه", html)
        self.assertIn("تایید شده", html)
        self.assertNotIn(">visibility<", html)
        # Verify bottom navbar contains all 5 navigation links
        for nav_route in (
            "core:dashboard",
            "core:sale_request_list",
            "core:pre_factor_list",
            "core:factor_list",
            "core:customers",
        ):
            self.assertIn(reverse(nav_route), html)

    @patch("core.views.TuaUser")
    @patch("core.views.ViewAllvisitors")
    @patch("core.views.Prefactortovisitor")
    @patch("core.views.Tblkala")
    @patch("core.views.Prefactordetail")
    @patch("core.views.Tblcustomer")
    @patch("core.views.Prefactordetailstatus")
    @patch("core.views.Prefactormaster")
    def test_pre_factor_detail_and_pdf_views(
        self,
        mock_pf_master,
        mock_pf_status,
        mock_customer,
        mock_pf_detail,
        mock_kala,
        mock_pf_visitor,
        mock_visitors,
        mock_user,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        master_obj = SimpleNamespace(
            prefactormasterid=200,
            gprefactormasterid="PF-GUID-200",
            prefactorno="000502",
            prefactordate="1405/02/05",
            createddate="1405/02/05",
            createdtime="10:30:00",
            gcustomerid="CUST-GUID-2",
            requestman="",
            prefactorstatuscode=None,
        )
        mock_pf_master.objects.using.return_value.filter.return_value.first.return_value = (
            master_obj
        )
        mock_pf_status.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            prefactordetailstatuscode=2, prefactordetailstatusname="تایید شده"
        )
        mock_visitors.objects.using.return_value.values.return_value = [
            {
                "gvisitorid": "VIS-GUID-2",
                "visitorid": 12,
                "gsubdetailid": None,
                "vizitorname": "سارا حسینی",
                "personname": "",
            }
        ]
        mock_pf_visitor.objects.using.return_value.filter.return_value.values.return_value = [
            {
                "gprefactorid": "PF-GUID-200",
                "prefactorid": 200,
                "gvisitorid": "VIS-GUID-2",
                "visitorid": 12,
            }
        ]
        mock_customer.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            custname="فروشگاه ستاره",
            economno="123456",
            nationalid="",
            mobile="09121234567",
            phone="",
            address="تهران",
        )
        mock_pf_detail.objects.using.return_value.filter.return_value.order_by.return_value = [
            SimpleNamespace(
                gkalaid="KALA-1",
                quantity=Decimal("3"),
                unitprice=Decimal("200000"),
                discount=Decimal("50000"),
                prefactordetailstatuscode=2,
                descript="",
            )
        ]
        mock_kala.objects.using.return_value.filter.return_value = [
            SimpleNamespace(
                gkalaid="kala-1",
                kalaname="کالای تستی",
                kalano="K-01",
                vahed1="بسته",
            )
        ]

        detail_url = reverse(
            "core:pre_factor_detail", kwargs={"pk": "PF-GUID-200"}
        )
        detail_req = _attach_authenticated_session(
            self.factory.get(detail_url)
        )
        detail_req.resolver_match = SimpleNamespace(
            url_name="pre_factor_detail"
        )
        detail_resp = PreFactorDetailView.as_view()(
            detail_req, pk="PF-GUID-200"
        )
        detail_resp.render()

        self.assertEqual(detail_resp.status_code, 200)
        self.assertTrue(detail_resp.context_data["pre_factor_found"])
        self.assertEqual(detail_resp.context_data["status_name"], "تایید شده")
        self.assertEqual(detail_resp.context_data["visitor_name"], "سارا حسینی")
        self.assertEqual(detail_resp.context_data["subtotal"], 600000)
        self.assertEqual(detail_resp.context_data["total_discount"], 50000)
        self.assertEqual(detail_resp.context_data["total_payable"], 550000)
        detail_html = detail_resp.content.decode("utf-8")
        self.assertIn("سارا حسینی", detail_html)
        self.assertIn("تایید شده", detail_html)
        self.assertIn(
            reverse("core:pre_factor_pdf", kwargs={"pk": "PF-GUID-200"}),
            detail_html,
        )

        # PDF view
        pdf_url = reverse("core:pre_factor_pdf", kwargs={"pk": "PF-GUID-200"})
        pdf_req = _attach_authenticated_session(self.factory.get(pdf_url))
        pdf_resp = PreFactorPDFView.as_view()(pdf_req, pk="PF-GUID-200")
        self.assertEqual(pdf_resp.status_code, 200)
        self.assertIn("پیش‌فاکتور فروش", pdf_resp.content.decode("utf-8"))

        # Missing PreFactor raises Http404 on PDF
        mock_pf_master.objects.using.return_value.filter.return_value.first.return_value = (
            None
        )
        with self.assertRaises(Http404):
            PreFactorPDFView.as_view()(pdf_req, pk="MISSING-PF")

    @patch("core.views.TuaUser")
    @patch("core.views.ViewAllvisitors")
    @patch("core.views.Salefactortovisitor")
    @patch("core.views.Salefactordetail")
    @patch("core.views.Tblcustomer")
    @patch("core.views.Salefactormaster")
    @patch("core.views.Salefactorstatus")
    def test_factor_list_view_and_bottom_nav(
        self,
        mock_sf_status,
        mock_sf_master,
        mock_customer,
        mock_sf_detail,
        mock_sf_visitor,
        mock_visitors,
        mock_user,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        mock_sf_status.objects.using.return_value.all.return_value.order_by.return_value = [
            SimpleNamespace(
                salefactorstatuscode=1, salefactorstatusname="قطعی شده"
            )
        ]
        mock_sf_master.objects.using.return_value.all.return_value.order_by.return_value = [
            SimpleNamespace(
                salefactormasterid=901,
                gsalefactormasterid="FAC-GUID-100",
                salefactorno="000901",
                salefactordate="1405/02/10",
                createddate="1405/02/10",
                gcustomerid="CUST-GUID-9",
                gvisitorid="VIS-GUID-9",
                discount=Decimal("100000"),
                requestman="",
                salefactorstatuscode=1,
            )
        ]
        mock_sf_detail.objects.using.return_value.filter.return_value.values.return_value.annotate.return_value = [
            {
                "gsalefactormasterid": "fac-guid-100",
                "line_net": Decimal("2500000"),
            }
        ]
        mock_visitors.objects.using.return_value.values.return_value = [
            {
                "gvisitorid": "vis-guid-9",
                "visitorid": 19,
                "gsubdetailid": None,
                "vizitorname": "مهدی کریمی",
                "personname": "",
            }
        ]
        mock_sf_visitor.objects.using.return_value.filter.return_value.values.return_value = []
        mock_customer.objects.using.return_value.filter.return_value = [
            SimpleNamespace(gcustomerid="cust-guid-9", custname="بازرگانی نوین")
        ]

        request = _attach_authenticated_session(
            self.factory.get(reverse("core:factor_list"))
        )
        request.resolver_match = SimpleNamespace(url_name="factor_list")
        response = FactorListView.as_view()(request)
        response.render()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context_data["factors"]), 1)
        fac_item = response.context_data["factors"][0]
        self.assertEqual(fac_item["customer_name"], "بازرگانی نوین")
        self.assertEqual(fac_item["visitor_name"], "مهدی کریمی")
        self.assertEqual(fac_item["total_amount"], 2400000)
        html = response.content.decode("utf-8")
        self.assertIn(
            reverse("core:factor_detail", kwargs={"pk": "FAC-GUID-100"}),
            html,
        )
        self.assertIn("مهدی کریمی", html)
        self.assertIn("۲,۴۰۰,۰۰۰", html)
        self.assertNotIn(">visibility<", html)

    @patch("core.views.TuaUser")
    @patch("core.views.ViewAllvisitors")
    @patch("core.views.Salefactortovisitor")
    @patch("core.views.Tblkala")
    @patch("core.views.Salefactordetail")
    @patch("core.views.Tblcustomer")
    @patch("core.views.Salefactorstatus")
    @patch("core.views.Salefactormaster")
    def test_factor_detail_and_pdf_views(
        self,
        mock_sf_master,
        mock_sf_status,
        mock_customer,
        mock_sf_detail,
        mock_kala,
        mock_sf_visitor,
        mock_visitors,
        mock_user,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        mock_visitors.objects.using.return_value.values.return_value = [
            {
                "gvisitorid": "VIS-200",
                "visitorid": 20,
                "gsubdetailid": None,
                "vizitorname": "حامد رضایی",
                "personname": "",
            }
        ]
        mock_sf_visitor.objects.using.return_value.filter.return_value.values.return_value = [
            {
                "gsalefactorid": "FAC-GUID-200",
                "salefactorid": None,
                "gvisitorid": "VIS-200",
                "visitorid": 20,
            }
        ]
        master_obj = SimpleNamespace(
            gsalefactormasterid="FAC-GUID-200",
            salefactorno="000902",
            salefactordate="1405/02/12",
            salefactortime="14:15",
            createddate="1405/02/12",
            gcustomerid="CUST-GUID-9",
            requestman="",
            salefactorstatuscode=1,
            discount=Decimal("25000"),
        )
        mock_sf_master.objects.using.return_value.filter.return_value.first.return_value = (
            master_obj
        )
        mock_sf_status.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            salefactorstatuscode=1, salefactorstatusname="قطعی شده"
        )
        mock_customer.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            custname="بازرگانی نوین",
            economno="",
            nationalid="0012345678",
            mobile="09120009988",
            phone="",
            address="اصفهان",
        )
        mock_sf_detail.objects.using.return_value.filter.return_value.order_by.return_value = [
            SimpleNamespace(
                gkalaid="KALA-9",
                quantity=Decimal("2"),
                unitprice=Decimal("500000"),
                discount=Decimal("50000"),
                descript="",
            )
        ]
        mock_kala.objects.using.return_value.filter.return_value = [
            SimpleNamespace(
                gkalaid="kala-9",
                kalaname="محصول ویژه",
                kalano="K-09",
                vahed1="عدد",
            )
        ]

        detail_url = reverse(
            "core:factor_detail", kwargs={"pk": "FAC-GUID-200"}
        )
        detail_req = _attach_authenticated_session(
            self.factory.get(detail_url)
        )
        detail_req.resolver_match = SimpleNamespace(url_name="factor_detail")
        detail_resp = FactorDetailView.as_view()(detail_req, pk="FAC-GUID-200")
        detail_resp.render()

        self.assertEqual(detail_resp.status_code, 200)
        self.assertTrue(detail_resp.context_data["factor_found"])
        self.assertEqual(detail_resp.context_data["visitor_name"], "حامد رضایی")
        self.assertEqual(detail_resp.context_data["subtotal"], 1000000)
        # 50,000 line discount + 25,000 master discount = 75,000
        self.assertEqual(detail_resp.context_data["total_discount"], 75000)
        self.assertEqual(detail_resp.context_data["total_payable"], 925000)
        detail_html = detail_resp.content.decode("utf-8")
        self.assertIn("حامد رضایی", detail_html)
        self.assertIn(
            reverse("core:factor_pdf", kwargs={"pk": "FAC-GUID-200"}),
            detail_html,
        )

        # PDF view
        pdf_url = reverse("core:factor_pdf", kwargs={"pk": "FAC-GUID-200"})
        pdf_req = _attach_authenticated_session(self.factory.get(pdf_url))
        pdf_resp = FactorPDFView.as_view()(pdf_req, pk="FAC-GUID-200")
        self.assertEqual(pdf_resp.status_code, 200)
        self.assertIn("فاکتور فروش", pdf_resp.content.decode("utf-8"))

        # Missing Factor raises Http404 on PDF
        mock_sf_master.objects.using.return_value.filter.return_value.first.return_value = (
            None
        )
        with self.assertRaises(Http404):
            FactorPDFView.as_view()(pdf_req, pk="MISSING-FAC")

    @patch("core.views.TuaUser")
    @patch("core.views.Salefactordetail")
    @patch("core.views.Salefactorstatus")
    @patch("core.views.Salefactormaster")
    @patch("core.views.Tblsanad")
    @patch("core.views.Tblsanadrad")
    @patch("core.views.ViewAllvisitors")
    @patch("core.views.Visitortocustomer")
    @patch("core.views.Customergroup")
    @patch("core.views.Customer2Group")
    @patch("core.views.Tblcustomer")
    def test_customer_detail_orders_pays_and_factors_by_date_and_links_factor(
        self,
        mock_customer,
        mock_c2g,
        mock_group,
        mock_v2c,
        mock_visitors,
        mock_sanadrad,
        mock_sanad,
        mock_sf_master,
        mock_sf_status,
        mock_sf_detail,
        mock_user,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        mock_customer.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            customerid=77,
            gcustomerid="CUST-GUID-77",
            gsubdetailid="SUB-GUID-77",
            custno="177",
            custname="بازرگانی سپهر",
            mobile="09121112233",
            phone="",
            address="تهران، خیابان شریعتی",
        )
        mock_c2g.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            gcustomergroupid="GRP-1",
            customergroupid=1,
        )
        mock_group.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            groupname="مشتریان ویژه"
        )
        mock_v2c.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            gvisitorid="VIS-1"
        )
        mock_visitors.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            vizitorname="رضا محمدی",
            personname="",
        )

        # Balance aggregate: 1,500,000 debit - 600,000 credit = +900,000 (بدهکار)
        sanadrad_qs = MagicMock()
        mock_sanadrad.objects.using.return_value.filter.side_effect = [
            sanadrad_qs,
            [
                SimpleNamespace(
                    gsanadradid="RAD-1",
                    gsanadid_id="SANAD-1",
                    credit=Decimal("200000"),
                    description="واریز نقدی اول",
                    serialid=10,
                    createddate=None,
                ),
                SimpleNamespace(
                    gsanadradid="RAD-2",
                    gsanadid_id="SANAD-2",
                    credit=Decimal("400000"),
                    description="حواله بانکی دوم",
                    serialid=20,
                    createddate=None,
                ),
            ],
            sanadrad_qs,
            [
                SimpleNamespace(
                    gsanadradid="RAD-1",
                    gsanadid_id="SANAD-1",
                    credit=Decimal("200000"),
                    description="واریز نقدی اول",
                    serialid=10,
                    createddate=None,
                ),
                SimpleNamespace(
                    gsanadradid="RAD-2",
                    gsanadid_id="SANAD-2",
                    credit=Decimal("400000"),
                    description="حواله بانکی دوم",
                    serialid=20,
                    createddate=None,
                ),
            ],
        ]
        sanadrad_qs.aggregate.return_value = {
            "total_debit": Decimal("1500000"),
            "total_credit": Decimal("600000"),
        }

        mock_sanad.objects.using.return_value.filter.return_value = [
            SimpleNamespace(
                gsanadid="sanad-1",
                sanadno="501",
                sanaddate="1405/01/10",
                sanadtime="09:00",
                sanaddesc="",
            ),
            SimpleNamespace(
                gsanadid="sanad-2",
                sanadno="505",
                sanaddate="1405/02/20",
                sanadtime="15:30",
                sanaddesc="",
            ),
        ]

        mock_sf_master.objects.using.return_value.filter.return_value = [
            SimpleNamespace(
                gsalefactormasterid="FAC-GUID-301",
                salefactorno="301",
                salefactordate="1405/02/05",
                salefactortime="11:00",
                createddate="1405/02/05",
                salefactorstatuscode=1,
                discount=Decimal("50000"),
                salefactordesc="ارسال فوری",
            )
        ]
        mock_sf_status.objects.using.return_value.all.return_value = [
            SimpleNamespace(
                salefactorstatuscode=1, salefactorstatusname="قطعی شده"
            )
        ]
        mock_sf_detail.objects.using.return_value.filter.return_value.values.return_value.annotate.return_value = [
            {
                "gsalefactormasterid": "fac-guid-301",
                "line_net": Decimal("1550000"),
            }
        ]

        detail_url = reverse(
            "core:customer_detail", kwargs={"pk": "CUST-GUID-77"}
        )
        req = _attach_authenticated_session(self.factory.get(detail_url))
        req.resolver_match = SimpleNamespace(url_name="customer_detail")
        resp = CustomerDetailView.as_view()(req, pk="CUST-GUID-77")
        resp.render()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context_data["hesab"], 900000)
        self.assertEqual(resp.context_data["status_name"], "بدهکار")
        self.assertEqual(resp.context_data["total_pays_amount"], 600000)
        self.assertEqual(resp.context_data["total_factors_amount"], 1500000)

        # Default order is newest first: 1405/02/20 (pay) -> 1405/02/05 (factor) -> 1405/01/10 (pay)
        txs = resp.context_data["transactions"]
        self.assertEqual(
            [(t["kind"], t["date"]) for t in txs],
            [
                ("pay", "1405/02/20"),
                ("factor", "1405/02/05"),
                ("pay", "1405/01/10"),
            ],
        )

        html = resp.content.decode("utf-8")
        expected_factor_link = (
            f"{reverse('core:factor_detail', kwargs={'pk': 'FAC-GUID-301'})}"
            "?from_customer=CUST-GUID-77"
        )
        self.assertIn(expected_factor_link, html)
        self.assertIn("حواله بانکی دوم", html)

        # Verify ?order=date_asc orders oldest first
        asc_req = _attach_authenticated_session(
            self.factory.get(f"{detail_url}?order=date_asc")
        )
        asc_req.resolver_match = SimpleNamespace(url_name="customer_detail")
        asc_resp = CustomerDetailView.as_view()(asc_req, pk="CUST-GUID-77")
        self.assertEqual(
            [(t["kind"], t["date"]) for t in asc_resp.context_data["transactions"]],
            [
                ("pay", "1405/01/10"),
                ("factor", "1405/02/05"),
                ("pay", "1405/02/20"),
            ],
        )

        # Missing customer raises Http404
        mock_customer.objects.using.return_value.filter.return_value.first.return_value = (
            None
        )
        with self.assertRaises(Http404):
            CustomerDetailView.as_view()(req, pk="MISSING-CUST")

    @patch("core.views.transaction.atomic")
    @patch("core.views.TuaUser")
    @patch("core.views.Salerequestdetail")
    @patch("core.views.Salerequesttovisitor")
    @patch("core.views.Salerequeststatus")
    @patch("core.views.Salerequestmaster")
    @patch("core.views.Statementprice")
    @patch("core.views.Tblkala")
    @patch("core.views.ViewAllvisitors")
    @patch("core.views.Tblinv")
    @patch("core.views.Branches")
    @patch("core.views.Tblcustomer")
    def test_sale_request_edit_allowed_only_when_sabt_shode(
        self,
        mock_customer,
        mock_branches,
        mock_inv,
        mock_visitors,
        mock_kala,
        mock_price,
        mock_master,
        mock_status,
        mock_srv,
        mock_detail,
        mock_user,
        mock_atomic,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        master_obj = SimpleNamespace(
            salerequestmasterid=15,
            gsalerequestmasterid="SR-GUID-15",
            salerequestno="000015",
            salerequeststatuscode=1,
            gcustomerid="CUST-1",
            gbranchid="BR-1",
            ginvid="INV-1",
            visitorid=5,
            save=MagicMock(),
        )
        mock_master.objects.using.return_value.filter.return_value.first.return_value = (
            master_obj
        )

        # 1. Non-'ثبت شده' status blocks GET and POST edit
        mock_status.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            salerequeststatuscode=2, salerequeststatusname="تایید شده"
        )
        edit_url = reverse(
            "core:sale_request_edit", kwargs={"pk": "SR-GUID-15"}
        )
        blocked_get = _attach_authenticated_session(self.factory.get(edit_url))
        blocked_resp = SaleRequestEditView.as_view()(
            blocked_get, pk="SR-GUID-15"
        )
        self.assertEqual(blocked_resp.status_code, 302)
        self.assertEqual(
            blocked_resp["Location"],
            reverse("core:sale_request_detail", kwargs={"pk": "SR-GUID-15"}),
        )

        # 2. 'ثبت شده' status allows GET and pre-populates form
        mock_status.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            salerequeststatuscode=1, salerequeststatusname="ثبت شده"
        )
        mock_customer.objects.using.return_value.values.return_value.order_by.return_value = [
            {
                "gcustomerid": "CUST-1",
                "custname": "فروشگاه البرز",
                "custno": "10",
                "mobile": "09121112233",
                "phone": "",
            }
        ]
        mock_customer.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            gcustomerid="CUST-1",
            custname="فروشگاه البرز",
            custno="10",
            mobile="09121112233",
            phone="",
        )
        mock_branches.objects.using.return_value.values.return_value.order_by.return_value = [
            {"gbranchid": "BR-1", "branchname": "شعبه مرکزی", "branchcode": "1"}
        ]
        mock_inv.objects.using.return_value.values.return_value.order_by.return_value = [
            {"ginvid": "INV-1", "invname": "انبار اصلی", "invcode": "1"}
        ]
        mock_visitors.objects.using.return_value.filter.return_value.values.return_value.order_by.return_value = [
            {
                "gvisitorid": "VIS-1",
                "vizitorname": "حسن کریمی",
                "personname": "",
                "vizitorcode": "V1",
            }
        ]
        mock_srv.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            gvisitorid="vis-1"
        )
        mock_price.objects.using.return_value.filter.return_value.values.return_value.order_by.return_value = []
        mock_kala.objects.using.return_value.values.return_value.order_by.return_value = [
            {
                "gkalaid": "KALA-1",
                "kalaname": "محصول الف",
                "kalano": "K1",
                "vahed1": "عدد",
                "selprice": Decimal("300000"),
            }
        ]
        mock_detail.objects.using.return_value.filter.return_value.order_by.return_value = [
            SimpleNamespace(
                gkalaid="kala-1",
                quantity=Decimal("3"),
                unitprice=Decimal("300000"),
                descript="",
            )
        ]
        mock_kala.objects.using.return_value.filter.return_value = [
            SimpleNamespace(
                gkalaid="KALA-1",
                kalaname="محصول الف",
                kalano="K1",
                vahed1="عدد",
            )
        ]

        ok_get = _attach_authenticated_session(self.factory.get(edit_url))
        ok_get.resolver_match = SimpleNamespace(url_name="sale_request_edit")
        get_resp = SaleRequestEditView.as_view()(ok_get, pk="SR-GUID-15")
        self.assertEqual(get_resp.status_code, 200)
        html = get_resp.content.decode("utf-8")
        self.assertIn("ویرایش درخواست فروش", html)
        self.assertIn("ذخیره تغییرات درخواست", html)
        self.assertIn("فروشگاه البرز", html)

        # 3. Valid POST updates master, visitor link, and replaces details
        mock_detail.side_effect = lambda **kw: SimpleNamespace(**kw)
        mock_visitors.objects.using.return_value.filter.return_value.values.return_value.first.return_value = {
            "visitorid": 8,
            "poorsant": Decimal("2.50"),
        }
        mock_srv.objects.using.return_value.filter.return_value.update.return_value = 1

        post_req = _attach_authenticated_session(
            self.factory.post(
                edit_url,
                {
                    "customer_id": "CUST-2",
                    "branch_id": "BR-2",
                    "inv_id": "INV-2",
                    "visitor_id": "VIS-2",
                    "product_id[]": ["KALA-1", "KALA-1"],
                    "quantity[]": ["2", "3"],
                    "price[]": ["300000", "300000"],
                },
            )
        )
        post_resp = SaleRequestEditView.as_view()(post_req, pk="SR-GUID-15")
        self.assertEqual(post_resp.status_code, 302)
        self.assertEqual(
            post_resp["Location"],
            reverse("core:sale_request_detail", kwargs={"pk": "SR-GUID-15"}),
        )
        self.assertEqual(master_obj.gcustomerid, "CUST-2")
        self.assertEqual(master_obj.gbranchid, "BR-2")
        self.assertEqual(master_obj.ginvid, "INV-2")
        self.assertEqual(master_obj.visitorid, 8)
        master_obj.save.assert_called_once()
        mock_detail.objects.using.return_value.filter.return_value.delete.assert_called_once()
        created_details = (
            mock_detail.objects.using.return_value.bulk_create.call_args[0][0]
        )
        # Duplicate KALA-1 rows merged into 1 row with quantity 2 + 3 = 5
        self.assertEqual(len(created_details), 1)
        self.assertEqual(created_details[0].quantity, Decimal("5"))

    @patch("core.views.transaction.atomic")
    @patch("core.views.TuaUser")
    @patch("core.views.Salerequesttovisitor")
    @patch("core.views.Salerequestdetail")
    @patch("core.views.Salerequeststatus")
    @patch("core.views.Salerequestmaster")
    def test_sale_request_delete_allowed_only_when_sabt_shode(
        self,
        mock_master,
        mock_status,
        mock_detail,
        mock_srv,
        mock_user,
        mock_atomic,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        master_obj = MagicMock(
            salerequestmasterid=22,
            gsalerequestmasterid="SR-GUID-22",
            salerequestno="000022",
            salerequeststatuscode=2,
        )
        mock_master.objects.using.return_value.filter.return_value.first.return_value = (
            master_obj
        )

        delete_url = reverse(
            "core:sale_request_delete", kwargs={"pk": "SR-GUID-22"}
        )

        # 1. Non-'ثبت شده' status blocks deletion
        mock_status.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            salerequeststatuscode=2, salerequeststatusname="تایید شده"
        )
        blocked_post = _attach_authenticated_session(
            self.factory.post(delete_url)
        )
        blocked_resp = SaleRequestDeleteView.as_view()(
            blocked_post, pk="SR-GUID-22"
        )
        self.assertEqual(blocked_resp.status_code, 302)
        self.assertEqual(
            blocked_resp["Location"],
            reverse("core:sale_request_detail", kwargs={"pk": "SR-GUID-22"}),
        )
        master_obj.delete.assert_not_called()

        # 2. 'ثبت شده' status deletes details, visitor link, and master
        master_obj.salerequeststatuscode = 1
        mock_status.objects.using.return_value.filter.return_value.first.return_value = SimpleNamespace(
            salerequeststatuscode=1, salerequeststatusname="ثبت شده"
        )
        ok_post = _attach_authenticated_session(self.factory.post(delete_url))
        ok_resp = SaleRequestDeleteView.as_view()(ok_post, pk="SR-GUID-22")
        self.assertEqual(ok_resp.status_code, 302)
        self.assertEqual(ok_resp["Location"], reverse("core:sale_request_list"))
        mock_detail.objects.using.return_value.filter.return_value.delete.assert_called_once()
        mock_srv.objects.using.return_value.filter.return_value.delete.assert_called_once()
        master_obj.delete.assert_called_once_with(using="plus")

    @patch("core.views.TuaUser")
    @patch("core.views.ViewAllvisitors")
    @patch("core.views.Salerequesttovisitor")
    @patch("core.views.Tblcustomer")
    @patch("core.views.Salerequestmaster")
    @patch("core.views.Salerequeststatus")
    def test_sale_request_list_visitor_name_and_no_eye_icon(
        self,
        mock_sr_status,
        mock_sr_master,
        mock_customer,
        mock_srv,
        mock_visitors,
        mock_user,
    ) -> None:
        mock_user.objects.using.return_value.filter.return_value.first.return_value = (
            self.user
        )
        mock_sr_status.objects.using.return_value.all.return_value.order_by.return_value = [
            SimpleNamespace(
                salerequeststatuscode=1, salerequeststatusname="ثبت شده"
            )
        ]
        mock_sr_master.objects.using.return_value.all.return_value.order_by.return_value = [
            SimpleNamespace(
                salerequestmasterid=51,
                gsalerequestmasterid="SR-GUID-51",
                salerequestno="000051",
                salerequestdate="1405/02/20",
                createddate="1405/02/20",
                gcustomerid="CUST-GUID-51",
                requestman="",
                visitorid=None,
                salerequeststatuscode=1,
            ),
            SimpleNamespace(
                salerequestmasterid=52,
                gsalerequestmasterid="SR-GUID-52",
                salerequestno="000052",
                salerequestdate="1405/02/19",
                createddate="1405/02/19",
                gcustomerid="CUST-GUID-51",
                requestman="",
                visitorid=77,
                salerequeststatuscode=1,
            ),
        ]
        mock_customer.objects.using.return_value.filter.return_value = [
            SimpleNamespace(
                gcustomerid="cust-guid-51", custname="بازرگانی آفتاب"
            )
        ]
        mock_visitors.objects.using.return_value.values.return_value = [
            {
                "gvisitorid": "vis-guid-51",
                "visitorid": 51,
                "gsubdetailid": None,
                "vizitorname": "امیر محمدی",
                "personname": "",
            },
            {
                "gvisitorid": "vis-guid-77",
                "visitorid": 77,
                "gsubdetailid": None,
                "vizitorname": "زهرا نوری",
                "personname": "",
            },
        ]
        mock_srv.objects.using.return_value.filter.return_value.values.return_value = [
            {
                "gsalerequestid": "sr-guid-51",
                "salerequestid": 51,
                "gvisitorid": "vis-guid-51",
                "visitorid": 51,
            }
        ]

        req = _attach_authenticated_session(
            self.factory.get(reverse("core:sale_request_list"))
        )
        req.resolver_match = SimpleNamespace(url_name="sale_request_list")
        resp = SaleRequestListView.as_view()(req)
        resp.render()

        self.assertEqual(resp.status_code, 200)
        items = resp.context_data["sale_requests"]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["visitor_name"], "امیر محمدی")
        self.assertEqual(items[1]["visitor_name"], "زهرا نوری")

        html = resp.content.decode("utf-8")
        self.assertIn("امیر محمدی", html)
        self.assertIn("زهرا نوری", html)
        self.assertNotIn(">visibility<", html)

