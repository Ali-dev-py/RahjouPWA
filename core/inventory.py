"""Inventory receipt validation and atomic writes to existing SQL Server tables."""
from contextlib import contextmanager
from decimal import Decimal
import re
import uuid

import jdatetime
from django.core.exceptions import ValidationError
from django.db import connections, transaction
from django.utils import timezone

from .income_report import guid, name_key, parse_date, variants
from .models import (Tblreceiptstock, Tblreceiptstockitem, Finalstatus, Tblinv,
                     Tblsubdetailgroup, Branches, Tblkala)

FINANCIAL_YEAR = 1405
MOIN_ID = '24D913F8-0153-45BF-9334-7372D7444E9A'
ACCOUNT_ID = 'BAEEBC7D-D669-4056-9346-67A921BFD04A'
CUSTOMER_ID = '42E87C6D-6AB6-4906-8881-F08125421653'
DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def inventory_allowed(user):
    return bool(user and getattr(user, 'gucode', None)) and name_key(getattr(user, 'utitle', '')) != 'ویزیتور'


def today_string():
    return jdatetime.date.fromgregorian(date=timezone.localdate()).strftime('%Y/%m/%d')


def live_receipts():
    from django.db.models import Q
    return Tblreceiptstock.objects.using('plus').filter(
        Q(deleteddate__isnull=True) | Q(deleteddate=''))


def can_modify(receipt):
    return (receipt.finalstatuscode == 1 and receipt.financialyear == FINANCIAL_YEAR
            and receipt.recivekindcode == 1 and not receipt.createbysaleretfactor
            and not any(getattr(receipt, field, None) for field in (
                'gsanadid', 'gbillstockid', 'gorderstockid', 'gtransferid', 'gpardakhtid')))


def require_mutable(receipt):
    if not can_modify(receipt):
        raise ValidationError('فقط رسید عادی سال ۱۴۰۵ با وضعیت اولیه و بدون سند مرتبط قابل ویرایش یا حذف است.')


def valid_guid(value):
    try:
        return str(uuid.UUID(str(value or '').strip().strip('{}')))
    except (ValueError, AttributeError):
        return ''


def validate_payload(data, *, require_branch=True, decimal_quantities=False):
    errors = []
    try:
        receipt_date = parse_date(data.get('receipt_date')).strftime('%Y/%m/%d')
    except ValueError as exc:
        receipt_date = str(data.get('receipt_date', ''))
        errors.append(str(exc))
    description = data.get('description', '').strip()
    if len(description) > 500:
        errors.append('توضیحات نباید بیشتر از ۵۰۰ نویسه باشد.')
    inv_id, branch_id = valid_guid(data.get('inventory')), valid_guid(data.get('branch'))
    inv = Tblinv.objects.using('plus').filter(ginvid__in=variants([inv_id])).first() if inv_id else None
    branch = Branches.objects.using('plus').filter(gbranchid__in=variants([branch_id])).first() if branch_id else None
    if not inv:
        errors.append('انتخاب انبار معتبر الزامی است.')
    if require_branch and not branch:
        errors.append('انتخاب شعبه معتبر الزامی است.')
    status = Finalstatus.objects.using('plus').filter(code=1).first()
    if not status:
        errors.append('وضعیت اولیه با کد ۱ در FinalStatus تعریف نشده است.')
    ids, quantities = data.getlist('product_id[]'), data.getlist('quantity[]')
    lines = []
    if not ids or len(ids) != len(quantities) or len(ids) > 200:
        errors.append('بین ۱ تا ۲۰۰ ردیف کالای معتبر وارد کنید.')
    else:
        products = {guid(p.gkalaid): p for p in Tblkala.objects.using('plus').filter(
            gkalaid__in=variants(valid_guid(value) for value in ids))}
        seen = set()
        for product_id, raw_quantity in zip(ids, quantities):
            key = guid(product_id)
            quantity = str(raw_quantity).translate(DIGITS).strip()
            if key not in products or key in seen:
                errors.append('کالای انتخاب‌شده نامعتبر یا تکراری است.')
                continue
            seen.add(key)
            # Receipts remain integer-only; orders also support imported decimal quantities.
            pattern = r'[0-9]{1,12}(?:\.[0-9]{1,8})?' if decimal_quantities else r'[0-9]{1,12}'
            if not re.fullmatch(pattern, quantity) or Decimal(quantity) <= 0:
                errors.append('تعداد باید مثبت، حداکثر ۱۲ رقم صحیح و ۸ رقم اعشار باشد.' if decimal_quantities
                              else 'تعداد هر کالا باید عدد صحیح مثبت و حداکثر ۱۲ رقمی باشد.')
                continue
            lines.append((products[key], Decimal(quantity) if decimal_quantities else int(quantity)))
    if errors:
        raise ValidationError(errors)
    return dict(date=receipt_date, description=description, inventory=inv,
                branch=branch, status=status, lines=lines)


