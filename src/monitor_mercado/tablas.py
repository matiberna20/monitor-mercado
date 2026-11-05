"""Tablas (pandas) armadas a partir de los servicios: las usan el panel web y la exportación a Excel.

Acá no se calcula nada nuevo: solo se pasan a filas y columnas los resultados que ya
producen los servicios (cartera, diario, dividendos, estrés, alertas y stops).
"""

from __future__ import annotations

import pandas as pd

from monitor_mercado.cartera.servicio import EstadoCartera, FotoCartera


def tabla_cartera(estado: EstadoCartera) -> pd.DataFrame:
    """Una fila por posición, de mayor a menor valor (montos en USD)."""
    filas = [{
        "Símbolo": f.simbolo,
        "Cantidad": f.posicion.cantidad,
        "Precio USD": _r(f.precio),
        "Var. día %": _pct(f.variacion_dia),
        "Valor USD": _r(f.valor),
        "Costo USD": _r(f.valor - f.resultado) if f.resultado is not None and f.valor is not None else None,
        "Resultado USD": _r(f.resultado),
        "Resultado %": _pct(f.resultado_pct),
        "Peso %": _pct(f.peso),
        "Fecha de compra": f.posicion.fecha_compra,
    } for f in estado.posiciones]
    return pd.DataFrame(filas).sort_values("Valor USD", ascending=False, na_position="last") if filas else \
        pd.DataFrame(columns=["Símbolo"])


def tabla_evolucion(fotos: list[FotoCartera]) -> pd.DataFrame:
    """Valor de la cartera al cierre de cada día (índice: fecha)."""
    if not fotos:
        return pd.DataFrame(columns=["Valor USD", "Invertido USD"])
    return pd.DataFrame(
        {"Valor USD": [f.valor for f in fotos], "Invertido USD": [f.costo for f in fotos]},
        index=pd.DatetimeIndex([pd.Timestamp(f.fecha) for f in fotos], name="Fecha"),
    )


def tabla_operaciones(movimientos) -> pd.DataFrame:
    """El diario, de la más nueva a la más vieja."""
    filas = [{
        "ID": m.id, "Fecha": m.fecha, "Tipo": m.tipo.value, "Símbolo": m.simbolo, "Cantidad": m.cantidad,
        "Precio": m.precio, "Moneda": m.moneda, "Comisión": m.comision, "Nota": m.nota or "",
    } for m in reversed(movimientos)]
    return pd.DataFrame(filas) if filas else pd.DataFrame(columns=["ID", "Fecha", "Tipo", "Símbolo"])


def tabla_ventas(estadisticas) -> pd.DataFrame:
    """Ventas cerradas con su resultado realizado."""
    filas = [{
        "Fecha": v.venta.movimiento.fecha, "Símbolo": v.venta.movimiento.simbolo,
        "Cantidad": v.venta.movimiento.cantidad, "Precio": v.venta.movimiento.precio,
        "Costo promedio": v.venta.costo_promedio, "Resultado USD": v.resultado_usd,
        "Resultado %": _pct(v.venta.resultado_pct),
    } for v in estadisticas.ventas]
    return pd.DataFrame(filas) if filas else pd.DataFrame(columns=["Fecha", "Símbolo", "Resultado USD"])


def tabla_dividendos(resumen) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(cobrados en los últimos 12 meses, próximos cobros)."""
    cobrados = pd.DataFrame([{
        "Fecha ex": c.fecha_ex, "Símbolo": c.simbolo, "Por acción": c.por_accion, "Moneda": c.moneda,
        "Acciones": c.cantidad, "Monto USD": c.monto_usd,
    } for c in resumen.cobrados]) if resumen.cobrados else pd.DataFrame(columns=["Fecha ex", "Símbolo", "Monto USD"])
    proximos = pd.DataFrame([{
        "Fecha ex": p.fecha_ex, "Fecha de pago": p.fecha_pago, "Símbolo": p.simbolo,
        "Por acción (último)": p.por_accion, "Moneda": p.moneda, "Monto USD estimado": p.monto_usd,
        "Fecha": "estimada" if p.estimado else "anunciada",
    } for p in resumen.proximos]) if resumen.proximos else pd.DataFrame(columns=["Fecha ex", "Símbolo"])
    return cobrados, proximos


def tabla_estres(resultado) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(escenarios, betas y aporte al riesgo por posición)."""
    escenarios = pd.DataFrame([{
        "Escenario": e.nombre, "Pérdida %": _pct(e.perdida_pct), "Pérdida USD": e.perdida,
        "Más aportan": ", ".join(s for s, _ in e.aportes[:3]),
    } for e in resultado.escenarios])
    posiciones = pd.DataFrame([{
        "Símbolo": p.simbolo, "Valor USD": p.valor, "Peso %": _pct(p.peso), "Beta": p.beta,
        "Contra": p.referencia, "Beta supuesta": "sí" if p.beta_estimada else "",
        "Aporte al riesgo %": _pct(p.aporte_riesgo),
    } for p in resultado.posiciones])
    return escenarios, posiciones


def tabla_alertas(alertas) -> pd.DataFrame:
    from monitor_mercado.notificaciones.formato import descripcion_condicion

    filas = [{"ID": a.id, "Símbolo": a.simbolo, "Operación": a.operacion.value,
              "Condición": descripcion_condicion(a), "Repetir": "sí" if a.repetir else "",
              "Estado": "activa" if a.armada else "en espera de cruce", "Nota": a.nota or ""} for a in alertas]
    return pd.DataFrame(filas) if filas else pd.DataFrame(columns=["ID", "Símbolo", "Condición"])


def tabla_stops(estados) -> pd.DataFrame:
    from monitor_mercado.stops.reporte import NOMBRE

    filas = [{"ID": e.stop.id, "Símbolo": e.stop.simbolo, "Tipo": NOMBRE[e.stop.tipo],
              "%": 100 * e.stop.porcentaje, "Referencia USD": e.referencia, "Nivel USD": e.nivel,
              "Precio USD": e.precio, "Le falta %": _pct(e.distancia),
              "Por defecto": "sí" if e.stop.por_defecto else ""} for e in estados]
    return pd.DataFrame(filas) if filas else pd.DataFrame(columns=["ID", "Símbolo", "Tipo"])


def tabla_resultado_por_posicion(
    estado: EstadoCartera, realizado: dict[str, float], dividendos: dict[str, float]
) -> pd.DataFrame:
    """Por símbolo: no realizado (abierto), realizado (ventas), dividendos y total, en USD.

    Incluye los símbolos que ya vendiste por completo (solo tienen realizado).
    """
    abiertas = {f.simbolo: f for f in estado.posiciones}
    filas = []
    for s in sorted(set(abiertas) | set(realizado) | set(dividendos)):
        f = abiertas.get(s)
        no_realizado = f.resultado if f is not None else None
        partes = [v for v in (no_realizado, realizado.get(s), dividendos.get(s)) if v is not None]
        filas.append({
            "Símbolo": s, "Valor actual USD": f.valor if f is not None else 0.0,
            "No realizado USD": no_realizado, "Realizado USD": realizado.get(s, 0.0),
            "Dividendos USD": dividendos.get(s, 0.0), "Total USD": sum(partes) if partes else None,
        })
    return pd.DataFrame(filas) if filas else pd.DataFrame(columns=["Símbolo", "Total USD"])


def _r(v: float | None, decimales: int = 2) -> float | None:
    return None if v is None else round(v, decimales)


def _pct(v: float | None) -> float | None:
    """Fracción -> porcentaje (0,05 -> 5,0)."""
    return None if v is None else round(100 * v, 2)
