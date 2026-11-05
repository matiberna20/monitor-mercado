"""Modelo de datos de los stops (tabla SQLite vía SQLAlchemy)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from monitor_mercado.db import Base


class TipoStop(StrEnum):
    """Contra qué se mide la caída."""

    STOP_LOSS = "stop_loss"  # desde tu precio de compra
    TRAILING = "trailing"  # desde el máximo desde que tenés la posición


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class Stop(Base):
    """Un stop sobre una posición de la cartera.

    Funciona como una alerta repetitiva de "baja de": avisa cuando el precio cruza el
    nivel del stop, queda en espera hasta que el precio vuelva a subir por encima y
    respeta el tiempo de enfriamiento de las alertas. Así no avisa dos veces lo mismo.
    Todos los precios se guardan en USD.
    """

    __tablename__ = "stops"

    id: Mapped[int] = mapped_column(primary_key=True)
    simbolo: Mapped[str] = mapped_column(String(20), index=True)
    tipo: Mapped[TipoStop] = mapped_column(
        Enum(TipoStop, native_enum=False, values_callable=lambda e: [m.value for m in e])
    )
    porcentaje: Mapped[float]  # fracción: 0.10 = 10%
    por_defecto: Mapped[bool] = mapped_column(default=False)  # creado desde config.yaml
    activa: Mapped[bool] = mapped_column(default=True, index=True)
    armada: Mapped[bool] = mapped_column(default=True)
    maximo: Mapped[float | None] = mapped_column(default=None)  # solo trailing, en USD
    creada_en: Mapped[datetime] = mapped_column(default=_ahora)
    ultimo_disparo: Mapped[datetime | None] = mapped_column(default=None)
    veces_disparada: Mapped[int] = mapped_column(default=0)

    def __repr__(self) -> str:
        return f"Stop(#{self.id} {self.simbolo} {self.tipo} {self.porcentaje:.1%} activa={self.activa})"
