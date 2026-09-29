"""Estructuras de las noticias: titular crudo, clasificación y tabla SQLite."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from monitor_mercado.db import Base


class Sentimiento(StrEnum):
    """Impacto probable de una noticia sobre el precio."""

    POSITIVA = "positiva"
    NEGATIVA = "negativa"
    NEUTRA = "neutra"


def _con_utc(fecha: datetime) -> datetime:
    # SQLite devuelve fechas sin zona horaria; se guardan siempre en UTC.
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)


def _normalizar_titulo(titulo: str) -> str:
    # Google News agrega " - Nombre del medio" al final; se quita para deduplicar.
    base = re.sub(r"\s+-\s+[^-]{2,40}$", "", titulo)
    return re.sub(r"\W+", " ", base.lower()).strip()


@dataclass(frozen=True)
class Noticia:
    """Un titular obtenido de alguna fuente, todavía sin clasificar."""

    simbolo: str
    titulo: str
    fuente: str
    url: str
    publicada: datetime  # UTC
    resumen: str = ""

    @property
    def id(self) -> str:
        """Identificador estable: el mismo titular del mismo activo da el mismo id."""
        clave = f"{self.simbolo}|{_normalizar_titulo(self.titulo)}"
        return hashlib.sha1(clave.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Clasificacion:
    """Resultado de analizar una noticia con el modelo de lenguaje."""

    sentimiento: Sentimiento
    puntaje: float  # -1 (muy negativa) a +1 (muy positiva)
    relevancia: float  # 0 (no habla de la empresa) a 1 (la afecta directamente)
    factor: str  # qué factor puede mover el precio, en pocas palabras
    explicacion: str


class NoticiaGuardada(Base):
    """Noticia ya clasificada, guardada para no volver a pagar por clasificarla."""

    __tablename__ = "noticias"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    simbolo: Mapped[str] = mapped_column(String(20), index=True)
    titulo: Mapped[str] = mapped_column(Text)
    fuente: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(Text)
    publicada: Mapped[datetime] = mapped_column(index=True)
    sentimiento: Mapped[str | None] = mapped_column(String(10), default=None)
    puntaje: Mapped[float | None] = mapped_column(default=None)
    relevancia: Mapped[float | None] = mapped_column(default=None)
    factor: Mapped[str | None] = mapped_column(Text, default=None)
    explicacion: Mapped[str | None] = mapped_column(Text, default=None)
    modelo: Mapped[str | None] = mapped_column(String(50), default=None)
    clasificada_en: Mapped[datetime | None] = mapped_column(default=None)

    def a_noticia(self) -> Noticia:
        """Convierte la fila guardada en una ``Noticia``."""
        return Noticia(self.simbolo, self.titulo, self.fuente, self.url, _con_utc(self.publicada))

    def clasificacion(self) -> Clasificacion | None:
        """La clasificación guardada, o None si todavía no se clasificó."""
        if self.sentimiento is None:
            return None
        return Clasificacion(
            Sentimiento(self.sentimiento),
            self.puntaje or 0.0,
            self.relevancia or 0.0,
            self.factor or "",
            self.explicacion or "",
        )


class ResumenNoticias(Base):
    """Último resumen general de noticias de un activo (para no pedirlo de nuevo)."""

    __tablename__ = "resumenes_noticias"

    simbolo: Mapped[str] = mapped_column(String(20), primary_key=True)
    texto: Mapped[str] = mapped_column(Text)
    generado_en: Mapped[datetime]
