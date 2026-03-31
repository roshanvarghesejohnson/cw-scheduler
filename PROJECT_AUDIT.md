# Project Overview

**cw-scheduler** is a Django monolith for CycleWorks-style **field service scheduling**: cities, customers, time **slots**, **bookings**, **technicians**, automatic **slot assignment** and **dispatch optimization**, plus **Zoho CRM** deal lifecycle sync. Operations rely heavily on **management commands** and **django-admin**; customer intake uses a small set of **REST** endpoints. Deployment target implied: **PostgreSQL** (e.g. Render), **Gunicorn**, optional **WhiteNoise** for static files.

---

# Codebase Size

| Metric | Value (approx.) |
|--------|------------------|
| **Total files** (excl. `.git`, `.venv`, `__pycache__`, `*.pyc`) | **110** |
| **Total lines** (same scope, `wc -l`) | **~5,050** |

### Breakdown by type

| Category | Count | Notes |
|----------|------:|------|
| **Python** (`.py`) | **99** | Application + migrations |
| **HTML templates** | **3** | `dispatch_dashboard.html`, `cycleworks_booking.html`, docs inject snippet |
| **Markdown** | **2** | `docs/` + root mapping doc |
| **Other config** | **~6** | `requirements.txt`, `Procfile`, `build.sh`, `.gitignore`, `.env` (local, gitignored) |

*Python-only LOC* (sum of `.py`): **~4,327** (remainder ~723 in HTML/MD/txt/shell/Procfile).

### Largest files (top 10 by LOC, Python)

| Rank | Lines | File |
|------|------:|------|
| 1 | 406 | `apps/routing/management/commands/simulate_routing.py` |
| 2 | 284 | `apps/integrations/services/zoho_crm_service.py` |
| 3 | 253 | `apps/routing/services/technician_assignment_service.py` |
| 4 | 218 | `apps/routing/services/dispatch_optimizer_service.py` |
| 5 | 199 | `scheduler_core/settings.py` |
| 6 | 198 | `apps/bookings/management/commands/generate_dummy_bookings.py` |
| 7 | 174 | `apps/bookings/signals.py` |
| 8 | 166 | `apps/bookings/api/booking_create_view.py` |
| 9 | 155 | `apps/routing/services/dispatch_dashboard_service.py` |
| 10 | 145 | `apps/scheduling/services/slot_generation_service.py` |

### Heavier / multi-responsibility modules

- **`simulate_routing.py`** — dev/simulation CLI; large but isolated from prod runtime.
- **`zoho_crm service`** — OAuth, deal create, generic `update_deal`, assignment PUT, payload builders; natural split candidate (auth vs records API).
- **`technician_assignment_service` / `dispatch_optimizer_service`** — core scheduling heuristics + Zoho side effects; high impact on behaviour.
- **`bookings/signals.py`** — slot utilization + Zoho stage sync; cross-cutting.
- **`settings.py`** — env, DB, CORS, API keys, Zoho config; typical Django concentration point.

---

# Architecture

## Style

- **Monolithic Django app** with multiple **`apps.*`** packages.
- **No** separate worker/Celery service in-repo; async/time-based work is **cron / Render jobs → management commands**.
- **PostgreSQL** required (`DATABASE_URL`); **DRF** for JSON APIs; **django-admin** for data ops.

## Separation of concerns

| Layer | Location | Notes |
|-------|----------|------|
| **Models** | `apps/*/models.py` | Booking, Customer, City, Slot, Technician; `routing` app has no models. |
| **HTTP / DRF** | `apps/*/api/`, `apps/*/views.py`, `scheduler_core/urls.py` | Thin views delegating to services. |
| **Business logic** | `apps/*/services/`, management `commands/` | Most non-trivial logic lives here (good direction); some duplication between assignment paths. |
| **Cross-cutting** | `apps/common/middleware/`, `apps/bookings/signals.py` | API key middleware; slot utilization + Zoho hooks. |

**Assessment:** Core scheduling logic is mostly **out of views** (good). **Risk:** Zoho calls and heuristics are interleaved in **optimizer / technician service** loops; signals add a **second path** for CRM updates on `save()`.

---

# Modules Breakdown

### `scheduler_core/`

