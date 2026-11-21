from decimal import Decimal
from types import SimpleNamespace as Obj
from unittest.mock import patch

import jdatetime
from django.db import DatabaseError
from django.test import SimpleTestCase, RequestFactory
from django.urls import reverse

from .income_report import (commission, report_period, parse_date, guid_batches,
                            build_report, factor_attribution)
from .views import IncomeReportView, DashboardView


def master(key='F1', visitor='V1', discount=0, customer='C1', number=1):
    return Obj(gsalefactormasterid=key, salefactormasterid=number,
               gvisitorid=visitor, gsubdetailid5=None, discount=discount,
               gcustomerid=customer, salefactorno=str(number),
               salefactordate='1405/08/05', requestman='مشتری')


def link(visitor='V1', key='F1', integer=1, visitor_int=None):
    return Obj(gvisitorid=visitor, visitorid=visitor_int, gsalefactorid=key,
               salefactorid=integer)


class CommissionMathTests(SimpleTestCase):
    def test_requested_examples_and_zero_floor(self):
        for discount, expected in ((0, 5000000), (5000000, 3333333),
                                   (10000000, 1666667), (15000000, 0), (20000000, 0)):
            with self.subTest(discount=discount):
                self.assertEqual(commission(100000000, discount)['income'], Decimal(expected))
        self.assertTrue(commission(100, 16)['over_margin'])
        self.assertFalse(commission(100, 15)['over_margin'])

    def test_five_percent_without_discount_and_one_third_remaining_margin(self):
        undiscounted = commission(100000000, 0)
        self.assertEqual(undiscounted['income'], 5000000)
        self.assertEqual(undiscounted['effective_rate'], 5)
        self.assertEqual(commission(100000000, '0.01')['income'], 5000000)
        self.assertEqual(commission(100000000, 5000000)['income'], 3333333)
        self.assertEqual(commission(100000000, 10000000)['income'], 1666667)

    def test_fractional_discount_rate_is_not_rounded_before_calculation(self):
        gross, discount = Decimal('123456789'), Decimal('1234567.89')
        result = commission(gross, discount)
        self.assertEqual(result['discount_percent'], 1)
        expected = (gross * Decimal('0.14') / 3).quantize(Decimal('1'), rounding='ROUND_HALF_UP')
        self.assertEqual(result['income'], expected)
        self.assertEqual(commission(100, Decimal('10.5'))['income'], 2)

    def test_decimal_precision_rounding_and_invalid_amounts(self):
        self.assertEqual(commission('100.5', 0)['income'], Decimal('5'))
        self.assertEqual(commission('100.5', '5.025')['discount_percent'], Decimal('5'))
        for gross, discount in ((0, 1), (-100, 0), (100, -1)):
            self.assertEqual(commission(gross, discount)['income'], 0)
            self.assertTrue(commission(gross, discount)['invalid_amount'])

    def test_jalali_presets_and_inclusive_custom_dates(self):
        today = jdatetime.date(1405, 1, 12)
        self.assertEqual(report_period({}, today), ('month', '1405/01/01', '1405/01/12'))
        self.assertEqual(report_period({'period': 'today'}, today)[1:], ('1405/01/12', '1405/01/12'))
        self.assertEqual(report_period({'period': 'last_month'}, today)[1:], ('1404/12/01', '1404/12/29'))
        self.assertEqual(report_period({'period': 'custom', 'start': '۱۴۰۵/۸/۱', 'end': '١٤٠٥/٨/١'})[1:],
                         ('1405/08/01', '1405/08/01'))

    def test_invalid_dates_and_reversed_periods(self):
        for value in ('2026-01-01', '1405/13/01', '1405/12/30', '', '1405/01/32'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_date(value)
        with self.assertRaises(ValueError):
            report_period({'period': 'custom', 'start': '1405/08/02', 'end': '1405/08/01'})
        with self.assertRaises(ValueError):
            report_period({'period': 'wrong'})

    def test_case_insensitive_sql_batches_never_duplicate_logical_guids(self):
        chunks = list(guid_batches([f'ID-{n}' for n in range(501)]))
        seen = set()
        for chunk in chunks:
            normalized = {v.lower() for v in chunk}
            self.assertFalse(seen & normalized)
            seen.update(normalized)
            self.assertLessEqual(len(chunk), 400)
        self.assertEqual(len(seen), 501)


class FactorAttributionTests(SimpleTestCase):
    @patch('core.income_report.Salefactortovisitor')
    def test_recorded_guid_overrides_junction_and_deduplicates_links(self, model):
        model.objects.using.return_value.filter.return_value = [link('V2'), link('V2')]
        visitors = {'v1': {}, 'v2': {}}
        self.assertEqual(factor_attribution([master()], visitors, {}, {})['f1'], 'v1')
        self.assertEqual(factor_attribution([master(visitor=None)], visitors, {}, {})['f1'], 'v2')

    @patch('core.income_report.Salefactortovisitor')
    def test_integer_and_tafzil_fallbacks_and_ambiguous_links(self, model):
        model.objects.using.return_value.filter.return_value = [link(None, visitor_int=7)]
        self.assertEqual(factor_attribution([master(visitor=None)], {'v1': {}}, {7: {'v1'}}, {})['f1'], 'v1')
        model.objects.using.return_value.filter.return_value = []
        m = master(visitor=None)
        m.gsubdetailid5 = '{SUB1}'
        self.assertEqual(factor_attribution([m], {'v1': {}}, {}, {'sub1': {'v1'}})['f1'], 'v1')
        model.objects.using.return_value.filter.return_value = [link('V1'), link('V2')]
        self.assertEqual(factor_attribution([m], {'v1': {}, 'v2': {}}, {}, {})['f1'], '')
        self.assertEqual(factor_attribution([master(visitor='UNKNOWN')], {'v1': {}}, {}, {})['f1'], '')


class IncomeReportTests(SimpleTestCase):
    def setUp(self):
        self.patches = []
        for target in ('visitor_directory', 'factor_attribution', 'Salefactormaster',
                       'Salefactordetail', 'Tblcustomer'):
            patcher = patch('core.income_report.' + target)
            self.patches.append(patcher.start())
            self.addCleanup(patcher.stop)
        self.directory, self.attribution, self.masters, self.details, self.customers = self.patches
        self.directory.return_value = ({
            'v1': {'id': 'v1', 'name': 'علی کریمی'},
            'v2': {'id': 'v2', 'name': 'سارا'},
        }, {}, {})
        self.attribution.return_value = {'f1': 'v1', 'f2': 'v2', 'f3': ''}
        self.masters.objects.using.return_value.filter.return_value.order_by.return_value = [
            master(discount=2000000), master('F2', 'V2', number=2), master('F3', None, number=3)]
        self.details.objects.using.return_value.filter.return_value.values.return_value = [
            {'gsalefactormasterid': 'F1', 'quantity': 2, 'unitprice': 50000000, 'discount': 3000000},
            {'gsalefactormasterid': 'F2', 'quantity': 1, 'unitprice': 100000000, 'discount': 0},
            {'gsalefactormasterid': 'F3', 'quantity': 1, 'unitprice': 100000000, 'discount': 0},
        ]
        self.customers.objects.using.return_value.filter.return_value = [Obj(gcustomerid='C1', custname='مشتری')]
        self.admin = Obj(utitle='مدیر', uname='مدیر')

    def report(self, user=None, selected=''):
        return build_report(user or self.admin, '1405/08/01', '1405/08/30', selected)

    def test_combines_header_and_line_discount_exactly_once_and_unassigned_has_no_income(self):
        report = self.report()
        self.assertEqual(report['report_rows'][0]['discount'], 5000000)
        self.assertEqual(report['report_rows'][0]['income'], 3333333)
        self.assertEqual(report['report_total']['income'], 8333333)
        self.assertEqual(report['report_total']['gross'], 300000000)
        self.assertEqual(report['unassigned_count'], 1)
        self.assertEqual(report['report_rows'][2]['income'], 0)
        self.assertEqual(len(report['visitor_summaries']), 3)
        query = self.masters.objects.using.return_value.filter.call_args.kwargs
        self.assertEqual(query['salefactordate__gte'], '1405/08/01')
        self.assertEqual(query['salefactordate__lte'], '1405/08/30')

    def test_visitor_cannot_select_someone_else_and_matches_normalized_name(self):
        # Simulate DB-side filtering: detail query can only return authorized factors.
        all_details = self.details.objects.using.return_value.filter.return_value.values.return_value
        self.details.objects.using.return_value.filter.return_value.values.return_value = all_details[:1]
        report = self.report(Obj(utitle='ویزیتور', uname=' علي  كريمي '), 'v2')
        self.assertEqual([r['id'] for r in report['report_rows']], ['F1'])
        self.assertEqual(report['report_total']['income'], 3333333)
        self.assertEqual(report['report_visitors'], [])
        detail_ids = self.details.objects.using.return_value.filter.call_args.kwargs['gsalefactormasterid__in']
        self.assertNotIn('f2', detail_ids)

    def test_unmatched_visitor_gets_no_factors_or_global_totals(self):
        report = self.report(Obj(utitle='ویزیتور', uname='نام ناموجود'))
        self.assertEqual(report['report_rows'], [])
        self.assertEqual(report['report_total']['income'], 0)
        self.details.objects.using.assert_not_called()
        self.customers.objects.using.assert_not_called()

    def test_admin_can_select_visitor_or_unassigned(self):
        report = self.report(selected='v2')
        self.assertEqual([r['id'] for r in report['report_rows']], ['F2'])
        report = self.report(selected='unassigned')
        self.assertEqual([r['id'] for r in report['report_rows']], ['F3'])
        with self.assertRaises(ValueError):
            self.report(selected='invalid')

    def test_missing_lines_produces_zero_income_and_warning(self):
        self.details.objects.using.return_value.filter.return_value.values.return_value = []
        report = self.report()
        self.assertEqual(report['report_total']['income'], 0)
        self.assertEqual(report['warning_count'], 3)


class IncomeDashboardTests(SimpleTestCase):
    def request(self, params):
        request = RequestFactory().get(reverse('core:income_report'), params)
        request.plus_user = Obj(utitle='ویزیتور', uname='علی')
        return request

    @patch('core.income_report.build_report')
    def test_invalid_dates_do_not_query_financial_data(self, build):
        view = IncomeReportView()
        view.request = self.request({'period': 'custom', 'start': 'bad', 'end': 'bad'})
        context = view.get_context_data()
        self.assertIn('report_error', context)
        build.assert_not_called()

    @patch('core.income_report.build_report', side_effect=DatabaseError('sensitive database info'))
    def test_database_failure_is_error_not_false_zero_report(self, build):
        view = IncomeReportView()
        view.request = self.request({})
        context = view.get_context_data()
        self.assertIn('report_error', context)
        self.assertNotIn('report_total', context)
        self.assertNotIn('sensitive', context['report_error'])

    @patch('core.income_report.build_report')
    @patch.object(IncomeReportView, '_visitor_customer_ids', return_value=[])
    def test_pagination_full_totals_and_visitor_selector_hidden(self, scope, build):
        rows = [dict(id=f'F{i}', customer_id='c1', customer_name='مشتری', gross=100,
                     discount=0, net=100, discount_percent=0, effective_rate=5,
                     income=5, date='1405/08/01', number=i) for i in range(25)]
        build.return_value = dict(report_rows=rows, report_total=dict(gross=2500, discount=0, net=2500, income=125),
                                  factor_count=25, is_visitor_report=True, selected_report_visitor='',
                                  report_visitors=[], visitor_summaries=[], warning_count=0, unassigned_count=0)
        view = IncomeReportView()
        view.request = self.request({'page': '2'})
        context = view.get_context_data()
        self.assertEqual(len(context['report_page']), 5)
        self.assertEqual(context['report_total']['income'], 125)
        self.assertFalse(context['report_page'][0]['can_open'])
        from django.template.loader import render_to_string
        html = render_to_string('core/income_report.html', context)
        self.assertNotIn('id="report-visitor"', html)
        self.assertNotIn('/factors/detail/F', html)
        self.assertIn('پورسانت من', html)


class HomeOverviewTests(SimpleTestCase):
    def setUp(self):
        payments = patch('core.payment_dues.payment_schedule', return_value={'rows': [], 'reminders': [], 'remaining_total': 0})
        payments.start()
        self.addCleanup(payments.stop)
        self.view = DashboardView()
        self.view.request = RequestFactory().get(reverse('core:dashboard'), {'period': 'custom', 'visitor': 'forged'})
        self.view.request.plus_user = Obj(gucode='USER1', utitle='ویزیتور', uname='علی')

    @patch('core.income_report.build_report')
    @patch.object(DashboardView, '_load_recent_activities')
    def test_home_has_four_small_cards_and_activity_feed_not_report_form(self, activities, build):
        activities.return_value = [dict(id='SR1', sale_request_no='123', date='1405/08/01',
                                       customer_name='فروشگاه نمونه', visitor_name='علی',
                                       total_amount=1000, status_name='ثبت شده')]
        build.return_value = dict(report_total=dict(income=50, net=1000, discount=0), factor_count=1)
        context = self.view.get_context_data()
        from django.template.loader import render_to_string
        html = render_to_string('core/dashboard.html', context)
        self.assertEqual(html.count('class="card home-summary-card'), 4)
        self.assertEqual(html.count("home-summary-card--white"), 4)
        self.assertNotIn("home-summary-card--primary", html)
        self.assertNotIn("home-summary-card--accent", html)
        self.assertIn('href="/income-report/?period=month"', html)
        self.assertIn('فعالیت‌های اخیر', html)
        self.assertIn('فروشگاه نمونه', html)
        self.assertIn(reverse('core:sale_request_detail', kwargs={'pk': 'SR1'}), html)
        self.assertNotIn('id="report-period"', html)
        self.assertEqual(html.count("btn app-fab"), 1)
        self.assertIn(reverse("core:sale_request_create"), html)
        self.assertNotIn("rounded-pill mt-3", html)
        self.assertNotIn('ریز پورسانت فاکتورها', html)
        self.assertNotIn('report_page', context)
        # Home is always a compact current-month overview, not a forged filter.
        self.assertEqual(len(build.call_args.args), 3)
        self.assertEqual(build.call_args.args[1][-2:], '01')

    @patch('core.income_report.build_report', side_effect=DatabaseError('private'))
    @patch.object(DashboardView, '_load_recent_activities', return_value=[{'id': 'SR1'}])
    def test_summary_failure_does_not_hide_recent_activities(self, activities, build):
        context = self.view.get_context_data()
        self.assertIn('report_error', context)
        self.assertNotIn('report_total', context)
        self.assertEqual(context['recent_activities'], [{'id': 'SR1'}])
        self.assertNotIn('private', context['report_error'])

    @patch('core.income_report.build_report')
    @patch.object(DashboardView, '_load_recent_activities', side_effect=DatabaseError('private'))
    def test_activity_failure_does_not_hide_summary(self, activities, build):
        build.return_value = dict(report_total={'income': 50}, factor_count=1)
        context = self.view.get_context_data()
        self.assertEqual(context['report_total']['income'], 50)
        self.assertIn('activity_error', context)

    @patch('core.views.Salerequeststatus')
    @patch('core.views._resolve_sale_request_visitors', return_value={'sr1': 'علی'})
    @patch('core.views._batch_sale_request_totals', return_value=({'sr1': 1000}, {}))
    @patch.object(DashboardView, '_customers')
    @patch.object(DashboardView, '_documents')
    def test_recent_feed_uses_scoped_documents_and_current_user(self, documents, customers, totals, visitors, statuses):
        documents.return_value.filter.return_value.order_by.return_value = [Obj(
            gsalerequestmasterid='SR1', salerequestmasterid=1, gcustomerid='C1',
            salerequestno='123', salerequestdate='1405/08/01', createddate='',
            salerequeststatuscode=1, requestman='')]
        customers.return_value.filter.return_value = [Obj(gcustomerid='C1', custname='مشتری', gareageoghrafiid='{A1}')]
        statuses.objects.using.return_value.all.return_value = [Obj(salerequeststatuscode=1, salerequeststatusname='ثبت شده')]
        with patch('core.views._area_map', return_value={'a1': 'شمال'}):
            rows = self.view._load_recent_activities()
        self.assertEqual(rows[0]['area_name'], 'شمال')
        self.assertEqual(rows[0]['number'], '123')
        documents.return_value.filter.assert_called_once_with(gcreatedby='USER1')
        self.assertEqual(rows[0]['sale_request_no'], '123')
        self.assertEqual(rows[0]['customer_name'], 'مشتری')
        self.assertEqual(rows[0]['visitor_name'], 'علی')
        self.assertEqual(rows[0]['total_amount'], 1000)

    def test_report_route_is_separate_and_requires_login(self):
        self.assertEqual(reverse('core:income_report'), '/income-report/')
        response = self.client.get(reverse('core:income_report'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('core:login'), response['Location'])


class IncomeMoneyDisplayTests(SimpleTestCase):
    def test_shared_factor_amount_is_whole_rials(self):
        from django.template.loader import render_to_string
        from .templatetags.i18n_extras import persian_digits
        for value, expected in (('1234567.0000000000', '1,234,567'),
                                ('1234567.6000000000', '1,234,568'),
                                ('0.0000000000', '0'), ('-1234.6000000000', '-1,235')):
            with self.subTest(value=value):
                html = render_to_string('partials/_document_card_body.html', {
                    'document': {}, 'document_label': 'فاکتور', 'amount': Decimal(value),
                })
                self.assertIn(persian_digits(expected) + ' ریال', html)
                self.assertNotIn('.', html)

    def test_report_money_is_integer_but_percentages_keep_decimals(self):
        import re
        from django.template.loader import render_to_string
        amount = Decimal('1234567.6000000000')
        totals = dict(gross=amount, discount=amount, net=amount, income=amount)
        row = dict(totals, id='F1', number='1', date='1405/08/01', customer_name='مشتری',
                   discount_percent=Decimal('5.25'), effective_rate=Decimal('2.75'),
                   can_open=False)
        html = render_to_string('core/income_report.html', {
            'report_page': [row], 'report_total': totals,
            'visitor_summaries': [dict(id='v1', name='علی', count=1, gross=amount, income=amount)],
        })
        self.assertNotIn('۶۰۰۰۰۰۰۰۰۰', html)
        self.assertRegex(html, r'۵[.٫]۲۵')
        self.assertRegex(html, r'۲[.٫]۷۵')
        for value in re.findall(r'([۰-۹0-9,٬.٫\-]+)\s*ریال', html):
            self.assertNotIn('.', value)
            self.assertNotIn('٫', value)
