from decimal import Decimal
from types import SimpleNamespace as Obj
from unittest.mock import patch

import jdatetime
from django.db import DatabaseError
from django.test import SimpleTestCase, RequestFactory
from django.urls import reverse

from .income_report import (commission, report_period, parse_date, guid_batches,
                            build_report, factor_attribution)
from .views import DashboardView


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
        for discount, expected in ((0, 4500000), (5000000, 3000000),
                                   (10000000, 1500000), (15000000, 0), (20000000, 0)):
            with self.subTest(discount=discount):
                self.assertEqual(commission(100000000, discount)['income'], Decimal(expected))
        self.assertTrue(commission(100, 16)['over_margin'])
        self.assertFalse(commission(100, 15)['over_margin'])

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
        self.assertEqual(report['report_rows'][0]['income'], 3000000)
        self.assertEqual(report['report_total']['income'], 7500000)
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
        self.assertEqual(report['report_total']['income'], 3000000)
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
        request = RequestFactory().get(reverse('core:dashboard'), params)
        request.plus_user = Obj(utitle='ویزیتور', uname='علی')
        return request

    @patch('core.income_report.build_report')
    def test_invalid_dates_do_not_query_financial_data(self, build):
        view = DashboardView()
        view.request = self.request({'period': 'custom', 'start': 'bad', 'end': 'bad'})
        context = view.get_context_data()
        self.assertIn('report_error', context)
        build.assert_not_called()

    @patch('core.income_report.build_report', side_effect=DatabaseError('sensitive database info'))
    def test_database_failure_is_error_not_false_zero_report(self, build):
        view = DashboardView()
        view.request = self.request({})
        context = view.get_context_data()
        self.assertIn('report_error', context)
        self.assertNotIn('report_total', context)
        self.assertNotIn('sensitive', context['report_error'])

    @patch('core.income_report.build_report')
    @patch.object(DashboardView, '_visitor_customer_ids', return_value=[])
    def test_pagination_full_totals_and_visitor_selector_hidden(self, scope, build):
        rows = [dict(id=f'F{i}', customer_id='c1', customer_name='مشتری', gross=100,
                     discount=0, net=100, discount_percent=0, effective_rate=4.5,
                     income=5, date='1405/08/01', number=i) for i in range(25)]
        build.return_value = dict(report_rows=rows, report_total=dict(gross=2500, discount=0, net=2500, income=125),
                                  factor_count=25, is_visitor_report=True, selected_report_visitor='',
                                  report_visitors=[], visitor_summaries=[], warning_count=0, unassigned_count=0)
        view = DashboardView()
        view.request = self.request({'page': '2'})
        context = view.get_context_data()
        self.assertEqual(len(context['report_page']), 5)
        self.assertEqual(context['report_total']['income'], 125)
        self.assertFalse(context['report_page'][0]['can_open'])
        from django.template.loader import render_to_string
        html = render_to_string('core/dashboard.html', context)
        self.assertNotIn('id="report-visitor"', html)
        self.assertNotIn('/factors/detail/F', html)
        self.assertIn('پورسانت من', html)
