"""Read-only warehouse balances; no stock quantities are persisted here."""
from decimal import Decimal
from django.db.models import Sum
from .income_report import guid, guid_batches, financial_precision
from .inventory import FINANCIAL_YEAR
from .models import Sanadkala, Tblkala


@financial_precision
def warehouse_balances(inventory):
    totals = {}
    for row in (Sanadkala.objects.using('plus')
                .filter(ginvid__in=[guid(inventory.ginvid), guid(inventory.ginvid).upper()],
                        financialyear=FINANCIAL_YEAR)
                .order_by().values('gkalaid')
                .annotate(incoming=Sum('varede'), outgoing=Sum('sadere'))):
        key = guid(row['gkalaid'])
        if not key:
            continue
        # Merge case variants too when the test/deployment collation is case-sensitive.
        totals[key] = totals.get(key, Decimal(0)) + (row['incoming'] or Decimal(0)) - (row['outgoing'] or Decimal(0))
    products = {}
    for chunk in guid_batches(totals):
        for product in Tblkala.objects.using('plus').filter(gkalaid__in=chunk):
            products[guid(product.gkalaid)] = product
    rows = []
    for key, amount in totals.items():
        product = products.get(key)
        rows.append(dict(id=key, name=product.kalaname if product else 'کالای نامشخص',
                         code=product.kalano if product else '', unit=product.vahed1 if product else '',
                         amount=amount))
    return sorted(rows, key=lambda row: (row['name'] or '', row['code'] or '', row['id']))
