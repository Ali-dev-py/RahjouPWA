import json
from types import SimpleNamespace as Obj
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.test import SimpleTestCase, RequestFactory
from django.views import View

from .customer_geography import customer_geography
from .visitor_assignment import resolve_visitor, is_visitor
from .views import PlusLoginRequiredMixin, CustomerCreateView, SaleRequestCreateView, SaleRequestEditView


class AssignmentProbe(PlusLoginRequiredMixin, View):
    automatic_visitor_assignment = True

    def post(self, request):
        return JsonResponse({'visitor': request.POST.get('visitor_id')})

    def get(self, request):
        return JsonResponse({'filter': request.GET.get('visitor'), 'area': request.GET.get('area'),
                             'error': getattr(request, 'automatic_visitor_error', '')})


class VisitorAssignmentTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = Obj(gucode='USER-1', uname='علی کریمی', utitle='ويزيتور', uactive=True)
        self.visitor = Obj(gvisitorid='VIS-1', vizitorname=' علي  كريمي ', active=True)

    @patch('core.visitor_assignment.ViewAllvisitors')
    def test_name_normalization_dedup_and_active_matching(self, visitors):
        visitors.objects.using.return_value.all.return_value = [self.visitor,
            Obj(gvisitorid='vis-1', vizitorname='علی کریمی', active=None),
            Obj(gvisitorid='OTHER', vizitorname='علی کریمی', active=False)]
        self.assertEqual(resolve_visitor(self.user).gvisitorid.lower(), 'vis-1')
        self.assertTrue(is_visitor(self.user))

    @patch('core.visitor_assignment.ViewAllvisitors')
    def test_missing_or_ambiguous_match_never_guesses(self, visitors):
        for rows in ([], [Obj(gvisitorid='OTHER', vizitorname='نام دیگر', active=True)],
                     [self.visitor, Obj(gvisitorid='OTHER', vizitorname='علی کریمی', active=True)]):
            visitors.objects.using.return_value.all.return_value = rows
            self.assertIsNone(resolve_visitor(self.user))

    @patch('core.visitor_assignment.ViewAllvisitors')
    def test_nonvisitor_never_queries_assignment(self, visitors):
        self.user.utitle = 'مدیر'
        self.assertIsNone(resolve_visitor(self.user))
        visitors.objects.using.assert_not_called()

    def request(self, method='post', data=None):
        request = getattr(self.factory, method)('/', data or {})
        request.session = {'user_id': self.user.gucode}
        return request

    @patch('core.views.resolve_visitor')
    @patch('core.views.TuaUser')
    def test_post_assignment_is_server_controlled_even_if_missing_or_tampered(self, users, resolve):
        users.objects.using.return_value.filter.return_value.first.return_value = self.user
        resolve.return_value = self.visitor
        for data in ({}, {'visitor_id': 'ATTACKER'}):
            response = AssignmentProbe.as_view()(self.request(data=data))
            self.assertJSONEqual(response.content, {'visitor': 'VIS-1'})
        for form in (CustomerCreateView, SaleRequestCreateView, SaleRequestEditView):
            self.assertTrue(form.automatic_visitor_assignment)

    @patch('core.views.resolve_visitor', return_value=None)
    @patch('core.views.TuaUser')
    def test_unmatched_post_denied_get_explains(self, users, resolve):
        users.objects.using.return_value.filter.return_value.first.return_value = self.user
        with self.assertRaises(PermissionDenied):
            AssignmentProbe.as_view()(self.request(data={'visitor_id': 'OTHER'}))
        response = AssignmentProbe.as_view()(self.request('get'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)['error'])

    @patch('core.views.resolve_visitor')
    @patch('core.views.TuaUser')
    def test_nonvisitor_keeps_selected_assignment_and_filters(self, users, resolve):
        self.user.utitle = 'مدیر'
        users.objects.using.return_value.filter.return_value.first.return_value = self.user
        self.assertJSONEqual(AssignmentProbe.as_view()(self.request(data={'visitor_id': 'SELECTED'})).content,
                             {'visitor': 'SELECTED'})
        response = AssignmentProbe.as_view()(self.request('get', {'visitor': 'SELECTED', 'area': 'A'}))
        self.assertJSONEqual(response.content, {'filter': 'SELECTED', 'area': 'A', 'error': ''})
        resolve.assert_not_called()

    @patch('core.views.resolve_visitor')
    @patch('core.views.TuaUser')
    def test_visitor_cannot_reactivate_hidden_filter_through_url(self, users, resolve):
        users.objects.using.return_value.filter.return_value.first.return_value = self.user
        resolve.return_value = self.visitor
        response = AssignmentProbe.as_view()(self.request('get', {'visitor': 'OTHER', 'area': 'A'}))
        self.assertJSONEqual(response.content, {'filter': None, 'area': 'A', 'error': ''})

    def test_assignment_templates_use_readonly_display_and_no_select_for_visitors(self):
        request = self.factory.get('/')
        request.plus_user = self.user
        request.automatic_visitor = self.visitor
        for template, select_id in (('core/customer_create.html', 'visitor_id'),
                                    ('core/sale_request_create.html', 'visitorSelect')):
            html = render_to_string(template, {'visitors': [{'id': 'OTHER', 'name': 'Other'}]}, request=request)
            self.assertIn('value="VIS-1"', html)
            self.assertNotIn('<select name="visitor_id"', html)
            self.assertNotIn('<select id="visitor_id"', html)
            self.assertNotIn('value="OTHER"', html)
            request.plus_user = Obj(utitle='مدیر')
            html = render_to_string(template, {'visitors': [{'id': 'OTHER', 'name': 'Other'}]}, request=request)
            self.assertIn('value="OTHER"', html)
            request.plus_user = self.user

    def test_filters_hidden_on_customers_documents_and_report(self):
        request = self.factory.get('/')
        request.plus_user = self.user
        for template, marker in (('core/customers.html', 'id="customerVisitorFilter"'),
                                  ('partials/_document_filters.html', 'id="visitor-filter"'),
                                  ('core/income_report.html', 'id="report-visitor"')):
            context = {'is_visitor_report': True}
            html = render_to_string(template, context, request=request)
            self.assertNotIn(marker, html)
            request.plus_user = Obj(utitle='مدیر')
            context['is_visitor_report'] = False
            self.assertIn(marker, render_to_string(template, context, request=request))
            request.plus_user = self.user


