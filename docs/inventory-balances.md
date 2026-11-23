# Warehouse product balances

The inventory home now links to **موجودی کالا**, a read-only report at `/inventory/balances/`.

1. Select an existing `Tblinv` warehouse. No ledger query or cross-warehouse report is made before selection. Unknown or malformed warehouse GUIDs return a validation error, never an unfiltered query.
2. Filter `Sanadkala` by that warehouse's `GInvID` and financial year **1405**.
3. Group by `GKalaID` and calculate **SUM(Varede) - SUM(Sadere)**, treating NULL amounts as zero. Canonical GUID merging also handles case-sensitive databases.
4. Batch resolve product name, code and unit from `Tblkala`. Display the decimal quantity without rounding to whole units (up to eight decimal places). Zero and negative balances remain visible; missing catalog records have an explicit unknown-product label. Rows without a product GUID are omitted. Products with no ledger activity in this warehouse/year are not listed.

The report supports product-name/code search (including Persian/Arabic digits) and pagination, retaining filters in navigation links. It uses the existing non-visitor inventory gate, so visitors are denied server-side. Database failures use the existing safe inventory-unavailable response.

No stock, receipt or order data is changed, and no schema migration is required. Isolated SQLite tests cover sums, precision, NULLs, GUID case, warehouse/year isolation, zero/negative balances, missing catalog records, input validation, search, authentication/role restrictions and database errors. Live SQL Server and browser/mobile validation remain pending.

> Repository cleanup: test files were removed by request after the consolidated views passed 165 Django checks and 13 JavaScript tests. Testing descriptions above document historical validation; the test suite is no longer included.
