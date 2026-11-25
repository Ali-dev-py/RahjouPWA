/* Same A5 PDF export for all sales documents; print mode never calls save(). */
(() => {
    'use strict';
    window.addEventListener('load', async () => {
        const container = document.getElementById('invoice-pdf-container');
        if (!container) return;
        const printMode = new URLSearchParams(location.search).get('print') === '1';
        let status;
        if (printMode) {
            status = document.createElement('p');
            status.setAttribute('role', 'status');
            status.textContent = 'در حال آماده‌سازی PDF برای چاپ…';
            document.body.prepend(status);
        }
        try {
            if (!window.jspdf?.jsPDF || !window.html2canvas) throw new Error('PDF libraries unavailable');
            if (document.fonts?.ready) await document.fonts.ready;
            await Promise.all([...container.querySelectorAll('img')].map(image =>
                image.decode ? image.decode().catch(() => {}) : Promise.resolve()));
            const canvas = await window.html2canvas(container, {scale: 3, useCORS: true, backgroundColor: '#ffffff'});
            const pdf = new window.jspdf.jsPDF({orientation: 'portrait', unit: 'mm', format: 'a5', compress: true});
            const width = pdf.internal.pageSize.getWidth();
            const height = pdf.internal.pageSize.getHeight();
            const imageHeight = canvas.height * width / canvas.width;
            const image = canvas.toDataURL('image/jpeg', 0.98);
            pdf.addImage(image, 'JPEG', 0, 0, width, imageHeight);
            let remaining = imageHeight - height;
            while (remaining > 2) {
                pdf.addPage();
                pdf.addImage(image, 'JPEG', 0, remaining - imageHeight, width, imageHeight);
                remaining -= height;
            }
            if (!printMode) {
                pdf.save(container.dataset.filename || 'document.pdf');
                return;
            }
            // Print the generated PDF in the browser's PDF viewer, not the HTML page.
            const blobUrl = URL.createObjectURL(pdf.output('blob'));
            container.hidden = true;
            document.body.style.cssText = 'margin:0;max-width:none;width:100%;background:#f4f5f8;';
            status.style.cssText = 'font:14px Tahoma,sans-serif;padding:12px;margin:0;';
            status.textContent = 'PDF آماده است. اگر پنجره چاپ باز نشد، دکمه «چاپ PDF» را بزنید یا از آیکون چاپ نمایشگر استفاده کنید.';
            const toolbar = document.createElement('div');
            toolbar.style.cssText = 'padding:0 12px 12px;display:flex;gap:12px;align-items:center;';
            const button = document.createElement('button');
            button.type = 'button'; button.textContent = 'چاپ PDF';
            button.disabled = true;
            button.style.cssText = 'padding:10px 20px;cursor:pointer;font:14px Tahoma,sans-serif;';
            toolbar.append(button);
            const direct = document.createElement('a');
            direct.href = blobUrl; direct.target = '_blank'; direct.rel = 'noopener';
            direct.textContent = 'باز کردن PDF در نمایشگر مرورگر';
            toolbar.append(direct);
            document.body.append(toolbar);
            const frame = document.createElement('iframe');
            frame.title = 'PDF آماده چاپ';
            frame.style.cssText = 'display:block;width:100%;height:85vh;border:0;';
            const printPDF = () => {
                try { frame.contentWindow.focus(); frame.contentWindow.print(); }
                catch (_) { status.textContent = 'از آیکون چاپ داخل نمایشگر PDF استفاده کنید یا PDF را در نمایشگر مرورگر باز کنید.'; }
            };
            button.addEventListener('click', printPDF);
            frame.addEventListener('load', () => {
                button.disabled = false;
                window.setTimeout(printPDF, 500);
            }, {once: true});
            frame.src = blobUrl;
            document.body.append(frame);
            // Keep the blob alive while the viewer/print dialog may still need it.
            window.addEventListener('pagehide', event => { if (!event.persisted) URL.revokeObjectURL(blobUrl); });
        } catch (error) {
            if (!status) { status = document.createElement('p'); document.body.prepend(status); }
            status.setAttribute('role', 'alert');
            status.textContent = 'آماده‌سازی PDF انجام نشد. اتصال اینترنت را بررسی و صفحه را دوباره بارگذاری کنید.';
            console.error('Document PDF preparation failed', error);
        }
    });
})();