class CustomerGeographyTests(SimpleTestCase):
    def test_batch_labels_guid_normalization_and_scoped_options(self):
        customers = [Obj(gprovinceid='{PROV-1}', gcityid='CITY-1'),
                     Obj(gprovinceid='prov-1', gcityid='city-1'), Obj(gprovinceid=None, gcityid=None)]
        provinces, cities = customer_geography(customers,
            [{'id': 'prov-1', 'name': 'تهران'}, {'id': 'prov-2', 'name': 'فارس'}],
            [{'id': 'city-1', 'name': 'ری'}, {'id': 'city-2', 'name': 'شیراز'}])
        self.assertEqual(customers[0].province_name, 'تهران')
        self.assertEqual(customers[0].city_name, 'ری')
        self.assertEqual(customers[0].province_key, 'prov-1')
        self.assertEqual(len(provinces), 2)  # one province and the unassigned option
        self.assertEqual(len(cities), 2)
        self.assertNotIn('فارس', str(provinces))
        self.assertNotIn('شیراز', str(cities))
        self.assertEqual(customers[-1].city_key, 'none')
        html = render_to_string('core/customers.html', {'customers': customers})
        self.assertIn('customer-province-badge', html)
        self.assertIn('customer-city-badge', html)
        self.assertIn('تهران', html)
        self.assertIn('ری', html)
        self.assertIn('data-province="prov-1"', html)

    def test_customer_list_initial_render_combines_province_city_and_status(self):
        from unittest.mock import MagicMock
        from .views import CustomersView
        rows = [Obj(gcustomerid='C1', custname='مشتری اول', gsubdetailid=None,
                    gprovinceid='P1', gcityid='CITY1', mobile='', phone=''),
                Obj(gcustomerid='C2', custname='مشتری دوم', gsubdetailid=None,
                    gprovinceid='P2', gcityid='CITY2', mobile='', phone='')]
        customers = MagicMock()
        customers.all.return_value.order_by.return_value = rows
        lookups = ([{'id': 'P1', 'name': 'تهران'}, {'id': 'P2', 'name': 'فارس'}],
                   [{'id': 'CITY1', 'name': 'ری', 'province_id': 'P1'},
                    {'id': 'CITY2', 'name': 'شیراز', 'province_id': 'P2'}])
        with patch('core.views.TuaUser') as users, \
             patch.object(CustomersView, '_customers', return_value=customers), \
             patch('core.views._load_provinces_and_cities_for_form', return_value=lookups), \
             patch('core.views.Tblsanadrad') as balances, \
             patch('core.views.Visitortocustomer') as links, \
             patch('core.views.ViewAllvisitors') as visitors:
            users.objects.using.return_value.filter.return_value.first.return_value = Obj(utitle='مدیر')
            balances.objects.using.return_value.values.return_value.annotate.return_value = []
            links.objects.using.return_value.filter.return_value.values.return_value = []
            visitors.objects.using.return_value.values.return_value = []
            for query, expected in (({'province': 'P1', 'city': 'CITY1'}, 1),
                                     ({'province': 'P1', 'city': 'CITY1', 'status': 'debtor'}, 0),
                                     ({'province': 'P2'}, 1)):
                request = RequestFactory().get('/', query)
                request.session = {'user_id': 'U1'}
                response = CustomersView.as_view()(request)
                self.assertEqual(response.context_data['visible_customers_count'], expected)
                self.assertEqual(len(response.context_data['customers']), 2)
                self.assertEqual(rows[0].province_name, 'تهران')
