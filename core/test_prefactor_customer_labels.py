from types import SimpleNamespace as Obj
from unittest.mock import patch
from django.test import SimpleTestCase
from django.template.loader import render_to_string
from .inventory_orders import prefactor_choices


class PrefactorCustomerLabelTests(SimpleTestCase):
    @patch('core.inventory_orders.Tblcustomer')
    @patch('core.inventory_orders.approved_prefactors')
    def test_labels_use_customer_guid_not_requester_and_preserve_order(self, approved, customers):
        prefactors = [Obj(gcustomerid='{CUSTOMER-1}', requestman='نام درخواست‌کننده'),
                      Obj(gcustomerid='customer-1'), Obj(gcustomerid='MISSING')]
        approved.return_value.order_by.return_value = prefactors
        customers.objects.using.return_value.filter.return_value = [Obj(gcustomerid='CUSTOMER-1', custname='فروشگاه نمونه')]
        choices = prefactor_choices()
        self.assertEqual(choices, prefactors)
        self.assertEqual(choices[0].customer_name, 'فروشگاه نمونه')
        self.assertEqual(choices[1].customer_name, 'فروشگاه نمونه')
        self.assertEqual(choices[2].customer_name, 'مشتری نامشخص')
        customers.objects.using.return_value.filter.assert_called_once()

    @patch('core.inventory_orders.Tblcustomer')
    @patch('core.inventory_orders.approved_prefactors')
    def test_empty_list_needs_no_customer_query(self, approved, customers):
        approved.return_value.order_by.return_value = []
        self.assertEqual(prefactor_choices(), [])
        customers.objects.using.assert_not_called()

    def test_customer_name_rendered_beside_number_and_escaped(self):
        html = render_to_string('core/order_form.html', {'prefactors': [Obj(
            gprefactormasterid='P1', prefactorno='123', prefactordate='1405/08/01',
            customer_name='فروشگاه <نمونه>')]})
        self.assertIn('۱۲۳ · فروشگاه &lt;نمونه&gt; ·', html)
        self.assertIn('جستجوی شماره یا نام مشتری', html)
