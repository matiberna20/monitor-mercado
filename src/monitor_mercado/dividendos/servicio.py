"""Dividendos cobrados, próximos cobros y rendimiento total de la cartera.

Reglas:
- Cobrás un dividendo si tenías la acción **antes de la fecha ex**.
- La cantidad que tenías en esa fecha sale del diario de operaciones, si el símbolo tiene
  operaciones cargadas. Si no, se usa la cantidad actual, desde la fecha de compra (o, si
  no la cargaste, para los últimos 12 meses).
- Todo se pasa a USD al tipo de cambio de hoy. No incluye impuestos ni retenciones.
"""

from __future__ import annotations

import logging
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta

from monitor_mercado.cartera.archivo import Posicion
from monitor_mercado.cartera.servicio import EstadoCartera, ServicioCartera
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.datos.monedas import ConversorMonedas
from monitor_mercado.datos.proveedor import ProveedorPrecios
from monitor_mercado.diario.calculo import calcular
from monitor_mercado.dividendos.fuente import Dividendo, FuenteDividendos

log = logging.getLogger(__name__)

HORIZONTE_PROXIMOS = 180  # días hacia adelante que se muestran


@dataclass(frozen=True)
class Cobro:
    """Un dividendo cobrado por una posición."""

    simbolo: str
    fecha_ex: date
    por_accion: float  # moneda del activo
    cantidad: float
    moneda: str
    monto_usd: float | None


@dataclass(frozen=True)
class ProximoCobro:
    """Un dividendo que viene."""

    simbolo: str
    fecha_ex: date | None
    fecha_pago: date | None
    por_accion: float | None  # se toma el último pagado
    cantidad: float
    moneda: str
    monto_usd: float | None
    estimado: bool  # True = fecha calculada por la frecuencia de pagos, no anunciada


@dataclass(frozen=True)
class ResumenDividendos:
    """Cobrados en el último año y próximos cobros."""

    cobrados: list[Cobro]
    proximos: list[ProximoCobro]
    errores: list[str] = field(default_factory=list)

    @property
    def total_anual(self) -> float:
        return sum(c.monto_usd or 0 for c in self.cobrados)


@dataclass(frozen=True)
class RendimientoTotal:
    """Variación de precio + dividendos cobrados desde la compra (USD)."""

    resultado_precio: float  # de las posiciones con costo
    costo: float
    dividendos: float  # todas las posiciones
    dividendos_con_costo: float  # solo las que tienen costo (para el %)
    por_simbolo: dict[str, float]
    sin_fecha: list[str]  # posiciones sin fecha de compra: se tomaron 12 meses

    @property
    def total(self) -> float:
        return self.resultado_precio + self.dividendos_con_costo

    @property
    def total_pct(self) -> float | None:
        return self.total / self.costo if self.costo else None