@contextmanager
def receipt_write_lock():
    """Serialize max+1 receipt numbers, including an empty table, on SQL Server.

    Identity columns generate ReceiptStockID/ReceiptStockItemID themselves;
    never use IDENTITY_INSERT or application-side max+1 for identity fields.
    The app lock covers all receipt create/edit/delete operations in this app.
    """
    with transaction.atomic(using='plus'):
        connection = connections['plus']
        if connection.vendor in ('microsoft', 'mssql'):
            with connection.cursor() as cursor:
                cursor.execute("""SET NOCOUNT ON;
                    DECLARE @result int;
                    EXEC @result = sys.sp_getapplock
                        @Resource = N'Rahjou.Inventory.ReceiptStock',
                        @LockMode = 'Exclusive', @LockOwner = 'Transaction', @LockTimeout = 10000;
                    SELECT @result;""")
                if cursor.fetchone()[0] < 0:
                    raise ValidationError('رسید دیگری در حال ثبت است؛ لطفاً دوباره تلاش کنید.')
                # Also coordinate max+1 with desktop writers not taking the app lock.
                cursor.execute('SELECT TOP (1) [ReceiptStockID] FROM [tblReceiptStock] WITH (TABLOCKX, HOLDLOCK)')
                cursor.fetchone()
        yield


def next_receipt_number():
    numbers = Tblreceiptstock.objects.using('plus').filter(financialyear=FINANCIAL_YEAR).values_list('receiptstockno', flat=True)
    maximum = 0
    for number in numbers:
        text = str(number or '').translate(DIGITS).strip()
        if text.isascii() and text.isdecimal():
            maximum = max(maximum, int(text))
    if maximum >= 9999999999:
        raise ValidationError('شماره رسید از سقف مجاز عبور کرده است.')
    return str(maximum + 1)


def save_receipt(payload, user, receipt_guid=None):
    with receipt_write_lock():
        now = today_string()
        inv, branch, status = payload['inventory'], payload['branch'], payload['status']
        if receipt_guid:
            receipt = live_receipts().select_for_update().get(greceiptstockid__in=variants([receipt_guid]))
            require_mutable(receipt)
            receipt.lastupdateddate = now
            receipt.glastupdatedby = str(user.gucode)
        else:
            receipt = Tblreceiptstock(
                greceiptstockid=str(uuid.uuid4()).upper(), receiptstockno=next_receipt_number(),
                regdate=now, createddate=now, lastupdateddate=now, okdate='',
                financialyear=FINANCIAL_YEAR, recivekindcode=1,
                gcreatedby=str(user.gucode), receiptstocktime=timezone.localtime().strftime('%H:%M'),
                pishpardakhtprice=0, discountpercent=0, isoffline=False,
                createbysaleretfactor=False, sethandiothercost=False,
                gmoinid=MOIN_ID, gaccid=ACCOUNT_ID, gcustid=CUSTOMER_ID,
                gcompanyid=inv.gcompanyid or branch.gcompanyid,
            )
        receipt.receiptstockdate = payload['date']
        receipt.receiptstockdesc = payload['description']
        receipt.ginvid = inv.ginvid
        receipt.ginvtafzilid = inv.gtafzilid
        receipt.gbranchid = branch.gbranchid
        receipt.finalstatuscode = status.code
        receipt.gfinalstatuscode = status.gcode
        receipt.save(using='plus')
        # Preserve identity/GUID and all non-form metadata of retained products.
        old_items = list(Tblreceiptstockitem.objects.using('plus').filter(
            greceiptstockid__in=variants([receipt.greceiptstockid])).select_for_update())
        by_product = {}
        for item in old_items:
            key = guid(item.gkalaid)
            if key in by_product:
                raise ValidationError('این رسید دارای ردیف‌های تکراری است؛ ویرایش آن باید در نرم‌افزار اصلی انجام شود.')
            by_product[key] = item
        retained = set()
        for product, quantity in payload['lines']:
            item = by_product.get(guid(product.gkalaid))
            if item:
                item.quantityv1 = quantity
                item.ginvid = inv.ginvid
                item.qualitycode = 1
                item.save(using='plus', update_fields=['quantityv1', 'ginvid', 'qualitycode'])
            else:
                item = Tblreceiptstockitem.objects.using('plus').create(
                    qualitycode=1, quantityv1=quantity,
                    greceiptstockitemid=str(uuid.uuid4()).upper(),
                    greceiptstockid=receipt.greceiptstockid, gkalaid=product.gkalaid,
                    ginvid=inv.ginvid, gcompanyid=receipt.gcompanyid,
                    vatprice=0, discountpercent=0, discountprice=0, isaward=False,
                    currencyprice=0, vatoption=0, rowcostpercent=0, rowcostprice=0, othercostvat=0,
                )
            retained.add(item.receiptstockitemid)
        for item in old_items:
            if item.receiptstockitemid not in retained:
                item.delete(using='plus')
        return receipt


def delete_receipt(receipt_guid):
    with receipt_write_lock():
        receipt = live_receipts().select_for_update().get(greceiptstockid__in=variants([receipt_guid]))
        require_mutable(receipt)
        Tblreceiptstockitem.objects.using('plus').filter(
            greceiptstockid__in=variants([receipt.greceiptstockid])).delete()
        receipt.delete(using='plus')


def receipt_lookups():
    """Read the fixed counterparty's display label from tblSubDetailGroup only."""
    counterparty = Tblsubdetailgroup.objects.using('plus').filter(gsubdetailid__in=variants([CUSTOMER_ID])).first()
    return {
        'inventories': list(Tblinv.objects.using('plus').all().order_by('invname')),
        'branches': list(Branches.objects.using('plus').all().order_by('branchname')),
        'counterparty_name': counterparty.subdetailname if counterparty else '',
    }
