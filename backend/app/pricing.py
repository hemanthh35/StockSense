"""Tax resolution and document totals. Rates are copied onto each line so old documents never change.
All money arithmetic is done in Decimal and rounded half-up to whole paise, so totals never drift."""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Category, Operation, OperationLine, Product, Tax

PAISE = Decimal("0.01")
HUNDRED = Decimal(100)


def _d(x) -> Decimal:
    return Decimal(str(x if x is not None else 0))


def default_tax(db: Session) -> Tax | None:
    return db.scalar(select(Tax).where(Tax.is_default.is_(True), Tax.active.is_(True)))


def auto_tax(db: Session, category_id: int | None) -> Tax | None:
    """Tax a new product should get: its category's default, else the global default."""
    if category_id:
        cat = db.get(Category, category_id)
        if cat and cat.default_tax and cat.default_tax.active:
            return cat.default_tax
    return default_tax(db)


def default_price(product: Product, op_type: str | None) -> float:
    """Receipts are bought at the purchase price; deliveries and the rest use the sales price."""
    return (product.cost_price or product.unit_cost) if op_type == "IN" else product.unit_cost


def fill_line(line: OperationLine, product: Product, unit_price: float | None = None, op_type: str | None = None) -> None:
    line.unit_price = default_price(product, op_type) if unit_price is None else unit_price
    tax = product.tax if product.tax and product.tax.active else None
    line.tax_rate = tax.rate if tax else 0
    line.tax_name = tax.name if tax else None


def _line(ln: OperationLine) -> tuple[Decimal, Decimal]:
    sub = (_d(ln.quantity) * _d(ln.unit_price)).quantize(PAISE, ROUND_HALF_UP)
    tax = (sub * _d(ln.tax_rate) / HUNDRED).quantize(PAISE, ROUND_HALF_UP)
    return sub, tax


def line_amounts(ln: OperationLine) -> tuple[float, float]:
    sub, tax = _line(ln)
    return float(sub), float(tax)


def op_totals(op: Operation) -> dict:
    subtotal = tax_total = Decimal(0)
    groups: dict[tuple[str, Decimal], dict] = {}
    for ln in op.lines:
        sub, tax = _line(ln)
        subtotal += sub
        tax_total += tax
        if ln.tax_name:
            g = groups.setdefault((ln.tax_name, _d(ln.tax_rate)), {"name": ln.tax_name, "rate": float(ln.tax_rate or 0), "base": Decimal(0), "amount": Decimal(0)})
            g["base"] += sub
            g["amount"] += tax
    return {
        "subtotal": float(subtotal),
        "tax_total": float(tax_total),
        "total": float(subtotal + tax_total),
        "tax_breakdown": [
            {**g, "base": float(g["base"]), "amount": float(g["amount"])} for g in sorted(groups.values(), key=lambda g: g["rate"])
        ],
    }
