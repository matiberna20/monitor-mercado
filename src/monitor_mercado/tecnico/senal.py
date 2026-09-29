"""Señal de tendencia (alcista / bajista / neutral) con nivel de confianza.

Diseño en dos pasos, pensado para sumar machine learning más adelante:

1. ``caracteristicas(df)``: convierte los indicadores en "votos" numéricos entre
   -1 (bajista) y +1 (alcista), uno por columna y para CADA fecha. Esta tabla es
   exactamente lo que necesita un modelo de ML (las "features") y el backtest.
2. Un ``GeneradorSenal`` combina esos votos en un puntaje. Hoy el único es
   ``SenalPorReglas`` (promedio ponderado con pesos fijos y transparentes). Un
   modelo de ML sería otra clase con los mismos métodos, entrenada sobre la
   misma tabla, y el resto del sistema no se entera del cambio.

Sobre la "confianza": mide cuánto coinciden los indicadores entre sí y si había
datos suficientes. NO es una probabilidad de acierto. Cuánto acierta de verdad
la señal se mide en el backtest (Etapa 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Protocol

import numpy as np
import pandas as pd


class Tendencia(StrEnum):
    """Dirección probable según la señal."""

    ALCISTA = "alcista"
    BAJISTA = "bajista"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class Factor:
    """El voto de un indicador y su explicación."""

    clave: str
    nombre: str
    voto: float  # -1 a +1
    peso: float
    explicacion: str


@dataclass(frozen=True)
class Senal:
    """Resultado del análisis técnico para una fecha."""

    fecha: date
    tendencia: Tendencia
    puntaje: float  # -1 a +1
    confianza: int  # 0 a 100 (consenso entre indicadores, no probabilidad)
    metodo: str
    factores: list[Factor] = field(default_factory=list)

    @property
    def nivel_confianza(self) -> str:
        """Etiqueta legible de la confianza."""
        if self.confianza >= 65:
            return "alta"
        if self.confianza >= 35:
            return "media"
        return "baja"


def _acotar(serie: pd.Series) -> pd.Series:
    return serie.clip(-1, 1)


def caracteristicas(df: pd.DataFrame) -> pd.DataFrame:
    """Votos de cada indicador para cada fecha (NaN si falta historia).

    Las distancias se miden en "unidades de volatilidad" del propio activo: un 5%
    sobre la media es muchísimo para SPY y casi nada para NUGT. Se divide por
    ``vol * raíz(n)``, que es cuánto se mueve normalmente el precio en n ruedas.
    Los divisores son supuestos razonables, no valores optimizados: optimizarlos
    mirando el pasado es justamente la forma más común de overfitting.
    """
    c = df["cierre"]
    # Volatilidad diaria de los últimos 3 meses (desvío estándar de los retornos).
    vol = df["retorno_1d"].rolling(63, min_periods=20).std()

    def escala(n: int) -> pd.Series:
        return vol * np.sqrt(n)

    v = pd.DataFrame(index=df.index)
    # Precio vs. media de 200: la tendencia de fondo (≈ 10 meses).
    v["tendencia_largo"] = _acotar((c / df["sma200"] - 1) / escala(100))
    # Media de 50 vs. media de 200: estructura de la tendencia.
    v["estructura_medias"] = _acotar((df["sma50"] / df["sma200"] - 1) / escala(75))
    # Precio vs. media de 50: tendencia de mediano plazo.
    v["tendencia_medio"] = _acotar((c / df["sma50"] - 1) / escala(25))
    # Pendiente de la media de 20 en las últimas 10 ruedas: tendencia de corto plazo.
    v["pendiente_corto"] = _acotar((df["sma20"] / df["sma20"].shift(10) - 1) / escala(10))
    # MACD: por encima de cero (+0,5) y con histograma positivo (+0,5).
    v["macd"] = 0.5 * np.sign(df["macd"]) + 0.5 * np.sign(df["macd_hist"])
    # RSI: entre 30 y 70 mide impulso; en los extremos se modera (riesgo de reversión).
    r = df["rsi14"]
    v["rsi"] = np.select([r > 70, r < 30], [0.5, -0.5], default=(r - 50) / 20)
    v.loc[r.isna(), "rsi"] = np.nan
    # Momentum de 3 meses.
    v["momentum_3m"] = _acotar(df["retorno_63d"] / escala(63))
    # Volumen: un día con mucho volumen confirma la dirección de ese día.
    vr = df["vol_relativo"]
    v["volumen"] = np.where(
        vr > 1.5, np.sign(df["retorno_1d"]) * np.minimum((vr - 1) / 1.5, 1), 0.0
    )
    v.loc[vr.isna(), "volumen"] = np.nan
    return v


NOMBRES = {
    "tendencia_largo": "Precio vs. media de 200 días",
    "estructura_medias": "Media de 50 vs. media de 200",
    "tendencia_medio": "Precio vs. media de 50 días",
    "pendiente_corto": "Pendiente de la media de 20 días",
    "macd": "MACD",
    "rsi": "RSI (14)",
    "momentum_3m": "Rendimiento de 3 meses",
    "volumen": "Volumen",
}


def _explicar(clave: str, fila: pd.Series) -> str:
    """Texto con el valor concreto que generó cada voto."""
    c = fila["cierre"]
    if clave == "tendencia_largo":
        return f"cierre {c / fila['sma200'] - 1:+.1%} respecto de la media de 200"
    if clave == "estructura_medias":
        return f"media 50 {fila['sma50'] / fila['sma200'] - 1:+.1%} respecto de la de 200"
    if clave == "tendencia_medio":
        return f"cierre {c / fila['sma50'] - 1:+.1%} respecto de la media de 50"
    if clave == "pendiente_corto":
        return "la media de 20 sube" if fila["_pend"] > 0 else "la media de 20 baja"
    if clave == "macd":
        lado = "positivo" if fila["macd"] > 0 else "negativo"
        impulso = "creciente" if fila["macd_hist"] > 0 else "decreciente"
        return f"MACD {lado}, impulso {impulso}"
    if clave == "rsi":
        extra = " (sobrecompra)" if fila["rsi14"] > 70 else " (sobreventa)" if fila["rsi14"] < 30 else ""
        return f"RSI {fila['rsi14']:.0f}{extra}"
    if clave == "momentum_3m":
        return f"{fila['retorno_63d']:+.1%} en 3 meses"
    if clave == "volumen":
        return f"volumen {fila['vol_relativo']:.1f} veces el promedio"
    return ""


class GeneradorSenal(Protocol):
    """Interfaz común para reglas hoy y modelos de ML en el futuro."""

    nombre: str

    def puntajes(self, votos: pd.DataFrame) -> pd.DataFrame:
        """Para cada fecha: columnas ``puntaje`` (-1 a 1) y ``confianza`` (0 a 100)."""
        ...

    def generar(self, df: pd.DataFrame) -> Senal:
        """Señal para la última fecha de ``df`` (salida de calcular_indicadores)."""
        ...


class SenalPorReglas:
    """Promedio ponderado de los votos de cada indicador."""

    nombre = "reglas v1"

    PESOS: dict[str, float] = {
        "tendencia_largo": 2.0,
        "estructura_medias": 1.5,
        "tendencia_medio": 1.0,
        "pendiente_corto": 1.0,
        "macd": 1.0,
        "rsi": 1.0,
        "momentum_3m": 1.5,
        "volumen": 0.5,
    }

    def __init__(self, umbral: float = 0.2) -> None:
        """
        Args:
            umbral: Puntaje a partir del cual la señal deja de ser neutral.
        """
        self.umbral = umbral

    def puntajes(self, votos: pd.DataFrame) -> pd.DataFrame:
        """Puntaje y confianza para todas las fechas (útil para el backtest)."""
        pesos = pd.Series(self.PESOS)
        v = votos[pesos.index]
        disponibles = v.notna().mul(pesos, axis=1)
        peso_total = disponibles.sum(axis=1)
        puntaje = v.fillna(0).mul(pesos, axis=1).sum(axis=1) / peso_total.replace(0, np.nan)
        cobertura = peso_total / pesos.sum()
        # Coincidencia: qué parte del peso vota en la misma dirección que el puntaje.
        mismo_signo = (np.sign(v).eq(np.sign(puntaje), axis=0) & v.notna()).mul(pesos, axis=1)
        acuerdo = mismo_signo.sum(axis=1) / peso_total.replace(0, np.nan)
        confianza = (100 * np.sqrt(puntaje.abs() * acuerdo) * cobertura).round()
        return pd.DataFrame({"puntaje": puntaje, "confianza": confianza})

    def tendencia(self, puntaje: float) -> Tendencia:
        """Clasifica un puntaje en alcista / bajista / neutral."""
        if puntaje >= self.umbral:
            return Tendencia.ALCISTA
        if puntaje <= -self.umbral:
            return Tendencia.BAJISTA
        return Tendencia.NEUTRAL

    def generar(self, df: pd.DataFrame) -> Senal:
        """Señal de la última rueda, con el detalle de cada factor."""
        votos = caracteristicas(df)
        resultado = self.puntajes(votos).iloc[-1]
        fila = df.iloc[-1].copy()
        fila["_pend"] = df["sma20"].iloc[-1] - df["sma20"].shift(10).iloc[-1]
        factores = [
            Factor(clave, NOMBRES[clave], float(voto), self.PESOS[clave], _explicar(clave, fila))
            for clave, voto in votos.iloc[-1].items()
            if pd.notna(voto)
        ]
        puntaje = float(resultado["puntaje"]) if pd.notna(resultado["puntaje"]) else 0.0
        confianza = int(resultado["confianza"]) if pd.notna(resultado["confianza"]) else 0
        return Senal(
            fecha=pd.Timestamp(df.index[-1]).date(),
            tendencia=self.tendencia(puntaje),
            puntaje=puntaje,
            confianza=confianza,
            metodo=self.nombre,
            factores=factores,
        )
