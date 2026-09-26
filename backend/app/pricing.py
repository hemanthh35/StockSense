"""Tax resolution and document totals. Rates are copied onto each line so old documents never change."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Category, Operation, OperationLine, Product, Tax


def default_tax(db: Session) -> Tax | None:
    return db.scalar(select(Tax).where(Tax.is_default.is_(True), Tax.active.is_(True)))


def auto_tax(db: Session, category_id: int | None) -> Tax | None:
    """Tax a new product should get: its category's default, else the global default."""
    if category_id:
        cat = db.get(Category, category_id)
        if cat and cat.default_tax and cat.default_tax.active:
            return cat.default_tax
    return default_tax(db)


def fill_line(line: OperationLine, product: Product, unit_price: float | None = None) -> None:
    line.unit_price = product.unit_cost if unit_price is None else unit_price
    tax = product.tax if product.tax and product.tax.active else None
    line.tax_rate = tax.rate if tax else 0
    line.tax_name = tax.name if tax else None


def line_amounts(ln: OperationLine) -> tuple[float, float]:
    sub = round((ln.quantity or 0) * (ln.unit_price or 0), 2)
    return sub, round(sub * (ln.tax_rate or 0) / 100, 2)


def op_totals(op: Operation) -> dict:
    subtotal = tax_total = 0.0
    groups: dict[tuple[str, float], dict] = {}
    for ln in op.lines:
        sub, tax = line_amounts(ln)
        subtotal += sub
        tax_total += tax
        if ln.tax_name:
            g = groups.setdefault((ln.tax_name, ln.tax_rate), {"name": ln.tax_name, "rate": ln.tax_rate, "base": 0.0, "amount": 0.0})
            g["base"] = round(g["base"] + sub, 2)
            g["amount"] = round(g["amount"] + tax, 2)
    return {
        "subtotal": round(subtotal, 2),
        "tax_total": round(tax_total, 2),
        "total": round(subtotal + tax_total, 2),
        "tax_breakdown": sorted(groups.values(), key=lambda g: g["rate"]),
    }
