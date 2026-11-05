"""Textos del diario de operaciones."""

from __future__ import annotations

from monitor_mercado.aviso_legal import pie_de_mensaje
from monitor_mercado.cartera.reporte import pct, usd
from monitor_mercado.diario.modelos import Movimiento, TipoMovimiento
from monitor_mercado.diario.servicio import Estadisticas, VentaEnUsd
from monitor_mercado.notificaciones.formato import numero

_ICONO = {TipoMovimiento.COMPRA: "🟢", TipoMovimiento.VENTA: "🔴"}


def _precio(v: float | None, moneda: str) -> str:
    if v is None:
        return "precio s/d"
    return f"{'$' if moneda == 'ARS' else 'US$' if moneda == 'USD' else moneda} {numero(v)}"


def linea_movimiento(m: Movimiento) -> str:
    """Una operación en una línea."""
    texto = (f"#{m.id} {m.fecha:%d/%m/%Y} {_ICONO[m.tipo]} {m.tipo.value} {numero(m.cantidad, 4).rstrip('0').rstrip(',')}"
             f" {m.simbolo} a {_precio(m.precio, m.moneda)}")
    if m.comision:
        texto += f" (comisión {numero(m.comision)})"
    if m.nota:
        texto += f" · {m.nota}"
    return texto


def texto_registrado(m: Movimiento) -> str:
    verbo = "Compra" if m.tipo is TipoMovimiento.COMPRA else "Venta"
    return (f"{verbo} registrada en el diario:\n{linea_movimiento(m)}\n\n"
            "Corregila con /editar_op o borrala con /borrar_op si hace falta.")


def _linea_venta(v: VentaEnUsd) -> str:
    m = v.venta.movimiento
    return f"{m.simbolo} {m.fecha:%d/%m/%Y}: {usd(v.resultado_usd, True)} ({pct(v.venta.resultado_pct)})"


def texto_estadisticas(e: Estadisticas) -> list[str]:
    """Bloque de resultados y estadísticas."""
    lineas = ["📊 Resultados"]
    lineas.append(f"• Realizado (ventas cerradas): {usd(e.realizado, True)}")
    if e.no_realizado is not None:
        lineas.append(f"• No realizado (posiciones abiertas, a precio de hoy): {usd(e.no_realizado, True)}")
    if not e.con_resultado:
        lineas.append("• Todavía no hay ventas con resultado para calcular estadísticas.")
    else:
        lineas.append(f"• Ventas: {len(e.con_resultado)} · aciertos: {numero(100 * e.tasa_aciertos, 0)}% "
                      f"({len(e.ganadoras)} ganadoras, {len(e.perdedoras)} perdedoras)")
        if e.ganancia_promedio is not None:
            lineas.append(f"• Ganancia promedio: {usd(e.ganancia_promedio, True)}")
        if e.perdida_promedio is not None:
            lineas.append(f"• Pérdida promedio: {usd(e.perdida_promedio, True)}")
        if e.ganancia_promedio and e.perdida_promedio:
            lineas.append(f"  (cada pérdida promedio equivale a {numero(abs(e.perdida_promedio) / e.ganancia_promedio, 2)}"
                          " ganancias promedio)")
        if e.mejores():
            lineas += ["🏆 Mejores:"] + [f"  {_linea_venta(v)}" for v in e.mejores()]
        if e.peores():
            lineas += ["💀 Peores:"] + [f"  {_linea_venta(v)}" for v in e.peores()]
    if e.sin_resultado:
        lineas.append(f"ℹ️ {e.sin_resultado} venta(s) sin resultado: falta el precio de compra o el tipo de cambio.")
    return lineas


def texto_diario(movimientos: list[Movimiento], estadisticas: Estadisticas | None, maximo: int = 20) -> str:
    """Últimas operaciones + resultados."""
    if not movimientos:
        return ("Tu diario está vacío. Registrá operaciones con /compre y /vendi, o importá tu cartera actual con "
                "/importar_diario.")
    ultimas = movimientos[-maximo:]
    lineas = [f"📒 Diario de operaciones ({len(movimientos)} en total"
              + (f", últimas {len(ultimas)}" if len(ultimas) < len(movimientos) else "") + ")"]
    lineas += [linea_movimiento(m) for m in reversed(ultimas)]
    if estadisticas is not None:
        lineas += [""] + texto_estadisticas(estadisticas)
    lineas += ["", "Resultado con costo promedio ponderado (incluye comisiones). Lo que está en otra moneda se pasa a "
               "USD al tipo de cambio de hoy. No incluye impuestos."]
    return "\n".join(lineas) + pie_de_mensaje()
