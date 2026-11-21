from decimal import Decimal
from types import SimpleNamespace as Obj
from datetime import date
from unittest.mock import patch
import jdatetime
from django.test import SimpleTestCase, RequestFactory
from django.template.loader import render_to_string
from django.db import DatabaseError
from django.urls import reverse

from .payment_dues import installment_row, payment_schedule
from .views import PaymentDuesView, DashboardView


class PaymentScheduleTests(SimpleTestCase):
    def setUp(self):
        self.today = jdatetime.date(1405, 8, 18)
        self.master = Obj(gsalefactormasterid='F1', salefactorno='100', gcustomerid='C1')

    def row(self, days, amount=100, paid=0):
        due = Obj(gsalefactorghestid='D1', ghestno=1, ghestprice=amount, payprice=paid,
                  shghestdate=(self.today + jdatetime.timedelta(days=days)).strftime('%Y/%m/%d'))
        return installment_row(due, self.master, 'مشتری', self.today)

    def test_reminder_window_boundaries_and_paid_balances(self):
        for days, status in ((-1, 'overdue'), (0, 'soon'), (1, 'soon'), (7, 'soon'), (8, 'upcoming')):
            with self.subTest(days=days):
                row = self.row(days, paid=30)
                self.assertEqual(row['status'], status)
                self.assertEqual(row['remaining'], 70)
                self.assertEqual(row['days'], days)
        self.assertEqual(self.row(7, paid=100)['status'], 'paid')
        self.assertEqual(self.row(7, paid=120)['remaining'], 0)

    def test_invalid_dates_do_not_generate_reminders_or_crash(self):
        for raw in (None, '', '1405/13/01', 'not a date'):
            installment = Obj(gsalefactorghestid='D', ghestno=1, ghestprice=100, payprice=0, shghestdate=raw)
            row = installment_row(installment, self.master, 'مشتری', self.today)
            self.assertEqual(row['status'], 'unknown')
            self.assertIsNone(row['days'])

    @patch('core.payment_dues.timezone.localdate', return_value=date(2026, 11, 9))
    @patch('core.payment_dues.factor_attribution')
    @patch('core.payment_dues.visitor_directory')
    @patch('core.payment_dues.Tblcustomer')
    @patch('core.payment_dues.Salefactorghest')
    @patch('core.payment_dues.Salefactormaster')
    def test_schedule_uses_recorded_visitor_and_never_notifies_other_roles(self, masters, dues, customers, directory, attribution, today):
        masters.objects.using.return_value.filter.return_value = [self.master,
            Obj(gsalefactormasterid='F2', salefactorno='200', gcustomerid='C2')]
        dues.objects.using.return_value.filter.return_value = [
            Obj(gsalefactorghestid='D1', ghestno=1, ghestprice=100, payprice=20, gsalefactormasterid='F1', shghestdate='1405/08/25'),
            Obj(gsalefactorghestid='D2', ghestno=1, ghestprice=200, payprice=0, gsalefactormasterid='F2', shghestdate='1405/08/25')]
        customers.objects.using.return_value.filter.return_value = [Obj(gcustomerid='C1', custname='مشتری اول')]
        directory.return_value = ({'v1': {'name': 'علی کریمی'}, 'v2': {'name': 'دیگر'}}, {}, {})
        attribution.return_value = {'f1': 'v1', 'f2': 'v2'}
        user = Obj(utitle='ويزيتور', uname=' علي كريمي ')
        schedule = payment_schedule(user)
        self.assertEqual([row['factor_id'] for row in schedule['rows']], ['f1'])
        self.assertEqual(len(schedule['reminders']), 1)
        self.assertEqual(schedule['remaining_total'], Decimal(80))
        user.uname = 'بدون تطبیق'
        schedule = payment_schedule(user)
        self.assertEqual(schedule['rows'], [])
        self.assertEqual(schedule['reminders'], [])
        user.utitle = 'مدیر'
        schedule = payment_schedule(user)
        self.assertEqual(len(schedule['rows']), 2)
        self.assertEqual(schedule['reminders'], [])
        self.assertEqual(schedule['remaining_total'], Decimal(280))

    def test_notification_template_is_visitor_only(self):
        row = self.row(7)
        for visitor, visible in ((True, True), (False, False)):
            html = render_to_string('partials/_payment_reminders.html',
                                    {'is_visitor_user': visitor, 'payment_reminders': [row]})
            self.assertEqual('notifications_active' in html, visible)

    def test_payment_page_requires_login(self):
        response = self.client.get(reverse('core:payment_dues'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('core:login'), response['Location'])

    @patch('core.payment_dues.payment_schedule')
    def test_page_paginates_filters_and_handles_database_failure(self, schedule):
        view = PaymentDuesView()
        view.request = RequestFactory().get('/', {'status': 'soon', 'page': 'invalid'})
        view.request.plus_user = Obj(utitle='مدیر')
        schedule.return_value = {'rows': [self.row(7) for _ in range(25)] + [self.row(10)],
                                 'reminders': [], 'remaining_total': 2600}
        context = view.get_context_data()
        self.assertEqual(context['due_page'].paginator.count, 25)
        self.assertEqual(len(context['due_page']), 20)
        self.assertIn('سررسید پرداخت فاکتورها', render_to_string('core/payment_dues.html', context))
        schedule.side_effect = DatabaseError('private database details')
        context = view.get_context_data()
        self.assertIn('payment_error', context)
        self.assertNotIn('private', context['payment_error'])


from unittest import skipUnless
from django.conf import settings
from django.db import connections
from django.test import TransactionTestCase
from . import test_inventory as inventory_fixtures
from .models import Tblcustomer, Salefactormaster, Salefactorghest, ViewAllvisitors, Salefactortovisitor


@skipUnless(settings.DATABASES['plus']['ENGINE'] == 'django.db.backends.sqlite3',
            'Isolated unmanaged schema requires SQLite test configuration')
class PaymentScheduleIntegrationTests(TransactionTestCase):
    databases = {'default', 'plus'}
    table_models = (Tblcustomer, Salefactormaster, Salefactorghest, ViewAllvisitors, Salefactortovisitor)

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

    @patch('core.payment_dues.timezone.localdate', return_value=date(2026, 11, 9))
    def test_real_guid_links_scope_and_deleted_or_orphan_exclusion(self, today):
        import uuid
        insert = inventory_fixtures.InventoryReceiptIntegrationTests.insert
        v1, v2, customer_id = [str(uuid.uuid4()).upper() for _ in range(3)]
        insert(ViewAllvisitors, gvisitorid=v1, vizitorname='علی کریمی', visitorid=1)
        insert(ViewAllvisitors, gvisitorid=v2, vizitorname='شخص دیگر', visitorid=2)
        insert(Tblcustomer, gcustomerid=customer_id, custname='مشتری آزمایشی')
        for number, visitor, deleted in (('1', v1, None), ('2', v2, None), ('3', v1, '1405/08/01')):
            factor_id = str(uuid.uuid4()).upper()
            insert(Salefactormaster, gsalefactormasterid=factor_id, salefactorno=number,
                   gcustomerid=customer_id, gvisitorid=visitor, deleteddate=deleted)
            insert(Salefactorghest, gsalefactorghestid=str(uuid.uuid4()), gsalefactormasterid=factor_id.lower(),
                   ghestprice=1000, payprice=250, shghestdate='۱۴۰۵/۰۸/۲۵', ghestno=1)
        insert(Salefactorghest, gsalefactorghestid=str(uuid.uuid4()), gsalefactormasterid=str(uuid.uuid4()),
               ghestprice=9000, payprice=0, shghestdate='1405/08/25')
        schedule = payment_schedule(Obj(utitle='ویزیتور', uname='علی کریمی'))
        self.assertEqual([row['factor_no'] for row in schedule['rows']], ['1'])
        self.assertEqual(schedule['remaining_total'], 750)
        self.assertEqual(len(schedule['reminders']), 1)
        self.assertEqual(schedule['rows'][0]['customer_name'], 'مشتری آزمایشی')
        schedule = payment_schedule(Obj(utitle='مدیر'))
        self.assertEqual({row['factor_no'] for row in schedule['rows']}, {'1', '2'})
        self.assertEqual(schedule['remaining_total'], 1500)
        self.assertEqual(schedule['reminders'], [])
