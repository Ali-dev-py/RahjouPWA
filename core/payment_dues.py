"""Read-only installment schedule with recorded-factor visitor attribution."""
from decimal import Decimal
import jdatetime
from django.db.models import Q
from django.utils import timezone

from .income_report import guid, guid_batches, name_key, parse_date, visitor_directory, factor_attribution
from .visitor_assignment import is_visitor
from .models import Salefactormaster, Salefactorghest, Tblcustomer


def installment_row(installment, master, customer, today):
    amount, paid = Decimal(installment.ghestprice), Decimal(installment.payprice)
    remaining = max(Decimal(0), amount - paid)
    try:
        due = parse_date(installment.shghestdate)
        days = (due - today).days
        date = due.strftime('%Y/%m/%d')
    except (ValueError, TypeError):
        days, date = None, 'نامشخص'
    status = ('paid' if remaining == 0 else 'unknown' if days is None else
              'overdue' if days < 0 else 'soon' if days <= 7 else 'upcoming')
    labels = {'paid': 'تسویه‌شده', 'unknown': 'تاریخ نامعتبر', 'overdue': 'سررسید گذشته',
              'soon': 'سررسید نزدیک', 'upcoming': 'در انتظار سررسید'}
    return dict(id=str(installment.gsalefactorghestid), factor_id=guid(master.gsalefactormasterid),
                factor_no=master.salefactorno, installment_no=installment.ghestno,
                customer_name=customer, date=date, days=days, amount=amount, paid=paid,
                remaining=remaining, status=status, status_label=labels[status])


def payment_schedule(user):
    today = jdatetime.date.fromgregorian(date=timezone.localdate())
    restricted = is_visitor(user)
    masters = list(Salefactormaster.objects.using('plus').filter(
        Q(deleteddate__isnull=True) | Q(deleteddate='')))
    if restricted:
        visitors, integers, subdetails = visitor_directory()
        name = name_key(getattr(user, 'uname', ''))
        allowed = {key for key, row in visitors.items() if name and name_key(row['name']) == name}
        assignments = factor_attribution(masters, visitors, integers, subdetails)
        masters = [master for master in masters if assignments.get(guid(master.gsalefactormasterid)) in allowed]
    by_id = {guid(master.gsalefactormasterid): master for master in masters}
    customers = {}
    for chunk in guid_batches(master.gcustomerid for master in masters):
        for customer in Tblcustomer.objects.using('plus').filter(gcustomerid__in=chunk):
            customers[guid(customer.gcustomerid)] = customer.custname
    rows = []
    for chunk in guid_batches(by_id):
        for installment in Salefactorghest.objects.using('plus').filter(gsalefactormasterid__in=chunk):
            master = by_id.get(guid(installment.gsalefactormasterid))
            if master:
                rows.append(installment_row(installment, master,
                    customers.get(guid(master.gcustomerid), 'مشتری نامشخص'), today))
    rows.sort(key=lambda row: (row['days'] is None, row['days'] if row['days'] is not None else 0,
                               row['factor_no'], row['installment_no'], row['id']))
    return {'rows': rows, 'reminders': [row for row in rows if restricted and row['status'] == 'soon'],
            'remaining_total': sum((row['remaining'] for row in rows), Decimal(0))}