- **Purpose:** Django project root — URLs, WSGI/ASGI, templates, `settings.py`.
- **Key flows:** Route `/api/*`, `/admin/`, `/routing/*` dispatch dashboard.

### `apps/bookings`

- **Purpose:** Booking lifecycle entity.
- **Key models:** `Booking` (status, slot, technician, `crm_deal_id`, geo, `route_position`, …).
- **Key APIs:** `BookingCreateView` — create booking, geocode, Zoho deal create, persist `crm_deal_id`.
- **Signals:** Slot utilization on delete/slot change; Zoho **Customer Approved** stage when CONFIRMED + technician + deal id (save path, with transition dedupe).

### `apps/customers`

- **Purpose:** Customer master data (contact, address, cycle info, coordinates).
- **Key models:** `Customer`.

### `apps/cities`

- **Purpose:** Operating cities (`handling_type`, `is_active`).
- **Key models:** `City`.
- **Key flows:** List cities API (`urls.py`).

### `apps/slots`

- **Purpose:** Bookable windows (capacity + utilization cache).
- **Key models:** `Slot` (date, times, city, `max_capacity`, `current_utilization`).

### `apps/technicians`

- **Purpose:** Technician roster and constraints.
- **Key models:** `Technician` (city, base coords, `daily_capacity`, availability flags).

### `apps/scheduling`

- **Purpose:** **Slot generation** (not technician assignment).
- **Key services:** `slot_generation_service` — IST windows, capacity from technician counts.
- **Commands:** `generate_slots`.

### `apps/routing`

- **Purpose:** **Distance**, **slot availability** read model, **scheduling service** (assign slots to bookings), **dispatch optimization**, **dashboard payload**, **simulation**.
- **Key models:** None (logic over `Booking` / `Slot` / `Technician`).
- **Key services:** `SchedulingService`, `SlotAvailabilityService`, `DistanceService`, `DispatchOptimizerService`, `TechnicianAssignmentService`, `DispatchDashboardService`, `GeocodingService` (referenced from bookings).
- **Key APIs:** Slot availability, dispatch plan, dashboard template.
- **Commands:** `run_daily_scheduling`, `run_next_day_dispatch`, `auto_assign_slots`, `auto_assign_technicians`, `run_dispatch`, `simulate_routing`.

### `apps/integrations`

- **Purpose:** **Zoho CRM** HTTP client.
- **Key services:** `ZohoCRMService` (OAuth refresh, `create_deal`, `build_deal_payload`, `update_deal`, `update_deal_assignment`).
- **Commands:** `test_crm_update` (manual test).

### `apps/common`

- **Purpose:** Shared middleware (`ApiKeyMiddleware` for `/api/`), `startup` (default superuser bootstrap).

### `docs/`

- **Purpose:** Technical notes and HTML snippets for external forms (not executable app code).

---

# Core Flows

### 1. Booking creation

| | |
|--|--|
| **Entry** | `POST /api/bookings/create/` → `BookingCreateView` |
| **Steps** | Validate payload; resolve `Slot`; capacity check; get/create `Customer`; atomic create `Booking` + bump slot utilization; geocode (Nominatim); `ZohoCRMService.create_deal` + save `crm_deal_id`. |
| **Dependencies** | PostgreSQL, Zoho OAuth + CRM API, Nominatim (optional coords), `DATABASE_URL`. |

### 2. Slot generation

| | |
|--|--|
| **Entry** | `python manage.py generate_slots` → `generate_slots_for_next_7_days()` |
| **Steps** | IST “today”; days +1..+7; per active city, if technicians exist → create missing `Slot` rows for fixed windows; capacity = tech count. |
| **Dependencies** | `City`, `Technician` data; no booking mutation. |

### 3. Dispatch / routing

| | |
|--|--|
| **Entry** | Commands: `run_daily_scheduling`, `auto_assign_technicians`, `run_next_day_dispatch`, etc.; API `GET /api/dispatch/plan/`, dashboard `/routing/dashboard/`. |
| **Steps** | `SchedulingService.auto_assign_slots` fills REQUESTED bookings without slots; `DispatchOptimizerService` or `TechnicianAssignmentService` assigns technicians (heuristics + distance); `bulk_update`; optimizer/assignment paths call Zoho (`update_deal` stage + `update_deal_assignment`). |
| **Dependencies** | Coordinates on booking/customer; technician base coords; Haversine `DistanceService`; Zoho for updates. |

