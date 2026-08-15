# Rahjou PWA

A conventional Django project for the Rahjou mobile-first accounting and sales interface. The original Google Stitch screens are Bootstrap 5 RTL Django templates connected through named routes. This phase contains presentation and PWA infrastructure only—not accounting, authentication, persistence, or PDF business logic.

## Screens and routes

| Screen | Route | Named URL | Template |
| --- | --- | --- | --- |
| Splash | `/` | `core:splash` | `core/splash.html` |
| Login | `/login/` | `core:login` | `core/login.html` |
| Dashboard | `/dashboard/` | `core:dashboard` | `core/dashboard.html` |
| Factor list | `/factors/` | `core:factor_list` | `core/factor_list.html` |
| Factor detail | `/factors/detail/` | `core:factor_detail` | `core/factor_detail.html` |
| New factor | `/factors/new/` | `core:factor_create` | `core/factor_create.html` |
| Offline fallback | `/offline/` | `core:offline` | `core/offline.html` |

All six source files originally used Tailwind and none used Bootstrap. They now extend `base.html`, use pinned Bootstrap 5.3 RTL assets, use Django `{% url %}` and `{% static %}` references, and share header/navigation partials. See [`docs/STATIC_HTML_AUDIT.md`](docs/STATIC_HTML_AUDIT.md) for the original audit.

## Project structure

The repository follows the default-style Django layout: one settings module and each app at the project root.

```text
.
├── manage.py
├── requirements.txt
├── config/
│   ├── __init__.py
│   ├── settings.py            # single environment-aware settings file
│   ├── urls.py
│   ├── views.py               # manifest and root service-worker delivery
│   ├── asgi.py
│   └── wsgi.py
├── core/                      # root-level Django app
│   ├── templates/core/
│   ├── __init__.py
│   ├── apps.py
│   ├── urls.py
│   ├── views.py               # TemplateView placeholders only
│   └── tests.py
├── templates/
│   ├── base.html
│   └── partials/
├── static/
│   ├── css/app.css
│   ├── js/app.js
│   ├── images/
│   ├── icons/
│   ├── screenshots/
│   ├── manifest.json
│   └── serviceworker.js
└── docs/design-reference/
```

There is deliberately no custom `models.py` or custom migration package in `core` yet.

## Local setup

Python 3.11+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate               # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python manage.py migrate                 # built-in Django tables only
python manage.py runserver
```

Open <http://127.0.0.1:8000/>. Every Django entry point uses the single `config.settings` module.

Run checks with:

```bash
python manage.py check
python manage.py test
```

Run Django's deployment checks against the same settings file by overriding its environment values:

```bash
DJANGO_DEBUG=False \
DJANGO_SECRET_KEY='a-long-random-secret-with-at-least-fifty-characters' \
DJANGO_ALLOWED_HOSTS='example.com' \
DJANGO_CSRF_TRUSTED_ORIGINS='https://example.com' \
python manage.py check --deploy
```

## Settings and environment

`config/settings.py` defaults to development mode. Production configuration uses environment variables rather than a second settings module:

- `DJANGO_DEBUG`
- `DJANGO_SECRET_KEY`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_SECURE_SSL_REDIRECT`
- `DJANGO_SECURE_HSTS_SECONDS`

See `.env.example` for example values. When `DJANGO_DEBUG=False`, secure cookies, HTTPS redirect, HSTS, proxy SSL handling, and WhiteNoise compressed manifest storage are enabled.

## PWA setup

- Canonical manifest: `/manifest.webmanifest`
- Static manifest copy: `/static/manifest.json`
- Root-scoped service worker: `/serviceworker.js`
- Static worker copy: `/static/serviceworker.js`
- Offline fallback: `/offline/`
- Network-first navigation and stale-while-revalidate static assets
- Installation left entirely to the browser's native PWA controls
- Cache version controlled by `CACHE_NAME` in `static/serviceworker.js`

The splash screen redirects to login after 2.5 seconds, with an HTML refresh fallback. Service workers require HTTPS outside localhost. In production, ensure the proxy/CDN preserves manifest and JavaScript MIME types, avoids aggressive caching for `/manifest.webmanifest` and `/serviceworker.js`, and preserves the worker's root scope header.

The current regular, maskable, and Apple touch icons are temporary exports from the supplied logo and should be replaced with final production artwork.

## Production outline

```bash
export DJANGO_SETTINGS_MODULE=config.settings
export DJANGO_DEBUG=False
export DJANGO_SECRET_KEY='a-long-random-production-secret'
export DJANGO_ALLOWED_HOSTS='example.com,www.example.com'
export DJANGO_CSRF_TRUSTED_ORIGINS='https://example.com,https://www.example.com'

python manage.py collectstatic --noinput
python manage.py migrate
gunicorn config.wsgi:application
```

## Intentionally stubbed

- No domain models or custom migrations
- No real authentication
- No saved forms or server-side form validation
- No database-backed filtering/search
- No PDF generation
- No real customer/profile screens
- Temporary PWA artwork

## Recommended next steps

1. Add customer, product, factor, line-item, tax, discount, and payment models.
2. Add forms/formsets and server-side validation.
3. Replace sample values with database query context.
4. Implement authentication and route authorization.
5. Add tested PDF output for factors and prefactors.
6. Add browser/integration tests and final PWA artwork.
