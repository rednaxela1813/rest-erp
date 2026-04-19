# rest-erp — Consolidated Code Review

**Repository:** https://github.com/rednaxela1813/rest-erp
**Reviewed:** 2026-04-17
**Method:** Six independent review passes (architecture × 2, code quality × 2, security × 2). Findings below are cross-pass consensus; items flagged by both passes are marked **[2×]** and carry stronger signal.

---

## Executive Summary

`rest-erp` is a multi-tenant Django 6 + DRF ERP/POS backend with a mature domain layer (org-scoped models, explicit service/`logic/` modules, Celery, structlog, JWT auth, OpenAPI docs, ~100+ tests). The architectural foundation is solid — clean app boundaries, row-level locking in critical flows, idempotency keys on payments, and consistent tenant isolation via `X-ORG-ID`.

However, the project is **not production-ready** as-is. Three issue classes block a confident deploy:

1. **Configuration and environment hygiene** — committed Celery Beat state, Celery workers hardcoded to prod settings, no test settings module, settings split incomplete.
2. **Hardening gaps** — no rate limiting, 5-minute HSTS, weak device-token auth on cashier endpoints, missing DRF default permission class, no JWT lifetime config.
3. **Tooling discipline** — no linter/formatter/type-checker in CI, no pre-commit hooks, unpinned dependencies, inconsistent service-layer naming (`logic/` vs `services/`).

**Overall risk verdict: Medium-High.** Fixable in ~1–2 focused sprints. Below is the prioritized action list.

---

## Top 10 Must-Fix Items (Ranked by Risk × Effort)

| # | Finding | Category | Severity | File(s) | Effort |
|---|---------|----------|----------|---------|--------|
| 1 | **Celery Beat schedule committed to Git** `[2×]` | Arch/Sec | Critical | `celerybeat-schedule*` | 15 min |
| 2 | **Celery hardcoded to `core.settings.prod`** | Arch | Critical | `core/celery.py:7` | 30 min |
| 3 | **No rate limiting on login/refresh/logout** `[2×]` | Security | Critical | `core/settings/base.py`, `config/users/urls.py` | 1 h |
| 4 | **Weak device-token auth on `@csrf_exempt` cashier endpoints** | Security | Critical | `apps/cashier/views.py:81-85, 906-949` | 4 h |
| 5 | **HSTS = 300 s (preload requires ≥1 year)** `[2×]` | Security | High | `core/settings/prod.py:6` | 5 min |
| 6 | **Missing `DEFAULT_PERMISSION_CLASSES`** | Security | High | `core/settings/base.py` | 15 min |
| 7 | **Missing `SIMPLE_JWT` lifetime/rotation config** | Security | High | `core/settings/base.py` | 30 min |
| 8 | **No linter/formatter/type-checker (flake8/black/mypy/pre-commit)** `[2×]` | Quality | High | repo root | 2 h |
| 9 | **Cross-domain hard imports in `cancel_order` → inventory/accounting** | Arch | High | `apps/orders/logic/cancel_order.py:76-95` | 4 h |
| 10 | **Bare `except Exception:` in `LogoutView` swallows token errors** | Quality | High | `config/users/api_views.py:31` | 10 min |

---

## 1. Architecture

### What works
- **Multi-tenancy is first-class.** `OrgScopedModel` + `SessionOrgMiddleware` + `get_request_org()` enforce tenant isolation consistently.
- **Service layer exists.** `apps/*/logic/` and `apps/*/services/` isolate pure business logic from views/serializers.
- **Concurrency taken seriously.** `select_for_update()` in `cancel_order`, `deduct_stock`, and finalize flows; idempotency keys on payments.
- **Observability in the fabric.** structlog with contextvars (`request_id`, `org_id`, `user_id`) is wired through middleware.
- **Test architecture is deep.** 100+ test files, composable fixtures (`auth_client`, `org_factory`, `member_factory`), concurrency tests exist.

### What to fix

