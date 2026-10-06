"""Resumen explicativo "para aprender" que acompaña cada análisis.

Explica en lenguaje simple qué es cada indicador y qué está diciendo HOY para
este activo, con los números concretos. Se genera con reglas fijas (no con un
modelo de lenguaje): es gratis, funciona sin clave de API y describe exactamente
lo que calculó el sistema, sin agregar nada.
"""

from __future__ import annotations

import math

import pandas as pd

from monitor_mercado.aviso_legal import pie_de_mensaje
from monitor_mercado.noticias.servicio import AnalisisNoticias
from monitor_mercado.notificaciones.formato import numero
from monitor_mercado.senal_final import SenalFinal
from monitor_mercado.tecnico.reporte_lectura import EXPLICACION_TRADER
from monitor_mercado.tecnico.senal import Tendencia
from monitor_mercado.tecnico.servicio import Analisis


def _pct(valor: float, decimales: int = 1) -> str:
    return f"{numero(100 * valor, decimales)}%"


def _ok(valor: object) -> bool:
    return valor is not None and not (isinstance(valor, float) and math.isnan(valor))


def _idea_general(a: Analisis) -> str:
    s = a.senal
    direccion = {
        Tendencia.ALCISTA: "la mayoría de los indicadores muestra que el precio viene subiendo",
        Tendencia.BAJISTA: "la mayoría de los indicadores muestra que el precio viene bajando",
        Tendencia.NEUTRAL: "los indicadores no muestran una dirección clara (o se contradicen entre sí)",
    }[s.tendencia]
    if s.confianza >= 65:
        acuerdo = "casi todos los indicadores dicen lo mismo"
    elif s.confianza >= 35:
        acuerdo = "hay bastante acuerdo, pero algunos indicadores opinan distinto"
    else:
        acuerdo = "los indicadores están divididos o la señal es débil"
    return (
        "🧭 La idea general\n"
        f"Tendencia {s.tendencia.value.upper()} significa que {direccion}. "
        "Cada indicador \"vota\" entre −1 (bajista) y +1 (alcista), y el puntaje es el promedio "
        f"ponderado de esos votos: acá dio {numero(s.puntaje, 2)}. "
        f"La confianza de {s.confianza}/100 indica que {acuerdo}. "
        "Ojo: la confianza NO es la probabilidad de que el precio siga en esa dirección."
    )


def _medias(u: pd.Series) -> str:
    c = u["cierre"]
    lineas = [
        "📏 Medias móviles",
        "Una media móvil es el promedio de los últimos N cierres. Suaviza el ruido diario y "
        "muestra hacia dónde va el precio: la de 20 días mira el último mes, la de 50 unos "
        "tres meses y la de 200 casi un año. Si el precio está por encima de una media, en ese "
        "plazo viene subiendo.",
    ]
    partes = []
    for col, plazo in (("sma20", "corto plazo (20)"), ("sma50", "mediano plazo (50)"), ("sma200", "largo plazo (200)")):
        if _ok(u[col]):
            lado = "por encima" if c > u[col] else "por debajo"
            partes.append(f"{lado} de la de {plazo} ({_pct(c / u[col] - 1)})")
    if partes:
        lineas.append("Hoy el precio está " + "; ".join(partes) + ".")
    if _ok(u["sma200"]):
        if u["sma20"] > u["sma50"] > u["sma200"]:
            lineas.append("Las tres medias están ordenadas de menor a mayor plazo (20 > 50 > 200): "
                          "es la \"alineación alcista\" clásica.")
        elif u["sma20"] < u["sma50"] < u["sma200"]:
            lineas.append("Las medias están ordenadas al revés (20 < 50 < 200): es la \"alineación "
                          "bajista\" clásica, típica de una tendencia de caída sostenida.")
        else:
            lineas.append("Las medias están mezcladas: suele pasar cuando la tendencia está cambiando "
                          "o el precio se mueve de costado.")
        cruce = "por encima" if u["sma50"] > u["sma200"] else "por debajo"
        lineas.append(f"La media de 50 está {cruce} de la de 200. Cuando la de 50 cruza hacia arriba "
                      "se llama \"cruce dorado\" (alcista); hacia abajo, \"cruce de la muerte\" (bajista).")
    return "\n".join(lineas)