### 4. CRM (Zoho)

| | |
|--|--|
| **Entry** | Create: booking API. Stage “Customer Approved”: post-assignment loops in optimizer/technician service + `post_save` signal on booking. Field updates: `update_deal_assignment`. |
| **Steps** | OAuth refresh (`accounts.zoho.in`); `POST /Deals` create; `PUT /Deals/{id}` generic update; `PUT /Deals` batch-style assignment update (legacy pattern). |
| **Dependencies** | Env: refresh token, client id/secret, optional base URL overrides. |

### 5. Admin / manual

| | |
|--|--|
| **Entry** | `/admin/`; booking edits trigger signals (slot + Zoho stage rules). |
| **Steps** | CRUD on all models; `ensure_default_superuser` on WSGI startup (creates default admin if none — review for production). |

---

# Integrations

| Integration | Used in | How | Risks |
|-------------|---------|-----|--------|
| **Zoho CRM (India)** | `ZohoCRMService`; booking create; dispatch/assignment; booking signals; `test_crm_update` | `requests` POST/PUT; OAuth refresh | Token expiry, rate limits, API shape differences (`PUT` path vs body-only updates), network timeouts; **create_deal** may raise and fail the HTTP request after DB write unless transaction boundaries change. |
| **OpenStreetMap Nominatim** | `GeocodingService` | `requests.get` + 1s sleep (usage policy) | Slow booking path, blocking I/O, external availability, address quality. |
| **PostgreSQL** | All persistence | `dj-database-url`, `DATABASE_URL` | Required at import time in settings. |

*Internal:* **Haversine** distance (no third-party routing API).

---

# Risks & Tech Debt

1. **Dual Zoho update patterns** — `update_deal` uses `PUT .../Deals/{id}`; `update_deal_assignment` uses `PUT .../Deals` with body. If one fails in production, alignment with Zoho docs should be verified.
2. **`bulk_update` bypasses `save()` signals** — CRM stage logic must stay duplicated in optimizer + technician services; easy to add a third assignment path and forget Zoho.
3. **`simulate_routing` size** — fine for tooling but adds noise in reviews; consider `tools/` or tighter scope.
4. **Secrets & settings** — hardcoded dev `SECRET_KEY`, `SCHEDULER_API_KEY`, default superuser credentials in `startup.py` are **high risk** if used in production unchanged **(informational — out of audit scope to change)**.
5. **Heavy `print()` in Zoho layer** — useful on Render; no structured logging levels; potential PII/token leakage in logs **(informational)**.
6. **Geocoding after commit** — booking exists before coords; race if dispatch runs immediately.
7. **`update_deal_assignment` field sourcing** — uses `getattr(booking, …)` for fields that may live on `Customer`; silent omission of data if names don’t match model **(informational)**.
8. **No in-repo Celery/queue** — long Zoho or Nominatim calls run in request/command thread.

---

# Code Quality Snapshot

| Area | Snapshot |
|------|----------|
| **Naming** | Generally consistent Django patterns (`Service` suffix, app-based layout). |
| **Logging** | Mixed: `logger` in some modules, extensive `print` in Zoho path for ops visibility. |
| **Error handling** | Create deal: strict (raises). Assignment CRM paths: try/except to avoid breaking dispatch. Signals: try/except + logger. |
| **Readability** | Service modules are readable; largest files (`simulate_routing`, Zoho) would benefit from section comments or split modules. |

---

# Recommendations (high-level)

1. **Unify Zoho HTTP** — one helper for authenticated request + consistent URL patterns per Zoho v2 docs.
2. **Centralize “booking confirmed → CRM”** — single function called from optimizer, technician service, and signal to avoid drift.
3. **Structured logging** — replace or supplement `print` with `logging` + explicit LOG level in production; redact tokens.
4. **Harden settings** — env-only secrets, remove default superuser auto-create for production, separate DEBUG defaults.
5. **Optional async** — queue Nominatim + Zoho create for booking API resilience (or idempotent retry job).
6. **Tests** — expand coverage on `SchedulingService`, optimizers, and Zoho payload builders (mock `requests`).

---

*Generated by read-only repository scan. Counts exclude `.git`, `.venv`, and `__pycache__`.*
