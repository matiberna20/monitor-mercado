"""Caso de uso de resultados: analizar una presentación y vigilar el calendario."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from monitor_mercado.configuracion import Configuracion
from monitor_mercado.datos.modelos import ErrorDatos
from monitor_mercado.noticias.nombres import ResolutorNombres
from monitor_mercado.noticias.sentimiento import ErrorSentimiento
from monitor_mercado.resultados.comunicado import AnalisisComunicado, AnalizadorComunicado, ClienteEdgar, ErrorComunicado
from monitor_mercado.resultados.datos import ConsensoProximo, EventoResultados, FuenteResultadosYahoo
from monitor_mercado.resultados.evaluacion import (
    UMBRAL_EPS, UMBRAL_INGRESOS, Evaluacion, Sorpresa, clasificar, evaluar, sorpresa_pct,
)
from monitor_mercado.resultados.metricas import Metricas, calcular_metricas, elegir_trimestre
from monitor_mercado.resultados.reaccion import Reaccion, calcular_reaccion
from monitor_mercado.resultados.repositorio import RepositorioResultados
from monitor_mercado.resultados.valuacion import CacheInfo, Valuacion, valuar
from monitor_mercado.tecnico.historico import AlmacenHistorico

log = logging.getLogger(__name__)
INDICE = "SPY"


@dataclass(frozen=True)
class ReporteResultados:
    """Todo lo que se sabe de una presentación de resultados."""

    simbolo: str
    empresa: str
    evento: EventoResultados
    sorpresa_eps: float | None
    clase_eps: Sorpresa
    ingresos_estimados: float | None
    sorpresa_ingresos: float | None
    clase_ingresos: Sorpresa
    metricas: Metricas | None
    moneda_estados: str | None
    reacciones: list[Reaccion]
    comunicado: AnalisisComunicado | None
    url_comunicado: str | None
    evaluacion: Evaluacion
    valuacion: Valuacion | None
    proximo: ConsensoProximo | None
    avisos: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Proxima:
    """Una próxima presentación de resultados."""

    simbolo: str
    fecha: datetime
    eps_estimado: float | None


class ServicioResultados:
    """Orquesta las fuentes de resultados, el análisis y los avisos."""

    def __init__(
        self,
        fuente: FuenteResultadosYahoo,
        repo: RepositorioResultados,
        almacen: AlmacenHistorico,
        cache_info: CacheInfo,
        nombres: ResolutorNombres,
        cfg: Configuracion,
        edgar: ClienteEdgar | None = None,
        analizador: AnalizadorComunicado | None = None,
    ) -> None:
        self.fuente = fuente
        self.repo = repo
        self._almacen = almacen
        self._cache = cache_info
        self._nombres = nombres
        self._cfg = cfg
        self._edgar = edgar
        self._analizador = analizador

    # ------------------------------------------------------------------ análisis
    def analizar(self, simbolo: str, fecha: date | None = None) -> ReporteResultados:
        """Analiza la última presentación publicada (o la más cercana a ``fecha``).

        Raises:
            ErrorDatos: Si no hay resultados publicados para el símbolo.
        """
        s = simbolo.upper()
        avisos: list[str] = []
        eventos = self.fuente.eventos(s)
        publicados = [e for e in eventos if e.publicado]
        if not publicados:
            raise ErrorDatos(f"{s}: no hay resultados publicados en Yahoo.")
        ev = min(publicados, key=lambda e: abs((e.fecha.date() - fecha).days)) if fecha else publicados[0]
        dia = ev.fecha.date()
        empresa = self._nombres.nombre(s)

        # 1. Ganancia por acción vs. consenso.
        s_eps = sorpresa_pct(ev.eps_reportado, ev.eps_estimado)

        # 2. Estados contables del trimestre.
        metricas = moneda = None
        try:
            estados = self.fuente.estados(s)
            moneda = estados.moneda
            trimestre = elegir_trimestre(list(estados.resultados.columns), dia)
            if trimestre is None:
                avisos.append("Los estados contables de este trimestre todavía no están en Yahoo "
                              "(suelen aparecer unos días después).")
            else:
                metricas = calcular_metricas(estados.resultados, estados.balance, estados.flujos, trimestre)
        except ErrorDatos as e:
            avisos.append(f"Sin estados contables: {e}")
        if moneda == "ARS":
            avisos.append("Los estados están en pesos. Las empresas argentinas los ajustan por inflación (NIC 29), "
                          "pero Yahoo puede mezclar trimestres ajustados y sin ajustar: tomá el crecimiento con cautela.")

        # 3. Ingresos vs. consenso guardado antes de la presentación.
        ing_est = s_ing = None
        guardado = self.repo.consenso(s, dia)
        if guardado is None or guardado.ingresos is None:
            avisos.append("No hay consenso de ingresos guardado para esta presentación (el sistema lo empieza "
                          "a guardar cuando seguís la empresa con /seguir).")
        elif guardado.moneda_ingresos and moneda and guardado.moneda_ingresos != moneda:
            avisos.append(f"El consenso de ingresos está en {guardado.moneda_ingresos} y los balances en {moneda}: "
                          "no se pueden comparar directamente.")
        elif metricas is not None:
            ing_est = guardado.ingresos
            s_ing = sorpresa_pct(metricas.ingresos, ing_est)

        # 4. Reacción del precio.
        reacciones: list[Reaccion] = []
        try:
            cierres = self._almacen.obtener(s)["cierre"]
            indice = self._almacen.obtener(INDICE)["cierre"] if s != INDICE else None
            reacciones = calcular_reaccion(cierres, indice, ev.fecha)
        except ErrorDatos as e:
            avisos.append(f"No se pudo medir la reacción del precio: {e}")

        # 5. Comunicado oficial (guidance y tono).
        comunicado, url = self._comunicado(s, empresa, dia, ev, s_eps, s_ing, metricas, avisos)

        evaluacion = evaluar(s_eps, s_ing, metricas, reacciones,
                             comunicado.guidance if comunicado else None, comunicado.tono if comunicado else None)

        # 6. Valuación contra pares.
        valuacion = None
        try:
            valuacion = valuar(s, self._cache, self._cfg.resultados.pares, self._cfg.watchlist_completa)
        except ErrorDatos as e:
            avisos.append(f"Sin datos de valuación: {e}")

        proximo = None
        try:
            proximo = self.fuente.consenso(s)
        except ErrorDatos:
            pass

        return ReporteResultados(
            s, empresa, ev, s_eps, clasificar(s_eps, UMBRAL_EPS), ing_est, s_ing, clasificar(s_ing, UMBRAL_INGRESOS),
            metricas, moneda, reacciones, comunicado, url, evaluacion, valuacion, proximo, avisos,
        )

    def _comunicado(self, s, empresa, dia, ev, s_eps, s_ing, metricas, avisos):
        guardado = self.repo.comunicado(s, dia)
        if guardado is not None:
            return guardado[0], guardado[1]
        if self._edgar is None:
            avisos.append("Sin comunicado oficial: falta un mail en resultados.sec_contacto (config.yaml).")
            return None, None
        try:
            doc = self._edgar.buscar(s, dia)
            if self._analizador is None:
                # Sin Claude: se da el link para que leas el comunicado (guidance incluida).
                avisos.append(f"Comunicado oficial ({doc.formulario}): {doc.url} — ahí están la guidance y el "
                              "detalle del trimestre.")
                return None, None
            datos = {
                "eps_reportado": ev.eps_reportado, "eps_consenso": ev.eps_estimado, "sorpresa_eps": s_eps,
                "sorpresa_ingresos": s_ing,
                "ingresos_interanual": metricas.ingresos_yoy if metricas else None,
                "margen_operativo": metricas.margen_operativo if metricas else None,
                "margen_operativo_hace_un_anio": metricas.margen_operativo_hace_un_anio if metricas else None,
            }
            analisis = self._analizador.analizar(empresa, doc, datos)
            self.repo.guardar_comunicado(s, dia, doc.formulario, doc.url, analisis)
            return analisis, doc.url
        except (ErrorComunicado, ErrorSentimiento) as e:
            avisos.append(f"Sin análisis del comunicado: {e}")
        except Exception as e:  # noqa: BLE001 - el comunicado es un complemento
            log.exception("%s: error inesperado con el comunicado", s)
            avisos.append(f"Sin análisis del comunicado: {e}")
        return None, None

    # ----------------------------------------------------------------- calendario
    def proximas(self, simbolos: list[str], dias: int = 60, ahora: datetime | None = None) -> list[Proxima]:
        """Próximas presentaciones de los símbolos, ordenadas por fecha."""
        ahora = ahora or datetime.now(timezone.utc)
        lista = []
        for s in simbolos:
            try:
                futuros = [e for e in self.fuente.eventos(s) if not e.publicado and e.fecha > ahora]
            except ErrorDatos as e:
                log.warning("%s: sin calendario: %s", s, e)
                continue
            if futuros:
                e = min(futuros, key=lambda x: x.fecha)
                if e.fecha - ahora <= timedelta(days=dias):
                    lista.append(Proxima(s, e.fecha, e.eps_estimado))
        return sorted(lista, key=lambda p: p.fecha)

    def revisar_calendario(self, ahora: datetime | None = None) -> list[tuple[str, ReporteResultados | Proxima]]:
        """Tarea periódica: guarda consensos y detecta presentaciones próximas o recién publicadas.

        Returns:
            Lista de (tipo, dato) con tipo "previo" (presenta pronto) o "resultado" (ya presentó).
        """
        ahora = ahora or datetime.now(timezone.utc)
        horas_previo = timedelta(hours=self._cfg.resultados.aviso_previo_horas)
        novedades: list[tuple[str, ReporteResultados | Proxima]] = []
        for s in self.repo.seguidas():
            try:
                c = self.fuente.consenso(s)
                if c.fecha and c.fecha >= ahora.date():
                    self.repo.guardar_consenso(s, c.fecha, c.eps, c.ingresos, c.moneda_ingresos)
                eventos = self.fuente.eventos(s)
            except ErrorDatos as e:
                log.warning("%s: no se pudo revisar el calendario: %s", s, e)
                continue

            for e in eventos:
                dia = e.fecha.date()
                if not e.publicado and timedelta(0) < e.fecha - ahora <= horas_previo \
                        and not self.repo.avisado(s, dia, "previo"):
                    novedades.append(("previo", Proxima(s, e.fecha, e.eps_estimado)))
                    self.repo.marcar_avisado(s, dia, "previo")
                if e.publicado and timedelta(0) <= ahora - e.fecha <= timedelta(days=4) \
                        and not self.repo.avisado(s, dia, "resultado"):
                    try:
                        novedades.append(("resultado", self.analizar(s, dia)))
                        self.repo.marcar_avisado(s, dia, "resultado")
                    except ErrorDatos as err:
                        log.warning("%s: no se pudo analizar el resultado: %s", s, err)
        return novedades
