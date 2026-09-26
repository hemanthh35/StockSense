# StockSense API (backend)

FastAPI service that owns all business rules: authentication, catalogue, stock movements,
taxes, reordering and reporting. The React app is a thin client over this API.

- **Runtime:** Python 3.12 · FastAPI 0.115 · Uvicorn 0.32
- **Data:** PostgreSQL 16 · SQLAlchemy 2.0 (typed `Mapped[]` models) · psycopg 3
- **Validation & config:** Pydantic 2 · pydantic-settings
- **Security:** bcrypt 4.2 (passwords, OTPs are SHA-256 hashed) · PyJWT 2.9 (bearer tokens)
- **Email:** Brevo transactional API called with `httpx`

Base URL: `http://localhost:8000/api` · Swagger UI: `http://localhost:8000/docs` · Health: `GET /api/health`

---

## Running

### With Docker (recommended)
From the repository root:

```bash
cp .env.example .env
docker compose up --build
```

The `backend/app` folder is bind-mounted and Uvicorn runs with `--reload`, so edits apply instantly.

### Without Docker
```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://stocksense:stocksense@localhost:5432/stocksense
export SECRET_KEY=dev-secret
uvicorn app.main:app --reload --port 8000
```
You still need a Postgres 16 instance reachable at `DATABASE_URL`
(`docker compose up -d db` starts just the database).

### Configuration (`app/config.py`)

| Setting | Env var | Default |
|---|---|---|
| Database URL | `DATABASE_URL` | `postgresql+psycopg://stocksense:stocksense@localhost:5432/stocksense` |
| JWT secret | `SECRET_KEY` | `dev-secret` (change it) |
| Token lifetime (min) | `ACCESS_TOKEN_MINUTES` | `720` |
| Brevo API key | `BREVO_API_KEY` | empty → OTP is logged instead of emailed |
| Brevo sender email | `BREVO_SENDER_EMAIL` | empty (must be a verified Brevo sender) |
| Brevo sender name | `BREVO_SENDER_NAME` | `StockSense` |

---

## Code layout

| File | Responsibility |
|---|---|
| `main.py` | Creates the app, CORS, mounts routers under `/api`. On startup: `create_all` → column migrations → seed. |
| `config.py` | Typed settings loaded from the environment. |
| `db.py` | SQLAlchemy engine, `SessionLocal`, `get_db` dependency. |
| `models.py` | All tables (see below). |
| `security.py` | Password hashing, password-strength rules, JWT create/decode. |
| `deps.py` | `current_user` dependency; returns 401 for missing/invalid tokens. |
| `mail.py` | `send_otp()` via Brevo. On failure or missing config it logs the OTP so development never blocks. |
| `stock.py` | **The stock engine**: references, on-hand, reservations, availability, workflow actions, adjustments. |
| `pricing.py` | Tax resolution for products/lines and document totals with per-tax breakdown. |
| `filters.py` | `op_filters()`: one place that applies type/status/warehouse/location/category/search to operation queries. |
| `seed.py` | Virtual locations, GST slabs, demo warehouse and products; back-fills older rows. Idempotent. |
| `routers/auth.py` | Sign-up, login, profile, OTP reset. |
| `routers/settings.py` | Warehouses, locations, taxes, per-category default tax. |
| `routers/products.py` | Categories and products. |
| `routers/operations.py` | Receipts, deliveries, transfers, workflow actions, contacts, move history. |
| `routers/inventory.py` | Stock view, adjustments, dashboard, reorder suggestions. |

---

## Data model

| Table | Key columns | Notes |
|---|---|---|
| `users` | `login_id` (unique, 6–12), `email` (unique), `password_hash` | |
| `otp_codes` | `email`, `code_hash`, `expires_at`, `attempts`, `used` | 10-minute expiry, 5 attempts |
| `warehouses` | `name`, `short_code` (unique), `address` | Short code prefixes references |
| `locations` | `name`, `short_code`, `type`, `warehouse_id` | `type`: `internal` (holds stock) · `vendor` · `customer` · `adjustment` (virtual) |
| `taxes` | `name` (unique), `rate`, `kind` (`GST`/`OTHER`), `active`, `is_default` | Only one default |
| `categories` | `name` (unique), `default_tax_id` | |
| `products` | `name`, `sku` (unique), `category_id`, `uom`, `unit_cost`, `hsn_code`, `tax_id`, `reorder_min`, `reorder_qty` | |
| `stock_quants` | `product_id`, `location_id`, `quantity` | Unique per product+location; only `internal` locations |
| `sequences` | `key` (`<warehouse id>/<type>`), `value` | Locked with `SELECT … FOR UPDATE` when numbering |
| `operations` | `reference` (unique), `type`, `status`, `contact`, `schedule_date`, `responsible_id`, `warehouse_id`, `source_location_id`, `dest_location_id`, `done_at` | `type`: `IN` `OUT` `INT` `ADJ` |
| `operation_lines` | `operation_id`, `product_id`, `quantity`, `unit_price`, `tax_rate`, `tax_name` | Price and tax are **snapshots** |

