# Factor payment schedule

## Data and scope

Read-only integration with unmanaged `Salefactorghest` in `core/models.py`:

- Join `GSaleFactorMasterID` to `Salefactormaster.GSaleFactorMasterID` using normalized GUIDs and batched case variants.
- Display `GhestNo`, `ShGhestDate` (Jalali due date), `GhestPrice`, `PayPrice`, and outstanding `max(0, GhestPrice - PayPrice)` in integer rials. Each installment record stays separate; records are not collapsed into an assumed single payment per factor.
- Exclude deleted factor masters and orphan installments. Invalid/missing dates remain visible with an explicit label but never trigger a reminder. Fully paid or overpaid installments have zero outstanding balance and never trigger reminders.
- Visitor-role users see only factors assigned to their normalized authenticated name, using the existing recorded-factor attribution resolver (master visitor, recorded factor junction, recorded tafzil). Customer's current visitor is not a fallback. Unmatched/ambiguous factor attribution does not grant visitor access.
- Other roles see all non-deleted factors, without visitor reminder notifications. All endpoints require login. Schedule cards deliberately have no factor-detail link because existing factor-detail permissions can differ from recorded-factor attribution.

## UI and reminders

Dashboard shows only the visitor reminder warning and a link to `/payment-dues/`; no installment cards or balance summary are shown below the warning. The full schedule page retains the installment cards and total outstanding, is paginated and supports unpaid, nearby, overdue, paid, invalid-date and all statuses.

**Notifications in this implementation are in-app reminders, not Web Push.** They appear when the visitor opens the dashboard or payment schedule. Unpaid installments in the inclusive window today through seven days ahead qualify; overdue, paid and invalid-date records do not. The catch-up window avoids losing reminders when a visitor did not open the app exactly seven days before the due date. Admin/non-visitor roles can inspect the same upcoming schedule but receive no reminder panel.

No background scheduler, device notification permission or push subscription is configured, and no delivery while the app is closed is claimed. Background Web Push would require a separately configured subscription store, VAPID keys, push handler and scheduled sender with role/ownership revalidation.

## Validation

Tests cover the seven-day boundaries, partial/full/overpayment, invalid dates, role scope, no notifications for other roles, pagination and safe database errors. An isolated unmanaged-schema integration test verifies GUID joins, persisted amounts, names, deleted/orphan exclusion and visitor/admin behavior. Live SQL Server and mobile/browser validation remain pending. No database writes or new schema are introduced.
