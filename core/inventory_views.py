import logging

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import TemplateView

from .views import PlusLoginRequiredMixin
from .inventory import (inventory_allowed, today_string, live_receipts, can_modify,
                        validate_payload, save_receipt, delete_receipt, receipt_lookups)
from .income_report import guid, variants
from .models import Tblreceiptstock, Tblreceiptstockitem, Tblinv, Branches, Tblkala, Finalstatus

logger = logging.getLogger(__name__)


def inventory_unavailable(request):
    return render(request, 'core/inventory_unavailable.html', status=503)


class InventoryRoleGate:
    def dispatch(self, request, *args, **kwargs):
        if not inventory_allowed(getattr(request, 'plus_user', None)):
            raise PermissionDenied('دسترسی به عملیات انبار مجاز نیست.')
        try:
            return super().dispatch(request, *args, **kwargs)
        except DatabaseError:
            logger.exception('Inventory database operation failed')
            return inventory_unavailable(request)


class InventoryAccessMixin(PlusLoginRequiredMixin, InventoryRoleGate):
    pass


class InventoryHomeView(InventoryAccessMixin, TemplateView):
    template_name = 'core/inventory_home.html'


class InventoryOrdersView(InventoryAccessMixin, TemplateView):
    template_name = 'core/inventory_orders.html'


def receipt_context(receipt):
    rows = list(Tblreceiptstockitem.objects.using('plus').filter(
        greceiptstockid__in=variants([receipt.greceiptstockid])).order_by('receiptstockitemid'))
    products = {guid(p.gkalaid): p for p in Tblkala.objects.using('plus').filter(
        gkalaid__in=variants(row.gkalaid for row in rows))} if rows else {}
    items = []
    for row in rows:
        product = products.get(guid(row.gkalaid))
        items.append({'id': row.gkalaid, 'name': product.kalaname if product else 'کالای نامشخص',
                      'code': product.kalano if product else '', 'quantity': row.quantityv1,
                      'unit': product.vahed1 if product else ''})
    inv = Tblinv.objects.using('plus').filter(ginvid__in=variants([receipt.ginvid])).first() if receipt.ginvid else None
    branch = Branches.objects.using('plus').filter(gbranchid__in=variants([receipt.gbranchid])).first() if receipt.gbranchid else None
    status = Finalstatus.objects.using('plus').filter(code=receipt.finalstatuscode).first()
    return dict(receipt=receipt, items=items, inventory_name=inv.invname if inv else '—',
                branch_name=branch.branchname if branch else '—', status_name=status.title if status else 'نامشخص',
                can_modify=can_modify(receipt))