class ServicioDividendos:
    """Junta dividendos de la fuente, tu cartera y el diario."""

    def __init__(self, fuente: FuenteDividendos, proveedor: ProveedorPrecios, cfg: Configuracion,
                 cartera: ServicioCartera, diario=None) -> None:
        self._fuente = fuente
        self._proveedor = proveedor
        self._cfg = cfg
        self._cartera = cartera
        self._diario = diario

    # ------------------------------------------------------------ auxiliares
    def _historiales(self, simbolos: list[str]) -> tuple[dict[str, list[Dividendo]], list[str]]:
        def uno(s: str):
            try:
                return s, self._fuente.historial(s), None
            except Exception as e:  # noqa: BLE001 - un símbolo que falla no frena al resto
                log.warning("Dividendos de %s: %s", s, e)
                return s, [], s

        with ThreadPoolExecutor(max_workers=8) as pool:
            resultados = list(pool.map(uno, simbolos))
        return {s: h for s, h, _ in resultados}, [e for _, _, e in resultados if e]

    def _monedas(self, simbolos: list[str]) -> dict[str, str]:
        return {s: c.moneda for s, c in self._proveedor.cotizaciones(simbolos).items()}

    def _a_usd(self, conversor: ConversorMonedas, monto: float, moneda: str) -> float | None:
        try:
            return conversor.a_usd(monto, moneda)
        except Exception:  # noqa: BLE001
            return None

    def _cantidades(self, posiciones: list[Posicion]):
        """Función (símbolo, fecha_ex) -> acciones que tenías antes de esa fecha."""
        movimientos = self._diario.repo.listar() if self._diario is not None else []
        por_simbolo: dict[str, list] = {}
        for m in movimientos:
            por_simbolo.setdefault(m.simbolo, []).append(m)
        actuales = {p.simbolo: p for p in posiciones}

        def cantidad(simbolo: str, fecha_ex: date) -> float:
            if simbolo in por_simbolo:
                previos = [m for m in por_simbolo[simbolo] if m.fecha < fecha_ex]
                t = calcular(previos).tenencias.get(simbolo)
                return t.cantidad if t else 0.0
            p = actuales.get(simbolo)
            if p is None or (p.fecha_compra is not None and p.fecha_compra >= fecha_ex):
                return 0.0
            return p.cantidad

        return cantidad

    # ---------------------------------------------------------------- resumen
    def resumen(self, hoy: date | None = None) -> ResumenDividendos:
        """Dividendos cobrados en los últimos 12 meses y próximos cobros."""
        hoy = hoy or date.today()
        posiciones = self._cartera.posiciones()
        simbolos = [p.simbolo for p in posiciones]
        historiales, errores = self._historiales(simbolos)
        monedas = self._monedas([s for s in simbolos if historiales.get(s)])
        conversor = ConversorMonedas(self._proveedor, self._cfg.monedas)
        cantidad_en = self._cantidades(posiciones)

        cobrados, proximos = [], []
        for p in posiciones:
            hist = historiales.get(p.simbolo) or []
            moneda = monedas.get(p.simbolo, "USD")
            for d in hist:
                if hoy - timedelta(days=365) < d.fecha_ex <= hoy and (q := cantidad_en(p.simbolo, d.fecha_ex)) > 0:
                    cobrados.append(Cobro(p.simbolo, d.fecha_ex, d.monto, q, moneda,
                                          self._a_usd(conversor, d.monto * q, moneda)))
            prox = self._proximo(p, hist, hoy)
            if prox is not None:
                ex, pago, estimado = prox
                por_accion = hist[-1].monto if hist else None
                monto = self._a_usd(conversor, por_accion * p.cantidad, moneda) if por_accion else None
                proximos.append(ProximoCobro(p.simbolo, ex, pago, por_accion, p.cantidad, moneda, monto, estimado))
        cobrados.sort(key=lambda c: c.fecha_ex, reverse=True)
        proximos.sort(key=lambda x: x.fecha_ex or x.fecha_pago or date.max)
        return ResumenDividendos(cobrados, proximos, errores)

    def _proximo(self, p: Posicion, hist: list[Dividendo], hoy: date) -> tuple[date | None, date | None, bool] | None:
        """(fecha ex, fecha de pago, estimado) del próximo dividendo, o None."""
        try:
            anuncio = self._fuente.anunciado(p.simbolo)
        except Exception:  # noqa: BLE001
            anuncio = None
        if anuncio is not None:
            ex, pago = anuncio.fecha_ex, anuncio.fecha_pago
            # Sirve si la fecha ex viene, o si ya pasó pero el pago todavía no.
            if (ex and ex > hoy) or (pago and pago >= hoy and (ex is None or ex <= hoy)):
                return ex, pago, False
        if len(hist) < 2:
            return None
        recientes = hist[-5:]
        intervalo = int(statistics.median((b.fecha_ex - a.fecha_ex).days for a, b in zip(recientes, recientes[1:])))
        if intervalo < 20:
            return None
        siguiente = hist[-1].fecha_ex + timedelta(days=intervalo)
        if siguiente < hoy - timedelta(days=intervalo):  # hace mucho que no paga: dejó de pagar
            return None
        while siguiente <= hoy:
            siguiente += timedelta(days=intervalo)
        return (siguiente, None, True) if siguiente <= hoy + timedelta(days=HORIZONTE_PROXIMOS) else None

    # -------------------------------------------------------- rendimiento
    def rendimiento_total(self, estado: EstadoCartera, hoy: date | None = None) -> RendimientoTotal:
        """Variación del precio + dividendos cobrados desde la compra."""
        hoy = hoy or date.today()
        filas = [f for f in estado.posiciones if f.precio is not None]
        historiales, _ = self._historiales([f.simbolo for f in filas])
        monedas = self._monedas([f.simbolo for f in filas if historiales.get(f.simbolo)])
        conversor = ConversorMonedas(self._proveedor, self._cfg.monedas)
        cantidad_en = self._cantidades([f.posicion for f in filas])

        por_simbolo, sin_fecha = {}, []
        for f in filas:
            desde = f.posicion.fecha_compra
            if desde is None:
                desde = hoy - timedelta(days=365)
                if historiales.get(f.simbolo):
                    sin_fecha.append(f.simbolo)
            total = 0.0
            for d in historiales.get(f.simbolo) or []:
                if desde < d.fecha_ex <= hoy and (q := cantidad_en(f.simbolo, d.fecha_ex)) > 0:
                    total += self._a_usd(conversor, d.monto * q, monedas.get(f.simbolo, "USD")) or 0.0
            if total:
                por_simbolo[f.simbolo] = total
        con_costo = {f.simbolo for f in filas if f.resultado is not None}
        return RendimientoTotal(
            resultado_precio=estado.resultado, costo=estado.costo, dividendos=sum(por_simbolo.values()),
            dividendos_con_costo=sum(v for s, v in por_simbolo.items() if s in con_costo),
            por_simbolo=por_simbolo, sin_fecha=sin_fecha,
        )
