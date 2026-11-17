/* Quantity-only product picker. All fields are validated again on the server. */
(() => {
    'use strict';
    const form = document.getElementById('receipt-form');
    if (!form) return;
    const isOrder = form.dataset.order === 'true';
    const saveButton = form.querySelector('button[type="submit"]:not([name="action"])');
    const saveText = isOrder ? 'ذخیره حواله' : 'ذخیره رسید';
    const key = value => String(value || '').trim().replace(/[{}]/g, '').toLowerCase();
    const normalize = value => String(value || '').replace(/ي/g, 'ی').replace(/ك/g, 'ک').toLowerCase();
    const ascii = value => String(value).replace(/[۰-۹٠-٩]/g, digit => String('۰۱۲۳۴۵۶۷۸۹'.includes(digit) ? '۰۱۲۳۴۵۶۷۸۹'.indexOf(digit) : '٠١٢٣٤٥٦٧٨٩'.indexOf(digit)));
    const products = JSON.parse(document.getElementById('receipt-products-data').textContent);
    const catalog = new Map(products.map(product => [key(product.id), product]));
    const selected = new Set();
    const container = document.getElementById('receipt-items');
    const empty = document.getElementById('receipt-items-empty');
    const dialog = document.getElementById('receipt-product-dialog');
    const search = document.getElementById('receipt-product-search');
    const results = document.getElementById('receipt-product-results');
    const hint = document.getElementById('receipt-product-hint');
    const error = document.getElementById('receipt-client-error');
    const element = (tag, className, text) => {
        const node = document.createElement(tag);
        node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    };
    function addProduct(product, amount = '1') {
        const id = key(product.id);
        if (selected.has(id)) return;
        selected.add(id);
        const card = element('div', 'card border-0 p-3 receipt-item');
        card.append(element('strong', 'small text-break mb-1', product.name));
        card.append(element('small', 'text-secondary mb-2', `کد: ${product.code || '—'} · ${product.unit || ''}`));
        const fields = element('div', 'd-flex align-items-end gap-2');
        const label = element('label', 'small flex-grow-1', 'تعداد');
        const quantity = element('input', 'form-control mt-1');
        // Text + numeric keyboard permits Persian digits; never silently truncate fractions.
        quantity.type = 'text'; quantity.inputMode = isOrder ? 'decimal' : 'numeric'; quantity.name = 'quantity[]';
        quantity.maxLength = isOrder ? 21 : 12; quantity.required = true;
        const normalized = ascii(amount);
        quantity.value = /^\d+\.0+$/.test(normalized) ? normalized.split('.')[0] : amount;
        label.append(quantity);
        const hidden = element('input', '');
        hidden.type = 'hidden'; hidden.name = 'product_id[]'; hidden.value = product.id;
        const remove = element('button', 'btn btn-outline-danger', 'حذف');
        remove.type = 'button'; remove.setAttribute('aria-label', `حذف ${product.name}`);
        remove.addEventListener('click', () => {
            selected.delete(id); card.remove(); empty.hidden = selected.size > 0;
        });
        fields.append(label, remove, hidden); card.append(fields); container.append(card);
        empty.hidden = true;
    }
    function renderResults() {
        results.replaceChildren();
        const query = normalize(ascii(search.value.trim()));
        const matches = products.filter(product => !selected.has(key(product.id)) &&
            normalize(ascii(`${product.name} ${product.code}`)).includes(query));
        matches.slice(0, 40).forEach(product => {
            const button = element('button', 'btn btn-light text-end p-3', `${product.name} · ${product.code || '—'}`);
            button.type = 'button';
            button.addEventListener('click', () => { addProduct(product); dialog.close(); });
            results.append(button);
        });
        hint.textContent = matches.length ? `${matches.length} کالا؛ حداکثر ۴۰ نتیجه نمایش داده می‌شود.` : 'کالایی یافت نشد یا قبلاً انتخاب شده است.';
    }
    JSON.parse(document.getElementById('receipt-initial-data').textContent).forEach(line => {
        const product = catalog.get(key(line.id));
        // Preserve invalid/removed selections so a rejected POST never silently drops a row.
        addProduct(product || {id: line.id, name: 'کالای نامعتبر؛ حذف و دوباره انتخاب کنید', code: '', unit: ''}, line.quantity);
    });
    document.getElementById('receipt-add-product').addEventListener('click', () => {
        search.value = ''; renderResults(); dialog.showModal(); search.focus();
    });
    document.getElementById('receipt-picker-close').addEventListener('click', () => dialog.close());
    search.addEventListener('input', renderResults);
    let submitting = false;
    form.addEventListener('submit', event => {
        if (event.submitter?.value === 'import') return;
        if (submitting) { event.preventDefault(); return; }
        error.hidden = true;
        const quantities = [...form.querySelectorAll('[name="quantity[]"]')];
        const invalid = quantities.find(input => !(isOrder ? /^\d{1,12}(?:\.\d{1,8})?$/ : /^\d{1,12}$/).test(ascii(input.value.trim())) || Number(ascii(input.value.trim())) <= 0);
        if (!quantities.length || quantities.length > 200 || invalid) {
            event.preventDefault();
            error.textContent = 'بین ۱ تا ۲۰۰ کالا با تعداد معتبر و مثبت انتخاب کنید.';
            error.hidden = false; if (invalid) invalid.focus();
        } else {
            submitting = true;
            const save = saveButton;
            save.disabled = true; save.textContent = 'در حال ذخیره…';
        }
    });
    window.addEventListener('pageshow', () => {
        submitting = false;
        const save = saveButton;
        save.disabled = false; save.textContent = saveText;
    });
})();
