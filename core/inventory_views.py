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

    def get_context_data(self, **kwargs):
        from .inventory_orders import live_orders
        from .models import Tblorderstockitems
        context = super().get_context_data(**kwargs)
        page = Paginator(live_orders().order_by('-orderstockid'), 20).get_page(self.request.GET.get('page'))
        inventories = {guid(inv.ginvid): inv.invname for inv in Tblinv.objects.using('plus').all()}
        products = {guid(p.gkalaid): p.kalaname for p in Tblkala.objects.using('plus').all()}
        rows = list(Tblorderstockitems.objects.using('plus').filter(gorderstockid__in=variants(o.gorderstockid for o in page)))
        for order in page:
            order.inventory_name = inventories.get(guid(order.ginvid), '—')
            order.lines = [dict(name=products.get(guid(row.gkalaid), 'کالای نامشخص'), quantity=row.quantityv1)
                           for row in rows if guid(row.gorderstockid) == guid(order.gorderstockid)]
        context['order_page'] = page
        return context


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


class OrderFormView(ReceiptFormView):
    template_name = 'core/order_form.html'

    def form_context(self, request, receipt=None, data=None, errors=None):
        from .inventory_orders import approved_prefactors
        context = super().form_context(request, data=data, errors=errors)
        context['prefactors'] = approved_prefactors().order_by('-prefactormasterid')
        context['imported_source'] = request.session.get('inventory_order_forms', {}).get(self.form_id, {}).get('source', '')
        context['form_id'] = self.form_id
        return context

    def get(self, request):
        import uuid
        self.form_id = str(uuid.uuid4())
        forms = request.session.get('inventory_order_forms', {})
        forms[self.form_id] = {}
        request.session['inventory_order_forms'] = dict(list(forms.items())[-10:])
        return render(request, self.template_name, self.form_context(request))

    def post(self, request):
        from django.core import signing
        from .inventory_orders import prefactor_lines, save_order, line_signature
        self.form_id = request.POST.get('form_id', '')
        forms = request.session.get('inventory_order_forms', {})
        if self.form_id not in forms:
            raise PermissionDenied('فرم منقضی شده است؛ صفحه ثبت حواله را دوباره باز کنید.')
        state = forms[self.form_id]
        data = request.POST.copy()
        try:
            if data.get('action') == 'import':
                master, totals = prefactor_lines(data.get('prefactor', ''))
                state = {'source': str(master.gprefactormasterid),
                         'baseline': sorted((key, str(value.normalize())) for key, value in totals.items())}
                forms[self.form_id] = state
                request.session['inventory_order_forms'] = forms
                data.setlist('product_id[]', list(totals))
                data.setlist('quantity[]', [format(value, 'f') for value in totals.values()])
                return render(request, self.template_name, self.form_context(request, data=data))
            payload = validate_payload(data, require_branch=False, decimal_quantities=True)
            signature = line_signature(payload['lines'])
            baseline = [tuple(row) for row in state.get('baseline', [])]
            changed = bool(state.get('source')) and signature != baseline
            # Confirmation is signed over the exact submitted header and rows, not a client flag.
            confirmation = {'form': self.form_id, 'source': state.get('source'), 'lines': signature,
                            'date': payload['date'], 'inventory': guid(payload['inventory'].ginvid),
                            'description': payload['description']}
            if changed:
                try:
                    confirmed = signing.loads(data.get('confirmation', ''), salt='inventory-order', max_age=1800)
                except signing.BadSignature:
                    confirmed = None
                # JSON signing converts tuple rows to lists.
                import json
                if data.get('confirm_changes') != 'yes' or confirmed != json.loads(json.dumps(confirmation)):
                    context = self.form_context(request, data=data)
                    context['confirmation'] = signing.dumps(confirmation, salt='inventory-order')
                    return render(request, self.template_name, context, status=409)
            order = save_order(payload, request.plus_user, state.get('source'))
        except ValidationError as exc:
            return render(request, self.template_name, self.form_context(request, data=data, errors=exc.messages), status=400)
        forms.pop(self.form_id, None)
        request.session['inventory_order_forms'] = forms
        messages.success(request, f'حواله انبار شماره {order.orderstockno} با موفقیت ثبت شد.')
        return redirect('core:inventory_orders')


class InventoryBalancesView(InventoryAccessMixin, View):
    template_name = 'core/inventory_balances.html'

    def get(self, request):
        from .inventory import valid_guid, FINANCIAL_YEAR, DIGITS
        from .inventory_balances import warehouse_balances
        inventories = list(Tblinv.objects.using('plus').all().order_by('invname'))
        for inventory in inventories:
            inventory.option_id = guid(inventory.ginvid)
        raw = request.GET.get('inventory', '').strip()
        selected = valid_guid(raw)
        inventory = next((inv for inv in inventories if guid(inv.ginvid) == selected), None)
        query = request.GET.get('q', '').strip()
        context = dict(inventories=inventories, selected_inventory=selected, query=query,
                       financial_year=FINANCIAL_YEAR, inventory=inventory)
        if raw and not inventory:
            context['error'] = 'انبار انتخاب‌شده معتبر نیست.'
            return render(request, self.template_name, context, status=400)
        if inventory:
            from .income_report import name_key
            rows = warehouse_balances(inventory)
            if query:
                needle = name_key(query.translate(DIGITS)).lower()
                rows = [row for row in rows if needle in name_key(
                    f"{row['name']} {row['code']}".translate(DIGITS)).lower()]
            context['balance_page'] = Paginator(rows, 30).get_page(request.GET.get('page'))
        return render(request, self.template_name, context)
