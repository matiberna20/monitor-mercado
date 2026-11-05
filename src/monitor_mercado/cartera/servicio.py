"""Valuación de la cartera y resumen del día."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from monitor_mercado.cartera.archivo import Posicion, leer_cartera
from monitor_mercado.cartera.noticias_dia import NoticiaDestacada, noticias_importantes
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.datos.monedas import ConversorMonedas
from monitor_mercado.datos.proveedor import ProveedorPrecios
from monitor_mercado.db import Base
from monitor_mercado.noticias.fuentes import FuenteNoticias
from monitor_mercado.noticias.nombres import ResolutorNombres

if TYPE_CHECKING:
    from monitor_mercado.cartera.rebalanceo import PlanRebalanceo

log = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")


class FotoCartera(Base):
    """Valor de la cartera al cierre de cada día (para ver la evolución)."""

    __tablename__ = "cartera_historial"

    fecha: Mapped[date] = mapped_column(primary_key=True)
    valor: Mapped[float]
    costo: Mapped[float]


@dataclass(frozen=True)
class EstadoPosicion:
    """Una posición valuada al precio actual (todo en USD)."""

    posicion: Posicion
    precio: float | None
    variacion_dia: float | None  # % del día
    valor: float | None
    resultado: float | None  # ganancia o pérdida en dinero
    resultado_pct: float | None
    resultado_dia: float | None  # ganancia o pérdida del día en dinero
    peso: float = 0.0  # fracción del valor total de la cartera

    @property
    def simbolo(self) -> str:
        return self.posicion.simbolo


@dataclass(frozen=True)
class EstadoCartera:
    """La cartera completa valuada."""

    posiciones: list[EstadoPosicion]
    valor: float
    costo: float  # solo de las posiciones con costo conocido
    resultado: float
    resultado_dia: float
    sin_precio: list[str]
    sin_costo: list[str]
    momento: datetime

    @property
    def resultado_pct(self) -> float | None:
        return self.resultado / self.costo if self.costo else None

    @property
    def variacion_dia(self) -> float | None:
        anterior = self.valor - self.resultado_dia
        return self.resultado_dia / anterior if anterior else None


@dataclass(frozen=True)
class ResumenDia:
    """Todo lo que va en el resumen de cierre."""

    estado: EstadoCartera
    noticias: list[NoticiaDestacada]
    variacion_semana: float | None
    concentradas: list[EstadoPosicion] = field(default_factory=list)


class ServicioCartera:
    """Lee tu cartera, la valúa y arma el resumen diario."""

    def __init__(
        self,
        ruta: Path,
        proveedor: ProveedorPrecios,
        cfg: Configuracion,
        motor: Engine,
        fuentes: list[FuenteNoticias] | None = None,
        nombres: ResolutorNombres | None = None,
    ) -> None:
        self.ruta = ruta
        self._proveedor = proveedor
        self._cfg = cfg
        self._sesiones = sessionmaker(motor, expire_on_commit=False)
        self._fuentes = fuentes or []
        self._nombres = nombres

    def posiciones(self) -> list[Posicion]:
        """Posiciones del archivo (lista vacía si todavía no existe)."""
        return leer_cartera(self.ruta) if self.ruta.exists() else []

    def estado(self) -> EstadoCartera:
        """Valúa todas las posiciones al último precio."""
        posiciones = self.posiciones()
        cotizaciones = self._proveedor.cotizaciones([p.simbolo for p in posiciones])
        conversor = ConversorMonedas(self._proveedor, self._cfg.monedas)
        filas: list[EstadoPosicion] = []
        for p in posiciones:
            c = cotizaciones.get(p.simbolo)
            if c is None:
                filas.append(EstadoPosicion(p, None, None, None, None, None, None))
                continue
            # Todo se lleva a USD (ej. ALUA.BA en pesos al CCL) para poder sumar.
            try:
                a_usd = conversor.a_usd(1.0, c.moneda)  # USD por unidad (contempla peniques, pesos, etc.)
            except Exception:  # noqa: BLE001
                log.warning("%s: no se pudo convertir %s a USD", p.simbolo, c.moneda)
                filas.append(EstadoPosicion(p, None, None, None, None, None, None))
                continue
            precio = c.precio * a_usd
            valor = precio * p.cantidad
            costo = p.costo if p.moneda == "USD" else (p.costo * a_usd if p.costo is not None else None)
            var = c.variacion_pct / 100 if c.variacion_pct is not None else None
            resultado_dia = valor - valor / (1 + var) if var is not None else None
            filas.append(EstadoPosicion(
                p, precio, var, valor,
                valor - costo if costo is not None else None,
                (valor / costo - 1) if costo else None,
                resultado_dia,
            ))

        valor_total = sum(f.valor for f in filas if f.valor is not None)
        filas = [EstadoPosicion(f.posicion, f.precio, f.variacion_dia, f.valor, f.resultado, f.resultado_pct,
                                f.resultado_dia, (f.valor / valor_total) if f.valor and valor_total else 0.0)
                 for f in filas]
        con_costo = [f for f in filas if f.resultado is not None]
        return EstadoCartera(
            posiciones=filas,
            valor=valor_total,
            costo=sum(f.posicion.costo for f in con_costo),
            resultado=sum(f.resultado for f in con_costo),
            resultado_dia=sum(f.resultado_dia for f in filas if f.resultado_dia is not None),
            sin_precio=[f.simbolo for f in filas if f.precio is None],
            sin_costo=[f.simbolo for f in filas if f.precio is not None and f.resultado is None],
            momento=datetime.now(timezone.utc),
        )

    def rebalanceo(self) -> "PlanRebalanceo":
        """Qué comprar o vender para volver a los pesos objetivo de config.yaml (solo sugiere)."""
        from monitor_mercado.cartera.rebalanceo import planificar

        return planificar(self.estado(), self._cfg)

    # ------------------------------------------------------------- historial
    def guardar_foto(self, estado: EstadoCartera, dia: date) -> None:
        """Guarda el valor de cierre del día."""
        with self._sesiones.begin() as s:
            s.merge(FotoCartera(fecha=dia, valor=estado.valor, costo=estado.costo))

    def variacion_desde(self, estado: EstadoCartera, dias: int, hoy: date) -> float | None:
        """Variación del valor contra la foto más cercana a ``dias`` atrás (None si no hay)."""
        objetivo = hoy - timedelta(days=dias)
        with self._sesiones() as s:
            foto = s.scalars(select(FotoCartera).where(FotoCartera.fecha <= objetivo)
                             .order_by(FotoCartera.fecha.desc())).first()
        if foto is None or not foto.valor:
            return None
        return estado.valor / foto.valor - 1

    # ---------------------------------------------------------------- resumen
    def resumen_dia(self, con_noticias: bool = True) -> ResumenDia:
        """Estado de la cartera + noticias importantes del día + alertas de concentración."""
        estado = self.estado()
        hoy = estado.momento.astimezone(NY).date()
        semana = self.variacion_desde(estado, 7, hoy)
        self.guardar_foto(estado, hoy)
        noticias: list[NoticiaDestacada] = []
        if con_noticias and self._fuentes and self._nombres:
            variaciones = {f.simbolo: f.variacion_dia for f in estado.posiciones if f.precio is not None}
            noticias = noticias_importantes(self._fuentes, self._nombres, variaciones,
                                            maximo=self._cfg.cartera.noticias_maximas)
        limite = self._cfg.cartera.concentracion_maxima
        concentradas = sorted((f for f in estado.posiciones if f.peso > limite), key=lambda f: -f.peso)
        return ResumenDia(estado, noticias, semana, concentradas)
