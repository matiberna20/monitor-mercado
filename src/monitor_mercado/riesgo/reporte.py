"""Textos de las herramientas de riesgo."""

from __future__ import annotations

from monitor_mercado.aviso_legal import pie_de_mensaje
from monitor_mercado.cartera.reporte import usd
from monitor_mercado.notificaciones.formato import numero
from monitor_mercado.riesgo.tamano import CalculoTamano


def _precio(v: float, moneda: str) -> str:
    return f"{'$' if moneda == 'ARS' else 'US$' if moneda == 'USD' else moneda} {numero(v)}"


def texto_tamano(c: CalculoTamano) -> str:
    """Resultado de la calculadora de tamaño de posición."""
    origen = "valor de tu cartera" if c.capital_es_cartera else "capital indicado"
    lineas = [
        f"📐 Tamaño de posición – {c.simbolo}",
        f"Entrada {_precio(c.entrada, c.moneda)} · stop {_precio(c.stop, c.moneda)} "
        f"({numero(100 * c.distancia_stop, 1)}% abajo)",
    ]
    if c.precio_actual is not None:
        lineas.append(f"Precio actual: {_precio(c.precio_actual, c.moneda)}")
    lineas += [
        f"Capital: {usd(c.capital)} ({origen}) · riesgo elegido: {usd(c.riesgo)} "
        f"({numero(100 * c.riesgo / c.capital, 2)}%)",
        "",
        f"👉 Acciones: {c.acciones}",
        f"💰 Monto a invertir: {usd(c.monto)}",
        f"🛑 Pérdida máxima si toca el stop: {usd(c.perdida_maxima)}",
        f"⚖️ Peso de {c.simbolo} en la cartera: {numero(100 * c.peso, 1)}%"
        + (f" (ya tenías {usd(c.valor_existente)})" if c.valor_existente else ""),
    ]
    if c.acciones == 0:
        lineas += ["", "⚠️ Con ese riesgo no alcanza ni para una acción: el stop está muy lejos o el riesgo "
                   "es muy chico."]
    if c.limitado_por_capital:
        lineas += ["", "⚠️ Para arriesgar eso harían falta más acciones de las que paga tu capital: se "
                   "calculó con todo el capital, y la pérdida máxima queda por debajo de tu riesgo."]
    if c.supera_limite:
        lineas += ["", f"⚠️ Concentración: {c.simbolo} pasaría a pesar {numero(100 * c.peso, 0)}% de la "
                   f"cartera, más que tu límite de {numero(100 * c.limite, 0)}%. Si le va mal, arrastra a toda "
                   "la cartera."]
    lineas += ["", "La pérdida máxima supone que vendés justo en el stop. Con un salto de precio (por ejemplo, "
               "una mala noticia con el mercado cerrado) podés perder más."]
    return "\n".join(lineas) + pie_de_mensaje()
