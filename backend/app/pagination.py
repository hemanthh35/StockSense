"""Optional server-side pagination.

Send `?page=1&page_size=25` and a list endpoint answers with an envelope
`{items, total, page, page_size, pages}`. Without `page` it returns the plain list exactly as before, so small
lookups (dropdowns, scripts, exports) keep working unchanged."""
import math

from fastapi import Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 25


class PageParams:
    """FastAPI dependency: `page: PageParams = Depends()`."""

    def __init__(
        self,
        page: int | None = Query(None, ge=1, description="1-based page number; omit for the full list"),
        page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    ):
        self.page = page
        self.size = page_size

    @property
    def enabled(self) -> bool:
        return self.page is not None

    @property
    def offset(self) -> int:
        return ((self.page or 1) - 1) * self.size


def count_rows(db: Session, stmt) -> int:
    """COUNT(*) over any select (ordering is irrelevant to the count and is dropped)."""
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def envelope(items: list, total: int, p: PageParams) -> dict:
    return {
        "items": items,
        "total": total,
        "page": p.page,
        "page_size": p.size,
        "pages": max(1, math.ceil(total / p.size)),
    }


def slice_stmt(stmt, p: PageParams):
    return stmt.limit(p.size).offset(p.offset)
