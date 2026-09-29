"""Validación honesta: walk-forward, prueba de azar (bootstrap) y poder predictivo.

Overfitting (sobreajuste): si probás muchas combinaciones de parámetros sobre los
mismos datos, alguna va a salir muy bien POR CASUALIDAD. Esa combinación "aprendió"
el ruido del pasado y falla con datos nuevos. Para detectarlo:

- Walk-forward: se eligen los parámetros con los datos de un período (entrenamiento)
  y se miden en el período siguiente, que el optimizador nunca vio (prueba). Después
  se corre la ventana hacia adelante y se repite. Solo cuentan los resultados de
  prueba ("fuera de muestra").
- Degradación: si el Sharpe de entrenamiento es mucho mayor que el de prueba, los
  parámetros estaban sobreajustados.
- Bootstrap: se remezclan los retornos miles de veces (en bloques, para respetar
  que los días consecutivos se parecen) para estimar qué tan seguido una ventaja
  como la observada aparecería por puro azar.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from monitor_mercado.backtest.motor import DIAS_POR_ANIO, posiciones, sharpe, simular

GRILLA_ENTRADA = (0.1, 0.2, 0.3, 0.4, 0.5)
GRILLA_SALIDA = (-0.3, -0.1, 0.0, 0.1)


@dataclass(frozen=True)
class Ventana:
    """Un tramo del walk-forward."""

    inicio_prueba: pd.Timestamp
    fin_prueba: pd.Timestamp
    entrada: float
    salida: float
    sharpe_entrenamiento: float
    sharpe_prueba: float


@dataclass(frozen=True)
class ResultadoWalkForward:
    """Retornos fuera de muestra y el detalle de cada ventana."""

    retornos: pd.DataFrame  # columnas de ``simular``, solo días de prueba
    ventanas: list[Ventana]

    @property
    def sharpe_entrenamiento_medio(self) -> float:
        """Sharpe promedio de los parámetros elegidos, medido donde se eligieron."""
        return float(np.mean([v.sharpe_entrenamiento for v in self.ventanas])) if self.ventanas else 0.0

    @property
    def sharpe_prueba_medio(self) -> float:
        """Sharpe promedio de esos mismos parámetros en datos nuevos."""
        return float(np.mean([v.sharpe_prueba for v in self.ventanas])) if self.ventanas else 0.0

    @property
    def parametros_estables(self) -> bool:
        """True si casi siempre se eligieron los mismos parámetros (buena señal)."""
        if not self.ventanas:
            return False
        elegidos = [(v.entrada, v.salida) for v in self.ventanas]
        mas_comun = max(set(elegidos), key=elegidos.count)
        return elegidos.count(mas_comun) / len(elegidos) >= 0.6


def walk_forward(
    datos: pd.DataFrame,
    puntajes: pd.Series,
    costo: float,
    anios_entrenamiento: int = 3,
    anios_prueba: int = 1,
    corto: bool = False,
) -> ResultadoWalkForward:
    """Optimiza umbrales en cada ventana de entrenamiento y los mide en la siguiente."""
    fechas = datos.index
    n_ent, n_pru = anios_entrenamiento * DIAS_POR_ANIO, anios_prueba * DIAS_POR_ANIO
    # Se simula una vez por combinación sobre toda la serie y después se recorta:
    # la posición del día solo depende de puntajes pasados, así que no hay filtración.
    simulaciones = {
        (e, s): simular(datos, posiciones(puntajes, e, s, corto), costo)
        for e in GRILLA_ENTRADA for s in GRILLA_SALIDA if s < e
    }
    ventanas: list[Ventana] = []
    tramos: list[pd.DataFrame] = []
    inicio = 0
    while inicio + n_ent + 20 < len(fechas):
        ent = slice(fechas[inicio], fechas[inicio + n_ent - 1])
        fin_idx = min(inicio + n_ent + n_pru, len(fechas)) - 1
        pru = slice(fechas[inicio + n_ent], fechas[fin_idx])
        (e, s), mejor = max(
            ((clave, sharpe(sim.loc[ent, "estrategia"])) for clave, sim in simulaciones.items()),
            key=lambda x: x[1],
        )
        tramo = simulaciones[(e, s)].loc[pru]
        tramos.append(tramo)
        ventanas.append(Ventana(pru.start, pru.stop, e, s, mejor, sharpe(tramo["estrategia"])))
        inicio += n_pru
    retornos = pd.concat(tramos) if tramos else pd.DataFrame(columns=["estrategia", "comprar_y_mantener"])
    return ResultadoWalkForward(retornos, ventanas)


def bootstrap_sharpe(
    a: pd.Series, b: pd.Series, repeticiones: int = 2000, bloque: int = 20, semilla: int = 42
) -> float:
    """Probabilidad aproximada de que la ventaja de Sharpe de ``a`` sobre ``b`` sea azar.

    Remuestrea bloques de días (los mismos para ambas series) y cuenta en qué fracción
    de los casos ``a`` NO supera a ``b``. Un valor bajo (ej. 0,05) indica que la ventaja
    es difícil de explicar por suerte; un valor cercano a 0,5 indica que es indistinguible
    del azar.
    """
    x = np.column_stack([a.to_numpy(float), b.to_numpy(float)])
    n = len(x)
    if n < bloque * 5:
        return 1.0
    rng = np.random.default_rng(semilla)
    bloques = int(np.ceil(n / bloque))
    no_supera = 0
    for _ in range(repeticiones):
        inicios = rng.integers(0, n - bloque, bloques)
        idx = (inicios[:, None] + np.arange(bloque)).ravel()[:n]
        m = x[idx]
        sa = m[:, 0].mean() / (m[:, 0].std() or np.inf)
        sb = m[:, 1].mean() / (m[:, 1].std() or np.inf)
        no_supera += sa <= sb
    return no_supera / repeticiones


@dataclass(frozen=True)
class PoderPredictivo:
    """Qué tan seguido acertó la señal la dirección de los días siguientes."""

    horizonte: int
    correlacion: float | None  # correlación de rangos entre puntaje y retorno futuro
    acierto_alcista: float | None  # % de veces que subió cuando la señal decía alcista
    acierto_bajista: float | None  # % de veces que bajó cuando la señal decía bajista
    base_suba: float  # % de veces que subió en general (lo que acertaría "adivinar siempre suba")
    muestras: int


def poder_predictivo(puntajes: pd.Series, cierres: pd.Series, umbral: float, horizonte: int = 20) -> PoderPredictivo:
    """Compara la señal con el retorno de los ``horizonte`` días siguientes.

    Se toma una observación cada ``horizonte`` días (no superpuestas): si no, el mismo
    movimiento se contaría 20 veces y los resultados parecerían más firmes de lo que son.
    """
    futuro = cierres.shift(-horizonte) / cierres - 1
    tabla = pd.DataFrame({"p": puntajes, "f": futuro}).dropna().iloc[::horizonte]
    if len(tabla) < 10:
        return PoderPredictivo(horizonte, None, None, None, 0.0, len(tabla))
    alcista, bajista = tabla[tabla["p"] >= umbral], tabla[tabla["p"] <= -umbral]
    return PoderPredictivo(
        horizonte=horizonte,
        correlacion=float(tabla["p"].rank().corr(tabla["f"].rank())),
        acierto_alcista=float((alcista["f"] > 0).mean()) if len(alcista) else None,
        acierto_bajista=float((bajista["f"] < 0).mean()) if len(bajista) else None,
        base_suba=float((tabla["f"] > 0).mean()),
        muestras=len(tabla),
    )
