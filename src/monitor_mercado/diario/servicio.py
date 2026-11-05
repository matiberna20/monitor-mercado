"""Casos de uso del diario: registrar, editar, borrar, importar y estadísticas."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from monitor_mercado.cartera.archivo import Posicion, leer_cartera
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.datos.monedas import ConversorMonedas
from monitor_mercado.datos.proveedor import ProveedorPrecios
from monitor_mercado.diario.calculo import Calculo, ErrorDiario, VentaCerrada, calcular
from monitor_mercado.diario.modelos import Movimiento, TipoMovimiento
from monitor_mercado.diario.parser import SolicitudMovimiento, moneda_por_defecto
from monitor_mercado.diario.repositorio import RepositorioDiario

log = logging.getLogger(__name__)
AR = ZoneInfo("America/Argentina/Buenos_Aires")


@dataclass(frozen=True)
class VentaEnUsd:
    """Una venta cerrada con su resultado pasado a USD (para poder comparar y sumar)."""

    venta: VentaCerrada
    resultado_usd: float | None


@dataclass(frozen=True)
class Estadisticas:
    """Resumen de cómo te fue con las operaciones cerradas."""

    ventas: list[VentaEnUsd]
    realizado: float  # USD, solo ventas con resultado conocido
    no_realizado: float | None  # USD, de las posiciones abiertas (viene de la cartera)
    sin_resultado: int  # ventas sin costo conocido o sin tipo de cambio

    @property
    def con_resultado(self) -> list[VentaEnUsd]:
        return [v for v in self.ventas if v.resultado_usd is not None]

    @property
    def ganadoras(self) -> list[VentaEnUsd]:
        return [v for v in self.con_resultado if v.resultado_usd > 0]

    @property
    def perdedoras(self) -> list[VentaEnUsd]:
        return [v for v in self.con_resultado if v.resultado_usd <= 0]

    @property
    def tasa_aciertos(self) -> float | None:
        return len(self.ganadoras) / len(self.con_resultado) if self.con_resultado else None

    @property
    def ganancia_promedio(self) -> float | None:
        g = self.ganadoras
        return sum(v.resultado_usd for v in g) / len(g) if g else None

    @property
    def perdida_promedio(self) -> float | None:
        p = self.perdedoras
        return sum(v.resultado_usd for v in p) / len(p) if p else None

    def mejores(self, n: int = 3) -> list[VentaEnUsd]:
        return sorted(self.ganadoras, key=lambda v: -v.resultado_usd)[:n]

    def peores(self, n: int = 3) -> list[VentaEnUsd]:
        return sorted(self.perdedoras, key=lambda v: v.resultado_usd)[:n]


class ServicioDiario:
    """Registra tus operaciones y calcula resultados."""

    def __init__(self, repo: RepositorioDiario, proveedor: ProveedorPrecios | None, cfg: Configuracion) -> None:
        self.repo = repo
        self._proveedor = proveedor
        self._cfg = cfg

    # ------------------------------------------------------------ registrar
    def _validar(self, movimientos: list[Movimiento]) -> Calculo:
        return calcular(movimientos)  # lanza ErrorDiario si queda inconsistente

    def registrar(self, tipo: TipoMovimiento, s: SolicitudMovimiento) -> Movimiento:
        """Guarda una compra o una venta.

        Raises:
            ErrorDiario: Si es una venta de más acciones de las que tenías en esa fecha.
        """
        mov = Movimiento(
            fecha=s.fecha or datetime.now(AR).date(), simbolo=s.simbolo, tipo=tipo, cantidad=s.cantidad,
            precio=s.precio, moneda=s.moneda or self._moneda_de(s.simbolo), comision=s.comision, nota=s.nota,
        )
        self._validar([*self.repo.listar(), mov])
        mov = self.repo.guardar(mov)
        log.info("Diario: %r", mov)
        return mov

    def _moneda_de(self, simbolo: str) -> str:
        """Moneda de una tenencia previa del mismo símbolo, o la de su bolsa."""
        previos = self.repo.listar(simbolo)
        return previos[-1].moneda if previos else moneda_por_defecto(simbolo)

    def editar(self, id_mov: int, campo: str, valor: object) -> Movimiento:
        """Cambia un campo de una operación.

        Raises:
            KeyError: Si la operación no existe.
            ErrorDiario: Si el cambio deja el diario inconsistente.
        """
        mov = self.repo.obtener(id_mov)
        if mov is None:
            raise KeyError(id_mov)
        setattr(mov, campo, valor)
        self._validar([m if m.id != id_mov else mov for m in self.repo.listar()])
        return self.repo.guardar(mov)

    def borrar(self, id_mov: int) -> bool:
        """Borra una operación.

        Raises:
            ErrorDiario: Si al borrarla una venta posterior queda sin acciones.
        """
        if self.repo.obtener(id_mov) is None:
            return False
        self._validar([m for m in self.repo.listar() if m.id != id_mov])
        return self.repo.borrar(id_mov)

    # ------------------------------------------------------------- importar
    def importar_cartera(self, ruta: Path) -> tuple[list[Movimiento], list[str]]:
        """Carga cada posición de mi_cartera.csv como una compra.

        Los símbolos que ya tienen operaciones en el diario se saltean (para no duplicar).
        Usa la fecha de compra del archivo o, si no hay, la de hoy.

        Returns:
            (compras importadas, símbolos salteados)
        """
        existentes = {m.simbolo for m in self.repo.listar()}
        hoy = datetime.now(AR).date()
        importadas, salteadas = [], []
        for p in leer_cartera(ruta):
            if p.simbolo in existentes:
                salteadas.append(p.simbolo)
                continue
            importadas.append(self.repo.guardar(Movimiento(
                fecha=p.fecha_compra or hoy, simbolo=p.simbolo, tipo=TipoMovimiento.COMPRA, cantidad=p.cantidad,
                precio=p.precio_compra, moneda=p.moneda, comision=0.0,
                nota=("importado de mi_cartera.csv" + (f": {p.nota}" if p.nota else ""))[:300],
            )))
        return importadas, salteadas

    # --------------------------------------------------------------- consultas
    def calculo(self) -> Calculo:
        return calcular(self.repo.listar())

    def posiciones(self) -> list[Posicion]:
        """Tu cartera calculada desde el diario (mismo formato que mi_cartera.csv)."""
        return [
            Posicion(t.simbolo, t.cantidad, t.costo_promedio, t.moneda, t.desde, "")
            for t in self.calculo().abiertas
        ]

    def estadisticas(self, no_realizado: float | None = None) -> Estadisticas:
        """Resultado realizado y estadísticas de las ventas (en USD al tipo de cambio de hoy)."""
        conversor = ConversorMonedas(self._proveedor, self._cfg.monedas) if self._proveedor else None
        ventas, sin_resultado = [], 0
        for v in self.calculo().cerradas:
            usd = None
            if v.resultado is not None:
                if v.movimiento.moneda == "USD":
                    usd = v.resultado
                elif conversor is not None:
                    try:
                        usd = conversor.a_usd(v.resultado, v.movimiento.moneda)
                    except Exception:  # noqa: BLE001 - sin tipo de cambio se informa aparte
                        log.warning("Sin tipo de cambio para %s", v.movimiento.moneda)
            if usd is None:
                sin_resultado += 1
            ventas.append(VentaEnUsd(v, usd))
        realizado = sum(v.resultado_usd for v in ventas if v.resultado_usd is not None)
        return Estadisticas(ventas, realizado, no_realizado, sin_resultado)

    def realizado_por_simbolo(self) -> dict[str, float]:
        """Resultado realizado en USD por símbolo (para el Excel y el panel)."""
        total: dict[str, float] = {}
        for v in self.estadisticas().con_resultado:
            s = v.venta.movimiento.simbolo
            total[s] = total.get(s, 0.0) + v.resultado_usd
        return total

    @staticmethod
    def hoy() -> date:
        return datetime.now(AR).date()


__all__ = ["ErrorDiario", "Estadisticas", "ServicioDiario", "VentaEnUsd"]
