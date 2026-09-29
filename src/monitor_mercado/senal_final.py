"""Señal final: combina la señal técnica (precios) con el sentimiento de noticias.

Fórmula:
    peso_efectivo = peso_noticias (config, 0,3) × cobertura de noticias (0 a 1)
    puntaje_final = (1 - peso_efectivo) × técnico + peso_efectivo × noticias

Si casi no hay noticias relevantes, la cobertura es baja y la señal final queda
prácticamente igual a la técnica. Si técnica y noticias apuntan en direcciones
opuestas, se baja la confianza: hay información contradictoria.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from monitor_mercado.noticias.servicio import AnalisisNoticias
from monitor_mercado.tecnico.senal import Senal, Tendencia

UMBRAL_OPINION = 0.1  # por debajo de esto una señal se considera "sin opinión"


@dataclass(frozen=True)
class SenalFinal:
    """Señal combinada de técnico + noticias."""

    tendencia: Tendencia
    puntaje: float
    confianza: int
    peso_noticias: float  # peso efectivo que tuvieron las noticias (0 a 1)
    coinciden: bool | None  # None si alguna de las dos no tiene opinión


def combinar(tecnica: Senal, noticias: AnalisisNoticias | None, peso_config: float, umbral: float) -> SenalFinal:
    """Combina ambas señales.

    Args:
        tecnica: Señal del análisis técnico.
        noticias: Análisis de noticias (None si está desactivado).
        peso_config: Peso máximo de las noticias (``noticias.peso_en_senal``).
        umbral: Puntaje a partir del cual la señal deja de ser neutral.
    """
    if noticias is None or noticias.puntaje is None:
        return SenalFinal(tecnica.tendencia, tecnica.puntaje, tecnica.confianza, 0.0, None)

    w = peso_config * noticias.cobertura
    puntaje = (1 - w) * tecnica.puntaje + w * noticias.puntaje
    confianza = (1 - w) * tecnica.confianza + w * 100 * abs(noticias.puntaje)

    coinciden: bool | None = None
    if abs(tecnica.puntaje) >= UMBRAL_OPINION and abs(noticias.puntaje) >= UMBRAL_OPINION:
        coinciden = bool(np.sign(tecnica.puntaje) == np.sign(noticias.puntaje))
        if not coinciden:
            confianza *= 1 - w  # información contradictoria: menos confianza

    if puntaje >= umbral:
        tendencia = Tendencia.ALCISTA
    elif puntaje <= -umbral:
        tendencia = Tendencia.BAJISTA
    else:
        tendencia = Tendencia.NEUTRAL
    return SenalFinal(tendencia, puntaje, int(round(confianza)), w, coinciden)
