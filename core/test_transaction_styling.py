from types import SimpleNamespace as Obj
from django.test import SimpleTestCase
from django.template.loader import render_to_string
from .transaction_styling import void_payment, cancelled_factor_status
from .models import Tblsanadrad, Tblsanad


class TransactionCancellationTests(SimpleTestCase):
    def test_payment_marker_in_row_parent_or_notes_with_unicode_variants(self):
        for row, parent in ((Obj(description='ابطال دریافت'), None),
                            (Obj(description='پرداخت معمولی'), Obj(sanaddesc='سند ابطال شده')),
                            (Obj(description='پرداخت معمولی'), Obj(sanadnote3='إبطال سند')),
                            (Obj(description='اِبْطال دریافت'), None),
                            (Obj(description='اب\u200cطال'), None)):
            self.assertTrue(void_payment(row, parent))
        self.assertFalse(void_payment(Obj(description='پرداخت'), Obj(sanadnote1=None)))
        self.assertFalse(void_payment(None, None))

    def test_model_scan_never_fetches_relations(self):
        row = Tblsanadrad(description='پرداخت', gsanadid_id='parent')
        parent = Tblsanad(sanaddesc='عادی', sanadnote2='ابطال')
        self.assertTrue(void_payment(row, parent))
        self.assertFalse(void_payment(row))

    def test_cancelled_factor_statuses_take_priority_over_success_words(self):
        for status in ('ابطال شده', 'ثبت ابطال شده', 'باطل شده', 'لغو شده', 'إبطال'):
            self.assertTrue(cancelled_factor_status(status))
        for status in ('ثبت شده', 'تایید شده', 'قطعی شده', None):
            self.assertFalse(cancelled_factor_status(status))

    def test_void_payment_title_badge_and_amount_are_red(self):
        tx = dict(kind='pay', is_cancelled=True, kind_label='سند ابطالی', amount=100,
                  description='شرح اصلی', is_initially_visible=True)
        html = render_to_string('core/customer_detail.html', {'customer_pk': 'C1', 'transactions': [tx]})
        self.assertIn('سند ابطالی', html)
        self.assertIn('bg-danger-subtle text-danger', html)
        self.assertIn('customer-tx-card--void', html)
        self.assertIn('شرح اصلی', html)
        self.assertNotIn('واریزی / بستانکار', html)

    def test_cancelled_payment_sidebar_does_not_match_green_rule(self):
        from django.conf import settings
        tx = dict(kind='pay', is_cancelled=True, kind_label='سند ابطالی', amount=100,
                  is_initially_visible=True)
        html = render_to_string('core/customer_detail.html', {'customer_pk': 'C1', 'transactions': [tx]})
        self.assertIn('.customer-tx-card--pay:not(.customer-tx-card--void)', html)
        self.assertNotIn('.customer-tx-card--pay {', html)
        css = (settings.BASE_DIR / 'static/css/app.css').read_text()
        self.assertIn('.page-customer-detail .customer-tx-card--pay.customer-tx-card--void { border-inline-start: 0.25rem solid #b42332 !important;', css)
