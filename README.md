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
| **Email (OTP)** | [Brevo](https://www.brevo.com) transactional email API via `httpx` | Falls back to logging the OTP when no key is set |
| **Infra** | Docker + Docker Compose | One command starts DB, API and web app |

### Third-party services and dependencies

| Service | Needed for | Required? |
|---|---|---|
| **Brevo** (API key + a verified sender) | Emailing the password-reset OTP | Optional for development. Without it the OTP is printed in the backend logs. |
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
| `SECRET_KEY` | Signs JWTs. **Change it.** Generate with `openssl rand -base64 32` | placeholder |
| `ACCESS_TOKEN_MINUTES` | Login lifetime | `720` |
| `BREVO_API_KEY` | Brevo API key (Brevo → SMTP & API → API Keys) | empty |
| `BREVO_SENDER_EMAIL` | A sender verified in Brevo | empty |
| `BREVO_SENDER_NAME` | Display name on OTP emails | `StockSense` |

`.env` is git-ignored. Never commit real keys.

---

## Features

**Authentication**
- Sign up with login ID (6–12 chars, unique), unique email, and a strong password
  (more than 8 chars with lower-case, upper-case and a special character); live rule checklist in the UI.
- Login, logout, profile menu.
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
- Stock availability per location.

**Operations** (list and kanban views, search, status and warehouse filters, pagination)
- **Receipts** (incoming): `Draft → Ready → Done`. Validating adds stock.
- **Deliveries** (outgoing): `Draft → Waiting → Ready → Done`. Validating removes stock.
  If stock is short the line turns red, a notification shows, and the order waits until stock arrives.
- **Internal transfers**: move stock between locations, including across warehouses.
- **Adjustments**: enter a counted quantity from the Stock page; the difference is logged.
- Every state can also be **Cancelled**. Completed documents can be printed.
- Search across documents by **reference, contact, product name or SKU**.
- Duplicate an order into a fresh draft; contacts are suggested from earlier orders.

**Taxes / GST**
- Tax master with GST 0 / 5 / 12 / 18 / 28 % pre-loaded. Add any new slab or other tax at any time
  (Settings → Taxes), with no code change.
- A product's tax resolves automatically: its own tax, else its category default, else the global default.
- Orders pre-fill unit price and tax from the product and show a CGST / SGST split and grand total.
- Each order line stores the rate it was created with, so validated documents never change if rates change later.

**Multi-warehouse**
- Warehouses and locations (Settings). Receipts and deliveries are created inside a chosen warehouse,
  and references follow it (`WH/IN/0001`, `ND/OUT/0003`).

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
│       ├── seed.py           # demo data + GST slabs + backfill
│       └── routers/          # auth, settings, products, operations, inventory
└── frontend/                 # React + Vite app
    ├── vite.config.js        # dev server + /api proxy
    └── src/
        ├── App.jsx           # routes + auth gate
        ├── api.js            # fetch wrapper with JWT
        ├── hooks.js          # useApi, useDebounced
        ├── styles.css        # design tokens + components
        ├── components/       # Layout, ui (pager, modal, stepper…), icons, CategoryManager
        └── pages/            # Auth, Dashboard, Operations, OperationDetail,
                              # Catalog (products + stock), MoveHistory, Settings, Taxes
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
| Catalogue | `/products`, `/categories`, `/taxes`, `/category-taxes` |
| Structure | `/warehouses`, `/locations` |
| Operations | `/operations`, `/operations/{id}/{todo,check,validate,cancel,duplicate}`, `/contacts`, `/moves` |
| Inventory | `/stock`, `/stock/adjust`, `/dashboard`, `/reorder/suggestions`, `/reorder/receipt` |

---

## Design decisions and known limitations

- **Schema management:** tables are created on startup with `create_all`, and later column additions are
  applied by small idempotent `ALTER TABLE … IF NOT EXISTS` statements in `main.py`. This keeps setup to one
  command for a hackathon. For production, switch to Alembic migrations.
- **Docker runs the dev servers** (Uvicorn `--reload`, Vite dev). For production build the frontend
  (`npm run build`) and serve the static files behind a reverse proxy.
- **Tax model:** intra-state GST (CGST + SGST) is displayed. Inter-state IGST, e-invoicing and GST returns are not implemented.
- **Roles:** all users have the same permissions. Inventory-manager vs warehouse-staff roles are not modelled.
- **Pagination** is done in the browser, which is fine for thousands of rows but not millions.
- **No automated test suite yet.** Behaviour was verified through the API and in the browser.
- **Security notes:** JWTs live in `localStorage`; there is no rate limiting on login or OTP endpoints beyond the
  5-attempt OTP cap. Add both before going to production.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `failed to connect to the docker API` | Start Docker Desktop and wait until it says it's running. |
| Page doesn't update after editing frontend files (Docker on Windows) | Already handled: Vite polling is on in `vite.config.js`. Restart with `docker compose restart frontend`. |
| No OTP email arrives | Check `BREVO_API_KEY`, that `BREVO_SENDER_EMAIL` is a *verified* sender in Brevo, and your spam folder. Without Brevo the code is in `docker compose logs backend`. |
| Want a clean database | `docker compose down -v && docker compose up --build` |
| Port already in use | Change the host side of the `ports:` mapping in `docker-compose.yml`. |
