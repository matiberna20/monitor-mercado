"""Tablas SQLite de la Etapa 4."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from monitor_mercado.db import Base


class EmpresaSeguida(Base):
    """Empresa cuyos resultados querés seguir (te avisa cuando presenta)."""

    __tablename__ = "empresas_seguidas"

    simbolo: Mapped[str] = mapped_column(String(20), primary_key=True)
    desde: Mapped[datetime]


class ConsensoGuardado(Base):
    """Consenso de analistas guardado ANTES de la presentación (Yahoo no guarda el histórico)."""

    __tablename__ = "consensos"

    simbolo: Mapped[str] = mapped_column(String(20), primary_key=True)
    fecha_evento: Mapped[date] = mapped_column(primary_key=True)
    eps: Mapped[float | None]
    ingresos: Mapped[float | None]
    moneda_ingresos: Mapped[str | None] = mapped_column(String(10))
    capturado_en: Mapped[datetime]


class AvisoResultados(Base):
    """Avisos ya enviados, para no repetirlos (tipo: "previo" o "resultado")."""

    __tablename__ = "avisos_resultados"

    simbolo: Mapped[str] = mapped_column(String(20), primary_key=True)
    fecha_evento: Mapped[date] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(10), primary_key=True)
    enviado_en: Mapped[datetime]


class ComunicadoGuardado(Base):
    """Análisis del comunicado ya hecho con Claude (para no pagarlo dos veces)."""

    __tablename__ = "comunicados"

    simbolo: Mapped[str] = mapped_column(String(20), primary_key=True)
    fecha_evento: Mapped[date] = mapped_column(primary_key=True)
    formulario: Mapped[str] = mapped_column(String(10))
    url: Mapped[str] = mapped_column(Text)
    analisis: Mapped[str] = mapped_column(Text)
