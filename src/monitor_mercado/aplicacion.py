"""Arma todas las piezas del sistema en un solo lugar (terminal y bot usan lo mismo)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from monitor_mercado.alertas.repositorio import RepositorioAlertas
from monitor_mercado.alertas.servicio import ServicioAlertas
from monitor_mercado.configuracion import Configuracion, Secretos, cargar_configuracion, cargar_secretos
from monitor_mercado.datos.yahoo import ProveedorYahoo
from monitor_mercado.db import crear_motor
from monitor_mercado.noticias.fuentes import (
    Finnhub, FuenteNoticias, GoogleNewsRSS, Marketaux, NewsAPI, SecEdgar, YahooRSS,
)
from monitor_mercado.noticias.nombres import ResolutorNombres
from monitor_mercado.noticias.repositorio import RepositorioNoticias
from monitor_mercado.noticias.sentimiento import ClasificadorClaude
from monitor_mercado.noticias.servicio import AnalisisNoticias, ServicioNoticias
from monitor_mercado.registro import configurar_logs
from monitor_mercado.senal_final import SenalFinal, combinar
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

    noticias = None
    if cfg.noticias.habilitado:
        clasificador = None
        if secretos.anthropic_api_key:
            import anthropic

            clasificador = ClasificadorClaude(
                cfg.noticias.modelo,
                cfg.noticias.esfuerzo,
                anthropic.Anthropic(api_key=secretos.anthropic_api_key.get_secret_value(), max_retries=3),
            )
        noticias = ServicioNoticias(
            armar_fuentes(cfg, secretos),
            clasificador,
            RepositorioNoticias(motor),
            ResolutorNombres(cfg.rutas.ruta_nombres(), cfg.noticias.nombres),
            cfg.noticias,
        )

    return Contexto(
        cfg=cfg,
        secretos=secretos,
        proveedor=proveedor,
        servicio=ServicioAlertas(RepositorioAlertas(motor), proveedor, cfg),
        tecnico=ServicioTecnico(almacen, cfg),
        noticias=noticias,
    )
