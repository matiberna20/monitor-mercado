"""Textos de la cartera: estado completo y resumen de cierre."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from monitor_mercado.aviso_legal import pie_de_mensaje
from monitor_mercado.cartera.servicio import EstadoCartera, EstadoPosicion, ResumenDia
from monitor_mercado.notificaciones.formato import numero

AR = ZoneInfo("America/Argentina/Buenos_Aires")


def pct(v: float | None) -> str:
    """"+1,2%" (o "s/d")."""
    return "s/d" if v is None else f"{100 * v:+.1f}%".replace(".", ",")


def usd(v: float | None, signo: bool = False) -> str:
    """"US$ 1.234" (sin decimales: en una cartera alcanza)."""
    if v is None:
        return "s/d"
    s = "+" if signo and v > 0 else "-" if v < 0 else ""
    return f"{s}US$ {numero(abs(v), 0)}"


def _icono(v: float | None) -> str:
    if v is None:
        return "⚪"
    return "🟢" if v > 0.0005 else "🔴" if v < -0.0005 else "⚪"


def _encabezado(e: EstadoCartera) -> list[str]:
    lineas = [
        f"💼 Valor: {usd(e.valor)}",
        f"{_icono(e.variacion_dia)} Hoy: {pct(e.variacion_dia)} ({usd(e.resultado_dia, True)})",
    ]
    if e.costo:
        lineas.append(f"{_icono(e.resultado_pct)} Total desde la compra: {pct(e.resultado_pct)} "
                      f"({usd(e.resultado, True)} sobre {usd(e.costo)} invertidos)")
    return lineas


def texto_cartera(e: EstadoCartera) -> str:
    """Estado completo, una línea por posición (de mayor a menor peso)."""
    if not e.posiciones:
        return "Todavía no cargaste tu cartera (archivo mi_cartera.csv)."
    lineas = [f"📋 Tu cartera ({e.momento.astimezone(AR):%d/%m %H:%M} hora Argentina)", *_encabezado(e), "",
              "Símbolo · hoy · desde la compra · peso"]
    for f in sorted(e.posiciones, key=lambda f: -(f.valor or 0)):
        if f.precio is None:
            lineas.append(f"⚪ {f.simbolo}: sin precio disponible")
            continue
        total = f"{pct(f.resultado_pct)} ({usd(f.resultado, True)})" if f.resultado is not None else "costo s/d"
        lineas.append(f"{_icono(f.variacion_dia)} {f.simbolo} {numero(f.precio)} · {pct(f.variacion_dia)} · "
                      f"{total} · {numero(100 * f.peso, 1)}%")
    lineas += _notas(e)
    return "\n".join(lineas) + pie_de_mensaje()


def _notas(e: EstadoCartera) -> list[str]:
    notas = []
    if e.sin_costo:
        notas.append(f"ℹ️ Sin precio de compra (no entran en la ganancia total): {', '.join(e.sin_costo)}. "
                     "Completalo en mi_cartera.csv.")
    if e.sin_precio:
        notas.append(f"⚠️ Sin cotización: {', '.join(e.sin_precio)}.")
    return [""] + notas if notas else []


def _linea_movimiento(f: EstadoPosicion) -> str:
    return f"{_icono(f.variacion_dia)} {f.simbolo} {pct(f.variacion_dia)} ({usd(f.resultado_dia, True)})"


def texto_resumen_dia(r: ResumenDia, umbral_movimiento: float = 0.05) -> str:
    """Resumen de cierre: cómo le fue a la cartera, cada acción y las noticias importantes."""
    e = r.estado
    lineas = [f"🔔 Resumen de tu cartera – {e.momento.astimezone(AR):%d/%m/%Y %H:%M}", *_encabezado(e)]
    if r.variacion_semana is not None:
        lineas.append(f"📅 Últimos 7 días: {pct(r.variacion_semana)}")

    con_precio = [f for f in e.posiciones if f.variacion_dia is not None]
    ordenadas = sorted(con_precio, key=lambda f: -(f.variacion_dia or 0))
    lineas += ["", "📈 Mejores del día:"] + [_linea_movimiento(f) for f in ordenadas[:3] if f.variacion_dia > 0]
    lineas += ["📉 Peores del día:"] + [_linea_movimiento(f) for f in reversed(ordenadas[-3:]) if f.variacion_dia < 0]

    fuertes = [f for f in con_precio if abs(f.variacion_dia) >= umbral_movimiento]
    if fuertes:
        lineas += ["", f"⚡ Movimientos fuertes (más de {numero(100 * umbral_movimiento, 0)}%): "
                   + ", ".join(f"{f.simbolo} {pct(f.variacion_dia)}" for f in fuertes)]

    lineas += ["", "Todas tus posiciones (variación del día):"]
    lineas += [f"{_icono(f.variacion_dia)} {f.simbolo} {pct(f.variacion_dia)}" for f in ordenadas]

    if r.noticias:
        lineas += ["", "📰 Noticias importantes del día:"]
        for d in r.noticias:
            lineas.append(f"• {d.simbolo}: {d.noticia.titulo}")
    elif r.noticias is not None:
        lineas += ["", "📰 No hubo noticias destacadas de tus empresas en las últimas 24 horas."]

    if r.concentradas:
        lineas += ["", "⚠️ Concentración: " + ", ".join(f"{f.simbolo} pesa {numero(100 * f.peso, 0)}%"
                                                         for f in r.concentradas)
                   + " de la cartera. Si a esa acción le va mal, arrastra a toda la cartera."]
    lineas += _notas(e)
    lineas += ["", "Las noticias se eligen con reglas simples (que nombren a la empresa y usen palabras como "
               "\"resultados\" o \"adquisición\"): pueden faltar algunas importantes."]
    return "\n".join(lineas) + pie_de_mensaje()
