from decimal import Decimal
from types import SimpleNamespace as Obj
from unittest import skipUnless
from unittest.mock import patch, MagicMock
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connections, models, DatabaseError
from django.http import QueryDict
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TransactionTestCase, RequestFactory, Client
from django.urls import reverse
from django.utils import timezone

from .inventory import (inventory_allowed, validate_payload, save_receipt, delete_receipt,
                        next_receipt_number, receipt_write_lock, can_modify,
                        FINANCIAL_YEAR, MOIN_ID, ACCOUNT_ID, CUSTOMER_ID)
from .models import (Tblreceiptstock, Tblreceiptstockitem, Finalstatus, Tblinv,
                     Tblsubdetailgroup, Branches, Tblkala, Tbldetailgroup)


class InventoryAccessTests(SimpleTestCase):
    def user(self, title='مدیر'):
        return Obj(gucode='00000000-0000-0000-0000-000000000001', utitle=title, uactive=True)

    def urls(self):
        pk = uuid.UUID('11111111-1111-1111-1111-111111111111')
        return [reverse('core:' + name, kwargs={'pk': pk} if name in ('receipt_detail', 'receipt_edit', 'receipt_delete') else None)
                for name in ('inventory_home', 'inventory_orders', 'receipt_list', 'receipt_create',
                             'receipt_detail', 'receipt_edit', 'receipt_delete', 'order_create')]

    def test_all_inventory_routes_require_login(self):
        for url in self.urls():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('core:login'), response['Location'])

    @patch('core.views.TuaUser')
    def test_visitor_cannot_get_or_post_any_inventory_url(self, users):
        users.objects.using.return_value.filter.return_value.first.return_value = self.user('ويزيتور')
        # Avoid a database session backend in this SimpleTestCase.
        from django.test import override_settings
        with override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies'):
            client = Client()
            session = client.session
            session['user_id'] = self.user().gucode
            session.save()
            client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
            for url in self.urls():
                for method in ('get', 'post'):
                    with self.subTest(url=url, method=method):
                        self.assertEqual(getattr(client, method)(url).status_code, 403)

    def test_inventory_navigation_hidden_for_visitors_and_anonymous(self):
        for title, visible in (('مدیر', True), ('کاربر فروش', True), ('ویزیتور', False), ('ويزيتور', False)):
            html = render_to_string('partials/_bottom_nav.html', {'current_user': self.user(title)})
            self.assertEqual(reverse('core:inventory_home') in html, visible)
        html = render_to_string('partials/_bottom_nav.html', {})
        self.assertNotIn(reverse('core:inventory_home'), html)
        self.assertFalse(inventory_allowed(None))

    @patch('core.views.TuaUser')
    def test_nonvisitor_can_open_home_and_orders(self, users):
        from .inventory_views import InventoryHomeView, InventoryOrdersView
        users.objects.using.return_value.filter.return_value.first.return_value = self.user()
        for view, route in ((InventoryHomeView, 'inventory_home'), (InventoryOrdersView, 'inventory_orders')):
            request = RequestFactory().get(reverse('core:' + route))
            request.session = {'user_id': self.user().gucode}
            with patch.object(InventoryOrdersView, 'get_context_data', return_value={}):
                response = view.as_view()(request)
                response.render()
            self.assertEqual(response.status_code, 200)
            self.assertIn('حواله انبار', response.content.decode())

    def test_identity_fields_use_database_sequences(self):
        self.assertIsInstance(Tblreceiptstock._meta.pk, models.AutoField)
        self.assertIsInstance(Tblreceiptstockitem._meta.pk, models.AutoField)
        self.assertFalse(Tblreceiptstock._meta.managed)
        self.assertTrue(Tblreceiptstock._meta.get_field('greceiptstockid').unique)

    @patch('core.inventory.transaction.atomic')
    @patch('core.inventory.connections')
    def test_sql_server_lock_coordinates_receipt_numbers(self, dbs, atomic):
        connection = MagicMock(vendor='microsoft')
        dbs.__getitem__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (0,)
        with receipt_write_lock():
            pass
        sql = ' '.join(call.args[0] for call in cursor.execute.call_args_list)
        self.assertIn('sp_getapplock', sql)
        self.assertIn('TABLOCKX, HOLDLOCK', sql)
        cursor.fetchone.return_value = (-1,)
        with self.assertRaises(ValidationError):
            with receipt_write_lock():
                self.fail('Lock failure must prevent writes')


