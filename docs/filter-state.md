# Filter state across navigation

`static/js/filter-state.js` is a shared, early-loaded enhancement for filtered pages. Applied state is stored as URL query strings in `sessionStorage` (tab-local), not as cached records or form POST data.

Covered pages:
- Customers: search, status, visitor, province/city, ordering.
- Customer account transactions: type and date ordering, separately for each customer URL.
- Sale requests, pre-factors and factors: search, status, region, visitor, branch and any query-based pagination.
- Income report: period, dates, visitor and pagination.
- Warehouse receipts: search and pagination.
- Warehouse stock: inventory, search and pagination.
- Payment dues: status and pagination.

Bare return links (header, bottom navigation, cancel) are decorated with the last query for that target path. Bare server redirects/bookmarks are restored on page load using a same-path replace navigation. Explicit query URLs always win, so applying new filters or using existing reset links does not resurrect previous selections. Customer search now updates and restores its `q` query parameter too.

Client-side `history.replaceState` changes are saved immediately, including clearing the last filter. Browser history entries are marked so returning to a known unfiltered history entry does not incorrectly apply newer filters. BFCache restores refresh the storage snapshot before writing, preserving filters for other pages. No cross-page record data is retained.

Each authenticated session gets an opaque storage namespace, rotated for user/role changes and logout/new login. Old namespaces are removed when the new authenticated page loads. This is a UI convenience only; all server-side visitor/record permissions remain authoritative. Storage failure leaves ordinary navigation working.

To opt another filterable template in, add `{% block filter_page %}1{% endblock %}`. Write applied filters to query parameters; the shared script handles navigation thereafter. POST/create/edit forms must not opt in. Explicit full reset can use `?filters_reset=1` or a link with `data-reset-filters`.

Validation: Django template/context tests plus `node --test tests/filter-state.test.cjs` cover restoration, explicit queries, clear/reset, independent paths, BFCache snapshots, session isolation, blocked/corrupt storage, same-origin link handling and GET vs POST. Manual real-browser/mobile verification remains pending.
