"""Arma todas las piezas del sistema en un solo lugar (terminal y bot usan lo mismo)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from monitor_mercado.alertas.repositorio import RepositorioAlertas
from monitor_mercado.alertas.servicio import ServicioAlertas
from monitor_mercado.backtest.servicio import ServicioBacktest
from monitor_mercado.cartera.servicio import ServicioCartera
from monitor_mercado.configuracion import Configuracion, Secretos, cargar_configuracion, cargar_secretos
from monitor_mercado.datos.yahoo import ProveedorYahoo
from monitor_mercado.db import crear_motor
from monitor_mercado.diario.repositorio import RepositorioDiario
from monitor_mercado.diario.servicio import ServicioDiario
from monitor_mercado.dividendos.fuente import FuenteDividendosYahoo
from monitor_mercado.dividendos.servicio import ServicioDividendos
from monitor_mercado.noticias.fuentes import (
    Finnhub, FuenteNoticias, GoogleNewsRSS, Marketaux, NewsAPI, SecEdgar, YahooRSS,
)
from monitor_mercado.noticias.nombres import ResolutorNombres
from monitor_mercado.noticias.repositorio import RepositorioNoticias
from monitor_mercado.noticias.sentimiento import ClasificadorClaude
from monitor_mercado.noticias.servicio import AnalisisNoticias, ServicioNoticias
from monitor_mercado.registro import configurar_logs
from monitor_mercado.resultados.comunicado import AnalizadorComunicado, ClienteEdgar
from monitor_mercado.resultados.datos import FuenteResultadosYahoo
from monitor_mercado.resultados.repositorio import RepositorioResultados
from monitor_mercado.resultados.servicio import ServicioResultados
from monitor_mercado.resultados.valuacion import CacheInfo
from monitor_mercado.senal_final import SenalFinal, combinar
from monitor_mercado.riesgo.tamano import ServicioTamano
from monitor_mercado.simbolos import BuscadorSimbolos
from monitor_mercado.stops.repositorio import RepositorioStops
from monitor_mercado.stops.servicio import ServicioStops
from monitor_mercado.tecnico.historico import AlmacenHistorico, FuenteYahoo
from monitor_mercado.tecnico.servicio import Analisis, ServicioTecnico

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalisisCompleto:
    """Técnico + noticias + señal combinada de un activo."""

    tecnico: Analisis
    noticias: AnalisisNoticias | None
    final: SenalFinal


@dataclass
class Contexto:
    """Objetos compartidos por la terminal y el bot."""

    cfg: Configuracion
    secretos: Secretos
    proveedor: ProveedorYahoo
    servicio: ServicioAlertas
    tecnico: ServicioTecnico
    noticias: ServicioNoticias | None
    resultados: ServicioResultados | None = None
    backtest: ServicioBacktest | None = None
    cartera: ServicioCartera | None = None
    nombres: ResolutorNombres | None = None
    stops: ServicioStops | None = None
    tamano: ServicioTamano | None = None
    diario: ServicioDiario | None = None
    dividendos: ServicioDividendos | None = None

    def buscador(self) -> BuscadorSimbolos:
        """Buscador con tu watchlist, tu cartera y las empresas que seguís (se arma al momento)."""
        simbolos = list(self.cfg.watchlist_completa)
        if self.cartera is not None:
            try:
                simbolos += [p.simbolo for p in self.cartera.posiciones()]
            except Exception:  # noqa: BLE001 - un error en el archivo de cartera no impide buscar
                log.warning("No se pudo leer la cartera para el buscador de símbolos")
        if self.resultados is not None:
            simbolos += self.resultados.repo.seguidas()
        return BuscadorSimbolos(simbolos, self.nombres.conocidos() if self.nombres else {})

    def rendimiento(self, estado):
        """Rendimiento total con dividendos, o None si falla la fuente (la cartera se muestra igual)."""
        if self.dividendos is None:
            return None
        try:
            return self.dividendos.rendimiento_total(estado)
        except Exception:  # noqa: BLE001 - los dividendos son un complemento
            log.exception("No se pudieron calcular los dividendos")
            return None

    def analisis_completo(self, simbolo: str) -> AnalisisCompleto:
        """Análisis técnico + noticias + señal final.

        Raises:
            ErrorDatos: Si no hay datos de precios (las noticias nunca hacen fallar el análisis).
        """
        tecnico = self.tecnico.analizar(simbolo)
        noticias = None
        if self.noticias is not None:
            try:
                noticias = self.noticias.analizar(simbolo)
            except Exception:  # noqa: BLE001 - las noticias son un complemento
                log.exception("%s: falló el análisis de noticias", simbolo)
        final = combinar(tecnico.senal, noticias, self.cfg.noticias.peso_en_senal, self.cfg.tecnico.umbral_tendencia)
        return AnalisisCompleto(tecnico, noticias, final)


def armar_fuentes(cfg: Configuracion, secretos: Secretos) -> list[FuenteNoticias]:
    """Fuentes gratuitas siempre; las que requieren clave, solo si la clave está en el .env."""
    fuentes: list[FuenteNoticias] = [YahooRSS(), GoogleNewsRSS(cfg.noticias.idiomas)]
    if cfg.noticias.sec_contacto:
        fuentes.append(SecEdgar(cfg.noticias.sec_contacto))
    if secretos.finnhub_api_key:
        fuentes.append(Finnhub(secretos.finnhub_api_key.get_secret_value()))
    if secretos.marketaux_api_key:
        fuentes.append(Marketaux(secretos.marketaux_api_key.get_secret_value()))
    if secretos.newsapi_key:
        fuentes.append(NewsAPI(secretos.newsapi_key.get_secret_value()))
    return fuentes


def armar_contexto() -> Contexto:
    """Lee la configuración y construye todos los servicios."""
    cfg = cargar_configuracion()
    configurar_logs(cfg.rutas.ruta_logs())
    secretos = cargar_secretos()
    proveedor = ProveedorYahoo()
    motor = crear_motor(cfg.rutas.ruta_base_de_datos())
    almacen = AlmacenHistorico(
        cfg.rutas.ruta_historico(), FuenteYahoo(), cfg.tecnico.anios_historia, cfg.tecnico.refresco_horas
    )

    cliente_claude = None
    if secretos.anthropic_api_key and (cfg.noticias.usar_claude or cfg.resultados.usar_claude):
        import anthropic

        cliente_claude = anthropic.Anthropic(api_key=secretos.anthropic_api_key.get_secret_value(), max_retries=3)
    nombres = ResolutorNombres(cfg.rutas.ruta_nombres(), cfg.noticias.nombres)

    noticias = None
    if cfg.noticias.habilitado:
        clasificador = (
            ClasificadorClaude(cfg.noticias.modelo, cfg.noticias.esfuerzo, cliente_claude)
            if cliente_claude and cfg.noticias.usar_claude else None
        )
        noticias = ServicioNoticias(
            armar_fuentes(cfg, secretos), clasificador, RepositorioNoticias(motor), nombres, cfg.noticias
        )

    repo_resultados = RepositorioResultados(motor)
    if not repo_resultados.seguidas():  # primera vez: se cargan las de config.yaml
        for s in cfg.resultados.empresas:
            repo_resultados.seguir(s)
    fuente_res = FuenteResultadosYahoo()
    contacto = cfg.resultados.sec_contacto or cfg.noticias.sec_contacto
    resultados = ServicioResultados(
        fuente_res,
        repo_resultados,
        almacen,
        CacheInfo(cfg.rutas.ruta_cache_info(), fuente_res),
        nombres,
        cfg,
        edgar=ClienteEdgar(contacto, cfg.rutas.ruta_ciks()) if contacto else None,
        analizador=AnalizadorComunicado(cliente_claude, cfg.resultados.modelo, cfg.resultados.esfuerzo)
        if cliente_claude and cfg.resultados.usar_claude else None,
    )

    tecnico = ServicioTecnico(almacen, cfg)
    diario = ServicioDiario(RepositorioDiario(motor), proveedor, cfg)
    cartera = ServicioCartera(cfg.cartera.ruta(), proveedor, cfg, motor, armar_fuentes(cfg, secretos), nombres,
                              diario=diario)
    return Contexto(
        cfg=cfg,
        secretos=secretos,
        proveedor=proveedor,
        servicio=ServicioAlertas(RepositorioAlertas(motor), proveedor, cfg),
        tecnico=tecnico,
        noticias=noticias,
        resultados=resultados,
        backtest=ServicioBacktest(tecnico, cfg),
        cartera=cartera,
        nombres=nombres,
        stops=ServicioStops(RepositorioStops(motor), proveedor, cfg, cartera),
        tamano=ServicioTamano(proveedor, cfg, cartera),
        diario=diario,
        dividendos=ServicioDividendos(FuenteDividendosYahoo(), proveedor, cfg, cartera, diario),
    )