@skipUnless(settings.DATABASES['plus']['ENGINE'] == 'django.db.backends.sqlite3',
            'Isolated unmanaged-schema integration test requires the SQLite test configuration')
class InventoryReceiptIntegrationTests(TransactionTestCase):
    databases = {'default', 'plus'}
    table_models = (Tbldetailgroup, Tblsubdetailgroup, Finalstatus, Tblinv, Branches,
                    Tblkala, Tblreceiptstock, Tblreceiptstockitem)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        connection = connections['plus']
        connection.ensure_connection()
        connection.connection.create_collation('Arabic_CI_AS', lambda a, b: (a.lower() > b.lower()) - (a.lower() < b.lower()))
        with connection.schema_editor() as schema:
            for model in cls.table_models:
                schema.create_model(model)

    @classmethod
    def tearDownClass(cls):
        with connections['plus'].schema_editor() as schema:
            for model in reversed(cls.table_models):
                schema.delete_model(model)
        super().tearDownClass()

    @staticmethod
    def insert(model, **overrides):
        values = {}
        for field in model._meta.local_fields:
            if field.null or isinstance(field, models.AutoField):
                continue
            if isinstance(field, models.BooleanField):
                value = False
            elif isinstance(field, (models.IntegerField, models.DecimalField, models.FloatField)):
                value = 0
            elif isinstance(field, models.DateTimeField):
                value = timezone.now()
            else:
                value = 'x'
            values[field.attname] = value
        values.update(overrides)
        return model.objects.using('plus').create(**values)

    def setUp(self):
        for model in reversed(self.table_models):
            model.objects.using('plus').all().delete()
        self.inv = self.insert(Tblinv, ginvid=str(uuid.uuid4()).upper(), gtafzilid=str(uuid.uuid4()).upper(), invname='انبار اصلی')
        self.inv2 = self.insert(Tblinv, ginvid=str(uuid.uuid4()).upper(), gtafzilid=str(uuid.uuid4()).upper(), invname='انبار دوم')
        self.branch = self.insert(Branches, gbranchid=str(uuid.uuid4()).upper(), branchname='شعبه مرکزی')
        self.product = self.insert(Tblkala, gkalaid=str(uuid.uuid4()).upper(), kalaname='کالای اول', kalano='100')
        self.product2 = self.insert(Tblkala, gkalaid=str(uuid.uuid4()).upper(), kalaname='کالای دوم', kalano='200')
        self.status = self.insert(Finalstatus, code=1, title='ثبت اولیه', gcode=str(uuid.uuid4()).upper())
        self.user = Obj(gucode=str(uuid.uuid4()).upper(), utitle='مدیر', uactive=True)

    def data(self, **overrides):
        data = QueryDict('', mutable=True)
        data.update(dict(receipt_date='۱۴۰۵/۰۸/۲۰', inventory=self.inv.ginvid,
                         branch=self.branch.gbranchid, description='رسید آزمایشی'))
        data.setlist('product_id[]', [self.product.gkalaid])
        data.setlist('quantity[]', ['۲'])
        for key, value in overrides.items():
            if isinstance(value, list):
                data.setlist(key, value)
            else:
                data[key] = value
        return data

    def save(self, data=None, pk=None):
        return save_receipt(validate_payload(data if data is not None else self.data()), self.user, pk)

    def test_create_exact_master_item_mapping_and_identity_numbers(self):
        with patch('core.inventory.today_string', return_value='1405/08/21'):
            receipt = self.save()
        self.assertEqual(receipt.receiptstockdate, '1405/08/20')
        self.assertEqual(receipt.regdate, '1405/08/21')
        self.assertEqual(receipt.financialyear, 1405)
        self.assertEqual(receipt.recivekindcode, 1)
        self.assertEqual(receipt.finalstatuscode, 1)
        self.assertEqual(receipt.gfinalstatuscode, self.status.gcode)
        self.assertEqual(receipt.gcreatedby, self.user.gucode)
        self.assertEqual(receipt.ginvid, self.inv.ginvid)
        self.assertEqual(receipt.ginvtafzilid, self.inv.gtafzilid)
        self.assertEqual(receipt.gbranchid, self.branch.gbranchid)
        self.assertEqual(receipt.gmoinid, MOIN_ID)
        self.assertEqual(receipt.gaccid, ACCOUNT_ID)
        self.assertEqual(receipt.gcustid, CUSTOMER_ID)
        self.assertEqual(receipt.receiptstockno, '1')
        self.assertIsNotNone(receipt.receiptstockid)
        self.assertRegex(receipt.receiptstocktime, r'^\d{2}:\d{2}$')
        uuid.UUID(receipt.greceiptstockid)
        item = Tblreceiptstockitem.objects.using('plus').get(greceiptstockid=receipt.greceiptstockid)
        self.assertEqual(item.quantityv1, 2)
        self.assertEqual(item.qualitycode, 1)
        self.assertEqual(item.ginvid, self.inv.ginvid)
        self.assertEqual(item.gkalaid, self.product.gkalaid)
        uuid.UUID(item.greceiptstockitemid)
        second = self.save()
        self.assertEqual(second.receiptstockno, '2')
        self.assertGreater(second.receiptstockid, receipt.receiptstockid)
        self.assertGreater(Tblreceiptstockitem.objects.using('plus').get(greceiptstockid=second.greceiptstockid).receiptstockitemid, item.receiptstockitemid)

    def test_numbering_uses_numeric_values_and_financial_year(self):
        receipt = self.save()
        receipt.receiptstockno = '9'
        receipt.save(using='plus')
        self.assertEqual(self.save().receiptstockno, '10')
        receipt.financialyear = 1404
        receipt.receiptstockno = '999'
        receipt.save(using='plus')
        self.assertEqual(next_receipt_number(), '11')

    def test_invalid_quantities_dates_selections_duplicates_cannot_write(self):
        for quantity in ('0', '-1', '1.5', '۲٫۵', '1e2', '1000000000000', ''):
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                self.save(self.data(**{'quantity[]': [quantity]}))
        for overrides in ({'receipt_date': '1405/13/01'}, {'inventory': 'bad-guid'},
                          {'branch': ''}, {'description': 'x' * 501},
                          {'product_id[]': [str(uuid.uuid4())]}, {'product_id[]': []},
                          {'product_id[]': [self.product.gkalaid] * 2, 'quantity[]': ['1', '2']},
                          {'quantity[]': []}):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self.save(self.data(**overrides))
        self.assertEqual(Tblreceiptstock.objects.using('plus').count(), 0)
        self.assertEqual(Tblreceiptstockitem.objects.using('plus').count(), 0)

    def test_missing_initial_status_prevents_writes(self):
        self.status.delete(using='plus')
        with self.assertRaises(ValidationError):
            self.save()
        self.assertFalse(Tblreceiptstock.objects.using('plus').exists())

    def test_edit_preserves_ids_updates_inventory_adds_removes_and_keeps_registration(self):
        receipt = self.save()
        item = Tblreceiptstockitem.objects.using('plus').get(greceiptstockid=receipt.greceiptstockid)
        old_guid, old_id, original_date = item.greceiptstockitemid, item.receiptstockitemid, receipt.regdate
        item.unitprice = 123
        item.save(using='plus')
        data = self.data(inventory=self.inv2.ginvid, **{'product_id[]': [self.product.gkalaid, self.product2.gkalaid], 'quantity[]': ['۳', '1']})
        updated = self.save(data, receipt.greceiptstockid)
        self.assertEqual(updated.receiptstockid, receipt.receiptstockid)
        self.assertEqual(updated.receiptstockno, receipt.receiptstockno)
        self.assertEqual(updated.regdate, original_date)
        self.assertEqual(updated.gcreatedby, receipt.gcreatedby)
        self.assertEqual(updated.ginvtafzilid, self.inv2.gtafzilid)
        self.assertEqual(updated.glastupdatedby, self.user.gucode)
        item.refresh_from_db(using='plus')
        self.assertEqual(item.quantityv1, 3)
        self.assertEqual(item.greceiptstockitemid, old_guid)
        self.assertEqual(item.receiptstockitemid, old_id)
        self.assertEqual(item.unitprice, 123)
        self.assertEqual(item.ginvid, self.inv2.ginvid)
        self.assertEqual(Tblreceiptstockitem.objects.using('plus').count(), 2)
        self.save(self.data(**{'product_id[]': [self.product2.gkalaid], 'quantity[]': ['5']}), receipt.greceiptstockid)
        self.assertEqual(Tblreceiptstockitem.objects.using('plus').count(), 1)
        self.assertEqual(Tblreceiptstockitem.objects.using('plus').get().gkalaid, self.product2.gkalaid)

    def test_create_failure_rolls_back_master_and_all_lines(self):
        with patch.object(Tblreceiptstockitem, 'save', side_effect=DatabaseError('failure')):
            with self.assertRaises(DatabaseError):
                self.save()
        self.assertFalse(Tblreceiptstock.objects.using('plus').exists())
        self.assertFalse(Tblreceiptstockitem.objects.using('plus').exists())

    def test_edit_failure_rolls_back_master_and_existing_lines(self):
        receipt = self.save()
        data = self.data(description='new', **{'product_id[]': [self.product.gkalaid, self.product2.gkalaid], 'quantity[]': ['9', '1']})
        with patch.object(Tblreceiptstockitem.objects, 'using') as manager:
            # Fail after the master update; atomic rollback must restore it.
            manager.side_effect = DatabaseError('failure')
            with self.assertRaises(DatabaseError):
                save_receipt(validate_payload(data), self.user, receipt.greceiptstockid)
        receipt.refresh_from_db(using='plus')
        self.assertEqual(receipt.receiptstockdesc, 'رسید آزمایشی')
        self.assertEqual(Tblreceiptstockitem.objects.using('plus').get().quantityv1, 2)

    def test_delete_removes_master_and_lines_atomically(self):
        receipt = self.save()
        with patch.object(Tblreceiptstock, 'delete', side_effect=DatabaseError('failure')):
            with self.assertRaises(DatabaseError):
                delete_receipt(receipt.greceiptstockid)
        self.assertEqual(Tblreceiptstockitem.objects.using('plus').count(), 1)
        delete_receipt(receipt.greceiptstockid)
        self.assertFalse(Tblreceiptstock.objects.using('plus').exists())
        self.assertFalse(Tblreceiptstockitem.objects.using('plus').exists())

    def test_posted_receipts_cannot_be_modified_or_deleted(self):
        receipt = self.save()
        for field, value in (('finalstatuscode', 2), ('gsanadid', str(uuid.uuid4())), ('financialyear', 1404)):
            setattr(receipt, field, value)
            receipt.save(using='plus')
            with self.assertRaises(ValidationError):
                delete_receipt(receipt.greceiptstockid)
            with self.assertRaises(ValidationError):
                self.save(pk=receipt.greceiptstockid)
            setattr(receipt, field, 1 if field == 'finalstatuscode' else 1405 if field == 'financialyear' else None)
        self.assertTrue(Tblreceiptstock.objects.using('plus').exists())

    @patch('core.views.TuaUser')
    def test_full_form_post_detail_edit_and_delete_confirmation(self, users):
        from django.test import override_settings
        users.objects.using.return_value.filter.return_value.first.return_value = self.user
        with override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies'):
            client = Client()
            session = client.session
            session['user_id'] = self.user.gucode
            session.save()
            client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
            create_url = reverse('core:receipt_create')
            response = client.get(create_url)
            self.assertEqual(response.status_code, 200)
            html = response.content.decode()
            self.assertIn('انتخاب انبار', html)
            self.assertIn('انبار اصلی', html)
            self.assertIn('شعبه مرکزی', html)
            self.assertIn('receipt-products-data', html)
            self.assertNotIn('name="unitprice"', html)
            bad = client.post(create_url, self.data(**{'quantity[]': ['0']}))
            self.assertEqual(bad.status_code, 400)
            self.assertFalse(Tblreceiptstock.objects.using('plus').exists())
            response = client.post(create_url, self.data())
            self.assertEqual(response.status_code, 302)
            receipt = Tblreceiptstock.objects.using('plus').get()
            self.assertIn(str(receipt.greceiptstockid).lower(), response['Location'])
            self.assertEqual(client.get(response['Location']).status_code, 200)
            self.assertEqual(client.get(reverse('core:receipt_list')).status_code, 200)
            edit_url = reverse('core:receipt_edit', kwargs={'pk': receipt.greceiptstockid})
            self.assertEqual(client.get(edit_url).status_code, 200)
            self.assertEqual(client.post(edit_url, self.data(**{'quantity[]': ['3']})).status_code, 302)
            delete_url = reverse('core:receipt_delete', kwargs={'pk': receipt.greceiptstockid})
            self.assertEqual(client.get(delete_url).status_code, 200)
            self.assertTrue(Tblreceiptstock.objects.using('plus').exists())
            self.assertEqual(client.post(delete_url).status_code, 302)
            self.assertFalse(Tblreceiptstock.objects.using('plus').exists())

    def test_fixed_system_fields_ignore_forged_post_values(self):
        receipt = self.save(self.data(financialyear='9999', finalstatuscode='2',
            gcreatedby=str(uuid.uuid4()), gmoinid=str(uuid.uuid4()),
            gcustid=str(uuid.uuid4()), receiptstockno='999', qualitycode='9'))
        self.assertEqual(receipt.financialyear, 1405)
        self.assertEqual(receipt.finalstatuscode, 1)
        self.assertEqual(receipt.receiptstockno, '1')
        self.assertEqual(receipt.gcreatedby, self.user.gucode)
        self.assertEqual(receipt.gcustid, CUSTOMER_ID)
        self.assertEqual(receipt.gmoinid, MOIN_ID)
        self.assertEqual(Tblreceiptstockitem.objects.using('plus').get().qualitycode, 1)

    def test_fixed_counterparty_label_comes_from_subdetailgroup(self):
        from .inventory import receipt_lookups
        group = self.insert(Tbldetailgroup, gdetailid=str(uuid.uuid4()))
        self.insert(Tblsubdetailgroup, gsubdetailid=CUSTOMER_ID,
                    gdetailid_id=group.gdetailid, subdetailname='طرف حساب ثابت رسید')
        self.assertEqual(receipt_lookups()['counterparty_name'], 'طرف حساب ثابت رسید')

    @patch('core.views.TuaUser')
    def test_csrf_required_for_inventory_writes(self, users):
        from django.test import override_settings
        users.objects.using.return_value.filter.return_value.first.return_value = self.user
        with override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies'):
            client = Client(enforce_csrf_checks=True)
            session = client.session
            session['user_id'] = self.user.gucode
            session.save()
            client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
            self.assertEqual(client.post(reverse('core:receipt_create'), self.data()).status_code, 403)
            self.assertFalse(Tblreceiptstock.objects.using('plus').exists())

    @patch('core.views.TuaUser')
    def test_uppercase_guid_routes_and_missing_record(self, users):
        from .inventory_views import ReceiptDetailView
        from django.urls import resolve
        receipt = self.save()
        route = reverse('core:receipt_detail', kwargs={'pk': receipt.greceiptstockid})
        self.assertIn(receipt.greceiptstockid.lower(), route)
        upper = route.replace(receipt.greceiptstockid.lower(), receipt.greceiptstockid.upper())
        self.assertEqual(str(resolve(upper).kwargs['pk']), receipt.greceiptstockid.lower())
        self.assertEqual(resolve(upper).func.view_class, ReceiptDetailView)
        users.objects.using.return_value.filter.return_value.first.return_value = self.user
        request = RequestFactory().get(reverse('core:receipt_detail', kwargs={'pk': uuid.uuid4()}))
        request.session = {'user_id': self.user.gucode}
        from django.http import Http404
        with self.assertRaises(Http404):
            ReceiptDetailView.as_view()(request, pk=uuid.uuid4())
