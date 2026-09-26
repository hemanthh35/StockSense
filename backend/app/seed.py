from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Category, Location, OperationLine, Product, Tax, Warehouse
from . import stock


GST_SLABS = [0, 5, 12, 18, 28]


def seed_taxes(db: Session) -> None:
    """GST slabs on first run; also back-fills products and lines created before taxes existed."""
    if not db.scalar(select(Tax)):
        for r in GST_SLABS:
            db.add(Tax(name=f"GST {r}%", rate=r, kind="GST", is_default=(r == 18)))
        db.commit()
    default = db.scalar(select(Tax).where(Tax.is_default.is_(True)))
    if default:
        for p in db.scalars(select(Product).where(Product.tax_id.is_(None))):
            p.tax_id = default.id
        db.flush()
    for ln in db.scalars(select(OperationLine).where(OperationLine.unit_price.is_(None) | (OperationLine.unit_price == 0))):
        prod = db.get(Product, ln.product_id)
        if prod and prod.unit_cost:
            ln.unit_price = prod.unit_cost
            ln.tax_rate = prod.tax.rate if prod.tax else 0
            ln.tax_name = prod.tax.name if prod.tax else None
    db.commit()


def seed(db: Session) -> None:
    """Idempotent: virtual locations always, demo warehouse/products only on a fresh DB."""
    if not db.scalar(select(Location).where(Location.type == "vendor")):
        db.add_all(
            [
                Location(name="vendor", short_code="vendor", type="vendor"),
                Location(name="customer", short_code="customer", type="customer"),
                Location(name="Inventory Adjustment", short_code="adjustment", type="adjustment"),
            ]
        )
        db.commit()

    seed_taxes(db)

    if db.scalar(select(Warehouse)):
        return

    wh = Warehouse(name="Main Warehouse", short_code="WH", address="Ahmedabad, Gujarat")
    db.add(wh)
    db.flush()
    s1 = Location(name="Stock1", short_code="Stock1", type="internal", warehouse_id=wh.id)
    s2 = Location(name="Stock2", short_code="Stock2", type="internal", warehouse_id=wh.id)
    furniture = Category(name="Furniture")
    db.add_all([s1, s2, furniture])
    db.flush()
    desk = Product(name="Desk", sku="DESK001", category_id=furniture.id, unit_cost=3000, reorder_min=10, hsn_code="9403")
    table = Product(name="Table", sku="TABLE001", category_id=furniture.id, unit_cost=3000, reorder_min=10, hsn_code="9403")
    db.add_all([desk, table])
    db.flush()
    db.refresh(s1), db.refresh(s2)
    s1.warehouse, s2.warehouse = wh, wh
    stock.adjust(db, desk, s1, 50, None)
    stock.adjust(db, table, s1, 50, None)
    db.commit()
    seed_taxes(db)  # give the demo products the default tax
