"""Set-based queries shared by the list, dashboard, report and export endpoints.

Each one answers for *many* products in a single round-trip. The old code asked the database one question per
product (or per product-and-location), which is what made big catalogues crawl."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Location, Operation, OperationLine, Product, StockQuant


def internal_stock(warehouse_id: int | None = None, location_id: int | None = None):
    """Select of (product_id, qty) summed over stock locations, optionally limited to a warehouse / one location."""
    stmt = (
        select(StockQuant.product_id.label("product_id"), func.sum(StockQuant.quantity).label("qty"))
        .join(Location, Location.id == StockQuant.location_id)
        .where(Location.type == "internal")
        .group_by(StockQuant.product_id)
    )
    if warehouse_id:
        stmt = stmt.where(Location.warehouse_id == warehouse_id)
    if location_id:
        stmt = stmt.where(Location.id == location_id)
    return stmt


def on_hand_map(db: Session, product_ids: list[int], warehouse_id: int | None = None, location_id: int | None = None) -> dict[int, float]:
    if not product_ids:
        return {}
    sub = internal_stock(warehouse_id, location_id).where(StockQuant.product_id.in_(product_ids)).subquery()
    return {pid: float(q or 0) for pid, q in db.execute(select(sub.c.product_id, sub.c.qty)).all()}


def reserved_map(db: Session, product_ids: list[int]) -> dict[tuple[int, int], float]:
    """(product, source location) -> units promised to Ready deliveries and transfers."""
    if not product_ids:
        return {}
    stmt = (
        select(OperationLine.product_id, Operation.source_location_id, func.sum(OperationLine.quantity))
        .join(Operation, Operation.id == OperationLine.operation_id)
        .where(
            Operation.status == "ready",
            Operation.type.in_(["OUT", "INT"]),
            OperationLine.product_id.in_(product_ids),
        )
        .group_by(OperationLine.product_id, Operation.source_location_id)
    )
    return {(pid, loc): float(q or 0) for pid, loc, q in db.execute(stmt).all()}


def incoming_map(db: Session, warehouse_id: int | None = None, product_ids: list[int] | None = None) -> dict[int, float]:
    """Units already on order: open receipts that have not been validated yet."""
    stmt = (
        select(OperationLine.product_id, func.sum(OperationLine.quantity))
        .join(Operation, Operation.id == OperationLine.operation_id)
        .where(Operation.type == "IN", Operation.status.in_(["draft", "waiting", "ready"]))
        .group_by(OperationLine.product_id)
    )
    if warehouse_id:
        stmt = stmt.where(Operation.warehouse_id == warehouse_id)
    if product_ids is not None:
        if not product_ids:
            return {}
        stmt = stmt.where(OperationLine.product_id.in_(product_ids))
    return {pid: float(q or 0) for pid, q in db.execute(stmt).all()}


def cost_expr():
    """Best known unit cost of a product: average cost, else purchase price, else sales price."""
    return func.coalesce(func.nullif(Product.avg_cost, 0), func.nullif(Product.cost_price, 0), Product.unit_cost)
