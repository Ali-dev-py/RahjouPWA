# Static HTML audit

This audit was completed before the Django conversion.

## HTML inventory

| Original file | UI technology found | Bootstrap found? |
| --- | --- | --- |
| `splash_screen/code.html` | Tailwind CSS CDN plus inline Tailwind config/CSS | No |
| `login_screen/code.html` | Tailwind CSS CDN plus inline Tailwind config/CSS | No |
| `dashboard/code.html` | Tailwind CSS CDN plus inline Tailwind config/CSS | No |
| `factors_list/code.html` | Tailwind CSS CDN plus inline Tailwind config/CSS | No |
| `factor_details/code.html` | Tailwind CSS CDN plus inline Tailwind config/CSS | No |
| `create_factor/code.html` | Tailwind CSS CDN plus inline Tailwind config/CSS | No |

No local Bootstrap distribution was present. All six pages were therefore normalized to pinned Bootstrap 5.3 RTL CDN assets. Theme-specific presentation was moved to `static/css/app.css` rather than kept inline.

## Other findings

- All pages duplicated document, typography, theme, and responsive boilerplate.
- Runtime image references pointed to Google-hosted assets.
- Internal navigation used `#` placeholders rather than application routes.
- There was no Django, Python dependency, URL, test, or PWA structure.
- The designs are mobile-first, right-to-left, Persian-language screens.
- The supplied design system specifies professional blue (`#1a56db`), yellow (`#fdc003`), Vazirmatn typography, light surfaces, and rounded cards.

The six original screenshots and the design specification are retained under `docs/design-reference/`. The obsolete static HTML copies were removed after their content was converted into Django templates.