- **[Critical] Celery Beat schedule files in version control.** `celerybeat-schedule`, `celerybeat-schedule-shm`, `celerybeat-schedule-wal` are committed. These are SQLite files — binary, merge-unfriendly, environment-specific, and they break horizontal Beat scaling. `.gitignore` them, `git rm --cached` them, and migrate to Redis-backed scheduling for prod.
- **[Critical] `core/celery.py:7` hardcodes `DJANGO_SETTINGS_MODULE=core.settings.prod`.** Celery workers in dev/CI run against prod settings. Read the env var with a `dev` default instead.
- **[High] `config/orgs/` and `config/users/` are full apps masquerading as config.** They ship models, serializers, views, URLs. Every `apps/*` model inherits `OrgScopedModel` from `config.orgs` — tight coupling in the wrong direction. Either move them under `apps/` or create a `shared/` package for cross-cutting models.
- **[High] Cross-domain hard imports.** `apps/orders/logic/cancel_order.py` directly imports `restore_stock` (inventory) and `record_stock_return` (accounting). Orders shouldn't know inventory/accounting internals. Replace with domain events or a registered-hook pattern so each app owns its own side effects.
- **[High] Service-layer naming inconsistency.** `payments`/`accounting`/`orders` use `logic/`; `recipes`/`inventory` use `services/`. No documented contract. Pick one and add an `ARCHITECTURE.md` explaining layering rules.
- **[Medium] Settings file is 200+ lines with no separation by concern.** Split `base.py` into `celery.py`, `payments.py`, `observability.py`, etc., imported via `*` into `base.py`.
- **[Medium] No `OrgScopedManager`.** Every ViewSet manually re-filters by org. One missed line is a tenant-leak bug. Add `Model.objects.for_org(org)` and refactor views to use it.
- **[Medium] No test settings module.** `pytest.ini` uses `core.settings.dev`. A `core/settings/test.py` with in-memory SQLite + `CELERY_TASK_ALWAYS_EAGER=True` would speed tests and isolate them.
- **[Medium] ASGI/WSGI modules hardcode `prod` settings** while `docker-compose` dev uses `dev`. Dev/prod parity issue for ASGI deployment testing.
- **[Low] No API versioning strategy beyond the `/api/v1/` URL prefix.** No deprecation plan documented.

---

## 2. Code Quality

### What works
- Business logic is isolated in testable, typed service functions.
- No raw SQL, `.extra()`, or `.raw()` — ORM used consistently.
- Transaction boundaries around critical flows are explicit.
- Structured logging is uniform and contextual.
- Docstrings are present in service layer (inventory, payments).

### What to fix

- **[High] No toolchain enforcement.** No `.flake8`, no `pyproject.toml` with black/isort/ruff, no `mypy.ini`, no `.pre-commit-config.yaml`. Add all four; start with `ruff` (replaces flake8+black+isort) + `mypy --strict` + pre-commit.
- **[High] `OrderItemCreateSerializer.validate()` in `apps/orders/serializers.py:89-149` is a 60-line serializer god-method** with 4 nested try/except blocks. Move to a `create_order_item_command()` in `apps/orders/logic/`.
- **[High] `finalize_paid_order` at `apps/orders/logic/finalize_paid_order.py:19-172` has cyclomatic complexity > 15.** Split into `_aggregate_quantities`, `_deduct_inventory`, `_create_kitchen_tickets`.
- **[High] `cancel_order.py:47-74` and `finalize_paid_order.py:57-100` duplicate ~80 lines of bundle/recipe qty aggregation.** Extract to `apps/orders/services/aggregate_order_quantities.py`.
- **[High] Bare `except Exception:` in `config/users/api_views.py:31` (`LogoutView`).** Catch `InvalidToken`/`TokenError` explicitly.
- **[Medium] `requirements.txt` has loose version specifiers** (`>=`). Pin with `==` or use `pip-tools`/`uv` with a lockfile.
- **[Medium] N+1 risk in `apps/cashier/logic/cart.py:83-91`** — `get_products()` calls `has_enough_ingredients()` inside a loop. Add `prefetch_related('recipe__ingredients__product')`.
- **[Medium] Missing `prefetch_related` in `cancel_order.py:39-41`** — inconsistent with `finalize_paid_order`. Same call chain, different prefetch strategy.
- **[Medium] Admin form `ProductAdminForm._resolve_org_id()` fetches `.all()` then filters in Python.** Push the filter into the queryset.
- **[Medium] `apps/payments/providers/ekasa.py:16-18` reads `settings.EKASA_*` directly in `__init__`.** Inject via constructor for testability.
- **[Medium] Redundant pre-lock validation in `finalize_paid_order.py:29-34 + 39-44`.** Keep only the post-lock check.
- **[Low] Russian-language TODO comment in `apps/orders/models.py:16`.** Clean up; move to English or resolve.
- **[Low] Commented-out `record_stock_out()` call at `finalize_paid_order.py:122-124`.** Either implement or delete.
- **[Low] `test_orders_payment_usecase.py:16-25` monkeypatches without asserting call args.** Use `pytest-mock`'s `MagicMock.assert_called_with`.
- **[Low] `__str__` methods missing `-> str` annotations** across multiple models (~30+ functions lack return type hints overall).

---

## 3. Security

### What works
- **Multi-tenant isolation is sound.** `IsOrgMemberReadOnlyOrOrgAdmin` + `org_id` filter on every `get_object_or_404` prevents IDOR across orgs.
- **No SQL injection, eval, pickle, or unsafe yaml.**
- **Serializers mark `public_id` as `read_only`** — mass-assignment protection is consistent.
- **JWT blacklist is configured.**
- **PII masking in logs** via `mask_sensitive()` (`config/observability/logging.py:224`).
- **Password validators are all enabled.**
- **Prod has `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`.**
- **Owner demotion guard** prevents accidentally leaving an org without an owner.

### What to fix

