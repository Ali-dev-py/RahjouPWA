from decimal import Decimal
from types import SimpleNamespace as Obj
from unittest import skipUnless
from unittest.mock import patch
import uuid

from django.conf import settings
from django.db import connections, DatabaseError
from django.test import TransactionTestCase, RequestFactory, SimpleTestCase
from django.urls import reverse

from . import test_inventory as fixtures
from .models import Tblinv, Tblkala, Sanadkala
from .inventory_balances import warehouse_balances
from .inventory_views import InventoryBalancesView


@skipUnless(settings.DATABASES['plus']['ENGINE'] == 'django.db.backends.sqlite3', 'Requires isolated SQLite schema')
class WarehouseBalanceTests(TransactionTestCase):
    databases = {'default', 'plus'}
    table_models = (Tblinv, Tblkala, Sanadkala)

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

    def setUp(self):
        for model in reversed(self.table_models):
            model.objects.using('plus').all().delete()
        self.insert = fixtures.InventoryReceiptIntegrationTests.insert
        self.inv = self.insert(Tblinv, ginvid=str(uuid.uuid4()).upper(), invname='انبار اصلی')
        self.product = self.insert(Tblkala, gkalaid=str(uuid.uuid4()).upper(), kalaname='کالای نمونه', kalano='123', vahed1='عدد')

    def ledger(self, **overrides):
        data = dict(gsanadkalaid=str(uuid.uuid4()), ginvid=self.inv.ginvid,
                    gkalaid=self.product.gkalaid, financialyear=1405, varede=0, sadere=0)
        data.update(overrides)
        return self.insert(Sanadkala, **data)

    def test_sums_multiple_rows_and_preserves_decimal_quantities(self):
        self.ledger(varede=Decimal('10.12345678'), sadere=None)
        self.ledger(varede=None, sadere=Decimal('2.10000000'), gkalaid=self.product.gkalaid.lower())
        self.ledger(varede=None, sadere=None)
        rows = warehouse_balances(self.inv)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['amount'], Decimal('8.02345678'))
        self.assertEqual(rows[0]['name'], 'کالای نمونه')
        self.assertEqual(rows[0]['unit'], 'عدد')
        self.assertEqual(Sanadkala.objects.using('plus').count(), 3)

    def test_only_selected_inventory_and_year_and_no_unused_products(self):
        self.ledger(varede=3)
        self.ledger(varede=100, financialyear=1404)
        self.ledger(varede=200, ginvid=str(uuid.uuid4()))
        self.insert(Tblkala, gkalaid=str(uuid.uuid4()), kalaname='بدون گردش', kalano='456')
        rows = warehouse_balances(self.inv)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['amount'], 3)

    def test_zero_negative_and_missing_catalog_product_remain_visible(self):
        self.ledger(varede=2, sadere=2)
        missing = str(uuid.uuid4())
        self.ledger(sadere=Decimal('1.5'), gkalaid=missing)
        self.ledger(varede=100, gkalaid=None)
        rows = {row['id']: row for row in warehouse_balances(self.inv)}
        self.assertEqual(rows[self.product.gkalaid.lower()]['amount'], 0)
        self.assertEqual(rows[missing]['amount'], Decimal('-1.5'))
        self.assertEqual(rows[missing]['name'], 'کالای نامشخص')
        self.assertEqual(len(rows), 2)

    def test_view_requires_selection_validates_and_searches(self):
        self.ledger(varede=5)
        factory = RequestFactory()
        view = InventoryBalancesView()
        response = view.get(factory.get('/'))
        self.assertContains(response, 'برای مشاهده موجودی، انبار را انتخاب کنید.')
        for value in ('not-a-guid', str(uuid.uuid4())):
            with self.subTest(value=value):
                response = view.get(factory.get('/', {'inventory': value}))
                self.assertEqual(response.status_code, 400)
        response = view.get(factory.get('/', {'inventory': self.inv.ginvid, 'q': '۱۲۳', 'page': 'bad'}))
        self.assertContains(response, 'کالای نمونه')
        response = view.get(factory.get('/', {'inventory': self.inv.ginvid, 'q': 'یافت نشد'}))
        self.assertNotContains(response, 'کالای نمونه')


class WarehouseBalanceAccessTests(SimpleTestCase):
    @patch('core.views.TuaUser')
    def test_database_failure_returns_safe_503(self, users):
        users.objects.using.return_value.filter.return_value.first.return_value = Obj(gucode='USER', utitle='مدیر')
        request = RequestFactory().get(reverse('core:inventory_balances'))
        request.session = {'user_id': 'USER'}
        with patch('core.inventory_views.Tblinv') as inventories:
            inventories.objects.using.side_effect = DatabaseError('private error')
            with self.assertLogs('core.inventory_views', level='ERROR'):
                response = InventoryBalancesView.as_view()(request)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private error', response.content.decode())
