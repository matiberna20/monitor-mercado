"""Textos de la Etapa 4: reporte de resultados, avisos y explicación para aprender."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from monitor_mercado.aviso_legal import pie_de_mensaje
from monitor_mercado.notificaciones.formato import numero
from monitor_mercado.resultados.evaluacion import Sorpresa, Veredicto
from monitor_mercado.resultados.servicio import Proxima, ReporteResultados

AR = ZoneInfo("America/Argentina/Buenos_Aires")
ICONO_VEREDICTO = {Veredicto.MEJOR: "🟢", Veredicto.EN_LINEA: "🟡", Veredicto.PEOR: "🔴"}
ICONO_SORPRESA = {Sorpresa.BEAT: "✅", Sorpresa.EN_LINEA: "➖", Sorpresa.MISS: "❌", Sorpresa.SIN_DATO: "❔"}
GUIDANCE = {"subio": "⬆️ mejoró sus proyecciones", "mantuvo": "➡️ mantuvo sus proyecciones",
            "bajo": "⬇️ bajó sus proyecciones", "no_informa": "no dio proyecciones"}


def pct(v: float | None, signo: bool = True) -> str:
    """Porcentaje en formato argentino ("+12,3%"), o "s/d" si no hay dato."""
    if v is None:
        return "s/d"
    return (f"{100 * v:+.1f}%" if signo else f"{100 * v:.1f}%").replace(".", ",")


def grande(v: float | None, moneda: str | None = None) -> str:
    """Montos grandes legibles: "94.930 millones USD"."""
    if v is None:
        return "s/d"
    sufijo = f" {moneda}" if moneda else ""
    if abs(v) >= 1e9:
        return f"{numero(v / 1e9, 1)} mil millones{sufijo}"
    if abs(v) >= 1e6:
        return f"{numero(v / 1e6, 0)} millones{sufijo}"
    return f"{numero(v, 0)}{sufijo}"


def _fecha(r_fecha) -> str:
    return r_fecha.astimezone(AR).strftime("%d/%m/%Y %H:%M")


def reporte_resultados(r: ReporteResultados) -> str:
    """Reporte principal de una presentación."""
    ev, m, e = r.evento, r.metricas, r.evaluacion
    mon = r.moneda_estados
    lineas = [
        f"{ICONO_VEREDICTO[e.veredicto]} {r.simbolo} ({r.empresa}): {e.veredicto.value}",
        f"Presentó el {_fecha(ev.fecha)} (hora Argentina)"
        + (f" · trimestre cerrado el {m.trimestre:%d/%m/%Y}" if m else ""),
        "",
        "📊 Contra lo que esperaba el mercado",
        f"{ICONO_SORPRESA[r.clase_eps]} Ganancia por acción (EPS): {numero(ev.eps_reportado)} vs. "
        f"{numero(ev.eps_estimado) if ev.eps_estimado is not None else 's/d'} esperado → "
        f"{pct(r.sorpresa_eps)} ({r.clase_eps.value})",
    ]
    if r.ingresos_estimados is not None and m is not None:
        lineas.append(f"{ICONO_SORPRESA[r.clase_ingresos]} Ingresos: {grande(m.ingresos, mon)} vs. "
                      f"{grande(r.ingresos_estimados, mon)} esperado → {pct(r.sorpresa_ingresos)} "
                      f"({r.clase_ingresos.value})")
    else:
        lineas.append(f"{ICONO_SORPRESA[Sorpresa.SIN_DATO]} Ingresos vs. consenso: sin dato")

    if m is not None:
        lineas += [
            "",
            "📈 Crecimiento",
            f"Ingresos: {grande(m.ingresos, mon)} · {pct(m.ingresos_yoy)} interanual · {pct(m.ingresos_qoq)} vs. trimestre anterior",
            f"Ganancia neta: {grande(m.ganancia_neta, mon)} · {pct(m.ganancia_yoy)} interanual",
            f"EPS del balance: {numero(m.eps) if m.eps is not None else 's/d'} {mon or ''} por acción · "
            f"{pct(m.eps_yoy)} interanual"
            + (" (el EPS vs. consenso de arriba está en otra unidad: por ADR y en dólares)"
               if mon and mon != "USD" and "." not in r.simbolo else ""),  # ADR que cotiza en EE.UU.
            "",
            "💰 Márgenes (hoy vs. hace un año)",
        ]
        for nombre, hoy, antes in (("Bruto", m.margen_bruto, m.margen_bruto_hace_un_anio),
                                   ("Operativo", m.margen_operativo, m.margen_operativo_hace_un_anio),
                                   ("Neto", m.margen_neto, m.margen_neto_hace_un_anio)):
            if hoy is not None:
                cambio = f" ({pct(hoy - antes).rstrip('%')} puntos)" if antes is not None else ""
                lineas.append(f"{nombre}: {pct(hoy, False)} vs. {pct(antes, False)}{cambio}")
        if m.margen_bruto is None and m.margen_operativo is None:
            lineas.append("(Margen bruto y operativo no aplican a este tipo de empresa, por ejemplo bancos.)")
        lineas += [
            "",
            "🏦 Deuda y caja",
            f"Deuda total: {grande(m.deuda_total, mon)} · Caja: {grande(m.caja, mon)} · Deuda neta: {grande(m.deuda_neta, mon)}",
        ]
        if m.deuda_neta_sobre_ebitda is not None:
            lineas.append(f"Deuda neta / EBITDA: {numero(m.deuda_neta_sobre_ebitda, 1)} veces")
        lineas.append(f"Flujo de caja libre: {grande(m.fcf, mon)} en el trimestre · {grande(m.fcf_12m, mon)} en 12 meses")

    if r.reacciones:
        lineas += ["", "📉📈 Reacción del precio"]
        for x in r.reacciones:
            indice = f" (mercado {pct(x.indice)}, propia {pct(x.anormal)})" if x.indice is not None else ""
            lineas.append(f"{x.ruedas} rueda{'s' if x.ruedas > 1 else ''} después: {pct(x.accion)}{indice}")
    else:
        lineas += ["", "📉📈 Reacción del precio: todavía no hay ruedas posteriores."]

    if r.comunicado is not None:
        c = r.comunicado
        lineas += ["", "📄 Comunicado oficial", c.resumen, f"Guidance: {GUIDANCE.get(c.guidance, c.guidance)}. {c.guidance_detalle}",
                   f"Tono de la gerencia: {c.tono}"]
        if c.positivos:
            lineas += ["A favor:"] + [f"  + {p}" for p in c.positivos]
        if c.negativos:
            lineas += ["En contra:"] + [f"  − {n}" for n in c.negativos]
        if r.url_comunicado:
            lineas.append(f"Fuente: {r.url_comunicado}")

    lineas += ["", f"🧮 Cómo se llegó al veredicto (puntaje {numero(e.puntaje, 2)}):"]
    for f in sorted(e.factores, key=lambda f: -abs(f.voto) * f.peso):
        marca = "▲" if f.voto > 0 else "▼" if f.voto < 0 else "·"
        lineas.append(f"{marca} {f.nombre}: {f.explicacion}")
    if r.comunicado is not None:
        lineas += ["", f"Opinión de Claude: {r.comunicado.veredicto_modelo.replace('_', ' ')}. {r.comunicado.justificacion}"]

    if r.valuacion is not None:
        v = r.valuacion
        lineas += ["", f"🏷️ Valuación vs. pares ({', '.join(v.pares) if v.pares else 'sin pares'})"]
        for x in v.multiplos:
            if x.empresa is not None:
                pares = f" vs. {numero(x.pares, 1)} de mediana" if x.pares is not None else ""
                lineas.append(f"{x.nombre}: {numero(x.empresa, 1)}{pares} → {x.lectura}")
        lineas.append("Un buen resultado no es lo mismo que una buena compra: si la acción ya está cara, "
                      "lo bueno puede estar en el precio.")

    if r.proximo is not None and r.proximo.fecha is not None:
        lineas += ["", f"📅 Próxima presentación: {r.proximo.fecha:%d/%m/%Y}"
                   + (f" · EPS esperado {numero(r.proximo.eps)}" if r.proximo.eps else "")]

    avisos = [*r.avisos, *(r.valuacion.avisos if r.valuacion else [])]
    if avisos:
        lineas.append("")
    for a in dict.fromkeys(avisos):
        lineas.append(f"ℹ️ {a}")
    return "\n".join(lineas) + pie_de_mensaje()


def explicacion_resultados(r: ReporteResultados) -> str:
    """Explicación para aprender, con los números de este reporte."""
    ev, m = r.evento, r.metricas
    partes = [
        f"📘 Explicación para aprender – resultados de {r.simbolo}",
        "🎯 Por qué importa lo ESPERADO y no solo el número\n"
        "Antes de cada presentación, los analistas publican lo que creen que la empresa va a ganar: el "
        "\"consenso\". El precio de la acción ya refleja esas expectativas. Por eso una empresa puede ganar "
        "mucho y aun así caer (si esperaban más), o perder y subir (si esperaban que perdiera más). Superar "
        "el consenso se llama \"beat\"; quedar por debajo, \"miss\".",
        "💵 EPS (ganancia por acción)\n"
        "Es la ganancia neta dividida por la cantidad de acciones. Permite comparar empresas de distinto "
        f"tamaño. Acá fue {numero(ev.eps_reportado)} contra {numero(ev.eps_estimado) if ev.eps_estimado is not None else 's/d'} "
        f"esperado: una sorpresa de {pct(r.sorpresa_eps)}.",
    ]
    if m is not None:
        partes.append(
            "📈 Interanual vs. trimestral\n"
            "El crecimiento interanual compara con el mismo trimestre del año anterior y elimina la "
            "estacionalidad (por ejemplo, las ventas navideñas). El trimestral compara con los tres meses "
            f"previos. Los ingresos variaron {pct(m.ingresos_yoy)} interanual y {pct(m.ingresos_qoq)} contra el "
            "trimestre anterior."
        )
        partes.append(
            "💰 Márgenes\n"
            "Muestran cuántos centavos quedan de cada peso vendido. El bruto descuenta el costo directo de lo "
            "vendido; el operativo, todos los gastos del negocio; el neto, además, intereses e impuestos. "
            "Que el margen suba indica que la empresa gana eficiencia o tiene poder para fijar precios."
            + (f" Acá el margen neto fue {pct(m.margen_neto, False)}." if m.margen_neto is not None else "")
        )
        partes.append(
            "🏦 Deuda neta y flujo de caja libre\n"
            "La deuda neta es la deuda menos la caja: si es negativa, la empresa tiene más caja que deuda. "
            "Dividida por el EBITDA (ganancia operativa antes de amortizaciones) indica cuántos años tardaría en "
            "pagarla: menos de 1 es muy cómodo, más de 3 empieza a ser mucho. El flujo de caja libre es la plata "
            "que genera el negocio después de invertir en máquinas, fábricas, etc.: es la que puede usar para "
            "dividendos, recompras o bajar deuda."
        )
    partes.append(
        "🔭 Guidance\n"
        "Son las proyecciones que da la propia empresa para los próximos meses. Suele mover el precio más que "
        "el trimestre que ya pasó, porque el mercado mira hacia adelante."
        + ("" if r.comunicado else " (No se analizó el comunicado de esta presentación.)")
    )
    if r.reacciones:
        x = r.reacciones[0]
        partes.append(
            "📉📈 Reacción del precio\n"
            "Es la mejor pista de qué esperaba el mercado. Se descuenta lo que hizo el índice (SPY) para aislar el "
            f"efecto de los resultados: al día siguiente la acción varió {pct(x.accion)}"
            + (f", y descontando al mercado, {pct(x.anormal)}." if x.indice is not None else ".")
        )
    partes.append(
        "🏷️ Múltiplos (P/E, EV/EBITDA)\n"
        "El P/E indica cuántos años de ganancias actuales pagás al comprar la acción. Un P/E alto no es "
        "necesariamente malo (puede reflejar mucho crecimiento esperado), pero significa que las expectativas "
        "ya son altas. Solo tiene sentido compararlo con empresas parecidas."
    )
    partes.append(
        "🚫 Lo que este análisis NO te dice\n"
        "• Si la acción va a subir: resume qué pasó en el trimestre y cómo lo recibió el mercado.\n"
        "• El veredicto combina factores con pesos fijos; es una guía para ordenar la información, no una verdad.\n"
        "• Leé el comunicado completo antes de decidir: puede haber detalles que cambian la lectura."
    )
    return "\n\n".join(partes) + pie_de_mensaje()


def mensaje_previo(p: Proxima) -> str:
    """Aviso de que una empresa presenta pronto."""
    eps = f"\nEPS esperado por los analistas: {numero(p.eps_estimado)}" if p.eps_estimado is not None else ""
    return (f"📅 {p.simbolo} presenta resultados el {_fecha(p.fecha)} (hora Argentina).{eps}\n"
            "Cuando salgan te mando el análisis automáticamente." + pie_de_mensaje())


def texto_calendario(proximas: list[Proxima], seguidas: list[str]) -> str:
    """Calendario de próximas presentaciones."""
    if not seguidas:
        return "No seguís ninguna empresa. Agregá una con /seguir SIMBOLO."
    lineas = ["📅 Próximas presentaciones de resultados:"]
    for p in proximas:
        eps = f" · EPS esperado {numero(p.eps_estimado)}" if p.eps_estimado is not None else ""
        lineas.append(f"• {p.fecha.astimezone(AR):%d/%m %H:%M} {p.simbolo}{eps}")
    sin_fecha = sorted(set(seguidas) - {p.simbolo for p in proximas})
    if sin_fecha:
        lineas.append(f"\nSin fecha anunciada en los próximos 60 días: {', '.join(sin_fecha)}")
    return "\n".join(lineas) + pie_de_mensaje()
