"""Filters shared by the dashboard, operation lists and move history so they always agree."""
from sqlalchemy import Select, or_, select

from .models import Location, Operation, OperationLine, Product


def op_filters(
    stmt: Select,
    *,
    type: str | None = None,
    status: str | None = None,
    warehouse_id: int | None = None,
    location_id: int | None = None,
    category_id: int | None = None,
    q: str | None = None,
) -> Select:
    if type:
        stmt = stmt.where(Operation.type == type)
    if status:
        stmt = stmt.where(Operation.status == status)
    if warehouse_id:
        # a transfer between warehouses belongs to both of them
        in_wh = select(Location.id).where(Location.warehouse_id == warehouse_id)
        stmt = stmt.where(
            or_(
                Operation.warehouse_id == warehouse_id,
                Operation.source_location_id.in_(in_wh),
                Operation.dest_location_id.in_(in_wh),
            )
        )
    if location_id:
        stmt = stmt.where(or_(Operation.source_location_id == location_id, Operation.dest_location_id == location_id))
    if category_id:
        in_category = (
            select(OperationLine.operation_id)
            .join(Product, Product.id == OperationLine.product_id)
            .where(Product.category_id == category_id)
        )
        stmt = stmt.where(Operation.id.in_(in_category))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Operation.reference.ilike(like), Operation.contact.ilike(like)))
    return stmt
