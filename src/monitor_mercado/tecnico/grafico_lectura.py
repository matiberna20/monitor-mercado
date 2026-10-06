"""Gráfico de velas anotado como lo marcaría un trader: niveles, canal, giros y figuras."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from monitor_mercado.aviso_legal import AVISO_LEGAL  # noqa: E402
from monitor_mercado.tecnico.lectura import LecturaGrafico  # noqa: E402

SUPERFICIE, TINTA, TINTA_2, MUTED, GRILLA = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SUBE, BAJA = "#2a78d6", "#e34948"  # par divergente: azul sube, rojo baja
SOPORTE, RESISTENCIA = "#2a78d6", "#e34948"
FIGURA = "#eb6834"
MEDIAS = {"sma20": ("#eda100", "Media 20"), "sma50": ("#1baf7a", "Media 50"), "sma200": ("#4a3aa7", "Media 200")}


def _fmt(v: float) -> str:
    return (f"{v:,.2f}" if v >= 1 else f"{v:,.3f}").replace(",", "_").replace(".", ",").replace("_", ".")


def grafico_lectura(simbolo: str, l: LecturaGrafico, moneda: str, carpeta: Path, ruedas: int = 130) -> Path:
    """Genera el PNG y devuelve la ruta."""
    df = l.datos.iloc[-ruedas:]
    inicio = len(l.datos) - len(df)  # para traducir posiciones de los giros
    x = np.arange(len(df))
    fig, (ax, ax_v) = plt.subplots(2, 1, figsize=(11, 7.5), sharex=True,
                                   gridspec_kw={"height_ratios": [4, 1], "hspace": 0.06})
    fig.patch.set_facecolor(SUPERFICIE)
    for a in (ax, ax_v):
        a.set_facecolor(SUPERFICIE)
        a.grid(axis="y", color=GRILLA, linewidth=0.6)
        a.tick_params(colors=MUTED, labelsize=8, length=0)
        for lado in ("top", "right", "left"):
            a.spines[lado].set_visible(False)

    # Canal de tendencia (solo la parte visible).
    c = l.canal
    visibles = [i for i, f in enumerate(df.index) if f in c.centro.index]
    if visibles and c.claro:
        fechas = df.index[visibles]
        ax.fill_between(visibles, c.inferior.loc[fechas], c.superior.loc[fechas], color="#f0efec", linewidth=0,
                        zorder=0, label="Canal de tendencia")
        ax.plot(visibles, c.centro.loc[fechas], color=MUTED, linewidth=0.8, linestyle=":", zorder=1)

    # Velas: la mecha va del mínimo al máximo; el cuerpo, de la apertura al cierre.
    for i, (_, v) in enumerate(df.iterrows()):
        color = SUBE if v["cierre"] >= v["apertura"] else BAJA
        ax.plot([i, i], [v["minimo"], v["maximo"]], color=color, linewidth=0.8, zorder=2)
        alto = abs(v["cierre"] - v["apertura"]) or (v["maximo"] - v["minimo"]) * 0.02
        ax.add_patch(Rectangle((i - 0.32, min(v["apertura"], v["cierre"])), 0.64, alto, facecolor=color,
                               edgecolor=color, linewidth=0.5, zorder=3))

    for col, (color, nombre) in MEDIAS.items():
        if df[col].notna().any():
            ax.plot(x, df[col], color=color, linewidth=1.1, label=nombre, zorder=2)

    # Soportes y resistencias con su etiqueta a la derecha.
    for nivel, color, letra in [*[(n, SOPORTE, "S") for n in l.soportes[:2]],
                                *[(n, RESISTENCIA, "R") for n in l.resistencias[:2]]]:
        ax.axhline(nivel.precio, color=color, linewidth=1.2 if nivel.toques >= 2 else 0.8,
                   linestyle="--", alpha=0.85, zorder=1)
        ax.annotate(f"{letra} {_fmt(nivel.precio)}", (len(df) - 1, nivel.precio), xytext=(8, 0),
                    textcoords="offset points", fontsize=8, color=color, va="center", fontweight="bold")

    # Giros etiquetados (HH = máximo más alto, LL = mínimo más bajo, etc.).
    for g in l.giros:
        i = g.pos - inicio
        if 0 <= i < len(df) and g.etiqueta:
            arriba = g.tipo == "H"
            ax.annotate(g.etiqueta, (i, g.precio), xytext=(0, 9 if arriba else -12), textcoords="offset points",
                        ha="center", fontsize=7.5, color=TINTA_2)

    # Figuras: une los giros que la forman, dibuja la línea clave y el objetivo.
    for f in l.figuras[:2]:
        puntos = [(g.pos - inicio, g.precio) for g in f.giros if 0 <= g.pos - inicio < len(df)]
        if len(puntos) >= 2:
            ax.plot(*zip(*puntos), color=FIGURA, linewidth=1.4, zorder=4)
        desde = puntos[0][0] if puntos else len(df) - 20
        ax.plot([desde, len(df) - 1], [f.linea, f.linea], color=FIGURA, linewidth=1.2, linestyle="-.", zorder=4)
        ax.annotate(f"{f.nombre} ({f.estado})", (desde, f.linea), xytext=(0, -12 if f.sesgo < 0 else 6),
                    textcoords="offset points", fontsize=8, color=FIGURA)
        if f.objetivo is not None and not f.objetivo_alcanzado(l.precio):
            x_obj = len(df) + 10  # a la derecha de las etiquetas de soportes y resistencias
            ax.annotate("", xy=(x_obj, f.objetivo), xytext=(x_obj, l.precio),
                        arrowprops={"arrowstyle": "->", "color": FIGURA, "linewidth": 1.4})
            ax.annotate(f"objetivo\n{_fmt(f.objetivo)}", (x_obj, f.objetivo), xytext=(4, 0),
                        textcoords="offset points", fontsize=8, color=FIGURA, va="center")

    ax.set_xlim(-1, len(df) + 20)
    ax.set_ylabel(moneda, color=MUTED, fontsize=8)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=8, frameon=False, ncol=4, labelcolor=TINTA_2)

    # Volumen, con el color de la vela.
    colores = [SUBE if cv >= ap else BAJA for cv, ap in zip(df["cierre"], df["apertura"])]
    ax_v.bar(x, df["volumen"], color=colores, width=0.7, alpha=0.5)
    ax_v.set_ylabel("Volumen", color=MUTED, fontsize=8)
    ax_v.yaxis.set_major_formatter(lambda v, _: f"{v / 1e6:.0f}M" if v >= 1e6 else f"{v / 1e3:.0f}k")
    marcas = np.linspace(0, len(df) - 1, 7).astype(int)
    ax_v.set_xticks(marcas)
    ax_v.set_xticklabels([df.index[i].strftime("%d/%m/%y") for i in marcas])

    fig.suptitle(f"{simbolo} · lectura del gráfico: {l.direccion} (convicción {l.conviccion})",
                 x=0.06, y=0.97, ha="left", fontsize=12, color=TINTA, fontweight="bold")
    fig.subplots_adjust(top=0.9)
    fig.text(0.06, 0.01, "S = soporte · R = resistencia · HH/HL = máximo/mínimo más alto · LH/LL = más bajo · "
             + AVISO_LEGAL.replace("⚠️", "").strip(), fontsize=7, color=MUTED)
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"lectura_{simbolo.replace('^', 'INDICE_')}.png"
    fig.savefig(ruta, dpi=120, bbox_inches="tight", facecolor=SUPERFICIE)
    plt.close(fig)
    return ruta
