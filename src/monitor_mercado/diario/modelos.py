"""Modelo de datos del diario (tabla ``operaciones``)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from monitor_mercado.db import Base


class TipoMovimiento(StrEnum):
    """Compra o venta."""

    COMPRA = "compra"
    VENTA = "venta"


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class Movimiento(Base):
    """Una compra o una venta que hiciste.

    ``precio`` es por acción, en ``moneda`` (la del activo, como en tu broker). Puede
    quedar vacío en una compra importada sin costo conocido. ``comision`` va en la
    misma moneda y se suma al costo (compras) o se resta de lo cobrado (ventas).
    """

    __tablename__ = "operaciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[date] = mapped_column(index=True)
    simbolo: Mapped[str] = mapped_column(String(20), index=True)
    tipo: Mapped[TipoMovimiento] = mapped_column(
        Enum(TipoMovimiento, native_enum=False, values_callable=lambda e: [m.value for m in e])
    )
    cantidad: Mapped[float]
    precio: Mapped[float | None] = mapped_column(default=None)
    moneda: Mapped[str] = mapped_column(String(8), default="USD")
    comision: Mapped[float] = mapped_column(default=0.0)
    nota: Mapped[str | None] = mapped_column(String(300), default=None)
    creada_en: Mapped[datetime] = mapped_column(default=_ahora)

    def __repr__(self) -> str:
        return f"Movimiento(#{self.id} {self.fecha} {self.tipo} {self.cantidad} {self.simbolo} @ {self.precio})"
