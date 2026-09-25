"""Modelo de datos de las alertas (tabla SQLite vía SQLAlchemy)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Enum, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Operacion(StrEnum):
    """Para qué querés el aviso: comprar o vender."""

    COMPRA = "compra"
    VENTA = "venta"


class Condicion(StrEnum):
    """Qué tiene que pasar para que se dispare la alerta."""

    SUBE_DE = "sube_de"  # el precio llega o supera el umbral
    BAJA_DE = "baja_de"  # el precio llega o cae por debajo del umbral
    VARIACION_SUBE = "variacion_sube"  # sube X% o más en el día
    VARIACION_BAJA = "variacion_baja"  # cae X% o más en el día

    @property
    def es_porcentual(self) -> bool:
        """True si el umbral es un porcentaje y no un precio."""
        return self in (Condicion.VARIACION_SUBE, Condicion.VARIACION_BAJA)


class Moneda(StrEnum):
    """Moneda en la que está expresado el umbral de precio."""

    USD = "USD"
    ARS = "ARS"


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _enum(tipo: type[StrEnum]) -> Enum:
    # Guarda el valor ("compra") y no el nombre ("COMPRA"): la base queda legible.
    return Enum(tipo, native_enum=False, values_callable=lambda e: [m.value for m in e])


class Base(DeclarativeBase):
    """Base declarativa de SQLAlchemy."""


class Alerta(Base):
    """Una alerta de precio.

    El campo ``armada`` implementa la lógica de "cruce": una alerta solo se
    dispara cuando el precio pasa de no cumplir la condición a cumplirla. Si al
    crearla el precio ya está del otro lado del umbral, se crea desarmada y se
    arma recién cuando el precio vuelve a no cumplir la condición. Así se evita
    un aviso inmediato e inútil, y las alertas repetitivas no avisan en cada
    revisión mientras el precio sigue del mismo lado.
    """

    __tablename__ = "alertas"

    id: Mapped[int] = mapped_column(primary_key=True)
    simbolo: Mapped[str] = mapped_column(String(20), index=True)
    operacion: Mapped[Operacion] = mapped_column(_enum(Operacion))
    condicion: Mapped[Condicion] = mapped_column(_enum(Condicion))
    umbral: Mapped[float]
    moneda: Mapped[Moneda] = mapped_column(_enum(Moneda), default=Moneda.USD)
    repetir: Mapped[bool] = mapped_column(default=False)
    activa: Mapped[bool] = mapped_column(default=True, index=True)
    armada: Mapped[bool] = mapped_column(default=True)
    creada_en: Mapped[datetime] = mapped_column(default=_ahora)
    ultimo_disparo: Mapped[datetime | None] = mapped_column(default=None)
    veces_disparada: Mapped[int] = mapped_column(default=0)
    precio_al_crear: Mapped[float | None] = mapped_column(default=None)
    nota: Mapped[str | None] = mapped_column(String(200), default=None)

    def __repr__(self) -> str:
        return (
            f"Alerta(#{self.id} {self.simbolo} {self.operacion} {self.condicion} "
            f"{self.umbral} {self.moneda} activa={self.activa})"
        )
