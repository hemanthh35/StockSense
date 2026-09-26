from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Exact decimals in the database (no binary-float drift). They come back to Python as floats, which is fine
# because every stored value is already rounded to its scale and money is *summed* with Decimal (see pricing.py).
Money = Numeric(14, 4, asdecimal=False)  # prices and costs
Qty = Numeric(14, 3, asdecimal=False)  # quantities
Rate = Numeric(7, 3, asdecimal=False)  # tax percentages


class Base(DeclarativeBase):
    pass


class User(Base):
    """role: staff | manager | admin (see deps.py for what each may do)."""

    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    login_id: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10), default="staff")
    active: Mapped[bool] = mapped_column(default=True)
    low_stock_digest: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OtpCode(Base):
    __tablename__ = "otp_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(default=False)


class Setting(Base):
    """Tiny key/value store for system state such as "digest last sent"."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), default="")


class Party(Base):
    """A supplier and/or customer. kind: vendor | customer | both."""

    __tablename__ = "parties"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    kind: Mapped[str] = mapped_column(String(10), default="both")
    gstin: Mapped[str | None] = mapped_column(String(15))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)  # optimistic locking: bumped on every user edit
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Warehouse(Base):
    __tablename__ = "warehouses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    short_code: Mapped[str] = mapped_column(String(10), unique=True)
    address: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(default=True)
    locations: Mapped[list["Location"]] = relationship(back_populates="warehouse")


class Location(Base):
    """type: internal (tracked stock) | vendor | customer | adjustment (virtual)."""

    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    short_code: Mapped[str] = mapped_column(String(20))
    type: Mapped[str] = mapped_column(String(15), default="internal")
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), index=True)
    active: Mapped[bool] = mapped_column(default=True)
    warehouse: Mapped[Warehouse | None] = relationship(back_populates="locations")

    @property
    def full_name(self) -> str:
        if self.warehouse is not None:
            return f"{self.warehouse.short_code}/{self.short_code}"
        return self.name


class Tax(Base):
    """A reusable tax rate (GST slab, cess, ...). Rates are snapshotted onto document lines."""

    __tablename__ = "taxes"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    rate: Mapped[float] = mapped_column(Rate, default=0)
    kind: Mapped[str] = mapped_column(String(10), default="GST")  # GST | OTHER
    active: Mapped[bool] = mapped_column(default=True)
    is_default: Mapped[bool] = mapped_column(default=False)


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    default_tax_id: Mapped[int | None] = mapped_column(ForeignKey("taxes.id"))
    default_tax: Mapped[Tax | None] = relationship()


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    sku: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), index=True)
    category: Mapped[Category | None] = relationship()
    uom: Mapped[str] = mapped_column(String(20), default="Unit")
    unit_cost: Mapped[float] = mapped_column(Money, default=0)  # the sales price
    cost_price: Mapped[float] = mapped_column(Money, default=0)  # default purchase price (falls back to unit_cost)
    avg_cost: Mapped[float] = mapped_column(Money, default=0)  # weighted average purchase cost
    reorder_min: Mapped[float] = mapped_column(Qty, default=0)
    reorder_qty: Mapped[float] = mapped_column(Qty, default=0)
    hsn_code: Mapped[str | None] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(default=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)  # optimistic locking: bumped on every user edit
    tax_id: Mapped[int | None] = mapped_column(ForeignKey("taxes.id"))
    tax: Mapped[Tax | None] = relationship()


class StockQuant(Base):
    __tablename__ = "stock_quants"
    __table_args__ = (
        UniqueConstraint("product_id", "location_id"),
        CheckConstraint("quantity >= 0", name="ck_stock_quants_nonnegative"),  # last line of defence against negative stock
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    quantity: Mapped[float] = mapped_column(Qty, default=0)


class Sequence(Base):
    __tablename__ = "sequences"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class Operation(Base):
    """type: IN receipt | OUT delivery | INT internal transfer | ADJ adjustment.
    status: draft | waiting | ready | done | cancelled."""

    __tablename__ = "operations"
    __table_args__ = (Index("ix_operations_type_status", "type", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(3), index=True)
    status: Mapped[str] = mapped_column(String(10), default="draft", index=True)
    contact: Mapped[str | None] = mapped_column(String(150))
    schedule_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    responsible_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    source_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    dest_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    done_at: Mapped[datetime | None] = mapped_column(DateTime)
    picked_at: Mapped[datetime | None] = mapped_column(DateTime)
    packed_at: Mapped[datetime | None] = mapped_column(DateTime)
    party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id"), index=True)
    backorder_of_id: Mapped[int | None] = mapped_column(ForeignKey("operations.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)  # optimistic locking: bumped on every change

    responsible: Mapped[User | None] = relationship()
    party: Mapped[Party | None] = relationship()
    warehouse: Mapped[Warehouse] = relationship()
    source_location: Mapped[Location] = relationship(foreign_keys=[source_location_id])
    dest_location: Mapped[Location] = relationship(foreign_keys=[dest_location_id])
    lines: Mapped[list["OperationLine"]] = relationship(
        back_populates="operation", cascade="all, delete-orphan", order_by="OperationLine.id"
    )


class OperationLine(Base):
    __tablename__ = "operation_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    operation_id: Mapped[int] = mapped_column(ForeignKey("operations.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[float] = mapped_column(Qty)
    unit_price: Mapped[float] = mapped_column(Money, default=0)
    tax_rate: Mapped[float] = mapped_column(Rate, default=0)
    tax_name: Mapped[str | None] = mapped_column(String(60))
    ordered_qty: Mapped[float | None] = mapped_column(Qty)  # original demand when a line was validated partially
    cost_price: Mapped[float | None] = mapped_column(Money)  # average cost when the line moved (for margin)
    operation: Mapped[Operation] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()