There is no separate ledger table: **operations + lines are the ledger**. Move history is derived
from them (direction comes from the source/destination location types).

---

## Business logic

### Workflow (`stock.py`)

```
Receipt   : draft ──todo──▶ ready ──validate──▶ done
Delivery  : draft ──todo──▶ ready ──validate──▶ done
                     └─short on stock─▶ waiting ──(stock arrives / check)──▶ ready
Any open state ──cancel──▶ cancelled
```

- `todo` (draft → ready). For outgoing moves, if any line is short the document goes to `waiting` instead
  and the response carries a notification message.
- `check` (waiting → ready) re-tests availability.
- `validate` (ready → done) re-tests availability, then moves stock: subtract from the source location,
  add to the destination (virtual locations are ignored). Afterwards every `waiting` document is re-checked and
  promoted to `ready` if it can now be served.
- Editing a document resets it to `draft`. Done and cancelled documents are immutable.

### Availability and reservation
`free = on hand at the source location − quantity on OTHER ready OUT/INT documents from that location`.
A line is *short* when the document's total need for that product exceeds `free`.
Only outgoing moves from `internal` locations are checked.

### Adjustments
`POST /stock/adjust` sets the on-hand quantity to a counted value and records a **done** `ADJ` operation for the
difference (from/to the virtual "Inventory Adjustment" location). New-product initial stock uses the same path.

### Warehouses and locations
- Receipts and deliveries belong to one warehouse; the chosen location must be an `internal` location in it.
- Internal transfers may cross warehouses; the document takes its reference from the **From** location's warehouse.
- The warehouse of an existing document is fixed (its reference prefix depends on it).

### Taxes (`pricing.py`)
- A product's tax is set explicitly, or resolved on create as *category default → global default*.
  `tax_id = 0` means "no tax"; omitting it means "automatic".
