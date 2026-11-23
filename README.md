# Rahjou PWA

A mobile-first, Persian/RTL Django application for customer management, sales
requests, pre-factors, sales factors, accounting summaries and warehouse operations.
The interface uses shared Bootstrap templates and a PWA manifest/service worker.

## Project structure

```text
manage.py
requirements.txt
config/                 Django settings, URL configuration, ASGI and WSGI
core/
  models.py             Existing SQL Server table/view mappings
  views.py              All HTTP views, including inventory and PWA delivery
  urls.py               Application routes
  income_report.py      Financial calculations and factor attribution
  inventory*.py         Receipt/order posting and stock balance services
  payment_dues.py        Payment schedule and visitor-only in-app reminders
  customer_geography.py Customer province/city labels
  visitor_assignment.py Authenticated visitor assignment and role context
  filter_state.py       Session-scoped filter persistence context
  transaction_styling.py Cancellation presentation helpers
  converters.py         URL converters
  templatetags/          Display helpers and inventory navigation permission
  templates/core/       Application screens
static/                 Styles, scripts, PWA assets, icons and logo
templates/              Base layout and shared partials
docs/                   Feature mappings, behavior and deployment caveats
```

All views live in `core/views.py`. `config/urls.py` imports the manifest and
service-worker delivery functions from there; `core/urls.py` maps business routes.
Business services remain separate from HTTP views to avoid mixing calculations
and database posting logic into request handlers.

## Setup

Use Python 3.11+ with Django 5.2.5. Install the dependencies in an isolated
virtual environment; SQL Server access also requires a compatible system ODBC
driver and the project's `mssql-django`/`pyodbc` dependencies.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python manage.py check
python manage.py migrate
python manage.py runserver
```

Review `config/settings.py` and configure the database aliases and deployment
settings for your environment before running database commands. Most domain
models are unmanaged mappings to existing tables: migrations do not provision
those SQL Server tables. Do not commit credentials or local environment files.

## Features

- Authenticated customer, sale-request, pre-factor and factor screens.
- Visitor assignment, role restrictions and customer/document scoping.
- Sales/commission reporting and print/PDF layouts.
- Customer transaction history, region and province/city information.
- Inventory receipts, outgoing stock orders and warehouse product balances.
- Factor payment schedules and visitor-only **in-app** reminders (not background Push).
- Per-tab filter persistence across navigation.

Feature-specific mappings and caveats are documented in `docs/`.

## PWA and deployment

- Manifest: `/manifest.webmanifest`, served from `static/manifest.json`.
- Root-scoped service worker: `/serviceworker.js`, served from `static/serviceworker.js`.
- Offline fallback: `/offline/`.
- Versioned cache: `CACHE_NAME` in `static/serviceworker.js`.

Use HTTPS in production. Preserve manifest/JavaScript MIME types and the
`Service-Worker-Allowed: /` header. Configure allowed hosts, trusted origins,
secrets, secure cookies and proxy handling in the deployment environment.

```bash
python manage.py check --deploy
python manage.py collectstatic --noinput
gunicorn config.wsgi:application
```

## Validation and repository cleanup

Test files were removed at the owner's request. Before removal, the consolidated
views and duplicate-model cleanup passed **165 Django tests and 13 JavaScript
tests**. Those results are historical; `manage.py test` no longer runs that suite.
Previous tests remain recoverable from Git history.

For ongoing changes, run Django system checks and JavaScript syntax checks, then
verify affected workflows in staging against SQL Server. Existing desktop-system
integration, triggers, transaction locks and mobile browser behavior require
live-environment validation. Runtime assets, domain services and mapping
documentation are retained; no database data was deleted by the cleanup.