def _rsi(u: pd.Series) -> str:
    r = u["rsi14"]
    if r > 70:
        lectura = ("está en SOBRECOMPRA: subió mucho en poco tiempo. No significa que vaya a bajar, "
                   "pero aumenta el riesgo de una corrección o pausa")
    elif r >= 55:
        lectura = "muestra fuerza compradora: en las últimas semanas pesaron más las subas"
    elif r > 45:
        lectura = "está neutral: subas y bajas recientes están equilibradas"
    elif r >= 30:
        lectura = "muestra debilidad: en las últimas semanas pesaron más las bajas"
    else:
        lectura = ("está en SOBREVENTA: cayó mucho en poco tiempo. Puede haber un rebote, pero en "
                   "una tendencia bajista el RSI puede quedarse abajo por semanas")
    return (
        "⚖️ RSI (índice de fuerza relativa)\n"
        "Va de 0 a 100 y compara el tamaño de las subas con el de las bajas de los últimos 14 días. "
        "Más de 70 se considera \"sobrecompra\" y menos de 30, \"sobreventa\".\n"
        f"Hoy vale {numero(r, 0)}, así que {lectura}."
    )


def _macd(u: pd.Series) -> str:
    lado = "positivo (la media rápida está por encima de la lenta: impulso alcista de fondo)" if u["macd"] > 0 \
        else "negativo (la media rápida está por debajo de la lenta: impulso bajista de fondo)"
    hist = "creciendo: el impulso reciente mejora" if u["macd_hist"] > 0 else "cayendo: el impulso reciente empeora"
    return (
        "🔀 MACD\n"
        "Es la diferencia entre dos medias exponenciales (12 y 26 días). Mide el impulso: si el MACD "
        "cruza hacia arriba su línea de señal (una media de 9 días del propio MACD), el impulso se "
        "vuelve alcista; si cruza hacia abajo, bajista. El histograma (las barras del gráfico) es la "
        "distancia entre ambas líneas.\n"
        f"Hoy el MACD es {lado}, y el histograma está {hist}."
    )


def _bollinger(a: Analisis) -> str:
    u = a.ultimo
    p = u["bb_pct"]
    if p > 1:
        pos = "POR ENCIMA de la banda superior: el precio está estirado hacia arriba"
    elif p > 0.8:
        pos = "cerca de la banda superior"
    elif p >= 0.2:
        pos = "en la zona media de las bandas"
    elif p >= 0:
        pos = "cerca de la banda inferior"
    else:
        pos = "POR DEBAJO de la banda inferior: el precio está estirado hacia abajo"
    ancho_medio = a.datos["bb_ancho"].tail(126).median()
    vol = "más anchas de lo habitual (volatilidad alta)" if u["bb_ancho"] > 1.2 * ancho_medio \
        else "más angostas de lo habitual (volatilidad baja; a veces anticipa un movimiento fuerte)" \
        if u["bb_ancho"] < 0.8 * ancho_medio else "de ancho normal"
    return (
        "📐 Bandas de Bollinger\n"
        "Son una media de 20 días con una banda arriba y otra abajo a 2 desvíos estándar. "
        "Alrededor del 95% del tiempo el precio queda adentro, así que muestran si está \"estirado\" "
        "respecto de su rango habitual. Que se ensanchen indica más volatilidad.\n"
        f"Hoy el precio está {pos}, y las bandas están {vol}."
    )


def _volumen_y_volatilidad(a: Analisis) -> str:
    u = a.ultimo
    lineas = ["📊 Volumen y volatilidad"]
    vr = u["vol_relativo"]
    if _ok(vr):
        if vr > 1.5:
            lectura = f"muy alto ({numero(vr, 1)} veces el promedio): el movimiento de hoy tiene mucha participación, lo que lo hace más \"creíble\""
        elif vr < 0.6:
            lectura = f"bajo ({numero(vr, 1)} veces el promedio): hubo poca participación"
        else:
            lectura = f"normal ({numero(vr, 1)} veces el promedio)"
        lineas.append(f"El volumen es la cantidad de acciones que se negociaron. Hoy fue {lectura}.")
    atr_pct = u["atr14"] / u["cierre"]
    lineas.append(
        "El ATR (rango verdadero promedio) mide cuánto se mueve el precio en un día típico. "
        f"Acá es {numero(u['atr14'])} {a.moneda}, un {_pct(atr_pct)} del precio: si invirtieras "
        f"1.000, un día normal podrías ver una variación de alrededor de ±{numero(1000 * atr_pct, 0)}."
    )
    if _ok(u["retorno_63d"]):
        lineas.append(f"En los últimos 3 meses el precio varió {_pct(u['retorno_63d'])}.")
    return "\n".join(lineas)


def _patrones(a: Analisis) -> str | None:
    if not a.patrones:
        return None
    lineas = ["🔎 Patrones de las últimas ruedas"]
    for p in a.patrones:
        lineas.append(f"• {p.definicion.nombre}: {p.definicion.descripcion}")
    lineas.append("Los patrones son pistas que muchos operadores miran, no reglas que siempre se cumplen.")
    return "\n".join(lineas)


