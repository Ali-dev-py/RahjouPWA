"""Outgoing stock documents: validate provenance and stock before atomic posting."""
from contextlib import contextmanager
from decimal import Decimal
import uuid

from django.core.exceptions import ValidationError
from django.db import connections, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .inventory import FINANCIAL_YEAR, DIGITS, today_string, valid_guid
from .income_report import guid, variants, guid_batches
from .models import (Tblorderstock, Tblorderstockitems, Sanadkala,
                     Prefactormaster, Prefactordetail, Tblcustomer, Branches)


def approved_prefactors():
    """Only status-4 pre-factors without a linked stock order are eligible."""
    return (Prefactormaster.objects.using('plus')
            .filter(Q(isbuy=False) | Q(isbuy__isnull=True))
            .filter(prefactorstatuscode=4, gorderstockid__isnull=True))


def prefactor_choices():
    """Label eligible pre-factors with their actual customer, using batched lookups."""
    prefactors = list(approved_prefactors().order_by('-prefactormasterid'))
    customers = {}
    for chunk in guid_batches(p.gcustomerid for p in prefactors):
        for customer in Tblcustomer.objects.using('plus').filter(gcustomerid__in=chunk):
            customers[guid(customer.gcustomerid)] = customer.custname
    for prefactor in prefactors:
        prefactor.customer_name = customers.get(guid(prefactor.gcustomerid)) or 'مشتری نامشخص'
    return prefactors


def prefactor_lines(prefactor_id):
    prefactor_id = valid_guid(prefactor_id)
    if not prefactor_id:
        raise ValidationError('انتخاب پیش‌فاکتور معتبر الزامی است.')
    master = approved_prefactors().filter(gprefactormasterid__in=variants([prefactor_id])).first()
    if not master:
        raise ValidationError('پیش‌فاکتور انتخاب‌شده باید وضعیت ۴ داشته باشد و بدون حواله انبار مرتبط باشد.')
    totals = {}
    for line in Prefactordetail.objects.using('plus').filter(gprefactormasterid__in=variants([master.gprefactormasterid])):
        key = guid(line.gkalaid)
        if not key or line.quantity is None or line.quantity <= 0:
            raise ValidationError('پیش‌فاکتور دارای ردیف کالای نامعتبر است.')
        totals[key] = totals.get(key, Decimal(0)) + line.quantity
    if not totals or len(totals) > 200:
        raise ValidationError('پیش‌فاکتور باید بین ۱ تا ۲۰۰ کالای معتبر داشته باشد.')
    return master, totals


def line_signature(lines):
    return sorted((guid(product.gkalaid), str(Decimal(quantity).normalize())) for product, quantity in lines)


@contextmanager
def order_write_lock():
    with transaction.atomic(using='plus'):
        connection = connections['plus']
        if connection.vendor in ('microsoft', 'mssql'):
            with connection.cursor() as cursor:
                # Table locks also serialize desktop writers and protect absent stock rows.
                # Lock ledger first, then order numbering, consistently for every posting.
                cursor.execute('SELECT TOP (1) [SanadKalaID] FROM [SanadKala] WITH (TABLOCKX, HOLDLOCK)')
                cursor.fetchone()
                cursor.execute('SELECT TOP (1) [OrderStockID] FROM [tblOrderStock] WITH (TABLOCKX, HOLDLOCK)')
                cursor.fetchone()
        yield


def prefactor_item_description(master):
    branch = (Branches.objects.using('plus').filter(gbranchid__in=variants([master.gbranchid])).first()
              if master.gbranchid else None)
    customer = (Tblcustomer.objects.using('plus').filter(gcustomerid__in=variants([master.gcustomerid])).first()
                if master.gcustomerid else None)
    number = str(master.prefactorno or '').translate(DIGITS).strip().zfill(6)
    customer_name = customer.custname if customer and customer.custname else 'مشتری نامشخص'
    return (f"پیش فاکتور فروش شماره {number} مورخ {master.prefactordate} "
            f"شعبه {branch.branchname if branch else 'نامشخص'} بنام جناب آقای {customer_name}")


def save_order(payload, user, source=None):
    with order_write_lock():
        item_description = None
        if source:
            # Approval can have changed since import; reject revoked approval.
            master, _ = prefactor_lines(source)
            item_description = prefactor_item_description(master)
        inv = payload['inventory']
        for product, quantity in payload['lines']:
            rows = Sanadkala.objects.using('plus').filter(
                financialyear=FINANCIAL_YEAR, ginvid__in=variants([inv.ginvid]),
                gkalaid__in=variants([product.gkalaid]))
            sums = rows.aggregate(incoming=Sum('varede'), outgoing=Sum('sadere'))
            balance = (sums['incoming'] or Decimal(0)) - (sums['outgoing'] or Decimal(0))
            if balance < quantity:
                raise ValidationError(f'موجودی «{product.kalaname}» کافی نیست. موجودی: {balance}')
        maximum = 0
        for number in Tblorderstock.objects.using('plus').filter(financialyear=FINANCIAL_YEAR).values_list('orderstockno', flat=True):
            text = str(number or '').translate(DIGITS).strip()
            if text.isascii() and text.isdecimal():
                maximum = max(maximum, int(text))
        if maximum >= 9999999999:
            raise ValidationError('شماره حواله از سقف مجاز عبور کرده است.')
        now = today_string()
        order = Tblorderstock.objects.using('plus').create(
            gorderstockid=str(uuid.uuid4()).upper(), orderstockno=str(maximum + 1).zfill(6),
            financialyear=FINANCIAL_YEAR, orderstockdate=payload['date'],
            orderstockdesc=payload['description'], regdate=now, createddate=now,
            lastupdateddate=now, okdate='', gcreatedby=str(user.gucode),
            ginvid=inv.ginvid, ginvtafzil4id=inv.gtafzilid, gcompanyid=inv.gcompanyid,
            finalstatuscode=payload['status'].code, gfinalstatuscode=payload['status'].gcode,
            orderkindcode=1, createbysalefactor=False, isoffline=False,
            orderstocktime=timezone.localtime().strftime('%H:%M'), gprefactorid=source or None)
        for index, (product, quantity) in enumerate(payload['lines'], 1):
            Tblorderstockitems.objects.using('plus').create(
                gorderstockitemsid=str(uuid.uuid4()).upper(), gorderstockid=order.gorderstockid,
                gkalaid=product.gkalaid, ginvid=inv.ginvid, quantityv1=quantity,
                qualitycode=1, isaward=False, vatprice=0, rowid=index, kaladescript=item_description,
                discountprice=0, discountpercent=0, gcompanyid=inv.gcompanyid)
            Sanadkala.objects.using('plus').create(
                gsanadkalaid=str(uuid.uuid4()).upper(), operdate=now, operkind=134,
                varede=0, sadere=quantity, financialyear=FINANCIAL_YEAR,
                ginvid=inv.ginvid, gkalaid=product.gkalaid, goperid=order.gorderstockid,
                operno=order.orderstockno, gcompanyid=inv.gcompanyid,
                othercost=0, isaward=False, totalprice=0, directpaymentprice=0,
                overheadprice=0, sumkalaprice=0, sumotherprice=0)
        return order


def live_orders():
    return Tblorderstock.objects.using('plus').filter(Q(deleteddate__isnull=True) | Q(deleteddate=''))
