"""Casos de uso de las alertas: crear (validando el símbolo) y revisar precios."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from monitor_mercado.alertas.evaluador import condicion_cumplida, evaluar
from monitor_mercado.alertas.modelos import Alerta, Moneda
from monitor_mercado.alertas.parser import SolicitudAlerta
from monitor_mercado.alertas.repositorio import RepositorioAlertas
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.datos.modelos import Cotizacion, ErrorDatos
from monitor_mercado.datos.monedas import ConversorMonedas, simbolo_para_moneda
from monitor_mercado.datos.proveedor import ProveedorPrecios
from monitor_mercado.mercados import esta_abierto

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrecioEvaluado:
    """Precio de un activo expresado en la moneda de una alerta."""

    cotizacion: Cotizacion
    precio: float  # en la moneda de la alerta
    moneda: Moneda


@dataclass(frozen=True)
class Disparo:
    """Una alerta que se cumplió en una revisión."""

    alerta: Alerta
    precio: PrecioEvaluado


@dataclass(frozen=True)
class ResultadoCreacion:
    """Alerta creada más un aviso opcional para mostrarle al usuario."""

    alerta: Alerta
    precio_actual: PrecioEvaluado
    aviso: str | None = None


class ServicioAlertas:
    """Orquesta repositorio, proveedor de precios y conversión de monedas."""

    def __init__(
        self, repo: RepositorioAlertas, proveedor: ProveedorPrecios, cfg: Configuracion
    ) -> None:
        self.repo = repo
        self._proveedor = proveedor
        self._cfg = cfg

    # ----------------------------------------------------------------- precios
    def precio_en(
        self, simbolo: str, moneda: Moneda, conversor: ConversorMonedas | None = None
    ) -> PrecioEvaluado:
        """Precio actual de ``simbolo`` en ``moneda``.

        Raises:
            ValueError: Si la combinación símbolo/moneda no es válida.
            ErrorDatos: Si no se pudo obtener el precio o el tipo de cambio.
        """
        consultado = simbolo_para_moneda(simbolo, moneda, self._cfg.monedas)
        cot = self._proveedor.cotizacion(consultado)
        return self._convertir(cot, moneda, conversor or self._conversor())

    def _conversor(self) -> ConversorMonedas:
        return ConversorMonedas(self._proveedor, self._cfg.monedas)

    @staticmethod
    def _convertir(cot: Cotizacion, moneda: Moneda, conversor: ConversorMonedas) -> PrecioEvaluado:
        if moneda is Moneda.USD:
            precio = conversor.a_usd(cot.precio, cot.moneda)
        elif cot.moneda == "ARS":
            precio = cot.precio
        else:
            raise ErrorDatos(f"{cot.simbolo} cotiza en {cot.moneda}, no en ARS")
        return PrecioEvaluado(cotizacion=cot, precio=precio, moneda=moneda)

    # ------------------------------------------------------------------- crear
    def crear(self, solicitud: SolicitudAlerta) -> ResultadoCreacion:
        """Valida el símbolo consultando su precio y guarda la alerta.

        Raises:
            ValueError: Si la combinación símbolo/moneda no es válida.
            ErrorDatos: Si el símbolo no tiene datos (no se crea la alerta).
        """
        actual = self.precio_en(solicitud.simbolo, solicitud.moneda)
        ya_cumple = condicion_cumplida(
            solicitud.condicion, solicitud.umbral, actual.precio, actual.cotizacion.variacion_pct
        )
        alerta = self.repo.guardar(
            Alerta(
                simbolo=solicitud.simbolo,
                operacion=solicitud.operacion,
                condicion=solicitud.condicion,
                umbral=solicitud.umbral,
                moneda=solicitud.moneda,
                repetir=solicitud.repetir,
                armada=not ya_cumple,
                precio_al_crear=actual.precio,
                nota=solicitud.nota,
            )
        )
        log.info("Alerta creada: %r", alerta)

        avisos = []
        if ya_cumple:
            avisos.append(
                "La condición ya se cumple con el precio actual: la alerta queda en espera "
                "y va a avisar recién cuando el precio vuelva a cruzar el umbral."
            )
        if solicitud.simbolo not in self._cfg.watchlist_activa:
            avisos.append(f"{solicitud.simbolo} no está en tu watchlist activa (igual se creó).")
        return ResultadoCreacion(alerta, actual, "\n".join(avisos) or None)

    # ----------------------------------------------------------------- revisar
    def revisar(self, ahora: datetime | None = None, forzar: bool = False) -> list[Disparo]:
        """Revisa todas las alertas activas contra los precios actuales.

        Args:
            ahora: Momento de la revisión (para tests). Por defecto, ahora en UTC.
            forzar: Si es True, ignora el horario de mercado.

        Returns:
            Las alertas que se dispararon en esta revisión.
        """
        ahora = ahora or datetime.now(timezone.utc)
        cfg = self._cfg.alertas
        margen = cfg.margen_minutos_post_cierre
        enfriamiento = timedelta(minutes=cfg.enfriamiento_minutos_repetir)

        pendientes: list[tuple[Alerta, str]] = []
        for alerta in self.repo.listar(solo_activas=True):
            try:
                consultado = simbolo_para_moneda(alerta.simbolo, alerta.moneda, self._cfg.monedas)
            except ValueError as e:
                log.error("Alerta #%s inválida: %s", alerta.id, e)
                continue
            if forzar or not cfg.solo_en_horario_de_mercado or esta_abierto(consultado, ahora, margen):
                pendientes.append((alerta, consultado))

        if not pendientes:
            log.info("Revisión: no hay alertas activas con el mercado abierto.")
            return []

        cotizaciones = self._proveedor.cotizaciones([s for _, s in pendientes])
        conversor = self._conversor()
        disparos: list[Disparo] = []

        for alerta, consultado in pendientes:
            cot = cotizaciones.get(consultado)
            if cot is None:
                continue  # el proveedor ya registró el motivo
            try:
                evaluado = self._convertir(cot, alerta.moneda, conversor)
            except ErrorDatos as e:
                log.warning("Alerta #%s: no se pudo convertir el precio: %s", alerta.id, e)
                continue

            decision = evaluar(alerta, evaluado.precio, cot.variacion_pct, ahora, enfriamiento)
            if decision.armada != alerta.armada or decision.activa != alerta.activa or decision.disparar:
                alerta.armada = decision.armada
                alerta.activa = decision.activa
                if decision.disparar:
                    alerta.ultimo_disparo = ahora
                    alerta.veces_disparada += 1
                alerta = self.repo.guardar(alerta)
            if decision.disparar:
                log.info("Alerta disparada: %r a %.4f %s", alerta, evaluado.precio, alerta.moneda)
                disparos.append(Disparo(alerta, evaluado))

        log.info("Revisión: %d alertas evaluadas, %d disparadas.", len(pendientes), len(disparos))
        return disparos
