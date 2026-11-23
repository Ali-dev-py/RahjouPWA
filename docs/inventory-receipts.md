# Inventory receipts

## Navigation and authorization

The new **انبار** bottom-nav item opens two sections: **رسید انبار** and
**حواله انبار**. Orders are a placeholder only; no order-stock writes exist yet.

Every inventory route requires a valid active `TuaUser` session and rejects
`uTitle = ویزیتور`, including direct GET and POST requests. The same normalized
role rule hides the inventory navigation item. Other titles retain access.
Create/edit/delete use CSRF-protected POSTs; GET deletion only displays confirmation.

## Existing SQL Server schema

The latest model definitions were added to `main` after the session branch began.
This branch incorporates that update, preserving the supplied OrderStock models
without implementing OrderStock operations. All inventory models are unmanaged;
**do not run migrations to create or replace these production tables**.

`ReceiptStockID` is mapped as the ORM `AutoField` primary key, while
`GReceiptStockID` is a unique business identifier. This corrects the supplied
model's conflicting non-primary `AutoField` / GUID-primary mapping so Django can
insert records using SQL Server's identity generator. It does **not** change the
actual SQL Server primary key or schema. Item IDs use their existing AutoField.
Identity sequences produce both numeric IDs; application code never explicitly
inserts identity values or enables IDENTITY_INSERT. Gaps after rollbacks/deletion
are normal SQL Server identity behavior.

`ReceiptStockNo` is a separate numeric text sequence for financial year **1405**.
Allocation includes deleted receipt numbers and compares numerically (`9 -> 10`,
not lexically). The sequence uses a transaction-owned SQL Server `sp_getapplock`
and `TABLOCKX, HOLDLOCK` so an empty-table max+1 allocation is protected as well.
This coordinates receipt writes in the app and blocks conflicting desktop table
writes during allocation. SQL Server permissions for these locks are required.

## Field mapping

Master:

- `ReceiptStockDate`: validated Jalali date, Persian/Arabic/ASCII digits accepted,
  stored as zero-padded ASCII `YYYY/MM/DD`. Default is today's local application date.
- `RegDate`, `CreatedDate`, initial `LastUpdatedDate`: today's local Jalali date.
  Unapproved `OkDate` is empty. `ReceiptStockTime`: current local `HH:MM` (column length 5).
- `FinancialYear = 1405`, actual schema field `ReciveKindCode = 1`.
- `GReceiptStockID`: a newly generated GUID; `GCreatedBy`: authenticated `TuaUser.GuCode`.
- `GInvID` and `GInvTafzilID`: selected `Tblinv.GInvID` and `Tblinv.GTafzilID`.
- `GBranchID`: selected `Branches.GBranchID`. Selects show names only.
- `GMoinID = 24D913F8-0153-45BF-9334-7372D7444E9A`.
- `GAccID = BAEEBC7D-D669-4056-9346-67A921BFD04A`.
- `GCustID = 42E87C6D-6AB6-4906-8881-F08125421653`.
- `FinalStatusCode = Finalstatus.Code = 1`; `GFinalStatusCode = Finalstatus.GCode`.
  Saving fails before any write if status 1 is absent.
- Short description is optional, maximum 500 characters.
- Required monetary fields default to zero and required booleans to false.
- `GCompanyID` on new master/items is inherited from inventory, falling back to branch.

`Tblsubdetailgroup` supplies the display label of the fixed counterparty by looking
up `GSubDetailID = GCustID`; this is read-only, not a new counterpart or account
creation operation. The fixed counterparty GUID is unchanged if no label is found.

Items:

- Identity `ReceiptStockItemID`; new unique `GReceiptStockItemID` per inserted item.
- `QualityCode = 1`; positive integer `Quantityv1`, default **1** in the product picker.
- Master `GReceiptStockID`, selected product `Tblkala.GKalaID`, selected `GInvID`.
- Required monetary/tax fields default to zero and `IsAward` to false.
- No unit-price or discount inputs: the receipt form is quantity-only.

## Validation, edits, and deletion

The mobile picker searches by product name/code, prevents duplicate selections,
and accepts Persian integer quantities. Server validation rejects invalid GUIDs,
unknown inventories/branches/products, duplicates, missing products, fractional,
zero/negative, or overflowing quantities, and mismatched payload arrays. Limits:
1–200 products; quantities at most 12 digits (Quantityv1's integer capacity).
Fixed system fields cannot be overridden by POST values.

Master and all items are saved in one `plus` transaction. Editing retains the
master number/GUID/identity and original creation fields, updates modification
metadata, synchronizes warehouse on every item, preserves IDs/GUIDs and non-form
metadata of retained products, inserts added products, and removes deleted ones.
Failure rolls back master and items together. Existing duplicate product rows
are rejected for editing rather than silently merging away their metadata.

For safety, only ordinary receipts in year 1405 with initial status 1 and without
linked accounting/bill/order/transfer/payment documents can be edited/deleted.
This is enforced again under lock, not just by hiding UI controls. Other receipts
remain read-only. Delete removes items first, then the master atomically; a failed
master deletion restores the items. No inventory totals are manually incremented:
this implementation writes only the requested receipt master/item tables and
leaves existing database stock/accounting logic in place.

## Verification / deployment

The automated suite includes isolated SQLite schemas generated from the supplied
unmanaged models: actual receipt creation, numeric sequences, field mappings,
edit/add/remove behavior, rollback on write/delete errors, protected records,
CSRF enforcement, GUID casing, and full form/detail/list/edit/delete request flows.
Role/nav tests cover all inventory routes and direct visitor POST attempts. The
SQL Server lock batch is tested with a mocked SQL Server cursor.

Live SQL Server checks (identity columns, existing triggers, account/warehouse
references, lock permissions, and integration with the desktop app) and a real
mobile-browser product-picker check remain necessary before production use.
No live production database was modified during development.

> Repository cleanup: test files were removed by request after the consolidated views passed 165 Django checks and 13 JavaScript tests. Testing descriptions above document historical validation; the test suite is no longer included.
