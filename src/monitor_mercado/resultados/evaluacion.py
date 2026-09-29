"""Evaluación de un resultado RELATIVO a lo que esperaba el mercado.

Idea clave: el precio ya refleja lo que el mercado espera. Una empresa que gana
mucho dinero puede caer si esperaban que ganara más, y una que pierde puede subir
si esperaban que perdiera más. Por eso lo central es la SORPRESA:

    sorpresa = (dato real - consenso de analistas) / |consenso|

- "Beat" (mejor): la sorpresa supera el umbral positivo.
- "En línea": la sorpresa es chica en cualquier dirección.
- "Miss" (peor): la sorpresa es menor al umbral negativo.

El veredicto final combina varios factores con pesos fijos y transparentes. La
guidance (lo que la empresa espera para adelante) pesa tanto como la sorpresa,
porque el mercado mira más el futuro que el pasado.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from monitor_mercado.resultados.metricas import Metricas
from monitor_mercado.resultados.reaccion import Reaccion

UMBRAL_EPS = 0.02  # ±2%: el EPS es más volátil
UMBRAL_INGRESOS = 0.01  # ±1%: los ingresos son más predecibles


class Sorpresa(StrEnum):
    """Resultado contra el consenso."""

    BEAT = "mejor de lo esperado"
    EN_LINEA = "en línea"
    MISS = "peor de lo esperado"
    SIN_DATO = "sin consenso disponible"


class Veredicto(StrEnum):
    """Conclusión general."""

    MEJOR = "MEJOR DE LO ESPERADO"
    EN_LINEA = "EN LÍNEA CON LO ESPERADO"
    PEOR = "PEOR DE LO ESPERADO"


def sorpresa_pct(real: float | None, estimado: float | None) -> float | None:
    """Sorpresa porcentual contra el consenso (None si falta alguno)."""
    if real is None or estimado is None or estimado == 0:
        return None
    return (real - estimado) / abs(estimado)


def clasificar(sorpresa: float | None, umbral: float) -> Sorpresa:
    """Beat / en línea / miss según el umbral."""
    if sorpresa is None:
        return Sorpresa.SIN_DATO
    if sorpresa > umbral:
        return Sorpresa.BEAT
    if sorpresa < -umbral:
        return Sorpresa.MISS
    return Sorpresa.EN_LINEA


@dataclass(frozen=True)
class FactorResultado:
    """Un factor del veredicto con su voto (-1 a +1), peso y explicación."""

    nombre: str
    voto: float
    peso: float
    explicacion: str


@dataclass(frozen=True)
class Evaluacion:
    """Veredicto y el detalle de cómo se llegó."""

    veredicto: Veredicto
    puntaje: float
    factores: list[FactorResultado]


def _p(valor: float, signo: bool = True) -> str:
    """Porcentaje con coma decimal: +6,9% / 32,6%."""
    return (f"{100 * valor:+.1f}%" if signo else f"{100 * valor:.1f}%").replace(".", ",")


def _signo_umbral(valor: float, umbral: float) -> float:
    return 1.0 if valor > umbral else -1.0 if valor < -umbral else 0.0


def evaluar(
    sorpresa_eps: float | None,
    sorpresa_ingresos: float | None,
    metricas: Metricas | None,
    reacciones: list[Reaccion],
    guidance: str | None = None,  # "subio" | "mantuvo" | "bajo" | "no_informa"
    tono: str | None = None,  # "positivo" | "neutral" | "negativo"
) -> Evaluacion:
    """Combina todos los factores disponibles en un veredicto."""
    f: list[FactorResultado] = []

    if sorpresa_eps is not None:
        f.append(FactorResultado("EPS vs. consenso", _signo_umbral(sorpresa_eps, UMBRAL_EPS), 2.0,
                                 f"sorpresa de {_p(sorpresa_eps)}"))
    if sorpresa_ingresos is not None:
        f.append(FactorResultado("Ingresos vs. consenso", _signo_umbral(sorpresa_ingresos, UMBRAL_INGRESOS), 2.0,
                                 f"sorpresa de {_p(sorpresa_ingresos)}"))
    if guidance in ("subio", "mantuvo", "bajo"):
        voto = {"subio": 1.0, "mantuvo": 0.0, "bajo": -1.0}[guidance]
        texto = {"subio": "la empresa mejoró sus proyecciones", "mantuvo": "mantuvo sus proyecciones",
                 "bajo": "la empresa bajó sus proyecciones"}[guidance]
        f.append(FactorResultado("Guidance", voto, 2.0, texto))
    if tono in ("positivo", "neutral", "negativo"):
        f.append(FactorResultado("Tono del comunicado", {"positivo": 1.0, "neutral": 0.0, "negativo": -1.0}[tono],
                                 1.0, f"tono {tono}"))
    if metricas is not None:
        if metricas.ingresos_yoy is not None:
            f.append(FactorResultado("Crecimiento de ingresos (interanual)",
                                     _signo_umbral(metricas.ingresos_yoy, 0.03), 0.5,
                                     f"{_p(metricas.ingresos_yoy)} contra el mismo trimestre del año pasado"))
        actual, anterior = metricas.margen_operativo, metricas.margen_operativo_hace_un_anio
        nombre = "Margen operativo"
        if actual is None or anterior is None:
            actual, anterior, nombre = metricas.margen_neto, metricas.margen_neto_hace_un_anio, "Margen neto"
        if actual is not None and anterior is not None:
            cambio = actual - anterior
            f.append(FactorResultado(f"{nombre} (interanual)", _signo_umbral(cambio, 0.01), 1.0,
                                     f"{_p(actual, False)} vs. {_p(anterior, False)} hace un año "
                                     f"({_p(cambio).rstrip('%')} puntos)"))
        if metricas.fcf_12m is not None:
            f.append(FactorResultado("Flujo de caja libre (12 meses)", 0.5 if metricas.fcf_12m > 0 else -1.0, 0.5,
                                     "positivo" if metricas.fcf_12m > 0 else "negativo: la empresa consume caja"))
        if metricas.deuda_neta_sobre_ebitda is not None:
            d = metricas.deuda_neta_sobre_ebitda
            voto = 0.5 if d < 1 else -0.5 if d > 3 else 0.0
            f.append(FactorResultado("Deuda neta / EBITDA", voto, 0.5, f"{d:.1f} veces".replace(".", ",")))
    reaccion = next((r for r in reacciones if r.ruedas == 1), None)
    if reaccion is not None:
        f.append(FactorResultado("Reacción del precio (1 rueda, vs. índice)", _signo_umbral(reaccion.anormal, 0.02),
                                 1.0, f"{_p(reaccion.anormal)} descontando al mercado"))

    peso_total = sum(x.peso for x in f)
    puntaje = sum(x.voto * x.peso for x in f) / peso_total if peso_total else 0.0
    veredicto = Veredicto.MEJOR if puntaje > 0.25 else Veredicto.PEOR if puntaje < -0.25 else Veredicto.EN_LINEA
    return Evaluacion(veredicto, puntaje, f)
