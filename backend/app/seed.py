from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Category, Location, Product, Warehouse
from . import stock


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
    desk = Product(name="Desk", sku="DESK001", category_id=furniture.id, unit_cost=3000, reorder_min=10)
    table = Product(name="Table", sku="TABLE001", category_id=furniture.id, unit_cost=3000, reorder_min=10)
    db.add_all([desk, table])
    db.flush()
    db.refresh(s1), db.refresh(s2)
    s1.warehouse, s2.warehouse = wh, wh
    stock.adjust(db, desk, s1, 50, None)
    stock.adjust(db, table, s1, 50, None)
    db.commit()