- **[Critical] No rate limiting anywhere.** Login, refresh, logout, cashier login — all brute-forceable. Add DRF throttle classes (`AnonRateThrottle` 5/min on `/login/`, global defaults 100/hr anon, 1000/hr user).
- **[Critical] Device endpoints `device_cash_confirm`, `device_card_confirm` are `@csrf_exempt` with weak plaintext-header token auth.** If `CASHIER_DEVICE_TOKEN` env var is empty (the default), `_device_token_ok()` returns true and the endpoints are wide open. At minimum: validate the token is non-empty on startup, and move to HMAC-SHA256(payload, timestamp) signatures or mTLS.
- **[High] `SECURE_HSTS_SECONDS = 300`** (5 min). Preload list requires ≥ 31,536,000. Set to 1 year.
- **[High] No `DEFAULT_PERMISSION_CLASSES`** in `REST_FRAMEWORK`. Future endpoints inherit DRF's default (`AllowAny`). Set `IsAuthenticated` by default; opt-in `AllowAny` only where documented.
- **[High] No `SIMPLE_JWT` config block.** Default lifetimes apply silently. Set `ACCESS_TOKEN_LIFETIME=15m`, `REFRESH_TOKEN_LIFETIME=7d`, `ROTATE_REFRESH_TOKENS=True`, `BLACKLIST_AFTER_ROTATION=True`.
- **[Medium] `LogoutView` uses `AllowAny`** (`config/users/api_views.py:21`). Require `IsAuthenticated`.
- **[Medium] Image upload `product_image_upload_to()` at `apps/products/models.py:12-14`** trusts user-supplied file extension. Whitelist `{jpg, jpeg, png, gif, webp}`; reject or coerce to `.bin` otherwise.
- **[Medium] `ProductSerializer.image`** has no size/MIME validation — add a `validate_image` method with 5 MB cap.
- **[Medium] `X-ORG-ID` is user-controlled & session-writable** (`config/orgs/middleware.py:17`). Membership is checked, but session hijack → org switch risk exists. Add audit logging on `active_org_id` changes.
- **[Medium] `.env.example` ships weak defaults** (`your-super-secret-key`, `auth_pass`). Replace with `CHANGE_ME` placeholders; add a CI check that blocks commits of real-looking secrets.
- **[Medium] No CSP headers in prod.** Swagger UI is served in-app — CSP would limit XSS blast radius.
- **[Medium] No CORS configured.** If a separate frontend exists, it's broken; if API is same-origin, document that.
- **[Medium] `Pillow`, `cryptography` ranges are loose.** Pin.
- **[Low] Public `Currency`/`Country` list endpoints** (`config/dictionaries/api_views.py:9-18`) with `AllowAny`. Document intent or require auth.

---

## Suggested Remediation Sequence

**Week 1 — emergency hardening (1–2 days of actual work):**
1. `.gitignore` `celerybeat-schedule*`, `git rm --cached`.
2. Fix `core/celery.py` settings default.
3. Add DRF throttles + `DEFAULT_PERMISSION_CLASSES=[IsAuthenticated]`.
4. Add `SIMPLE_JWT` block with short access + rotating refresh.
5. `SECURE_HSTS_SECONDS = 31536000`.
6. Require `CASHIER_DEVICE_TOKEN` non-empty on prod startup.
7. Fix bare `except Exception:` in `LogoutView`.

**Week 1–2 — toolchain & hygiene:**
8. Add `ruff` + `mypy` + `.pre-commit-config.yaml` + CI jobs.
9. Pin `requirements.txt`; add dev/prod split or move to `uv`/`pip-tools`.
10. Add `core/settings/test.py`.

**Week 2–3 — refactors:**
11. Extract `aggregate_order_quantities` helper; shrink `finalize_paid_order`.
12. Move `OrderItemCreateSerializer.validate()` into `logic/`.
13. Introduce `OrgScopedManager.for_org(org)`; refactor views.
14. Replace direct cross-app imports in `cancel_order` with domain events.

**Week 3+ — strategic:**
15. Rename `config/orgs`, `config/users` into `apps/` (or `shared/`).
16. Migrate Celery Beat to Redis-backed scheduler.
17. Harden device-endpoint auth to HMAC or mTLS.
18. Add CSP headers; configure CORS explicitly.
19. Document architecture (`docs/ARCHITECTURE.md`) — layering, service vs logic, tenancy contract.

---

## Overall Grade

| Dimension | Grade | Notes |
|-----------|-------|-------|
| Architecture | **B** | Strong foundations, marred by config/layering smells and Beat-in-git. |
| Code Quality | **B−** | Clean intent; no enforcement tooling; a few god-functions. |
| Security | **C+** | No injection vectors or obvious IDORs, but missing rate limits, weak device auth, and bad HSTS make this pre-prod. |
| Test Coverage | **B+** | Thoughtful concurrency & idempotency tests; lacks coverage reporting. |
| Documentation | **B−** | README is good; architectural contract is undocumented. |

**Production-ready verdict: Not yet.** After the Week-1 items above, the project clears the bar for a pilot deployment with small traffic and trusted users. Full production readiness needs Weeks 2–3 as well.
