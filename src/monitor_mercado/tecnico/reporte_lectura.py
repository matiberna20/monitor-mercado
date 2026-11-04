"""Texto de la lectura del gráfico, como lo explicaría un trader técnico."""

from __future__ import annotations

from monitor_mercado.aviso_legal import pie_de_mensaje
from monitor_mercado.notificaciones.formato import numero
from monitor_mercado.tecnico.lectura import LecturaGrafico

ICONO = {"ALCISTA": "📈", "BAJISTA": "📉"}


def _p(precio: float | None) -> str:
    if precio is None:
        return "s/d"
    return numero(precio, 2 if precio >= 1 else 3)


def _dist(nivel: float, precio: float) -> str:
    return f"{100 * (nivel / precio - 1):+.1f}%".replace(".", ",")


def texto_lectura(simbolo: str, l: LecturaGrafico, moneda: str) -> str:
    """Lectura completa del gráfico."""
    icono = ICONO.get(l.direccion, "↔️")
    lineas = [
        f"{icono} {simbolo} – lectura del gráfico: {l.direccion} (convicción {l.conviccion})",
        f"Precio: {_p(l.precio)} {moneda}",
        "",
        "🏗️ Estructura",
        f"{l.estructura_texto[0].upper()}{l.estructura_texto[1:]}.",
    ]
    ult = [g for g in l.giros[-4:]]
    if ult:
        lineas.append("Últimos giros: " + " → ".join(
            f"{'máx' if g.tipo == 'H' else 'mín'} {_p(g.precio)} ({g.fecha:%d/%m})" for g in ult))
    e = l.extras
    if e is not None:
        lineas.append(e.grados.texto)
        lineas.append(f"{e.regimen.texto}.")
    lineas.append(f"Medias móviles: {l.medias_texto}.")
    if e is not None:
        lineas.append(f"Gráfico semanal: {e.medias_semanales}; {e.regla_4_semanas}.")

    c = l.canal
    if c.claro:
        dir_canal = "alcista" if c.pendiente_mensual > 0 else "bajista"
        lugar = "cerca del techo" if c.posicion > 0.8 else "cerca del piso" if c.posicion < 0.2 else "en la mitad"
        lineas.append(f"Se mueve en un canal {dir_canal} ({numero(100 * c.pendiente_mensual, 1)}% por mes) y hoy "
                      f"está {lugar} del canal (techo {_p(c.superior.iloc[-1])}, piso {_p(c.inferior.iloc[-1])}).")
    else:
        lineas.append("No se mueve en un canal limpio: los últimos meses no siguen una línea recta clara.")

    lineas += ["", "🧱 Soportes y resistencias (zonas donde el precio giró antes)"]
    def detalle(n) -> str:
        extra = [f"{n.fuerza}, {n.toques} toque(s)"]
        if n.volumen_alto:
            extra.append("se formó con volumen alto")
        rol = n.cambio_de_rol(l.precio)
        if rol:
            extra.append(rol)
        return " · " + ", ".join(extra)

    for n in reversed(l.resistencias):
        lineas.append(f"🔴 Resistencia {_p(n.precio)} ({_dist(n.precio, l.precio)}){detalle(n)}")
    lineas.append(f"▶️ Precio actual {_p(l.precio)}")
    for n in l.soportes:
        lineas.append(f"🟢 Soporte {_p(n.precio)} ({_dist(n.precio, l.precio)}){detalle(n)}")
    if not l.resistencias:
        lineas.append("(No hay resistencias arriba: el precio está en máximos del último año.)")
    if not l.soportes:
        lineas.append("(No hay soportes debajo: el precio está en mínimos del último año.)")
    if e is not None:
        lineas.append(e.redondos)
        if e.retrocesos is not None:
            lineas.append(e.retrocesos.texto)
        if e.lineas:
            lineas += ["", "📏 Líneas de tendencia"]
            lineas += [x.texto for x in e.lineas]

    if l.figuras:
        lineas += ["", "📐 Figuras en el gráfico"]
        for f in l.figuras:
            objetivo = ""
            if f.objetivo is not None:
                objetivo = f" Objetivo medido: {_p(f.objetivo)} ({_dist(f.objetivo, l.precio)})"
                if f.objetivo_alcanzado(l.precio):
                    objetivo += " – ya alcanzado."
                else:
                    objetivo += "."
            invalida = f" Se anula si {'supera' if f.sesgo < 0 else 'pierde'} {_p(f.invalidacion)}." \
                if f.invalidacion is not None and f.sesgo != 0 else ""
            lineas.append(f"• {f.nombre} ({f.estado}): {f.explicacion}{objetivo}{invalida}")

    lineas += ["", "🔊 Volumen y fuerza"]
    lineas.append(f"Volumen: {l.volumen_texto}.")
    if l.ruptura_texto:
        lineas.append(f"Ruptura reciente: {l.ruptura_texto}.")
    if l.divergencia_texto:
        lineas.append(f"Atención: {l.divergencia_texto}.")
    if e is not None:
        if e.obv:
            lineas.append(f"Atención: {e.obv}.")
        lineas += ["", "🎚️ Osciladores (secundarios: se leen a favor de la tendencia)"]
        lineas += e.osciladores.textos
        senales = []
        relevantes = [h for h in e.huecos if not h.cerrado or h.tipo in ("separación", "agotamiento")]
        senales += [h.texto for h in relevantes[-3:]]
        if e.isla:
            senales.append(e.isla)
        if e.giro_diario:
            senales.append(f"{e.giro_diario[0].upper()}{e.giro_diario[1:]}.")
        if e.giro_semanal:
            senales.append(f"{e.giro_semanal[0].upper()}{e.giro_semanal[1:]}.")
        senales += [v.texto for v in e.velas]
        if senales:
            lineas += ["", "🕯️ Señales de corto plazo (huecos, velas y días de giro)"]
            lineas += senales

    lineas += ["", "🧭 Qué podría pasar"]
    base = {
        "ALCISTA": "La lectura técnica es alcista: la tendencia sigue vigente mientras respete sus soportes.",
        "BAJISTA": "La lectura técnica es bajista: la tendencia sigue vigente mientras no recupere sus resistencias.",
    }.get(l.direccion, "El gráfico no muestra una dirección clara: el precio se mueve entre sus soportes y "
                       "resistencias hasta que rompa alguno.")
    lineas.append(base)
    lineas.append(f"📈 Escenario alcista: {l.escenario_alcista.texto}")
    lineas.append(f"📉 Escenario bajista: {l.escenario_bajista.texto}")
    if l.invalidacion is not None:
        contrario = "cierra debajo de" if l.sesgo > 0 else "cierra arriba de"
        lineas.append(f"❌ La lectura {l.direccion.lower()} se anula si {contrario} {_p(l.invalidacion)} "
                      f"({_dist(l.invalidacion, l.precio)}).")

    lineas += ["", "🧑‍🏫 Cómo lo usaría un trader técnico"]
    if l.direccion == "ALCISTA" and l.soportes:
        s = l.soportes[0].precio
        lineas.append(f"Buscaría oportunidades de compra cerca del soporte de {_p(s)} o después de una ruptura "
                      "con volumen de la resistencia más cercana, y pondría su límite de pérdida (stop) un poco "
                      f"debajo de {_p(s)}: si el precio pierde ese nivel, la idea estaba equivocada.")
    elif l.direccion == "BAJISTA" and l.resistencias:
        r = l.resistencias[0].precio
        lineas.append(f"No compraría mientras el precio esté debajo de {_p(r)}: esperaría a que recupere esa "
                      "resistencia con volumen o a que aparezca una figura de giro (doble piso, hombro-cabeza-"
                      "hombro invertido). Quien ya tiene la acción suele vigilar el soporte más cercano.")
    else:
        lineas.append("Esperaría a que el precio salga del rango: comprar en el medio de un rango tiene poca "
                      "ventaja. La ruptura (con volumen) del techo o del piso marca hacia dónde ir.")
    if e is not None and e.relacion_riesgo:
        lineas.append(e.relacion_riesgo)
    lineas += [
        "",
        "⚠️ Importante: en la validación histórica (/validar_grafico), la dirección que marca esta lectura NO "
        "anticipó el movimiento de las semanas siguientes mejor que el azar. Lo útil es el mapa de niveles "
        "(soportes, resistencias y dónde se invalida una idea), no la predicción de suba o baja.",
    ]
    return "\n".join(lineas) + pie_de_mensaje()


