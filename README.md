# StockSense

A modular **Inventory Management System** that replaces spreadsheets and paper registers with one
real-time app: products, receipts, deliveries, internal transfers, stock adjustments, a full
movement ledger, multi-warehouse support and automatic GST.

Built for the Odoo × GCET hackathon (problem statement: *StockSense*).

---

## Tech stack

| Layer | Technology | Notes |
|---|---|---|
| **Frontend** | React 18, React Router 6, Vite 5 | Plain JSX + hand-written CSS design system (no UI framework) |
| **Typography / icons** | Geist + Geist Mono, inline SVG icon set | Loaded from Google Fonts |
| **Backend** | Python 3.12, FastAPI 0.115, Uvicorn 0.32 | Auto-generated OpenAPI docs at `/docs` |
| **ORM / DB access** | SQLAlchemy 2.0, psycopg 3 | Typed `Mapped[]` models |
| **Validation / config** | Pydantic 2, pydantic-settings | `.env`-driven settings |
| **Database** | PostgreSQL 16 (Docker) | Data persisted in a named volume |
| **Auth** | JWT (PyJWT) + bcrypt | Bearer tokens, 12 h default lifetime |
| **Email (OTP, digest)** | [Brevo](https://www.brevo.com) transactional email API via `httpx` | Falls back to logging when no key is set |
| **Infra** | Docker + Docker Compose | One command starts DB, API and web app |

### Third-party services and dependencies

| Service | Needed for | Required? |
|---|---|---|
| **Brevo** (API key + a verified sender) | Password-reset OTP and the daily low-stock digest | Optional for development. Without it the OTP is printed in the backend logs and no digest is sent. |
| **Google Fonts** | Geist / Geist Mono fonts in the browser | Optional. The UI falls back to system fonts offline. |
| Docker Desktop | Running everything | Yes |

There are no other external APIs, payment providers or paid services.

---

## Quick start

**Prerequisites:** Docker Desktop (running). Node/Python are *not* needed on the host.

```bash
# 1. Create your environment file
cp .env.example .env
#    edit .env: set SECRET_KEY, and (optionally) the Brevo values

# 2. Start everything
docker compose up --build
```

| Service | URL |
|---|---|
| Web app | http://localhost:5173 |
| API | http://localhost:8000/api |
| API docs (Swagger) | http://localhost:8000/docs |
| Postgres | `localhost:5432` (user/password/db from `.env`) |

Open the web app and click **Create an account**. The first start seeds a demo warehouse,
locations, GST slabs and two products so there is something to click on straight away.

### Demo data for presentations

```bash
docker compose exec backend python -m app.demo --reset
```

Loads two warehouses, 18 products and about 40 documents in every status (late receipts, waiting deliveries,
a half-picked delivery, cross-warehouse transfers, low-stock items) plus a `demo_admin` account. Re-run it any
time to reset. A click-by-click script is in **[DEMO.md](DEMO.md)**.

### Running the tests

```bash
docker compose exec backend python -m pytest tests -q
```

169 tests run against a separate throw-away database (`stocksense_test`), so your data is never touched.

Handy commands:

```bash
docker compose up -d              # start in the background
docker compose logs -f backend    # follow API logs (OTP is printed here without Brevo)
docker compose down               # stop (keeps data)
docker compose down -v            # stop and DELETE the database volume (fresh start)
```

### Environment variables (`.env`)

| Variable | Purpose | Default in `.env.example` |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Database credentials | `stocksense` |
| `SECRET_KEY` | Signs JWTs. **Change it.** Generate with `openssl rand -base64 48` (32+ characters) | placeholder |
| `APP_ENV` | `development` or `production`. Production refuses weak secrets at startup | `development` |
| `CORS_ORIGINS` | Comma-separated origins allowed to call the API | `http://localhost:5173,http://127.0.0.1:5173` |
| `RATE_LIMIT_ENABLED` | Turn the login / sign-up / OTP rate limits on or off | `true` |
| `ACCESS_TOKEN_MINUTES` | Login lifetime | `720` |
| `BREVO_API_KEY` | Brevo API key (Brevo → SMTP & API → API Keys) | empty |
| `BREVO_SENDER_EMAIL` | A sender verified in Brevo | empty |
| `BREVO_SENDER_NAME` | Display name on outgoing emails | `StockSense` |
| `DIGEST_ENABLED` | Run the daily low-stock digest scheduler | `true` |
| `DIGEST_HOUR_UTC` | Hour (UTC) after which the digest is sent, once a day | `3` (08:30 IST) |

`.env` is git-ignored. Never commit real keys.

---

## Features

**Authentication**
- Sign up with login ID (6–12 chars, unique), unique email, and a strong password
  (more than 8 chars with lower-case, upper-case and a special character); live rule checklist in the UI.
- Login, logout, and a **My profile** page to change your email and password.
- OTP password reset: 6-digit code emailed through Brevo, valid 10 minutes, max 5 attempts, stored hashed,
  and the response never reveals whether an email is registered.

**Dashboard**
- KPIs: products in stock, low stock, out of stock, pending receipts, pending deliveries, scheduled transfers.
- Operation cards with a status bar (draft / waiting / ready) and late / waiting / scheduled counts.
- Filters: **document type, status, warehouse, location, category**. They drive the cards, KPIs,
  low-stock table and the recent-movements feed. Filters are remembered for the session.
- Low-stock alerts with **suggested reorder quantities** and one-click "Create receipt".

**Products**
- Name, SKU, category, unit of measure, unit price, HSN code, tax, reorder level and quantity, optional initial stock.
- Category management (add, rename, delete when unused).
- **Archive, restore or delete** products, warehouses and locations. Archiving keeps history and is refused while stock
  remains or documents are open; only never-used items can be deleted.
- **CSV import** of products (matched by SKU) with a row-by-row preview before anything is written.
- Stock availability per location.

**Operations** (list and kanban views, search, status and warehouse filters, server-side pagination)
- **Receipts** (incoming): `Draft → Ready → Done`. Validating adds stock.
- **Deliveries** (outgoing): `Draft → Waiting → Ready → Done`. Validating removes stock.
  If stock is short the line turns red, a notification shows, and the order waits until stock arrives.
  Once Ready, a delivery is **picked, then packed, then validated**; validation is refused until both are done.
- **Internal transfers**: move stock between locations, including across warehouses.
- **Adjustments**: enter a counted quantity from the Stock page; the difference is logged.
- **Partial receipts and deliveries (backorders):** validate with the quantities that really arrived or shipped. The
  rest either continues on an automatic **backorder** document (linked both ways) or is cancelled. Totals and taxes follow
  what actually moved.
- Every state can also be **Cancelled**. Completed documents can be printed (with the supplier/customer, address and GSTIN).
- Search across documents by **reference, contact, product name or SKU**.
- Duplicate an order into a fresh draft; contacts are suggested from earlier orders.

**Contacts (suppliers and customers)**
- Saved contacts with type (supplier / customer / both), **GSTIN** (format, state code and check digit validated; the state
  is derived), email, phone and address. Receipts pick a supplier, deliveries a customer; the name, address and GSTIN flow
  onto the document and its printout. Each contact shows its document history and totals.
- Add a contact on the fly from a receipt or delivery; archive or delete like other records; export to CSV.

**Valuation and margin**
- Products have a **sales price** and a **purchase cost**. Receipts default to the purchase cost and deliveries to the sales price.
- Stock is valued at **weighted-average cost**: each receipt blends its price into the average, deliveries record the average at
  that moment. **Stock → Valuation** shows stock value, value at sales price and potential margin by product and category;
  **Stock → Margin** shows revenue, cost and margin per product for the last 7 / 30 / 90 days or 12 months. Both export to CSV,
  and the dashboard shows the total stock value.

**Notifications**
- An optional **daily low-stock email** (My profile): what to reorder, what is late and what is waiting for stock. It is sent
  once a day after a configured hour, only to people who opted in, and there is a "send me today's digest now" button.

**Taxes / GST**
- Tax master with GST 0 / 5 / 12 / 18 / 28 % pre-loaded. Add any new slab or other tax at any time
  (Settings → Taxes), with no code change.
- A product's tax resolves automatically: its own tax, else its category default, else the global default.
- Orders pre-fill unit price and tax from the product and show a CGST / SGST split and grand total.
- Each order line stores the rate it was created with, so validated documents never change if rates change later.

**Access and audit**
- Three roles (warehouse staff, inventory manager, administrator) with server-enforced permissions and a Users page for admins.
- An **activity log** of every change with before/after values, plus a per-document history panel.
- **Conflict protection** so two people editing the same record can't silently overwrite each other.

**Multi-warehouse**
- Warehouses and locations (Settings). Receipts and deliveries are created inside a chosen warehouse,
  and references follow it (`WH/IN/0001`, `ND/OUT/0003`).

**CSV export**
- Products, stock, move history and every operation list export to CSV, honouring the current filters.
  Cells are sanitised against spreadsheet formula injection and include a BOM so Excel opens them correctly.

**Move history**
- One ledger row per product line: reference, contact, product, from → to, quantity, date, status.
  Incoming moves are green, outgoing red.

---

## How the key rules work

**Reference numbers** are `<warehouse short code>/<IN|OUT|INT|ADJ>/<0001>`, incremented per warehouse and type
from a locked sequence row, so concurrent users never get duplicates.

**Stock is only ever changed by validating a document** (or an adjustment). Locations of type `vendor`,
`customer` and `adjustment` are virtual and don't hold stock; only `internal` locations do.

**Availability** for an outgoing move is `on hand − quantity reserved by other Ready orders` from the same
location. When stock arrives, waiting orders that can now be served are promoted to Ready automatically.

**Reordering** uses a min/max rule per product: when `on hand + already-incoming receipts ≤ reorder level`,
the suggestion is the reorder quantity (in whole multiples if the shortfall is larger). Products with no rule
get no suggestion. "Create receipt" makes a draft receipt with those quantities.

---

## Project structure

```
StockSense/
├── docker-compose.yml        # db + backend + frontend
├── .env.example              # copy to .env
├── README.md                 # this file
├── backend/                  # FastAPI service (see backend/README.md)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py           # app, CORS, startup (create tables, migrations, seed)
│       ├── config.py         # settings from environment
│       ├── db.py             # engine + session dependency
│       ├── models.py         # SQLAlchemy models
│       ├── security.py       # bcrypt, JWT, password rules
│       ├── deps.py           # current_user dependency
│       ├── mail.py           # Brevo OTP email
│       ├── stock.py          # stock engine + workflow (todo/validate/cancel/adjust)
│       ├── pricing.py        # tax resolution + document totals
│       ├── filters.py        # filters shared by dashboard, lists, moves
│       ├── lifecycle.py      # can this be archived / deleted? (stock, open documents, history)
│       ├── pagination.py     # optional ?page= / ?page_size= envelope
│       ├── queries.py        # set-based stock / reservation / incoming queries
│       ├── audit.py          # activity log model + record()/diff()
│       ├── conflict.py       # optimistic-locking version checks
│       ├── ratelimit.py      # sliding-window limiter for auth endpoints
│       ├── migrations.py     # idempotent schema upgrades (columns, decimals, indexes, checks)
│       ├── digest.py         # daily low-stock email: build, render, once-a-day scheduling
│       ├── seed.py           # first-run data + GST slabs + backfill
│       ├── demo.py           # `python -m app.demo`: presentation dataset
│       └── routers/          # auth, settings, products, parties, operations, inventory,
│                             # reports, exports, notifications
│   └── tests/                # pytest suite (169 tests, own database) + bench_scale.py
├── DEMO.md                   # 6-minute demo script
└── frontend/                 # React + Vite app
    ├── vite.config.js        # dev server + /api proxy
    └── src/
        ├── App.jsx           # routes + auth gate
        ├── api.js            # fetch wrapper with JWT
        ├── hooks.js          # useApi, useDebounced
        ├── styles.css        # design tokens + components
        ├── components/       # Layout, ui (pager, modal, stepper…), icons, CategoryManager,
                              # PartyModal, ProductImport, Lifecycle
        └── pages/            # Auth, Dashboard, Operations, OperationDetail, Catalog (products + stock),
                              # StockReports (valuation, margin), Contacts, MoveHistory,
                              # Settings (warehouses, locations), Taxes, Users, Activity, Profile
```

The frontend talks to the API only through `/api/...`; Vite proxies that to the backend
container, so there is no CORS setup to fiddle with in development.

---

## API overview

Interactive docs: **http://localhost:8000/docs**. Everything except `/auth/*` and `/health` needs
`Authorization: Bearer <token>`. Full endpoint list with parameters is in [backend/README.md](backend/README.md).

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/signup`, `/auth/login`, `/auth/forgot-password`, `/auth/reset-password`, `GET /auth/me` |
| Catalogue | `/products`, `/categories`, `/taxes`, `/category-taxes`, `/parties` (contacts) |
| Structure | `/warehouses`, `/locations` |
| Operations | `/operations`, `/operations/{id}/{todo,check,pick,pack,validate,cancel,duplicate}` (`validate` takes optional per-line quantities), `/contacts`, `/moves` |
| Inventory | `/stock`, `/stock/adjust`, `/dashboard`, `/reorder/suggestions`, `/reorder/receipt` |
| Reports | `GET /reports/valuation`, `GET /reports/margin` |
| Notifications | `GET/PUT /notifications/preferences`, `POST /notifications/digest/test` |
| Lifecycle | `POST /{products,locations,warehouses}/{id}/{archive,restore}`, `DELETE` on the same |
| CSV | `GET /export/{products,stock,moves,operations,valuation,margin,parties}.csv`, `POST /products/import` |
| Account | `PUT /auth/me`, `POST /auth/change-password` |
| Admin | `GET /users`, `PUT /users/{id}` (admin) · `GET /audit` (manager) · `GET /operations/{id}/history` |

List endpoints (`products`, `stock`, `operations`, `moves`, `parties`, `reports/*`, `reorder/suggestions`) take optional
`?page=1&page_size=25` (max 200) and then answer `{items, total, page, page_size, pages}`; without `page` they return the plain list as before.
`PUT`s accept an optional `version` and workflow actions an optional `?version=`; a stale value gets a 409.

---

## Performance

Measured with `backend/tests/bench_scale.py` on a synthetic dataset of **8,000 products, 30,000 documents and 75,000
document lines** (one laptop, in-process, warm database). "Before" is the code as it stood before the scale work, and every
screen now asks for one 25-row page.

| Endpoint | Before | After (25-row page) |
|---|---|---|
| `GET /stock` | did not finish in 60 s | **39 ms** |
| `GET /products` | 8,321 ms · 2.9 MB | **41 ms** · 9 KB |
| `GET /operations` | 12,582 ms · 19 MB | **64 ms** · 16 KB |
| `GET /moves` | 7,075 ms · 15 MB | **87 ms** · 6 KB |
| `GET /reports/margin` (12 months) | 8,476 ms | **161 ms** |
| `GET /reports/valuation` | 693 ms | **130 ms** |
| `GET /parties` | 192 ms | **31 ms** |
| `GET /dashboard` (no pagination needed) | 649 ms | **134 ms** |

What changed: list endpoints page in the database (`LIMIT/OFFSET` plus a `COUNT`), the per-product and
per-product-and-location queries became a handful of set-based queries (`app/queries.py`), the dashboard and reports are
computed with grouped SQL instead of Python loops, and every foreign key and hot filter column is indexed. Run
`docker compose exec backend python tests/bench_scale.py --rebuild` to reproduce it (the first run builds the dataset in its
own `stocksense_bench` database).

---

## Security and access

**Roles.** The first person to sign up becomes the **administrator**; everyone after starts as **warehouse staff** until an
admin promotes them (Settings → Users). The server enforces the rules; the UI simply hides what you can't use.

| | Staff | Manager | Admin |
|---|:-:|:-:|:-:|
| See everything (products, stock, documents, contacts, reports, move history) | ✓ | ✓ | ✓ |
| Count stock (adjustments) | ✓ | ✓ | ✓ |
| Create and edit **internal transfers** | ✓ | ✓ | ✓ |
| Move any document through its stages (To do, check, pick, pack, validate) | ✓ | ✓ | ✓ |
| Create, edit, cancel, duplicate **receipts and deliveries** | | ✓ | ✓ |
| Products, categories, contacts, CSV import, reorder receipts, archive / delete | | ✓ | ✓ |
| Read the **activity log** | | ✓ | ✓ |
| Warehouses, locations, taxes, users | | | ✓ |

**Other protections**
- **Activity log:** every change is recorded (who, when, what, before and after) in the same transaction as the change, and
  each document shows its own history.
- **Conflict protection:** products, contacts and documents carry a version. Saving from an out-of-date screen is refused with
  "changed by someone else, reload" instead of silently overwriting their work.
- **No overselling:** stock rows are locked while availability is checked, and the database itself refuses negative stock.
- **Exact money:** amounts are stored as decimals and summed in `Decimal`, rounded half-up to whole paise, so totals never drift.
- **Rate limits:** login, sign-up and the password-reset endpoints are limited per person and per address; one inbox can't be
  flooded with codes. Reset emails are sent after the response, so the reply doesn't reveal whether an address exists.
- **Input limits:** lengths, ranges and list sizes are validated before anything reaches the database.
- **Secure by default:** with `APP_ENV=production` the API refuses to start with a placeholder or short `SECRET_KEY`;
  CORS origins come from `CORS_ORIGINS`; deactivating a user invalidates their token immediately.

**Before going live:** set `APP_ENV=production`, a real `SECRET_KEY`, your `CORS_ORIGINS`, serve over HTTPS, build the frontend
(`npm run build`) instead of running the dev server, and put the API behind a reverse proxy. The in-process rate limiter is per
worker; with several workers use a shared store such as Redis.

---

## Design decisions and known limitations

- **Schema management:** tables are created on startup with `create_all`, and upgrades to existing databases (new columns,
  float → decimal conversion, indexes, the non-negative stock check) are idempotent steps in `app/migrations.py`. This keeps
  setup to one command. A team with several environments should switch to Alembic.
- **Docker runs the dev servers** (Uvicorn `--reload`, Vite dev). For production build the frontend
  (`npm run build`) and serve the static files behind a reverse proxy.
- **Tax model:** intra-state GST (CGST + SGST) is displayed. Inter-state IGST, e-invoicing and GST returns are not implemented.
- **Costing:** weighted-average only (no FIFO / lot costing). Returns, credit notes, lot/serial numbers and expiry dates are not modelled.
- **Digest scheduler** runs inside the API process (checked every 15 minutes). It claims the day in the database first, so a restart
  or a second worker cannot send it twice, but a fleet of workers would be better served by a dedicated job runner.
- **Roles** are coarse (three fixed roles). There are no per-warehouse permissions and no approval workflows.
- **Pick and pack** is a two-step confirmation on Ready deliveries. There are no pick lists, wave picking or packages.
- **Search** uses `ILIKE`. That is fast at tens of thousands of rows; beyond that add trigram indexes (`pg_trgm`).
- **CSV export/import** run in one request (import is capped at 2,000 rows), which is fine for spreadsheets, not for bulk loads.
- **Tests:** the backend has an API-level pytest suite (workflow, backorders, taxes, warehouses, reorder, archive/delete, contacts,
  valuation, digest, CSV, auth, pagination, roles, audit, locking and concurrency, exact money, rate limits, migrations).
  The React UI has no automated tests; it was checked by hand in the browser, including phone width and print view.
- **Security notes:** JWTs live in `localStorage` (an HttpOnly cookie is safer against XSS). The activity log is written by the
  application, so someone with direct database access could alter it; ship it to an append-only store for strict compliance.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `failed to connect to the docker API` | Start Docker Desktop and wait until it says it's running. |
| Page doesn't update after editing frontend files (Docker on Windows) | Already handled: Vite polling is on in `vite.config.js`. Restart with `docker compose restart frontend`. |
| No OTP email arrives | Check `BREVO_API_KEY`, that `BREVO_SENDER_EMAIL` is a *verified* sender in Brevo, and your spam folder. Without Brevo the code is in `docker compose logs backend`. |
| Want a clean database | `docker compose down -v && docker compose up --build` |
| Port already in use | Change the host side of the `ports:` mapping in `docker-compose.yml`. |
