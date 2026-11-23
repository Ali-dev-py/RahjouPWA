# Factor commission dashboard

The home dashboard shows four compact current-month cards and recent Sale Requests.
The profit card links to `/income-report/`, the full period-selectable report.
This is a **read-only calculated commission report**, not a payroll,
receivables, payment, or actual cost-of-goods profit ledger. It writes no records
and does not use the database's pre-existing `Porsant`/`PorsantPrice` values.

## Confirmed business rules

- Gross = sum of `SaleFactorDetail.Quantity * UnitPrice`.
- Discount = sum of detail `Discount` + master `Discount`, matching the existing
  factor PDF. Do not also subtract `PercentDiscount` or allocated `Discount_Koli`
  fields: that would potentially double-count the same discount.
- Total discount percent = `discount / gross * 100` (do not round this before
  computing commission).
- Commission = `gross * max(0, 0.15 - discount / gross) / 3`, equivalently
  `max(0, gross * 0.15 - discount) / 3`.
- With no discount the share is exactly `gross * 0.05` (5%). This is continuous
  with the discounted formula; the previous 30% multiplier is no longer used.
- Use Decimal arithmetic, with sufficient precision for SQL decimal fields.
  Round commission per factor to a whole rial, half-up; totals sum the rounded
  per-factor commissions, so the list reconciles with the dashboard total.
- Tax and other costs do not enter the commission base. Zero/negative gross,
  negative total discount, and factors without detail lines receive zero
  commission and a visible warning. Discounts exceeding 15% also receive a warning.
- Unassigned, unknown, or ambiguous visitor assignments contribute sales to the
  all-factors overview, but receive no visitor commission.

Examples for gross 100,000,000 rials:

| Discount | Commission |
| --- | --- |
| 0 | 5,000,000 |
| 5,000,000 (5%) | 3,333,333 |
| 10,000,000 (10%) | 1,666,667 |
| 15,000,000 or more | 0 |

## Attribution and access

Resolve by factor's recorded `GVisitorID`, then `SaleFactorToVisitor` junction
(GUID or integer IDs), then recorded `GSubDetailID5`. Distinct multiple junction
visitors are ambiguous: do not arbitrarily allocate the entire commission or
count it more than once. Duplicate links for the same visitor are deduplicated.
Never fall back to the customer's current assignment for historical income.

For `TUA_user.uTitle = ویزیتور`, resolve allowed visitor identities using the
server-loaded user's `uName` and the visitor directory name (normalized whitespace
and Arabic/Persian letter forms). Ignore submitted visitor filters. No matching
identity means an empty report, not unrestricted access. Keep financial/customer
queries after authorization filtering. No other visitors' selectors or summary
rows are returned in the visitor's report.

Other account titles retain the application's existing unrestricted reporting
access and can select a visitor, all factors, or unassigned factors. Selections
use visitor GUIDs, not display names (different visitors may share names).

Existing customer-scoped detail/PDF permissions are unchanged. If historical
attribution grants access to an income row but the customer is no longer assigned
to that visitor, show the income breakdown without a forbidden detail link.

## Period and totals

- Default: current Jalali month through today. Presets: today and previous Jalali
  month; custom start/end accept Persian, Arabic, or ASCII digits.
- Filter by `SaleFactorDate`, including both boundaries. Existing database dates
  are expected in the application's zero-padded `YYYY/MM/DD` format.
- Exclude factors with a non-empty `DeletedDate`. Include all other factor
  statuses regardless of approval or collection; the UI explicitly says so.
- Invalid dates, reversed ranges, unknown selections, and database errors display
  an error rather than a misleading zero-income report.
- List pagination is 20 factors; totals and visitor summaries cover **all**
  authorized factors in the selected period.
- Query large GUID lists in batches (all case variants of one GUID stay together
  to prevent double-counting on case-insensitive SQL Server collations).

## Validation history

Before the repository cleanup, automated checks covered math, rounding, dates,
attribution, ambiguous links, access/forged filters, totals, database errors,
pagination and isolated SQLite ORM mappings. Test files were removed by request;
this is historical coverage, not a currently runnable suite. Live SQL Server and
mobile-browser validation is still recommended before deployment. No schema
migration is needed.
