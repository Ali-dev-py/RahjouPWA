from types import SimpleNamespace as Obj
from django.test import SimpleTestCase, RequestFactory
from django.template.loader import render_to_string
from .filter_state import filter_state_context


class FilterStateTests(SimpleTestCase):
    def test_scope_stable_per_session_rotates_for_other_user_or_role(self):
        request = RequestFactory().get('/')
        request.session = {}
        request.plus_user = Obj(gucode='USER1', utitle='ویزیتور')
        first = filter_state_context(request)['filter_state_scope']
        self.assertEqual(first, filter_state_context(request)['filter_state_scope'])
        request.plus_user = Obj(gucode='USER2', utitle='ویزیتور')
        second = filter_state_context(request)['filter_state_scope']
        self.assertNotEqual(first, second)
        request.plus_user.utitle = 'مدیر'
        self.assertNotEqual(second, filter_state_context(request)['filter_state_scope'])
        request.session = {}
        self.assertNotEqual(first, filter_state_context(request)['filter_state_scope'])

    def test_anonymous_gets_no_storage_scope(self):
        request = RequestFactory().get('/')
        request.session = {}
        self.assertEqual(filter_state_context(request), {})
        self.assertEqual(request.session, {})

    def test_all_filter_pages_opt_in_but_edit_forms_do_not(self):
        for name in ('customers', 'customer_detail', 'sale_request_list', 'pre_factor_list',
                     'factor_list', 'income_report', 'receipt_list', 'inventory_balances', 'payment_dues'):
            with self.subTest(page=name):
                html = render_to_string('core/' + name + '.html', {'filter_state_scope': 'test-scope', 'customer_pk': 'C1', 'edit_pk': 'C1'})
                self.assertIn('data-filter-page="1"', html)
                self.assertIn('data-filter-scope="test-scope"', html)
        for name in ('customer_create', 'customer_edit', 'sale_request_create', 'receipt_form', 'order_form'):
            with self.subTest(page=name):
                html = render_to_string('core/' + name + '.html', {'filter_state_scope': 'test-scope', 'customer_pk': 'C1', 'edit_pk': 'C1'})
                self.assertIn('data-filter-page=""', html)

    def test_customer_search_prefills_from_query(self):
        request = RequestFactory().get('/customers/', {'q': 'فروشگاه', 'province': 'P1'})
        html = render_to_string('core/customers.html', {}, request=request)
        self.assertIn('value="فروشگاه"', html)
