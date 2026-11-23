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
from .models import Tblorderstock, Tblorderstockitems, Sanadkala, Prefactormaster, Prefactordetail, Prefactordetailstatus, Tblcustomer


class OrderIntegrationTests(InventoryReceiptIntegrationTests):
    table_models = InventoryReceiptIntegrationTests.table_models + (
        Tblcustomer, Tblorderstock, Tblorderstockitems, Sanadkala,
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
                             prefactorstatuscode=4, isbuy=False, gorderstockid=None)
        self.insert(Prefactordetail, gprefactormasterid=master.gprefactormasterid,
                    gkalaid=self.product.gkalaid, quantity=2)
        return master

    def test_order_equal_balance_and_ledger_mapping(self):
        self.stock()
        with patch('core.inventory_orders.today_string', return_value='1405/08/21'):
            order = save_order(self.payload(), self.user)
        self.assertEqual(order.orderstockno, '000001')
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

    def test_prefactor_item_description_uses_real_metadata_and_padded_number(self):
        master = self.prefactor()
        customer = self.insert(Tblcustomer, gcustomerid=str(uuid.uuid4()), custname='حمید بیدی')
        master.prefactorno = '000109'
        master.prefactordate = '1405/09/02'
        master.gbranchid = self.branch.gbranchid
        master.gcustomerid = customer.gcustomerid
        master.save(using='plus')
        self.branch.branchname = 'تهران'
        self.branch.save(using='plus')
        self.stock('20')
        first = save_order(self.payload(), self.user)
        self.assertIsNone(Tblorderstockitems.objects.using('plus').get().kaladescript)
        first.orderstockno = '164'
        first.save(using='plus')
        order = save_order(self.payload(), self.user, master.gprefactormasterid)
        self.assertEqual(order.orderstockno, '000165')
        item = Tblorderstockitems.objects.using('plus').get(gorderstockid=order.gorderstockid)
        self.assertEqual(item.kaladescript,
            'پیش فاکتور فروش شماره 000109 مورخ 1405/09/02 شعبه تهران بنام جناب آقای حمید بیدی')
        self.assertEqual(Sanadkala.objects.using('plus').get(goperid=order.gorderstockid).operno, '000165')
        first.refresh_from_db(using='plus')
        self.assertEqual(first.orderstockno, '164')

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

    def test_detail_approval_cannot_override_master_status(self):
        master = self.prefactor()
        Prefactordetail.objects.using('plus').update(prefactordetailstatuscode=8)
        for code in (None, 0, 1, 2, 3, 8):
            master.prefactorstatuscode = code
            master.save(using='plus')
            self.assertFalse(approved_prefactors().filter(pk=master.pk).exists())
            with self.assertRaises(ValidationError):
                prefactor_lines(master.gprefactormasterid)

    def test_purchase_and_unapproved_prefactors_stay_excluded(self):
        master = self.prefactor()
        master.isbuy = True
        master.save(using='plus')
        Prefactordetail.objects.using('plus').update(prefactordetailstatuscode=8)
        self.assertFalse(approved_prefactors().exists())
        master.isbuy = False
        master.prefactorstatuscode = 0
        master.save(using='plus')
        Prefactordetail.objects.using('plus').update(prefactordetailstatuscode=0)
        self.assertFalse(approved_prefactors().exists())
        with self.assertRaises(ValidationError):
            prefactor_lines(master.gprefactormasterid)

    def test_master_status_four_needs_no_status_labels_or_detail_approval(self):
        master = self.prefactor()
        Prefactordetailstatus.objects.using('plus').all().delete()
        Prefactordetail.objects.using('plus').update(prefactordetailstatuscode=0)
        self.assertEqual(approved_prefactors().count(), 1)
        imported, totals = prefactor_lines(master.gprefactormasterid)
        self.assertEqual(imported.pk, master.pk)
        self.assertEqual(list(totals.values()), [2])

    def test_revoked_master_approval_blocks_posting_even_with_approved_details(self):
        master = self.prefactor()
        self.stock('20')
        Prefactordetail.objects.using('plus').update(prefactordetailstatuscode=8)
        master.prefactorstatuscode = 1
        master.save(using='plus')
        with self.assertRaises(ValidationError):
            save_order(self.payload(), self.user, master.gprefactormasterid)
        self.assertFalse(Tblorderstock.objects.using('plus').exists())
        self.assertFalse(Tblorderstockitems.objects.using('plus').exists())
        self.assertFalse(Sanadkala.objects.using('plus').filter(operkind=134).exists())

    def test_linked_prefactor_is_excluded_and_rejected_on_import_and_posting(self):
        master = self.prefactor()
        self.stock('20')
        # It was eligible when selected, but another system linked it before posting.
        prefactor_lines(master.gprefactormasterid)
        master.gorderstockid = str(uuid.uuid4())
        master.save(using='plus')
        self.assertFalse(approved_prefactors().filter(pk=master.pk).exists())
        with self.assertRaises(ValidationError):
            prefactor_lines(master.gprefactormasterid)
        with self.assertRaises(ValidationError):
            save_order(self.payload(), self.user, master.gprefactormasterid)
        self.assertFalse(Tblorderstock.objects.using('plus').exists())
        self.assertFalse(Tblorderstockitems.objects.using('plus').exists())
        self.assertFalse(Sanadkala.objects.using('plus').filter(operkind=134).exists())

    def test_order_form_shows_approved_options_or_explicit_empty_state(self):
        from django.test import RequestFactory
        from django.contrib.sessions.backends.signed_cookies import SessionStore
        request = RequestFactory().get('/')
        request.plus_user = self.user
        request.session = SessionStore()
        response = OrderFormView().get(request)
        self.assertContains(response, 'پیش‌فاکتور تأییدشده‌ای یافت نشد.')
        master = self.prefactor()
        master.prefactorstatuscode = 4
        master.save(using='plus')
        Prefactordetail.objects.using('plus').update(prefactordetailstatuscode=8)
        response = OrderFormView().get(request)
        self.assertContains(response, master.gprefactormasterid)
        self.assertContains(response, 'id="prefactor-search"')
        self.assertNotContains(response, 'شماره و شناسه‌ها هنگام ذخیره')
        self.assertNotContains(response, 'تعداد پیش‌فرض')


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
