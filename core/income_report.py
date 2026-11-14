"""Read-only, Decimal-based factor commission reporting (amounts are rials)."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP, localcontext
from functools import wraps
import re

import jdatetime
from django.db.models import Q

from .models import (Salefactormaster, Salefactordetail, Salefactortovisitor,
                     ViewAllvisitors, Tblcustomer)

ZERO = Decimal('0')


def guid(value):
    return str(value or '').strip().strip('{}').lower()


def name_key(value):
    return ' '.join(str(value or '').replace('ي', 'ی').replace('ك', 'ک').split())


def variants(values):
    return list({v for value in values if value for v in (guid(value), guid(value).upper())})


def batches(values, size=400):
    values = list(values)
    for i in range(0, len(values), size):
        yield values[i:i + size]


def guid_batches(values):
    # Keep case variants of a logical GUID in the SAME batch. On SQL Server's
    # case-insensitive collation, splitting them could count a detail twice.
    for chunk in batches(sorted({guid(v) for v in values if v}), size=200):
        yield variants(chunk)


def money(value):
    return Decimal(str(value or 0))


def financial_precision(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        # SQL quantity/price fields together can exceed Decimal's default 28 digits.
        with localcontext() as context:
            context.prec = 60
            return function(*args, **kwargs)
    return wrapped


@financial_precision
def commission(gross, discount):
    """Round per factor to the nearest rial, then sum those displayed amounts."""
    gross, discount = money(gross), money(discount)
    invalid = gross <= ZERO or discount < ZERO
    margin = gross * Decimal('0.15') - discount
    income = ZERO if invalid else max(ZERO, margin) * Decimal('0.30')
    return {
        'gross': gross, 'discount': discount, 'net': gross - discount,
        'discount_percent': discount / gross * 100 if gross > ZERO else ZERO,
        'effective_rate': income / gross * 100 if gross > ZERO else ZERO,
        'income': income.quantize(Decimal('1'), rounding=ROUND_HALF_UP),
        'over_margin': gross > ZERO and discount > gross * Decimal('0.15'),
        'invalid_amount': invalid,
    }


def parse_date(value):
    value = str(value or '').translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')).strip()
    if not re.fullmatch(r'\d{4}/\d{1,2}/\d{1,2}', value):
        raise ValueError('تاریخ را به صورت ۱۴۰۵/۰۸/۰۱ وارد کنید.')
    year, month, day = map(int, value.split('/'))
    try:
        return jdatetime.date(year, month, day)
    except ValueError:
        raise ValueError('تاریخ شمسی واردشده معتبر نیست.') from None


def report_period(params, today=None):
    today = today or jdatetime.date.today()
    period = params.get('period', 'month')
    if period == 'today':
        start = end = today
    elif period == 'last_month':
        end = today.replace(day=1) - jdatetime.timedelta(days=1)
        start = end.replace(day=1)
    elif period == 'custom':
        start, end = parse_date(params.get('start')), parse_date(params.get('end'))
    elif period == 'month':
        start, end = today.replace(day=1), today
    else:
        raise ValueError('بازه زمانی انتخاب‌شده معتبر نیست.')
    if start > end:
        raise ValueError('تاریخ شروع باید قبل از تاریخ پایان باشد.')
    return period, start.strftime('%Y/%m/%d'), end.strftime('%Y/%m/%d')


def visitor_directory():
    visitors = {}
    integers, subdetails = defaultdict(set), defaultdict(set)
    for v in ViewAllvisitors.objects.using('plus').all():
        key = guid(v.gvisitorid)
        if not key:
            continue
        visitors[key] = {'id': key, 'name': v.vizitorname or v.personname or 'بدون نام'}
        if v.visitorid is not None:
            integers[v.visitorid].add(key)
        if v.gsubdetailid:
            subdetails[guid(v.gsubdetailid)].add(key)
    return visitors, integers, subdetails


def factor_attribution(masters, visitors, integers, subdetails):
    """Use factor GUID, then recorded junction, then recorded tafzil5.

    Multiple distinct visitors are not arbitrarily given the entire commission.
    No fallback to the customer's current assignment is permitted here.
    """
    by_guid, by_int = defaultdict(set), defaultdict(set)
    links = []
    for chunk in guid_batches(m.gsalefactormasterid for m in masters):
        links.extend(Salefactortovisitor.objects.using('plus').filter(gsalefactorid__in=chunk))
    for chunk in batches(m.salefactormasterid for m in masters):
        links.extend(Salefactortovisitor.objects.using('plus').filter(salefactorid__in=chunk))
    for link in links:
        keys = {guid(link.gvisitorid)} if link.gvisitorid else integers.get(link.visitorid, set())
        # Retain unknown GUIDs: a broken assignment must not become a different visitor.
        by_guid[guid(link.gsalefactorid)].update(keys)
        by_int[link.salefactorid].update(keys)
    resolved = {}
    for master in masters:
        key = guid(master.gsalefactormasterid)
        if master.gvisitorid:
            candidates = {guid(master.gvisitorid)}
        else:
            candidates = by_guid.get(key) or by_int.get(master.salefactormasterid) or subdetails.get(guid(master.gsubdetailid5), set())
        resolved[key] = next(iter(candidates)) if len(candidates) == 1 and next(iter(candidates)) in visitors else ''
    return resolved


@financial_precision
def build_report(user, start, end, selected=''):
    visitors, integers, subdetails = visitor_directory()
    restricted = name_key(getattr(user, 'utitle', '')) == 'ویزیتور'
    allowed = {key for key, v in visitors.items()
               if name_key(getattr(user, 'uname', '')) and name_key(v['name']) == name_key(user.uname)} if restricted else set(visitors)
    selected = guid(selected)
    if not restricted and selected and selected != 'unassigned' and selected not in visitors:
        raise ValueError('ویزیتور انتخاب‌شده معتبر نیست.')
    masters = list(Salefactormaster.objects.using('plus').filter(
        Q(deleteddate__isnull=True) | Q(deleteddate=''),
        salefactordate__gte=start, salefactordate__lte=end,
    ).order_by('-salefactordate', '-salefactorno'))
    assignments = factor_attribution(masters, visitors, integers, subdetails)
    masters = [m for m in masters if (
        assignments.get(guid(m.gsalefactormasterid)) in allowed if restricted else
        (not selected or assignments.get(guid(m.gsalefactormasterid)) == ('' if selected == 'unassigned' else selected))
    )]
    # Load financial/customer data only for factors in the authorized report.
    totals = defaultdict(lambda: {'gross': ZERO, 'discount': ZERO, 'lines': 0})
    for chunk in guid_batches(m.gsalefactormasterid for m in masters):
        details = Salefactordetail.objects.using('plus').filter(gsalefactormasterid__in=chunk).values(
            'gsalefactormasterid', 'quantity', 'unitprice', 'discount')
        for detail in details:
            total = totals[guid(detail['gsalefactormasterid'])]
            total['gross'] += money(detail['quantity']) * money(detail['unitprice'])
            total['discount'] += money(detail['discount'])
            total['lines'] += 1
    customers = {}
    for chunk in guid_batches(m.gcustomerid for m in masters):
        for c in Tblcustomer.objects.using('plus').filter(gcustomerid__in=chunk):
            customers[guid(c.gcustomerid)] = c.custname
    rows, summaries = [], {}
    total = {key: ZERO for key in ('gross', 'discount', 'net', 'income')}
    unassigned_count = warning_count = 0
    for master in masters:
        key = guid(master.gsalefactormasterid)
        visitor = assignments.get(key, '')
        amounts = totals[key]
        row = commission(amounts['gross'], amounts['discount'] + money(master.discount))
        if not visitor:
            row['income'] = ZERO
            row['effective_rate'] = ZERO
            unassigned_count += 1
        row.update(id=master.gsalefactormasterid, number=master.salefactorno,
                   date=master.salefactordate, customer_name=customers.get(guid(master.gcustomerid)) or master.requestman or 'مشتری نامشخص',
                   customer_id=guid(master.gcustomerid), visitor_id=visitor,
                   visitor_name=visitors[visitor]['name'] if visitor else 'بدون ویزیتور / نیازمند بررسی',
                   missing_details=not amounts['lines'])
        warning_count += bool(row['over_margin'] or row['invalid_amount'] or row['missing_details'])
        rows.append(row)
        for field in total:
            total[field] += row[field]
        summary = summaries.setdefault(visitor, {'id': visitor, 'name': row['visitor_name'], 'count': 0, 'gross': ZERO, 'income': ZERO})
        summary['count'] += 1
        summary['gross'] += row['gross']
        summary['income'] += row['income']
    return {
        'report_rows': rows, 'report_total': total, 'factor_count': len(rows),
        'visitor_summaries': sorted(summaries.values(), key=lambda s: (-s['income'], s['name'])),
        'report_visitors': sorted(visitors.values(), key=lambda v: (v['name'], v['id'])) if not restricted else [],
        'is_visitor_report': restricted, 'selected_report_visitor': '' if restricted else selected,
        'unassigned_count': unassigned_count, 'warning_count': warning_count,
    }
