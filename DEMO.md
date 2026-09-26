# StockSense demo script (about 6 minutes)

## Before you start

```bash
docker compose up -d
docker compose exec backend python -m app.demo --reset    # loads the demo data
```

Open http://localhost:5173 and sign in as **`demo_admin`** (the password is `DEMO_PASSWORD` in
[`backend/app/demo.py`](backend/app/demo.py)). Re-run the `--reset` command any time to put the data back exactly
as it starts below, for example between two run-throughs.

**What the data contains:** two warehouses (Main Warehouse `WH`, North Depot `ND`), 18 products with HSN codes and
reorder rules, and about 40 documents in every status: a late receipt, a half-picked delivery, two deliveries
waiting for stock, a cross-warehouse transfer, a cancelled receipt and a few stock counts.

## The walkthrough

### 1. Dashboard: "one glance at the business" (1 min)
- Three cards show open work with a status bar and **late / waiting / scheduled** counts. The red "late" number is
  a receipt that should have arrived three days ago.
- Below: **Low stock alerts** and **Recent movements**.
- Use the filter bar: **Document = Deliveries**, then **Status = Waiting**. The cards, KPIs and feed all follow.
  Try **Warehouse = North Depot** and then **Clear filters**.

### 2. Stock arrives and unblocks a waiting order (1 min): the headline feature
- Open **Operations → Deliveries** and find the **Waiting** order for *Gemini Furniture* (a Conference Table and a
  Chair). Open it: the table line is **red** with "Short by 2 — not in stock" and a banner explains why.
- **Operations → Receipts → New receipt**: contact *Wood Corner*, product *Conference Table*, quantity 5.
  Note the **price and GST 18% appear on their own**. Click **To do**, then **Validate**.
- Go back to that delivery: it has moved from **Waiting to Ready** by itself.

### 3. Pick, pack, validate (1 min)
- Open the Ready delivery for *Wood Corner*: it shows **Picked ✓ / Packed ·**. Click **Mark packed**, then
  **Validate**. Stock drops and a **Print** button appears; print it to show the document header and the
  **CGST / SGST split** with the grand total.
- Open the Ready delivery for *Azure Interior*: the big button reads **Mark picked**. The workflow won't
  validate a delivery until it's picked and packed.

### 4. Tax that never has to be re-entered (45 s)
- **Products → New product**: choose category *Pantry* and leave Tax on **Automatic**. It resolves to
  **GST 5%** because that category's default is 5%. Save.
- **Settings → Taxes**: add a new slab (for example GST 40%) and it is immediately selectable everywhere. Old
  documents keep the rate they were created with.

### 5. Reorder suggestions (45 s)
- **Dashboard → Low stock alerts**: *USB-C Hub* and *Sticky Notes* suggest an order quantity, *Keyboard* says
  **Covered by incoming** (its receipt is already on the way).
- Click **Reorder 4 items** and a draft receipt is created with the suggested quantities. Go back: the suggestions
  are now covered, so they can't be double-ordered.

### 6. Multi-warehouse and transfers (45 s)
- **Operations → Internal transfers**: open the Ready transfer of Paper from `WH/Stock1` to `ND/RackB`. It crosses
  warehouses, and shows under both warehouses when filtered.
- **Operations → Receipts → New receipt**: switch **Warehouse** to *North Depot*. The locations change and the
  reference will read `ND/IN/…`.

### 7. Stock counts and the ledger (45 s)
- **Stock**: click **Update** on any row, enter the counted quantity, and see the live difference. It is logged
  as an adjustment.
- **Move History**: incoming moves are **green**, outgoing **red**. Search a SKU such as `MOUSE01`: search works
  on reference, contact, product name and SKU. Switch to **Kanban**.

### 8. Import and export (30 s)
- **Products → Import**: download the template, add a row, upload it. You get a row-by-row **preview**
  (new / update / skipped, with reasons) before anything is written. **Export CSV** exists on products, stock, move
  history and every operation list.

### 9. Housekeeping (30 s)
- **Products → Categories**: rename or delete categories. A category in use can't be deleted.
- Open a product with stock and click **Archive**: it's refused with a clear reason. Archived items stay in history
  but disappear from pickers. **Settings → Warehouses / Locations** work the same way.
- **My profile** (top right): change email and password.

## If something goes wrong
| Symptom | Fix |
|---|---|
| Data looks different from the script | `docker compose exec backend python -m app.demo --reset` |
| Page is blank | Make sure Docker is running: `docker compose ps` |
| OTP email doesn't arrive | Check the Brevo settings in `.env` (see README) |
