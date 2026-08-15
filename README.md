# Rahjou PWA

A production-oriented Django scaffold for the Rahjou mobile-first accounting and sales interface. The original Google Stitch HTML screens have been converted to Bootstrap 5 RTL Django templates and connected through named routes. This phase intentionally contains **presentation and PWA infrastructure only**—not accounting, authentication, persistence, or PDF business logic.

## What was converted

| Original screen | Django route | Named URL | Template |
| --- | --- | --- | --- |
| Splash | `/` | `core:splash` | `core/splash.html` |
| Login | `/login/` | `core:login` | `core/login.html` |
| Dashboard | `/dashboard/` | `core:dashboard` | `core/dashboard.html` |
| Factor list | `/factors/` | `core:factor_list` | `core/factor_list.html` |
| Factor detail | `/factors/detail/` | `core:factor_detail` | `core/factor_detail.html` |
| New factor | `/factors/new/` | `core:factor_create` | `core/factor_create.html` |
| Offline fallback | `/offline/` | `core:offline` | `core/offline.html` |

All six source files used Tailwind from a CDN and none used Bootstrap. They now extend one `base.html`, use pinned Bootstrap 5.3 RTL CDN assets, use `{% url %}`/`{% static %}` references, and share app-header/bottom-navigation partials. The detailed pre-change inventory is in [`docs/STATIC_HTML_AUDIT.md`](docs/STATIC_HTML_AUDIT.md).

## Project structure

```text
.
├── manage.py
├── requirements.txt
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   ├── views.py              # root-scoped service-worker delivery
│   ├── asgi.py
│   └── wsgi.py
├── apps/
│   └── core/
│       ├── templates/core/   # one child template per screen
│       ├── apps.py
│       ├── urls.py
│       ├── views.py          # TemplateView placeholders only
│       └── tests.py
├── templates/
│   ├── base.html
│   └── partials/
├── static/
│   ├── css/app.css
│   ├── js/app.js
│   ├── images/logo.png
│   ├── icons/
│   ├── manifest.json
│   └── serviceworker.js
└── docs/design-reference/    # original screenshots and design tokens
```

There is deliberately no custom `models.py` or custom migration package in `apps/core` yet.

## Local setup

Python 3.11+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate               # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python manage.py migrate                 # Django's built-in auth/admin/session tables only
python manage.py runserver
```

Open <http://127.0.0.1:8000/>. The default `manage.py` settings module is `config.settings.development`.

Run smoke tests and deployment checks with:

```bash
python manage.py test
python manage.py check
DJANGO_SECRET_KEY='test-only-secret' \
DJANGO_ALLOWED_HOSTS='example.com' \
python manage.py check --deploy --settings=config.settings.production
```

## PWA setup

- Canonical manifest: `/manifest.webmanifest` with `application/manifest+json`
- Source/static manifest copy: `/static/manifest.json`
- Root-scoped service worker: `/serviceworker.js`
- Static copy of worker: `/static/serviceworker.js`
- Offline fallback: `/offline/`
- Strategy: network-first for navigation; stale-while-revalidate for local static files and approved CDN assets.
- Installation is left entirely to the browser's native PWA controls.
- Cache version: `CACHE_NAME` in `static/serviceworker.js`; bump it when the app shell changes.

Dedicated Django views serve the canonical manifest and service worker at the origin root. The worker response sets `Content-Type: application/javascript` and `Service-Worker-Allowed: /`, allowing it to control all application routes. WhiteNoise handles collected static assets in production.

The current regular, maskable, and Apple touch icons are temporary exports built from the supplied logo. Replace them with final, safe-zone-tested install icons before release and update the manifest if filenames or purposes change.

Service workers require HTTPS outside localhost. Browser-native install promotion is controlled by the browser and requires a top-level browsing context. In production, confirm at the reverse proxy/CDN that manifest and JavaScript MIME types are preserved, `/manifest.webmanifest` and `/serviceworker.js` are not aggressively cached, and the worker's root scope header is not stripped.

## Production outline

Copy `.env.example` values into your platform's secret/environment configuration—do not commit a real `.env` file.

```bash
export DJANGO_SETTINGS_MODULE=config.settings.production
export DJANGO_SECRET_KEY='a-long-random-secret'
export DJANGO_ALLOWED_HOSTS='example.com,www.example.com'
export DJANGO_CSRF_TRUSTED_ORIGINS='https://example.com,https://www.example.com'

python manage.py collectstatic --noinput
python manage.py migrate
gunicorn config.wsgi:application
```

`production.py` enables HTTPS redirect, secure cookies, HSTS, proxy SSL handling, and compressed manifest static storage. Review those values for the target platform before first deployment.

## Intentionally stubbed

- **Models/database domain:** no customers, products, factors, line items, payments, or ledger models.
- **Authentication:** the login form only links to the dashboard; it does not authenticate.
- **Forms/validation:** editor inputs are presentational and do not save.
- **Filtering/search:** controls render but do not query data.
- **PDF:** download/issue controls are visible placeholders only.
- **Customers/profile:** bottom-nav destinations remain marked dashboard placeholders because no matching source screens were supplied.
- **Icons:** install icons need final production artwork and platform testing.

## Recommended next steps

1. Define customer, product/service, factor, line-item, tax, discount, and payment models with domain constraints.
2. Add Django forms/formsets and server-side validation for factor creation.
3. Replace sample template values with view/query context and pagination/filtering.
4. Implement Django authentication, authorization, password reset, and protected routes.
5. Add transactional factor numbering and draft/final state transitions.
6. Add tested PDF rendering for factors and prefactors, then connect the existing buttons.
7. Add real customer/profile screens, API boundaries if needed, and integration/browser tests.
8. Replace placeholder install icons, run Lighthouse PWA/accessibility checks, and establish a cache-version release process.