- When a line is saved, `unit_price` (defaults to the product's `unit_cost`) and the tax rate/name are copied onto it.
  Later rate changes therefore only affect drafts you re-save, never validated documents.
- Totals: `subtotal = Σ qty × price`, `tax = Σ subtotal × rate`, plus a breakdown per tax. The UI splits GST into CGST/SGST.

### Reordering (`routers/inventory.py`)
For each product with a rule (`reorder_min > 0` or `reorder_qty > 0`):
`effective = on hand + quantity on open receipts`. If `effective ≤ reorder_min` then
`need = reorder_min − effective` and the suggestion is `reorder_qty × ceil(need / reorder_qty)`
(or `max(need, 1)` when no reorder quantity is set). Open receipts count, so pressing the button twice never double-orders.

### Search (`filters.py`)
`q` matches operation reference, contact, or **any line's product name/SKU**. In Move History, when the match
was by product, only that product's rows are shown.

---

## Endpoints

All paths are under `/api`. Errors use `{"detail": "message"}` with 401 (auth), 404, 409 (conflict/state) or 422 (validation).

### Auth
| Method | Path | Body / notes |
|---|---|---|
| POST | `/auth/signup` | `login_id`, `email`, `password`, `confirm_password` → `{token, user}` |
| POST | `/auth/login` | `login_id`, `password` → `{token, user}`. Wrong credentials: 401 `Invalid Login Id or Password` |
| GET | `/auth/me` | Current user |
| POST | `/auth/forgot-password` | `email`. Always answers the same message. Sends the OTP if the account exists |
| POST | `/auth/reset-password` | `email`, `otp`, `new_password`, `confirm_password` |

### Settings
| Method | Path | Notes |
|---|---|---|
| GET/POST | `/warehouses` | `name`, `short_code`, `address` |
| PUT | `/warehouses/{id}` | |
| GET | `/locations` | `?warehouse_id=` `?internal_only=true` |
| POST/PUT | `/locations`, `/locations/{id}` | `name`, `short_code`, `warehouse_id` |
| GET | `/taxes` | `?include_inactive=true` |
| POST/PUT | `/taxes`, `/taxes/{id}` | `name`, `rate` (0–100), `kind`, `active`, `is_default` |
| GET | `/category-taxes` | Categories with their default tax and product counts |
| PUT | `/category-taxes/{id}` | `default_tax_id` (or null) |

### Catalogue
| Method | Path | Notes |
|---|---|---|
| GET | `/categories` | Includes `products` count |
| POST | `/categories` | `name` (returns the existing one if the name already exists) |
| PUT | `/categories/{id}` | Rename; 409 on duplicate name |
| DELETE | `/categories/{id}` | 409 while products still use it |
| GET | `/products` | `?q=` (name/SKU) `?category_id=` |
| POST/PUT | `/products`, `/products/{id}` | `name`, `sku`, `category_id`, `uom`, `unit_cost`, `hsn_code`, `tax_id`, `reorder_min`, `reorder_qty`; on create also `initial_stock`, `initial_location_id` |

### Operations
| Method | Path | Notes |
|---|---|---|
| GET | `/operations` | `?type=IN\|OUT\|INT\|ADJ` `?status=` `?q=` `?warehouse_id=` `?location_id=` `?category_id=`; includes `total` |
| POST | `/operations` | `type` (IN/OUT/INT), `contact`, `schedule_date`, `warehouse_id`, `source_location_id`, `dest_location_id`, `lines[{product_id, quantity, unit_price?}]` |
| GET | `/operations/{id}` | Full document with lines, shortages, totals and tax breakdown |
| PUT | `/operations/{id}` | Same body as create; only while not done/cancelled |
| POST | `/operations/{id}/todo` | draft → ready (or waiting) |
| POST | `/operations/{id}/check` | waiting → ready if stock allows |
| POST | `/operations/{id}/validate` | ready → done, moves stock |
| POST | `/operations/{id}/cancel` | |
| POST | `/operations/{id}/duplicate` | New draft copy at current prices |
| GET | `/contacts` | `?type=` previously used contacts |
| GET | `/moves` | Ledger rows. `?q=` `?status=` `?direction=in\|out\|transfer` `?type=` `?warehouse_id=` `?location_id=` `?category_id=` |

### Inventory
| Method | Path | Notes |
|---|---|---|
| GET | `/stock` | Per product and location: on hand, free to use. `?q=` `?warehouse_id=` `?category_id=` |
| POST | `/stock/adjust` | `product_id`, `location_id`, `counted_qty` |
| GET | `/dashboard` | `?doc_type=` `?status=` `?warehouse_id=` `?location_id=` `?category_id=` → `cards`, `kpis`, `low_stock_items`, `reorder_count` |
| GET | `/reorder/suggestions` | `?warehouse_id=` |
| POST | `/reorder/receipt` | `product_ids` (optional; default all suggested), `warehouse_id` → new draft receipt |

---

## Try it with curl

```bash
API=http://localhost:8000/api

# sign up and keep the token
TOKEN=$(curl -s -X POST $API/auth/signup -H 'Content-Type: application/json' \
  -d '{"login_id":"demo_user1","email":"demo@example.com","password":"Str0ng!Passw","confirm_password":"Str0ng!Passw"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

# create a receipt for 20 units of product 1, then validate it
ID=$(curl -s -X POST $API/operations -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"type":"IN","contact":"Vendor A","lines":[{"product_id":1,"quantity":20}]}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -s -X POST $API/operations/$ID/todo     -H "Authorization: Bearer $TOKEN"
curl -s -X POST $API/operations/$ID/validate -H "Authorization: Bearer $TOKEN"

# stock and movement ledger
curl -s "$API/stock?q=desk" -H "Authorization: Bearer $TOKEN"
curl -s "$API/moves"        -H "Authorization: Bearer $TOKEN"
```

---

## Working on the backend

**Database access**
```bash
docker compose exec db psql -U stocksense -d stocksense
```

**Reset everything:** `docker compose down -v && docker compose up --build`.

**Schema changes.** Adding a *table*: add the model; `create_all` creates it on next start.
Adding a *column to an existing table*: add it to the model **and** append an idempotent statement to
`MIGRATIONS` in `main.py`, for example
`ALTER TABLE products ADD COLUMN IF NOT EXISTS weight DOUBLE PRECISION`.
If you outgrow this, adopt Alembic.

**Adding an endpoint.** Put it in the matching router, depend on `current_user` for auth, keep business rules in
`stock.py` / `pricing.py` rather than in the route, and reuse `op_filters()` for anything that lists operations.

**Conventions**
- Routes stay thin; state changes go through `stock.py` so every entry point follows the same rules.
- Raise `HTTPException` with a clear human message: the UI shows `detail` verbatim.
- Money and quantities are floats rounded to 2 decimals for amounts. Fine for a hackathon; use `Numeric`/`Decimal` in production.

**Not yet covered:** automated tests, rate limiting, roles/permissions, audit of who edited what, Alembic migrations.
