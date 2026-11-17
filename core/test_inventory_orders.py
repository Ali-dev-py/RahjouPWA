from decimal import Decimal
from unittest.mock import patch
import uuid

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.test import RequestFactory
from django.contrib.sessions.backends.signed_cookies import SessionStore

from .test_inventory import InventoryReceiptIntegrationTests
from .inventory import validate_payload
from .inventory_orders import save_order, prefactor_lines, approved_prefactors
from .inventory_views import OrderFormView
from .models import Tblorderstock, Tblorderstockitems, Sanadkala, Prefactormaster, Prefactordetail, Prefactordetailstatus


class OrderIntegrationTests(InventoryReceiptIntegrationTests):
    table_models = InventoryReceiptIntegrationTests.table_models + (
        Tblorderstock, Tblorderstockitems, Sanadkala,
        Prefactormaster, Prefactordetail, Prefactordetailstatus)

    def stock(self, amount='2', **kwargs):
        return self.insert(Sanadkala, gsanadkalaid=str(uuid.uuid4()), ginvid=self.inv.ginvid,
                           gkalaid=self.product.gkalaid, financialyear=1405,
                           varede=Decimal(amount), sadere=0, **kwargs)

    def payload(self, quantity='2'):
        return validate_payload(self.data(branch='', **{'quantity[]': [quantity]}),
                                require_branch=False, decimal_quantities=True)

    def prefactor(self):
        self.insert(Prefactordetailstatus, prefactordetailstatuscode=8, prefactordetailstatusname='تائید شده')
        master = self.insert(Prefactormaster, prefactorno='123', gprefactormasterid=str(uuid.uuid4()),
                             prefactorstatuscode=8, isbuy=False)
        self.insert(Prefactordetail, gprefactormasterid=master.gprefactormasterid,
                    gkalaid=self.product.gkalaid, quantity=2)
        return master

    def test_order_equal_balance_and_ledger_mapping(self):
        self.stock()
        with patch('core.inventory_orders.today_string', return_value='1405/08/21'):
            order = save_order(self.payload(), self.user)
        self.assertEqual(order.orderstockno, '1')
        self.assertEqual(order.orderstockdate, '1405/08/20')
        self.assertEqual(order.financialyear, 1405)
        item = Tblorderstockitems.objects.using('plus').get()
        self.assertEqual(item.quantityv1, 2)
        ledger = Sanadkala.objects.using('plus').get(operkind=134)
        self.assertEqual((ledger.varede, ledger.sadere), (0, 2))
        self.assertEqual(ledger.operdate, '1405/08/21')
        self.assertEqual(ledger.goperid, order.gorderstockid)
        self.assertEqual(ledger.ginvid, self.inv.ginvid)
        self.assertEqual(ledger.gkalaid, self.product.gkalaid)
        with self.assertRaises(ValidationError):
            save_order(self.payload('1'), self.user)

    def test_absent_negative_insufficient_wrong_year_or_warehouse(self):
        with self.assertRaises(ValidationError):
            save_order(self.payload(), self.user)
        row = self.stock('-1')
        for amount in ('-1', '0', '1'):
            row.varede = Decimal(amount)
            row.save(using='plus')
            with self.assertRaises(ValidationError):
                save_order(self.payload(), self.user)
        row.varede = 100
        row.financialyear = 1404
        row.save(using='plus')
        with self.assertRaises(ValidationError):
            save_order(self.payload(), self.user)
        row.financialyear = 1405
        row.ginvid = self.inv2.ginvid
        row.save(using='plus')
        with self.assertRaises(ValidationError):
            save_order(self.payload(), self.user)
        self.assertFalse(Tblorderstock.objects.using('plus').exists())

    def test_decimal_quantity_and_rollback(self):
        self.stock('3')
        with patch.object(Sanadkala, 'save', side_effect=DatabaseError('ledger failed')):
            with self.assertRaises(DatabaseError):
                save_order(self.payload('1.25'), self.user)
        self.assertFalse(Tblorderstock.objects.using('plus').exists())
        self.assertFalse(Tblorderstockitems.objects.using('plus').exists())
        save_order(self.payload('1.25'), self.user)
        self.assertEqual(Tblorderstockitems.objects.using('plus').get().quantityv1, Decimal('1.25'))

    def test_prefactor_approval_and_import_aggregation(self):
        master = self.prefactor()
        self.assertEqual(approved_prefactors().count(), 1)
        _, totals = prefactor_lines(master.gprefactormasterid)
        self.assertEqual(list(totals.values()), [2])
        master.prefactorstatuscode = 9
        master.save(using='plus')
        with self.assertRaises(ValidationError):
            prefactor_lines(master.gprefactormasterid)

    def request(self, data):
        request = RequestFactory().post('/', data)
        request.plus_user = self.user
        request.session = self.session
        return request

    def test_modified_import_requires_signed_exact_confirmation(self):
        master = self.prefactor()
        self.stock('20')
        self.session = SessionStore()
        form_id = str(uuid.uuid4())
        self.session['inventory_order_forms'] = {form_id: {}}
        view = OrderFormView()
        data = self.data()
        data.update({'form_id': form_id, 'action': 'import', 'prefactor': master.gprefactormasterid})
        response = view.post(self.request(data))
        self.assertEqual(response.status_code, 200)
        data['action'] = 'save'
        data.setlist('quantity[]', ['3'])
        data['confirm_changes'] = 'yes'  # An unchecked client claim alone cannot authorize changes.
        response = view.post(self.request(data))
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Tblorderstock.objects.using('plus').exists())
        import re
        from html import unescape
        token = unescape(re.search(r'name="confirmation" value="([^"]+)"', response.content.decode()).group(1))
        data['confirmation'] = token
        data.setlist('quantity[]', ['4'])
        self.assertEqual(view.post(self.request(data)).status_code, 409)
        data.setlist('quantity[]', ['3'])
        request = self.request(data)
        from django.contrib.messages.storage.fallback import FallbackStorage
        request._messages = FallbackStorage(request)
        self.assertEqual(view.post(request).status_code, 302)
        self.assertEqual(Tblorderstock.objects.using('plus').get().gprefactorid, master.gprefactormasterid)

    def test_added_or_removed_products_require_confirmation(self):
        master = self.prefactor()
        self.session = SessionStore()
        form_id = str(uuid.uuid4())
        self.session['inventory_order_forms'] = {form_id: {}}
        view = OrderFormView()
        data = self.data()
        data.update({'form_id': form_id, 'action': 'import', 'prefactor': master.gprefactormasterid})
        self.assertEqual(view.post(self.request(data)).status_code, 200)
        data['action'] = 'save'
        data.setlist('product_id[]', [self.product.gkalaid, self.product2.gkalaid])
        data.setlist('quantity[]', ['2', '1'])
        self.assertEqual(view.post(self.request(data)).status_code, 409)
        data.setlist('product_id[]', [self.product2.gkalaid])
        data.setlist('quantity[]', ['1'])
        self.assertEqual(view.post(self.request(data)).status_code, 409)
        self.assertFalse(Tblorderstock.objects.using('plus').exists())


from django.test import SimpleTestCase
from unittest.mock import MagicMock
from .inventory_orders import order_write_lock


class OrderLockTests(SimpleTestCase):
    @patch('core.inventory_orders.transaction.atomic')
    @patch('core.inventory_orders.connections')
    def test_sql_server_locks_ledger_before_numbering(self, dbs, atomic):
        connection = MagicMock(vendor='microsoft')
        dbs.__getitem__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        with order_write_lock():
            pass
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertIn('[SanadKala]', statements[0])
        self.assertIn('[tblOrderStock]', statements[1])
        self.assertTrue(all('TABLOCKX, HOLDLOCK' in sql for sql in statements))