def _noticias(n: AnalisisNoticias, final: SenalFinal | None) -> str:
    lineas = ["📰 Noticias"]
    if n.puntaje is None:
        if n.noticias:
            lineas.append(f"Se encontraron {len(n.noticias)} titulares recientes. No se les asigna un puntaje "
                          "automático, así que la señal final es solo técnica. Leelos: una noticia importante "
                          "(resultados, cambios de regulación, fusiones) puede pesar más que cualquier indicador.")
        else:
            lineas.append("No se encontraron noticias recientes, así que la señal final es solo técnica.")
        return "\n".join(lineas)
    tono = "positivo" if n.puntaje > 0.1 else "negativo" if n.puntaje < -0.1 else "neutro"
    lineas.append(
        "Cada titular se clasifica como positivo, negativo o neutro según cómo podría afectar el precio "
        "de ESTA empresa, y se pondera por su relevancia y por lo reciente que es. "
        f"El tono general es {tono} ({numero(n.puntaje, 2)}), con una cobertura de {_pct(n.cobertura, 0)} "
        "(cuánta información relevante y reciente hubo)."
    )
    if final is not None:
        lineas.append(
            f"En la señal final las noticias pesaron un {_pct(final.peso_noticias, 0)} y el análisis "
            f"técnico el resto. Pesan poco a propósito: los titulares se interpretan rápido y a veces el "
            "mercado ya los reflejó en el precio."
        )
        if final.coinciden is False:
            lineas.append("⚠️ Las noticias y los precios apuntan en direcciones opuestas: por eso bajó la "
                          "confianza. Cuando pasa esto conviene mirar con más cuidado qué está pasando.")
        elif final.coinciden:
            lineas.append("Las noticias y los precios apuntan en la misma dirección, lo que refuerza la señal.")
    return "\n".join(lineas)


def _en_resumen(a: Analisis, final: SenalFinal | None) -> str:
    votos = {f.clave: f.voto for f in a.senal.factores}
    fondo = (votos.get("tendencia_largo", 0) + votos.get("estructura_medias", 0)) / 2
    corto = (votos.get("pendiente_corto", 0) + votos.get("macd", 0)) / 2
    r = a.ultimo["rsi14"]

    def dir_(v: float) -> str:
        return "alcista" if v > 0.2 else "bajista" if v < -0.2 else "sin dirección clara"

    if dir_(fondo) == dir_(corto):
        frases = [f"Tanto la tendencia de fondo (meses) como la de corto plazo (semanas) están "
                  f"{dir_(fondo).replace('alcista', 'alcistas').replace('bajista', 'bajistas')}."]
    else:
        frases = [f"La tendencia de fondo (meses) es {dir_(fondo)} y la de corto plazo (semanas) es {dir_(corto)}."]
    if dir_(fondo) != dir_(corto) and "sin dirección clara" not in (dir_(fondo), dir_(corto)):
        frases.append("Que no coincidan suele indicar un rebote dentro de una caída o una corrección dentro "
                      "de una suba: todavía no se sabe si es un cambio de tendencia o una pausa.")
    if r < 30 and fondo < 0:
        frases.append("El RSI en sobreventa dentro de una tendencia bajista dice que la caída fue rápida; "
                      "puede haber un rebote, pero eso solo no cambia la tendencia de fondo.")
    if r > 70 and fondo > 0:
        frases.append("El RSI en sobrecompra dentro de una tendencia alcista dice que la suba fue rápida; "
                      "es común que haya pausas o correcciones antes de seguir.")
    if final is not None and final.peso_noticias > 0:
        frases.append(f"Sumando las noticias, la señal final es {final.tendencia.value.upper()} "
                      f"con confianza {final.confianza}/100.")
    return "✅ En resumen\n" + " ".join(frases)


QUE_NO_DICE = (
    "🚫 Lo que este análisis NO te dice\n"
    "• No predice el futuro: resume lo que pasó con el precio. Las tendencias pueden cortarse en cualquier momento.\n"
    "• No mira si la empresa es buena o está cara (eso es análisis fundamental: Etapa 4).\n"
    "• Todavía no sabemos cuánto acierta esta señal: lo vamos a medir con el backtest (Etapa 5).\n"
    "• Usalo como un insumo más, junto con tu propio criterio y otras fuentes."
)


def explicacion_completa(
    a: Analisis, noticias: AnalisisNoticias | None = None, final: SenalFinal | None = None
) -> str:
    """Texto explicativo completo para un activo."""
    u = a.ultimo
    secciones = [
        f"📘 Explicación para aprender – {a.simbolo}",
        EXPLICACION_TRADER,
        _idea_general(a),
        _medias(u),
        _rsi(u),
        _macd(u),
        _bollinger(a),
        _volumen_y_volatilidad(a),
    ]
    if (p := _patrones(a)) is not None:
        secciones.append(p)
    if a.en_ccl:
        secciones.append(
            "💵 Por qué en dólares CCL\n"
            "Esta acción cotiza en pesos. Con inflación, el precio en pesos sube aunque la empresa valga lo "
            "mismo en términos reales, y el análisis técnico lo confundiría con una tendencia alcista. Por "
            "eso se convierte a dólares con el \"contado con liquidación\" (CCL), el tipo de cambio implícito "
            "en comprar la acción acá y venderla en Nueva York."
        )
    if noticias is not None:
        secciones.append(_noticias(noticias, final))
    secciones += [_en_resumen(a, final), QUE_NO_DICE]
    return "\n\n".join(secciones) + pie_de_mensaje()


