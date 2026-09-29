"""Reportes del backtest: texto, gráfico, resumen de varios activos y explicación."""

from __future__ import annotations

from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from monitor_mercado.aviso_legal import AVISO_LEGAL, pie_de_mensaje  # noqa: E402
from monitor_mercado.backtest.motor import Metricas, curva  # noqa: E402
from monitor_mercado.backtest.servicio import Conclusion, ResultadoBacktest  # noqa: E402
from monitor_mercado.notificaciones.formato import numero  # noqa: E402

ICONO = {Conclusion.APORTA: "🟢", Conclusion.DUDOSA: "🟡", Conclusion.MENOS_RIESGO: "🟠", Conclusion.NO_APORTA: "🔴"}


def _p(v: float | None, signo: bool = False) -> str:
    if v is None:
        return "s/d"
    return (f"{100 * v:+.1f}%" if signo else f"{100 * v:.1f}%").replace(".", ",")


def _n(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def _tabla(est: Metricas, bh: Metricas) -> list[str]:
    acierto = _p(est.tasa_acierto) if est.tasa_acierto is not None else "s/d"
    return [
        "(señal vs. comprar y mantener)",
        f"• Retorno anual: {_p(est.retorno_anual, True)} vs. {_p(bh.retorno_anual, True)}",
        f"• Retorno total: {_p(est.retorno_total, True)} vs. {_p(bh.retorno_total, True)}",
        f"• Volatilidad anual: {_p(est.volatilidad)} vs. {_p(bh.volatilidad)}",
        f"• Sharpe: {_n(est.sharpe)} vs. {_n(bh.sharpe)}",
        f"• Peor caída: {_p(est.max_drawdown)} vs. {_p(bh.max_drawdown)}",
        f"• Tiempo invertido: {_p(est.exposicion)} vs. 100%",
        f"• Operaciones: {est.operaciones} · con ganancia: {acierto} · costos pagados: {_p(est.costos)} del capital",
    ]


def _azar(p: float) -> str:
    if p < 0.05:
        return f"{_p(p)} → muy difícil de explicar por suerte"
    if p < 0.10:
        return f"{_p(p)} → poco probable que sea suerte"
    if p < 0.40:
        return f"{_p(p)} → podría ser suerte"
    return f"{_p(p)} → indistinguible del azar"


def reporte_backtest(r: ResultadoBacktest) -> str:
    """Reporte completo de un activo."""
    lineas = [
        f"{ICONO[r.conclusion]} Backtest de {r.simbolo}: {r.conclusion.value.upper()}",
        f"Período: {r.desde:%m/%Y} a {r.hasta:%m/%Y} · precios en {r.moneda} · costo por operación "
        f"{_p(r.costo_por_lado)} (comisión + slippage)",
        "",
        "1️⃣ La señal tal como la usa el sistema (compra si es alcista, vende si es bajista, sin optimizar):",
        *_tabla(r.fija, r.fija_bh),
        f"¿Suerte? Probabilidad de que una ventaja así aparezca por azar: {_azar(r.prob_azar_fija)}",
    ]
    if r.wf_estrategia is not None and r.wf_bh is not None:
        w = r.wf
        lineas += [
            "",
            f"2️⃣ Walk-forward (umbrales elegidos con {len(w.ventanas)} ventanas de entrenamiento y medidos "
            "en el año siguiente, que no vieron):",
            *_tabla(r.wf_estrategia, r.wf_bh),
            f"¿Suerte? {_azar(r.prob_azar_wf or 1.0)}",
            "",
            "🔬 Overfitting (sobreajuste)",
            f"Sharpe en entrenamiento: {_n(w.sharpe_entrenamiento_medio)} · en datos nuevos: {_n(w.sharpe_prueba_medio)}",
        ]
        caida = w.sharpe_entrenamiento_medio - w.sharpe_prueba_medio
        if caida > 0.3:
            lineas.append("⚠️ Rinde bastante peor con datos nuevos que donde se optimizó: los parámetros "
                          "\"aprendieron\" ruido del pasado. Es la señal típica de overfitting.")
        elif caida > 0:
            lineas.append("Rinde algo peor con datos nuevos, lo normal. La diferencia no es alarmante.")
        else:
            lineas.append("Con datos nuevos rindió igual o mejor que en entrenamiento: no hay señales de sobreajuste.")
        lineas.append("Los parámetros elegidos fueron " + ("estables entre ventanas (buena señal)." if w.parametros_estables
                      else "cambiando de una ventana a otra: no hay una configuración que funcione siempre."))

    pp = r.predictivo
    if pp.correlacion is not None:
        lineas += [
            "",
            f"🎯 Poder predictivo (dirección de los {pp.horizonte} días siguientes, {pp.muestras} observaciones)",
            f"Correlación señal-retorno futuro: {_n(pp.correlacion)} (0 = ninguna relación; negativa = al revés)",
        ]
        if pp.acierto_alcista is not None:
            lineas.append(f"Cuando dijo ALCISTA, subió el {_p(pp.acierto_alcista)} de las veces "
                          f"(en general subió el {_p(pp.base_suba)}).")
        if pp.acierto_bajista is not None:
            lineas.append(f"Cuando dijo BAJISTA, bajó el {_p(pp.acierto_bajista)} de las veces "
                          f"(en general bajó el {_p(1 - pp.base_suba)}).")

    lineas += ["", "📌 Conclusión", _texto_conclusion(r)]
    lineas += ["", "Un backtest mide el PASADO con una sola historia de precios: que algo haya funcionado (o no) "
               "no garantiza lo que va a pasar."]
    return "\n".join(lineas) + pie_de_mensaje()


def _texto_conclusion(r: ResultadoBacktest) -> str:
    est = r.wf_estrategia or r.fija
    bh = r.wf_bh or r.fija_bh
    base = {
        Conclusion.APORTA: "En datos que no vio, la señal tuvo mejor relación retorno/riesgo que comprar y mantener, "
                           "y es difícil de explicar por suerte. Aun así, es un solo activo y un solo período.",
        Conclusion.DUDOSA: "Rindió algo mejor ajustado por riesgo, pero la diferencia es chica y podría ser suerte. "
                           "No alcanza para confiar en la señal.",
        Conclusion.MENOS_RIESGO: "No mejora la relación retorno/riesgo, pero sus caídas fueron bastante menores "
                                 f"({_p(est.max_drawdown)} contra {_p(bh.max_drawdown)}). Puede servir para quien "
                                 "prioriza no sufrir caídas grandes, aceptando rendir menos.",
        Conclusion.NO_APORTA: "Para este activo, seguir la señal fue PEOR (o no mejor) que simplemente comprar y "
                              "mantener, una vez que se descuentan comisiones y se mide con datos nuevos. "
                              "Con la evidencia disponible, la señal no aporta valor.",
    }[r.conclusion]
    return base


def resumen_backtests(resultados: list[ResultadoBacktest], errores: dict[str, str]) -> str:
    """Resumen de varios activos con la conclusión general."""
    if not resultados:
        return "No se pudo correr el backtest para ningún activo." + pie_de_mensaje()
    lineas = ["📊 Backtest de la watchlist (fuera de muestra, con costos)",
              "Sharpe señal vs. comprar y mantener · peor caída señal vs. comprar y mantener", ""]
    for r in sorted(resultados, key=lambda x: -(x.wf_estrategia or x.fija).sharpe):
        est, bh = r.wf_estrategia or r.fija, r.wf_bh or r.fija_bh
        lineas.append(f"{ICONO[r.conclusion]} {r.simbolo}: Sharpe {_n(est.sharpe)} vs. {_n(bh.sharpe)} · "
                      f"caída {_p(est.max_drawdown)} vs. {_p(bh.max_drawdown)}")
    lineas.append("(Sharpe = retorno por unidad de riesgo: más alto es mejor)")
    ganadores = [r for r in resultados if r.conclusion is Conclusion.APORTA]
    mejores = [r for r in resultados if (r.wf_estrategia or r.fija).sharpe > (r.wf_bh or r.fija_bh).sharpe]
    diferencia = median([(r.wf_estrategia or r.fija).sharpe - (r.wf_bh or r.fija_bh).sharpe for r in resultados])
    ics = [r.predictivo.correlacion for r in resultados if r.predictivo.correlacion is not None]
    lineas += [
        "",
        "📌 Conclusión general",
        f"• Le ganó a comprar y mantener (ajustado por riesgo) en {len(mejores)} de {len(resultados)} activos; "
        f"con evidencia firme, en {len(ganadores)}.",
        f"• Diferencia típica de Sharpe: {_n(diferencia)}.",
    ]
    if ics:
        lineas.append(f"• Correlación típica entre señal y retorno de los {resultados[0].predictivo.horizonte} "
                      f"días siguientes: {_n(median(ics))}.")
    if len(ganadores) <= len(resultados) * 0.2 and diferencia <= 0:
        lineas.append("➡️ Dicho claro: con estos datos, la señal técnica NO aporta valor frente a comprar y "
                      "mantener. Sirve como resumen ordenado de los indicadores, pero no como sistema para "
                      "decidir compras y ventas.")
    elif len(ganadores) >= len(resultados) * 0.5:
        lineas.append("➡️ La señal mostró ventaja en la mayoría de los activos. Aun así, revisá el riesgo de "
                      "overfitting y probala más tiempo antes de confiar en ella.")
    else:
        lineas.append("➡️ Resultados mixtos: la señal funciona en algunos activos y en otros no. Eso es "
                      "compatible con el azar; no hay evidencia suficiente de que aporte valor.")
    if errores:
        lineas += ["", "Sin backtest: " + ", ".join(f"{s} ({e})" for s, e in errores.items())]
    return "\n".join(lineas) + pie_de_mensaje()


def explicacion_backtest(r: ResultadoBacktest) -> str:
    """Explicación para aprender."""
    partes = [
        f"📘 Explicación para aprender – backtest de {r.simbolo}",
        "🧪 Qué es un backtest\n"
        "Es simular qué hubiera pasado si seguías la señal en el pasado: comprar cuando decía alcista y vender "
        "cuando decía bajista, pagando comisiones. Se compara contra lo más simple posible: comprar el primer "
        "día y no tocar nada (\"comprar y mantener\"). Si una estrategia no le gana a eso, no vale la pena el esfuerzo.",
        "📏 Las métricas\n"
        "• Retorno anual: cuánto rindió por año en promedio.\n"
        "• Volatilidad: cuánto se movió el valor; más volatilidad es más riesgo.\n"
        "• Sharpe: retorno dividido por volatilidad. Es la métrica central porque compara estrategias con distinto "
        "riesgo: más de 1 es muy bueno; entre 0 y 0,5, flojo.\n"
        "• Drawdown: la peor caída desde un máximo. Un −50% significa que en algún momento perdiste la mitad.\n"
        "• Tasa de acierto: qué porcentaje de las operaciones terminó en ganancia. Ojo: podés acertar poco y "
        "ganar, si las ganancias son más grandes que las pérdidas.",
        "⏳ Sin trampas\n"
        "La señal de cada día usa solo datos hasta ese cierre, y la operación se hace en la apertura siguiente. "
        f"Cada compra o venta paga {_p(r.costo_por_lado)}. Sin estos cuidados, casi cualquier estrategia parece "
        "rentable en el papel.",
        "🔬 Overfitting y walk-forward\n"
        "Si probás muchas combinaciones de parámetros sobre los mismos datos, alguna va a salir muy bien por "
        "casualidad. El walk-forward evita ese autoengaño: elige los parámetros con 3 años, los prueba en el año "
        "siguiente (que no vio), corre la ventana y repite. Solo cuentan los años de prueba. Si el rendimiento cae "
        "mucho del entrenamiento a la prueba, los parámetros estaban sobreajustados.",
        "🎲 ¿Suerte o habilidad?\n"
        "El bootstrap remezcla los retornos miles de veces para ver con qué frecuencia una ventaja como la "
        "observada aparece por azar. Si pasa en más del 10% de los casos, no se puede descartar que sea suerte.",
        "⚠️ Sesgos que el backtest NO corrige\n"
        "• Supervivencia: tu watchlist tiene empresas que hoy existen y conocés; las que quebraron no están, y eso "
        "hace que \"comprar y mantener\" parezca mejor de lo que fue.\n"
        "• Un solo período: 10 años son una sola historia; otro período podría dar otro resultado.\n"
        "• Yo diseñé las reglas conociendo cómo suelen funcionar estos indicadores: eso ya es un poco de "
        "información del pasado filtrada en la señal.\n"
        "• No se incluyen impuestos, dividendos del efectivo mientras estás afuera, ni el costo de tu tiempo.",
    ]
    return "\n\n".join(partes) + pie_de_mensaje()


def grafico_backtest(r: ResultadoBacktest, carpeta: Path) -> Path:
    """Curva de $1 invertido: señal vs. comprar y mantener, y sus caídas."""
    superficie, tinta, muted, grilla = "#fcfcfb", "#0b0b0b", "#898781", "#e1e0d9"
    fig, (ax, ax_dd) = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True,
                                    gridspec_kw={"height_ratios": [3, 1.2], "hspace": 0.1})
    fig.patch.set_facecolor(superficie)
    bh = curva(r.fija_retornos["comprar_y_mantener"])
    series = [("Comprar y mantener", bh, "#898781"),
              ("Señal del sistema", curva(r.fija_retornos["estrategia"]), "#2a78d6")]
    if r.wf_estrategia is not None:
        # El walk-forward empieza años después: arranca desde el valor que tenía "comprar y
        # mantener" ese día, para comparar a partir de ese punto.
        wf = curva(r.wf.retornos["estrategia"])
        series.append(("Señal con walk-forward (desde su inicio)", wf * bh.asof(wf.index[0]), "#eb6834"))
    for nombre, c, color in series:
        ax.plot(c.index, c, color=color, linewidth=1.8, label=nombre)
        ax_dd.plot(c.index, c / c.cummax() - 1, color=color, linewidth=1.2)
    for a in (ax, ax_dd):
        a.set_facecolor(superficie)
        a.grid(axis="y", color=grilla, linewidth=0.6)
        a.tick_params(colors=muted, labelsize=8, length=0)
        for lado in ("top", "right", "left"):
            a.spines[lado].set_visible(False)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:.1f}".replace(".", ","))
    ax.yaxis.set_minor_formatter(lambda v, _: f"${v:.1f}".replace(".", ","))
    ax.tick_params(which="minor", colors=muted, labelsize=7, length=0)
    ax.set_ylabel("Valor de $1 invertido (escala logarítmica)", color=muted, fontsize=8)
    ax_dd.set_ylabel("Caída desde el máximo", color=muted, fontsize=8)
    ax_dd.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.legend(loc="upper left", fontsize=8, frameon=False, labelcolor="#52514e")
    fig.suptitle(f"{r.simbolo} · backtest con costos · {r.conclusion.value}", x=0.06, ha="left", fontsize=11,
                 color=tinta, fontweight="bold")
    fig.text(0.06, 0.01, AVISO_LEGAL.replace("⚠️", "").strip(), fontsize=7.5, color=muted)
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"backtest_{r.simbolo.replace('^', 'INDICE_')}.png"
    fig.savefig(ruta, dpi=120, bbox_inches="tight", facecolor=superficie)
    plt.close(fig)
    return ruta