class ReceiptListView(InventoryAccessMixin, TemplateView):
    template_name = 'core/receipt_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            query = self.request.GET.get('q', '').strip()
            receipts = live_receipts()
            if query:
                # Receipt numbers are text, never compare GUID columns to empty strings.
                receipts = receipts.filter(receiptstockno__icontains=query.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')))
            page = Paginator(receipts.order_by('-receiptstockid'), 20).get_page(self.request.GET.get('page'))
            inv_names = {guid(i.ginvid): i.invname for i in Tblinv.objects.using('plus').all()}
            branch_names = {guid(b.gbranchid): b.branchname for b in Branches.objects.using('plus').all()}
            statuses = {s.code: s.title for s in Finalstatus.objects.using('plus').all()}
            for receipt in page:
                receipt.inventory_name = inv_names.get(guid(receipt.ginvid), '—')
                receipt.branch_name = branch_names.get(guid(receipt.gbranchid), '—')
                receipt.status_name = statuses.get(receipt.finalstatuscode, 'نامشخص')
            context.update(receipt_page=page, query=query)
        except DatabaseError:
            logger.exception('Could not load inventory receipt list')
            context['inventory_error'] = 'دریافت رسیدها ممکن نشد؛ لطفاً دوباره تلاش کنید.'
        return context


class ReceiptDetailView(InventoryAccessMixin, TemplateView):
    template_name = 'core/receipt_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        receipt = get_object_or_404(live_receipts(), greceiptstockid__in=variants([self.kwargs['pk']]))
        context.update(receipt_context(receipt))
        return context


class ReceiptFormView(InventoryAccessMixin, View):
    template_name = 'core/receipt_form.html'

    def get_receipt(self, pk):
        if pk is None:
            return None
        receipt = get_object_or_404(live_receipts(), greceiptstockid__in=variants([pk]))
        if not can_modify(receipt):
            raise PermissionDenied('این رسید تأیید شده یا سند مرتبط دارد و قابل ویرایش نیست.')
        return receipt

    def form_context(self, request, receipt=None, data=None, errors=None):
        context = receipt_lookups()
        products = list(Tblkala.objects.using('plus').values('gkalaid', 'kalaname', 'kalano', 'vahed1').order_by('kalaname'))
        context['products'] = [dict(id=str(p['gkalaid']), name=p['kalaname'], code=p['kalano'] or '', unit=p['vahed1'] or '') for p in products]
        if data is not None:
            values = dict(receipt_date=data.get('receipt_date', ''), inventory=data.get('inventory', ''),
                          branch=data.get('branch', ''), description=data.get('description', ''))
            lines = [dict(id=key, quantity=qty) for key, qty in zip(data.getlist('product_id[]'), data.getlist('quantity[]'))]
        elif receipt:
            values = dict(receipt_date=receipt.receiptstockdate, inventory=receipt.ginvid,
                          branch=receipt.gbranchid, description=receipt.receiptstockdesc or '')
            lines = [dict(id=str(item.gkalaid), quantity=str(item.quantityv1)) for item in Tblreceiptstockitem.objects.using('plus').filter(
                greceiptstockid__in=variants([receipt.greceiptstockid])).order_by('receiptstockitemid')]
        else:
            values = dict(receipt_date=today_string(), inventory='', branch='', description='')
            lines = []
        # Canonical selection values avoid brace/case mismatches in the template.
        for field in ('inventory', 'branch'):
            values[field] = guid(values[field])
        for inv in context['inventories']:
            inv.option_id = guid(inv.ginvid)
        for branch in context['branches']:
            branch.option_id = guid(branch.gbranchid)
        context.update(current_user=request.plus_user, receipt=receipt, values=values,
                       initial_lines=lines, errors=errors or [], financial_year=1405)
        return context

    def get(self, request, pk=None):
        receipt = self.get_receipt(pk)
        return render(request, self.template_name, self.form_context(request, receipt))

    def post(self, request, pk=None):
        receipt = self.get_receipt(pk)
        try:
            payload = validate_payload(request.POST)
            receipt = save_receipt(payload, request.plus_user, str(pk) if pk else None)
        except ValidationError as exc:
            return render(request, self.template_name, self.form_context(request, receipt, request.POST, exc.messages), status=400)
        except Tblreceiptstock.DoesNotExist:
            raise Http404('رسید یافت نشد.')
        except DatabaseError:
            logger.exception('Could not save inventory receipt')
            return inventory_unavailable(request)
        messages.success(request, 'رسید انبار با موفقیت ذخیره شد.')
        return redirect('core:receipt_detail', pk=receipt.greceiptstockid)


class ReceiptDeleteView(InventoryAccessMixin, View):
    template_name = 'core/receipt_delete.html'

    def context(self, pk):
        receipt = get_object_or_404(live_receipts(), greceiptstockid__in=variants([pk]))
        if not can_modify(receipt):
            raise PermissionDenied('این رسید قابل حذف نیست.')
        return dict(receipt=receipt)

    def get(self, request, pk):
        return render(request, self.template_name, self.context(pk))

    def post(self, request, pk):
        context = self.context(pk)
        try:
            delete_receipt(str(pk))
        except ValidationError as exc:
            context['errors'] = exc.messages
            return render(request, self.template_name, context, status=400)
        except Tblreceiptstock.DoesNotExist:
            raise Http404('رسید یافت نشد.')
        except DatabaseError:
            logger.exception('Could not delete inventory receipt')
            context['errors'] = ['حذف رسید انجام نشد. لطفاً دوباره تلاش کنید.']
            return render(request, self.template_name, context, status=503)
        messages.success(request, 'رسید انبار و ردیف‌های آن حذف شد.')
        return redirect('core:receipt_list')
