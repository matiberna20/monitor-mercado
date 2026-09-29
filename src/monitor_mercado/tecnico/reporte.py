"""Reportes de texto del análisis técnico (Telegram y consola)."""

from __future__ import annotations

from monitor_mercado.aviso_legal import pie_de_mensaje
from monitor_mercado.notificaciones.formato import numero
from monitor_mercado.tecnico.senal import Tendencia
from monitor_mercado.tecnico.servicio import Analisis

ICONO = {Tendencia.ALCISTA: "📈", Tendencia.BAJISTA: "📉", Tendencia.NEUTRAL: "➖"}


def _pct(valor: float) -> str:
    return f"{valor:+.1%}".replace(".", ",")


def _barra(voto: float) -> str:
    """Voto de -1 a +1 como texto: ▲▲ / ▲ / · / ▼ / ▼▼."""
    if voto >= 0.5:
        return "▲▲"
    if voto >= 0.15:
        return "▲ "
    if voto <= -0.5:
        return "▼▼"
    if voto <= -0.15:
        return "▼ "
    return "· "


def reporte_completo(a: Analisis) -> str:
    """Reporte detallado de un activo."""
    u = a.ultimo
    s = a.senal
    lineas = [
        f"{ICONO[s.tendencia]} {a.simbolo}: tendencia {s.tendencia.value.upper()}",
        f"Confianza: {s.confianza}/100 ({s.nivel_confianza}) · puntaje {s.puntaje:+.2f}".replace(".", ","),
        f"Cierre {s.fecha:%d/%m/%Y}: {numero(u['cierre'])} {a.moneda}"
        + (f" ({_pct(u['retorno_1d'])} en el día)" if u["retorno_1d"] == u["retorno_1d"] else ""),
    ]
    if a.en_ccl:
        lineas.append("(Precios en pesos convertidos a dólares CCL para quitar el efecto de la inflación)")

    lineas += ["", "Qué dice cada indicador:"]
    for f in sorted(s.factores, key=lambda f: -abs(f.voto) * f.peso):
        lineas.append(f"{_barra(f.voto)} {f.nombre}: {f.explicacion.replace('.', ',')}")

    lineas += ["", "Niveles:"]
    for col, nombre in (("sma20", "Media 20"), ("sma50", "Media 50"), ("sma200", "Media 200")):
        if u[col] == u[col]:  # no es NaN
            lineas.append(f"  {nombre}: {numero(u[col])}")
    lineas.append(f"  Bollinger: {numero(u['bb_inferior'])} – {numero(u['bb_superior'])}")
    lineas.append(f"  Rango 20 días: {numero(u['min_20d'])} – {numero(u['max_20d'])}")
    if u["max_252d"] == u["max_252d"]:
        lineas.append(f"  Rango 52 semanas: {numero(u['min_252d'])} – {numero(u['max_252d'])}")
    atr_pct = numero(100 * u["atr14"] / u["cierre"], 1)
    lineas.append(f"  Volatilidad diaria (ATR): {numero(u['atr14'])} ({atr_pct}% del precio)")

    if a.patrones:
        lineas += ["", f"Patrones recientes (últimas ruedas):"]
        for p in a.patrones:
            sesgo = {1: "alcista", -1: "bajista", 0: "neutro"}[p.definicion.sesgo]
            lineas.append(f"• {p.fecha:%d/%m} {p.definicion.nombre} ({sesgo}): {p.definicion.descripcion}")

    lineas += [
        "",
        "La confianza mide cuánto coinciden los indicadores, no la probabilidad de acierto. "
        "El análisis técnico mira solo precios pasados: no incluye noticias ni resultados.",
    ]
    return "\n".join(lineas) + pie_de_mensaje()


def linea_resumen(a: Analisis) -> str:
    """Una línea por activo para el resumen de la watchlist."""
    s = a.senal
    ret = a.ultimo["retorno_1d"]
    dia = f" | día {_pct(ret)}" if ret == ret else ""
    return f"{ICONO[s.tendencia]} {a.simbolo}: {s.tendencia.value} ({s.confianza}/100){dia}"


def reporte_resumen(analisis: list[Analisis], errores: dict[str, str]) -> str:
    """Resumen de varios activos, ordenado de más alcista a más bajista."""
    orden = sorted(analisis, key=lambda a: -a.senal.puntaje)
    lineas = ["Resumen técnico de la watchlist:", ""]
    lineas += [linea_resumen(a) for a in orden]
    if errores:
        lineas += ["", "Sin datos: " + ", ".join(errores)]
    lineas += ["", "Detalle de un activo: /analisis SIMBOLO"]
    return "\n".join(lineas) + pie_de_mensaje()
