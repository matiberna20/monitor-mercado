"""Base de datos SQLite compartida por todos los módulos (alertas, noticias, ...)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    """Base declarativa de SQLAlchemy: todas las tablas heredan de acá."""


def crear_motor(ruta: Path | str) -> Engine:
    """Crea el motor SQLite y todas las tablas que falten.

    Args:
        ruta: Ruta del archivo .db, o ":memory:" para una base temporal (tests).
    """
    # Importar los modelos registra sus tablas en Base.metadata antes de crearlas.
    from monitor_mercado.alertas import modelos as _alertas  # noqa: F401
    from monitor_mercado.noticias import modelos as _noticias  # noqa: F401
    from monitor_mercado.resultados import modelos as _resultados  # noqa: F401
    from monitor_mercado.cartera import servicio as _cartera  # noqa: F401
    from monitor_mercado.stops import modelos as _stops  # noqa: F401

    if str(ruta) == ":memory:":
        # Una base en memoria existe solo dentro de su conexión: StaticPool hace
        # que todos los hilos compartan la misma, si no cada hilo vería otra vacía.
        motor = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        motor = create_engine(
            f"sqlite+pysqlite:///{Path(ruta).as_posix()}",
            connect_args={"check_same_thread": False},
        )
    Base.metadata.create_all(motor)
    return motor