GLOSARIO: dict[str, str] = {
    "tendencia": "La dirección general del precio en un período: alcista (sube), bajista (baja) o lateral.",
    "media movil": "Promedio de los últimos N cierres. Suaviza el ruido y muestra la dirección de fondo.",
    "rsi": "Índice de 0 a 100 que compara subas y bajas recientes. >70 sobrecompra, <30 sobreventa.",
    "macd": "Diferencia entre dos medias exponenciales (12 y 26). Mide el impulso y sus cambios.",
    "bollinger": "Bandas a ±2 desvíos de la media de 20. Muestran si el precio está estirado y la volatilidad.",
    "volumen": "Cantidad de acciones negociadas. Movimientos con mucho volumen se consideran más firmes.",
    "atr": "Rango verdadero promedio: cuánto se mueve el precio en un día típico.",
    "volatilidad": "Cuánto varía el precio. Más volatilidad = más riesgo y movimientos más grandes.",
    "ccl": "Dólar contado con liquidación: el tipo de cambio implícito en comprar un activo en pesos y venderlo en dólares afuera.",
    "cedear": "Certificado que se compra en pesos en BYMA y representa acciones del exterior (ej. AAPL.BA).",
    "adr": "Certificado que cotiza en EE.UU. y representa acciones de una empresa extranjera (ej. GGAL, YPF).",
    "soporte": "Zona de precio donde antes aparecieron compradores y frenó la caída.",
    "resistencia": "Zona de precio donde antes aparecieron vendedores y frenó la suba.",
    "sobrecompra": "El precio subió mucho en poco tiempo (RSI > 70). Aumenta el riesgo de corrección.",
    "sobreventa": "El precio cayó mucho en poco tiempo (RSI < 30). Puede haber rebote.",
    "sentimiento": "Si las noticias recientes son favorables o desfavorables para el precio de la empresa.",
    "backtest": "Probar una estrategia con datos del pasado para ver cómo le habría ido.",
    "overfitting": "Ajustar tanto una estrategia al pasado que funciona ahí pero falla con datos nuevos.",
    "drawdown": "La caída desde un máximo hasta el mínimo siguiente: mide el peor momento de una inversión.",
    "sharpe": "Retorno por unidad de riesgo (volatilidad). Más alto = mejor relación retorno/riesgo.",
    "eps": "Ganancia por acción: ganancia neta dividida por la cantidad de acciones.",
    "consenso": "Promedio de lo que esperan los analistas para un dato (EPS, ingresos). El precio ya lo refleja.",
    "beat": "Cuando el resultado supera el consenso de analistas. Lo contrario es \"miss\".",
    "miss": "Cuando el resultado queda por debajo del consenso de analistas.",
    "guidance": "Proyecciones que da la propia empresa sobre sus próximos trimestres.",
    "margen": "Qué parte de cada peso vendido queda como ganancia (bruta, operativa o neta).",
    "ebitda": "Ganancia operativa antes de intereses, impuestos y amortizaciones: aproxima la caja que genera el negocio.",
    "flujo de caja libre": "Caja que genera el negocio después de invertir en activos (capex). Paga dividendos y deuda.",
    "deuda neta": "Deuda total menos caja. Si es negativa, la empresa tiene más caja que deuda.",
    "pe": "Precio / ganancia por acción: cuántos años de ganancias actuales pagás al comprar.",
    "ev/ebitda": "Valor de la empresa (incluye deuda) sobre su EBITDA. Compara empresas con distinta deuda.",
    "interanual": "Comparación con el mismo período del año anterior (YoY). Elimina la estacionalidad.",
}


def texto_glosario(termino: str | None = None) -> str:
    """Definición de un término, o la lista completa si no se indica ninguno."""
    import unicodedata

    def normal(t: str) -> str:
        return unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode().strip()

    if termino:
        clave = normal(termino)
        for k, v in GLOSARIO.items():
            if clave in (k, k.replace(" ", "")) or k.startswith(clave):
                return f"📖 {k.upper()}: {v}"
        return f"No tengo \"{termino}\" en el glosario. Mandá /glosario para ver la lista."
    return "📖 Glosario\n\n" + "\n".join(f"• {k.upper()}: {v}" for k, v in GLOSARIO.items())
