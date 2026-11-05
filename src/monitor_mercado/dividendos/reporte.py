"""Textos de dividendos y rendimiento total."""

from __future__ import annotations

from monitor_mercado.aviso_legal import pie_de_mensaje
from monitor_mercado.cartera.reporte import pct, usd
from monitor_mercado.dividendos.servicio import RendimientoTotal, ResumenDividendos
from monitor_mercado.notificaciones.formato import numero

AVISO_IMPUESTOS = "No incluye impuestos ni retenciones (en EE.UU. suelen retener el 30% a no residentes)."


def lineas_rendimiento(r: RendimientoTotal) -> list[str]:
    """Líneas para /cartera y el resumen de cierre."""
    if not r.dividendos:
        return []
    lineas = [f"💵 Dividendos cobrados desde la compra: {usd(r.dividendos)}"]
    if r.costo:
        lineas.append(f"📦 Rendimiento total (precio + dividendos): {pct(r.total_pct)} ({usd(r.total, True)})")
    if r.sin_fecha:
        lineas.append(f"ℹ️ Sin fecha de compra, se tomaron los dividendos de 12 meses: {', '.join(r.sin_fecha)}.")
    lineas.append(f"ℹ️ {AVISO_IMPUESTOS}")
    return lineas


def texto_dividendos(r: ResumenDividendos, rendimiento: RendimientoTotal | None = None) -> str:
    """Calendario de próximos cobros y cobrados en el último año."""
    lineas = ["💵 Dividendos de tu cartera", ""]
    if r.proximos:
        lineas.append("📅 Próximos cobros:")
        for p in r.proximos:
            fecha = f"ex {p.fecha_ex:%d/%m/%Y}" if p.fecha_ex else ""
            if p.fecha_pago:
                fecha += f"{' · ' if fecha else ''}pago {p.fecha_pago:%d/%m/%Y}"
            estimado = " (fecha estimada por la frecuencia de pagos)" if p.estimado else ""
            monto = f" · ~{usd(p.monto_usd)}" if p.monto_usd else ""
            por_accion = f" ({numero(p.por_accion, 4)} {p.moneda} por acción, como el último)" if p.por_accion else ""
            lineas.append(f"• {p.simbolo}: {fecha}{estimado}{monto}{por_accion}")
    else:
        lineas.append("📅 No hay próximos cobros a la vista en los próximos 6 meses.")

    lineas += ["", f"✅ Cobrados en los últimos 12 meses: {usd(r.total_anual)}"]
    por_simbolo: dict[str, float] = {}
    for c in r.cobrados:
        por_simbolo[c.simbolo] = por_simbolo.get(c.simbolo, 0.0) + (c.monto_usd or 0.0)
    for s, v in sorted(por_simbolo.items(), key=lambda x: -x[1]):
        n = sum(1 for c in r.cobrados if c.simbolo == s)
        lineas.append(f"• {s}: {usd(v)} ({n} pago{'s' if n > 1 else ''})")
    if rendimiento is not None and rendimiento.dividendos:
        lineas += [""] + lineas_rendimiento(rendimiento)
    elif r.cobrados:
        lineas += ["", f"ℹ️ {AVISO_IMPUESTOS}"]
    if r.errores:
        lineas += ["", f"⚠️ No se pudieron consultar: {', '.join(r.errores)}."]
    lineas += ["", "Se cobra el dividendo si tenías la acción antes de la fecha ex. Los montos se calculan con la "
               "cantidad que tenías (según el diario si lo usás; si no, la cantidad actual) y se pasan a dólares al "
               "tipo de cambio de hoy."]
    return "\n".join(lineas) + pie_de_mensaje()
