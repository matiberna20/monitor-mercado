"""Gráfico PNG del análisis técnico (para ver en la PC o mandar por Telegram).

Cuatro paneles, cada uno con su propio eje (nunca dos escalas en el mismo panel):
precio con medias y bandas de Bollinger, volumen, RSI y MACD.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sin ventana: solo genera el archivo
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.dates import AutoDateLocator, DateFormatter  # noqa: E402

from monitor_mercado.aviso_legal import AVISO_LEGAL  # noqa: E402
from monitor_mercado.tecnico.servicio import Analisis  # noqa: E402

# Paleta categórica en orden fijo (validada para daltonismo) y tintas neutras.
SERIE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
DIVERGENTE_POS, DIVERGENTE_NEG = "#2a78d6", "#e34948"
SUPERFICIE, TINTA, TINTA_2, MUTED, GRILLA, BASE = (
    "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7")
BANDA = "#f0efec"


def _estilo(ax: plt.Axes) -> None:
    ax.set_facecolor(SUPERFICIE)
    ax.grid(axis="y", color=GRILLA, linewidth=0.6)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(BASE)


def generar_grafico(analisis: Analisis, carpeta: Path, ruedas: int = 180) -> Path:
    """Genera el PNG y devuelve su ruta."""
    df = analisis.datos.tail(ruedas)
    x = df.index
    fig, (ax_p, ax_v, ax_r, ax_m) = plt.subplots(
        4, 1, figsize=(10, 9), sharex=True,
        gridspec_kw={"height_ratios": [3.2, 0.9, 1, 1.1], "hspace": 0.12},
    )
    fig.patch.set_facecolor(SUPERFICIE)
    for ax in (ax_p, ax_v, ax_r, ax_m):
        _estilo(ax)

    # Precio, medias y bandas.
    ax_p.fill_between(x, df["bb_inferior"], df["bb_superior"], color=BANDA, linewidth=0,
                      label="Bandas de Bollinger")
    ax_p.plot(x, df["cierre"], color=SERIE[0], linewidth=2, label="Cierre")
    for color, col, nombre in zip(SERIE[1:], ("sma20", "sma50", "sma200"),
                                  ("Media 20", "Media 50", "Media 200")):
        if df[col].notna().any():
            ax_p.plot(x, df[col], color=color, linewidth=1.4, label=nombre)
    # Leyenda arriba del panel, para que no tape los datos.
    ax_p.legend(loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=8, frameon=False, ncol=5,
                labelcolor=TINTA_2, borderaxespad=0.2)
    ax_p.set_ylabel(analisis.moneda, color=MUTED, fontsize=8)
    ultimo = df["cierre"].iloc[-1]
    ax_p.annotate(f"{ultimo:,.2f}", (x[-1], ultimo), xytext=(6, 0), textcoords="offset points",
                  fontsize=8, color=TINTA, va="center")

    s = analisis.senal
    fig.suptitle(
        f"{analisis.simbolo}  ·  tendencia {s.tendencia.value.upper()}  ·  confianza {s.confianza}/100 "
        f"({s.nivel_confianza})",
        x=0.06, y=0.95, ha="left", fontsize=12, color=TINTA, fontweight="bold",
    )
    fig.subplots_adjust(top=0.90)

    # Volumen (neutro: el color no agrega información acá).
    ax_v.bar(x, df["volumen"], color=BASE, width=0.8)
    ax_v.set_ylabel("Volumen", color=MUTED, fontsize=8)
    ax_v.yaxis.set_major_formatter(lambda v, _: f"{v / 1e6:.0f}M" if v >= 1e6 else f"{v / 1e3:.0f}k")

    # RSI con zonas de 30 y 70.
    ax_r.plot(x, df["rsi14"], color=SERIE[0], linewidth=1.4)
    for nivel in (30, 70):
        ax_r.axhline(nivel, color=MUTED, linewidth=0.8, linestyle="--")
    ax_r.set_ylim(0, 100)
    ax_r.set_ylabel("RSI 14", color=MUTED, fontsize=8)

    # MACD: histograma divergente (positivo/negativo) y las dos líneas.
    colores = [DIVERGENTE_POS if v >= 0 else DIVERGENTE_NEG for v in df["macd_hist"].fillna(0)]
    ax_m.bar(x, df["macd_hist"], color=colores, width=0.8, alpha=0.55)
    ax_m.plot(x, df["macd"], color=SERIE[0], linewidth=1.4, label="MACD")
    ax_m.plot(x, df["macd_senal"], color=SERIE[1], linewidth=1.4, label="Señal")
    ax_m.axhline(0, color=BASE, linewidth=0.8)
    ax_m.legend(loc="upper left", fontsize=8, frameon=False, ncol=2, labelcolor=TINTA_2)
    ax_m.set_ylabel("MACD", color=MUTED, fontsize=8)

    ax_m.xaxis.set_major_locator(AutoDateLocator())
    ax_m.xaxis.set_major_formatter(DateFormatter("%m/%y"))
    # Sin el emoji: la fuente del gráfico no lo tiene y aparecería un cuadrado.
    fig.text(0.06, 0.01, AVISO_LEGAL.replace("⚠️", "").strip(), fontsize=7.5, color=MUTED)

    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{analisis.simbolo.replace('^', 'INDICE_')}.png"
    fig.savefig(ruta, dpi=120, bbox_inches="tight", facecolor=SUPERFICIE)
    plt.close(fig)
    return ruta