EXPLICACION_TRADER = (
    "🧑‍🏫 Cómo lee un gráfico un trader técnico\n"
    "• Estructura (teoría de Dow): en una tendencia alcista cada máximo y cada mínimo es más alto que el anterior; "
    "en una bajista, más bajo. Cuando eso se rompe (por ejemplo, un mínimo más bajo en una tendencia alcista) "
    "es la primera señal de que la tendencia puede estar cambiando.\n"
    "• Soporte: zona donde el precio dejó de caer varias veces porque aparecieron compradores. Resistencia: zona "
    "donde dejó de subir porque aparecieron vendedores. Cuanto más veces se respetó, más importante es. Cuando "
    "una resistencia se rompe, muchas veces pasa a funcionar como soporte (y al revés).\n"
    "• Ruptura: cuando el precio atraviesa un soporte o una resistencia. Con mucho volumen es más creíble; sin "
    "volumen puede ser una \"ruptura falsa\" y volver atrás.\n"
    "• Figuras: formas que se repiten en los gráficos. El doble techo y el hombro-cabeza-hombro suelen anticipar "
    "caídas; el doble piso y el hombro-cabeza-hombro invertido, subas; los triángulos y banderas, la continuación "
    "o una ruptura. El \"objetivo medido\" es la altura de la figura proyectada desde la ruptura: una referencia, "
    "no una promesa.\n"
    "• Divergencia: cuando el precio hace un nuevo máximo pero el RSI no, la suba está perdiendo fuerza (y al revés "
    "en las caídas).\n"
    "• Stop (límite de pérdida): el precio en el que un trader acepta que se equivocó y sale. Se pone del otro lado "
    "del nivel que justificaba la operación."
)
