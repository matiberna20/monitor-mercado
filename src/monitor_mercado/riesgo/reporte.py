"""Textos de las herramientas de riesgo."""

from __future__ import annotations

from monitor_mercado.aviso_legal import pie_de_mensaje
from monitor_mercado.cartera.reporte import pct, usd
from monitor_mercado.notificaciones.formato import numero
from monitor_mercado.riesgo.estres import ResultadoEstres
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


def texto_estres(r: ResultadoEstres) -> str:
    """Reporte de la prueba de estrés."""
    if not r.posiciones:
        return "No hay posiciones con precio para simular."
    lineas = [f"🧪 Prueba de estrés de tu cartera ({usd(r.valor)})", ""]
    for e in r.escenarios:
        if not e.aportes:
            lineas.append(f"• {e.nombre}: sin efecto (no tenés posiciones afectadas)")
            continue
        top = ", ".join(f"{s} {usd(v, True)}" for s, v in e.aportes[:3])
        lineas.append(f"• {e.nombre}: {pct(e.perdida_pct)} ({usd(e.perdida, True)}). Más aportan: {top}")

    if r.var_mensual_pct is not None:
        lineas += ["", f"📉 Con las correlaciones de las últimas {r.semanas} semanas:",
                   f"• Volatilidad anual de la cartera: {numero(100 * r.volatilidad_anual, 1)}%",
                   f"• Un mes malo (1 de cada 20): {pct(r.var_mensual_pct)} "
                   f"({usd(r.var_mensual_pct * r.valor, True)})"]
        aportes = sorted((p for p in r.posiciones if p.aporte_riesgo is not None), key=lambda p: -p.aporte_riesgo)[:5]
        if aportes:
            lineas.append("• Quiénes aportan más riesgo (vs. su peso):")
            lineas += [f"  {p.simbolo}: {numero(100 * p.aporte_riesgo, 0)}% del riesgo con "
                       f"{numero(100 * p.peso, 0)}% del valor" for p in aportes]

    lineas += ["", "Beta de cada posición (cuánto se mueve cuando el mercado se mueve 1%):"]
    for p in r.posiciones:
        nota = " (sin historia: se supuso 1)" if p.beta_estimada else ""
        lineas.append(f"  {p.simbolo} {numero(p.beta, 2)} vs {p.referencia}{nota} · {numero(100 * p.peso, 1)}%")
    if r.sin_precio:
        lineas += ["", f"⚠️ Sin precio, quedan afuera: {', '.join(r.sin_precio)}."]
    lineas += ["", "⚠️ Es una estimación, no una predicción. Supone que cada acción repite su relación histórica "
               "con el mercado; en las crisis las correlaciones suben y las caídas suelen ser peores que lo que "
               "dice la beta. No contempla noticias propias de cada empresa, ni que el CCL o las acciones en "
               "pesos se ajusten tras una devaluación (para lo que cotiza en pesos se supone el peor caso: el "
               "precio en pesos no se mueve)."]
    return "\n".join(lineas) + pie_de_mensaje()
