/* Tab-local filter history. Explicit query URLs always override remembered state. */
(() => {
    'use strict';
    const script = document.currentScript;
    const scope = script?.dataset.filterScope;
    if (!scope) return;
    const prefix = 'rahjou.filters.';
    const storageKey = prefix + scope;
    let store;
    try {
        // A new login/session must not inherit another user's saved filters.
        for (let i = sessionStorage.length - 1; i >= 0; i--) {
            const key = sessionStorage.key(i);
            if (key.startsWith(prefix) && key !== storageKey) sessionStorage.removeItem(key);
        }
        store = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
        if (!store || typeof store !== 'object' || Array.isArray(store)) store = {};
    } catch (_) { return; } // Disabled storage must never break normal navigation.
    const path = location.pathname;
    const filtered = script.dataset.filterPage === '1';
    const write = () => {
        try { sessionStorage.setItem(storageKey, JSON.stringify(store)); } catch (_) { /* quota/private mode */ }
    };
    const refresh = () => {
        try {
            const latest = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
            if (latest && typeof latest === 'object' && !Array.isArray(latest)) store = latest;
        } catch (_) { /* retain last readable state */ }
    };
    const remember = () => {
        if (!filtered) return;
        refresh();
        store[path] = {query: location.search};
        write();
    };
    const originalReplace = history.replaceState.bind(history);
    const marker = state => ({...(state && typeof state === 'object' ? state : {}), rahjouFilterPath: path});
    if (filtered) {
        const params = new URLSearchParams(location.search);
        if (params.has('filters_reset')) {
            delete store[path]; write();
            location.replace(path);
            return;
        }
        const saved = store[path];
        if (!location.search && history.state?.rahjouFilterPath !== path && (typeof saved?.query === 'string' && saved.query.startsWith('?'))) {
            location.replace(path + saved.query + location.hash);
            return;
        }
        originalReplace(marker(history.state), '', location.href);
        remember();
        // Customers/account transactions filter in place using replaceState.
        history.replaceState = (state, unused, url) => {
            originalReplace(marker(state), unused, url);
            remember();
        };
        window.addEventListener('pageshow', remember);
    }
    // Back buttons, bottom tabs and cancel links get the saved URL before navigation.
    document.addEventListener('click', event => {
        const link = event.target.closest?.('a[href]');
        if (!link || link.hasAttribute('download')) return;
        const url = new URL(link.href, location.href);
        if (url.origin !== location.origin) return;
        refresh();
        if (link.hasAttribute('data-reset-filters')) {
            delete store[url.pathname]; write();
            return;
        }
        if (url.search || url.hash) return;
        const saved = store[url.pathname];
        if ((typeof saved?.query === 'string' && saved.query.startsWith('?'))) {
            url.search = saved.query;
            link.href = url.href;
        }
    }, true);
    // Empty GET submissions are intentional defaults, not a request to restore.
    document.addEventListener('submit', event => {
        const form = event.target;
        if (!filtered || (form.method || '').toLowerCase() !== 'get') return;
        const target = new URL(form.action || location.href, location.href);
        if (target.origin !== location.origin || target.pathname !== path) return;
        const params = new URLSearchParams(new FormData(form));
        refresh();
        store[path] = {query: params.toString() ? '?' + params.toString() : ''};
        write();
    }, true);
})();
