"""Servidor MCP: conecta el monitor de mercado con Claude.

Con este servidor, Claude (Claude Code en la nube o en tu PC, o Claude Desktop) puede usar
las mismas funciones que el bot de Telegram y la terminal: precios, análisis técnico, lectura
del gráfico, noticias, resultados, backtest, cartera y alertas. Así le podés hacer preguntas
en lenguaje natural ("¿cómo viene GGAL?", "¿qué pasó con mi cartera hoy?") y Claude arma la
respuesta con los datos de tu propio sistema, más lo que sabe y lo que busca en la web.

Además de los comandos de siempre, agrega herramientas "de datos crudos" que el bot no tenía
(historial de precios, ficha de la empresa, estados contables, comparación entre activos),
para que Claude pueda responder preguntas más abiertas.

Arranque: ``monitor-claude`` (o ``python -m monitor_mercado.servidor_claude``). Habla por
stdin/stdout con el protocolo MCP: no se usa a mano, lo lanza Claude.
"""

from __future__ import annotations

import logging
import math
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from mcp.server.mcpserver import Image, MCPServer

from monitor_mercado.alertas.modelos import Moneda
from monitor_mercado.alertas.parser import AYUDA_FORMATO, ErrorFormato, parsear_alerta
from monitor_mercado.aplicacion import Contexto, armar_contexto
from monitor_mercado.aviso_legal import pie_de_mensaje
from monitor_mercado.datos.modelos import ErrorDatos
from monitor_mercado.explicacion import explicacion_completa, texto_glosario
from monitor_mercado.noticias.reporte import linea_senal_final, reporte_noticias
from monitor_mercado.notificaciones import formato

log = logging.getLogger(__name__)

INSTRUCCIONES = """\
Monitor de mercado personal del usuario (Argentina). Respondé siempre en español rioplatense.
- Usá estas herramientas para obtener datos reales antes de opinar. Si una pregunta es amplia
  ("¿cómo viene X?"), combiná varias: analizar + noticias + datos_empresa, y resultados si es
  una empresa que presenta balances.
- Las acciones argentinas en pesos se analizan en dólares CCL (para descontar la inflación).
- Explicá los términos técnicos con palabras simples: el usuario está aprendiendo.
- El backtest del propio sistema mostró que la señal técnica NO predice la dirección del precio:
  presentala como un resumen ordenado de indicadores y un mapa de niveles, nunca como una
  predicción. Nada de esto es asesoramiento financiero: decilo cuando hables de comprar o vender.
- Los precios de Yahoo pueden tener 15-20 minutos de demora.
"""

servidor = MCPServer("monitor-mercado", instructions=INSTRUCCIONES)

_contexto: Contexto | None = None


def contexto() -> Contexto:
    """Contexto del sistema, armado una sola vez (la primera herramienta que se usa)."""
    global _contexto
    if _contexto is None:
        _contexto = armar_contexto()
    return _contexto


def usar_contexto(ctx: Contexto | None) -> None:
    """Reemplaza el contexto (lo usan los tests para no depender de internet)."""
    global _contexto
    _contexto = ctx


def _simbolo(texto: str) -> str:
    """Acepta símbolos o nombres de empresa ("mercado libre" -> MELI)."""
    return contexto().buscador().resolver(texto.strip()).upper()


def _error(e: Exception) -> str:
    return f"⚠️ No se pudo completar la consulta: {e}"


def _imagen(ruta: Path) -> Image | None:
    try:
        return Image(path=str(ruta))
    except Exception:  # noqa: BLE001 - el gráfico es un complemento
        log.exception("No se pudo leer el gráfico %s", ruta)
        return None


def _num(v: Any, decimales: int = 2) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "-"
    if not math.isfinite(x):
        return "-"
    return f"{x:,.{decimales}f}"


def _pct(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "-"
    return "-" if not math.isfinite(x) else f"{x * 100:+.1f}%"


def _grande(v: Any) -> str:
    """1.234.000.000 -> 1,23 B (miles de millones)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "-"
    if not math.isfinite(x):
        return "-"
    for limite, sufijo in ((1e12, " T"), (1e9, " B"), (1e6, " M")):
        if abs(x) >= limite:
            return f"{x / limite:,.2f}{sufijo}"
    return f"{x:,.0f}"


# ---------------------------------------------------------------------------
# Las mismas funciones del bot y de la terminal
# ---------------------------------------------------------------------------


@servidor.tool()
def precio(simbolo: str, en_pesos: bool = False) -> str:
    """Precio actual de un activo (acción, ADR, CEDEAR, ETF, índice).

    Args:
        simbolo: Símbolo de Yahoo (AAPL, GGAL, ALUA.BA, PETR4.SA, ^IXIC) o nombre de la empresa.
        en_pesos: True = precio en pesos (el CEDEAR para acciones de EE.UU., la acción local para las argentinas).
    """
    try:
        p = contexto().servicio.precio_en(_simbolo(simbolo), Moneda.ARS if en_pesos else Moneda.USD)
    except (ValueError, ErrorDatos) as e:
        return _error(e)
    return formato.detalle_precio(p) + pie_de_mensaje()


@servidor.tool(structured_output=False)
def analizar(simbolo: str, incluir_grafico: bool = True) -> list[Any]:
    """Análisis completo de un activo: lectura del gráfico como un trader (estructura, soportes,
    resistencias, figuras, escenarios), indicadores (medias, RSI, MACD, Bollinger, volumen),
    patrones recientes, noticias de la semana, señal final y un resumen para aprender.

    Args:
        simbolo: Símbolo o nombre de la empresa.
        incluir_grafico: True = devuelve también el gráfico de velas anotado (imagen).
    """
    from monitor_mercado.tecnico.grafico_lectura import grafico_lectura
    from monitor_mercado.tecnico.reporte import reporte_completo
    from monitor_mercado.tecnico.reporte_lectura import texto_lectura

    ctx = contexto()
    try:
        r = ctx.analisis_completo(_simbolo(simbolo))
    except ErrorDatos as e:
        return [_error(e)]
    partes = []
    if r.tecnico.lectura is not None:
        partes.append(texto_lectura(r.tecnico.simbolo, r.tecnico.lectura, r.tecnico.moneda))
    partes.append(reporte_completo(r.tecnico, con_pie=False))
    if r.noticias is not None:
        partes.append(reporte_noticias(r.noticias, maximo=8, con_pie=False))
    partes.append(linea_senal_final(r.final) + pie_de_mensaje())
    partes.append(explicacion_completa(r.tecnico, r.noticias, r.final))
    salida: list[Any] = ["\n\n".join(partes)]
    if incluir_grafico and r.tecnico.lectura is not None:
        img = _imagen(grafico_lectura(r.tecnico.simbolo, r.tecnico.lectura, r.tecnico.moneda,
                                      ctx.cfg.rutas.ruta_graficos()))
        if img is not None:
            salida.append(img)
    return salida


@servidor.tool(structured_output=False)
def grafico(simbolo: str) -> list[Any]:
    """Solo la lectura del gráfico como un trader (estructura, niveles, canal, figuras con objetivo
    e invalidación, escenarios), con el gráfico de velas anotado.

    Args:
        simbolo: Símbolo o nombre de la empresa.
    """
    from monitor_mercado.tecnico.grafico_lectura import grafico_lectura
    from monitor_mercado.tecnico.reporte_lectura import texto_lectura

    ctx = contexto()
    try:
        a = ctx.tecnico.analizar(_simbolo(simbolo))
    except ErrorDatos as e:
        return [_error(e)]
    if a.lectura is None:
        return ["No se pudo leer el gráfico (historia insuficiente)."]
    salida: list[Any] = [texto_lectura(a.simbolo, a.lectura, a.moneda)]
    img = _imagen(grafico_lectura(a.simbolo, a.lectura, a.moneda, ctx.cfg.rutas.ruta_graficos()))
    if img is not None:
        salida.append(img)
    return salida


@servidor.tool()
def resumen_watchlist(completa: bool = False) -> str:
    """Señal técnica de toda la watchlist, de la más alcista a la más bajista.

    Args:
        completa: False = la watchlist de prueba (10 símbolos); True = la completa (~89, tarda más).
    """
    from monitor_mercado.tecnico.reporte import reporte_resumen

    ctx = contexto()
    simbolos = ctx.cfg.watchlist_completa if completa else ctx.cfg.watchlist_activa
    analisis, errores = ctx.tecnico.resumen(simbolos)
    return reporte_resumen(analisis, errores)


@servidor.tool()
def noticias(simbolo: str) -> str:
    """Titulares de los últimos días de un activo (Yahoo, Google News en español/portugués, SEC),
    con su sentimiento si está activada la clasificación con Claude.

    Args:
        simbolo: Símbolo o nombre de la empresa.
    """
    ctx = contexto()
    if ctx.noticias is None:
        return "Las noticias están desactivadas en config.yaml (noticias.habilitado)."
    try:
        return reporte_noticias(ctx.noticias.analizar(_simbolo(simbolo)), maximo=25)
    except ErrorDatos as e:
        return _error(e)


@servidor.tool()
def resultados(simbolo: str, fecha: str | None = None) -> str:
    """Análisis de la presentación de resultados trimestrales: EPS e ingresos vs. lo esperado,
    crecimiento, márgenes, deuda y caja, reacción del precio, guidance y valuación vs. sus pares.

    Args:
        simbolo: Símbolo o nombre de la empresa.
        fecha: Opcional (AAAA-MM-DD): la presentación más cercana a esa fecha. Vacío = la última.
    """
    from monitor_mercado.resultados.reporte import explicacion_resultados, reporte_resultados

    ctx = contexto()
    try:
        r = ctx.resultados.analizar(_simbolo(simbolo), date.fromisoformat(fecha) if fecha else None)
    except (ErrorDatos, ValueError) as e:
        return _error(e)
    return reporte_resultados(r) + "\n\n" + explicacion_resultados(r)


@servidor.tool()
def calendario() -> str:
    """Próximas presentaciones de resultados de las empresas que sigue el usuario."""
    from monitor_mercado.resultados.reporte import texto_calendario

    ctx = contexto()
    seguidas = ctx.resultados.repo.seguidas()
    return texto_calendario(ctx.resultados.proximas(seguidas), seguidas)


@servidor.tool()
def seguir_empresa(simbolo: str) -> str:
    """Agrega una empresa a la lista de resultados que sigue el usuario.

    Args:
        simbolo: Símbolo o nombre de la empresa.
    """
    ctx = contexto()
    s = _simbolo(simbolo)
    try:
        ctx.proveedor.cotizacion(s)
    except ErrorDatos:
        return ctx.buscador().mensaje_no_encontrado(s)
    return f"Ahora seguís {s}." if ctx.resultados.repo.seguir(s) else f"Ya seguías {s}."


@servidor.tool()
def dejar_de_seguir(simbolo: str) -> str:
    """Quita una empresa de la lista de resultados que sigue el usuario.

    Args:
        simbolo: Símbolo de la empresa.
    """
    s = simbolo.strip().upper()
    return f"Dejaste de seguir {s}." if contexto().resultados.repo.dejar(s) else f"No seguías {s}."


@servidor.tool()
def empresas_seguidas() -> str:
    """Empresas cuyos resultados sigue el usuario."""
    return ", ".join(contexto().resultados.repo.seguidas()) or "Ninguna."


@servidor.tool(structured_output=False)
def backtest(simbolo: str) -> list[Any]:
    """¿Seguir la señal técnica le hubiera ganado a comprar y mantener? Con costos, walk-forward
    fuera de muestra, bootstrap (¿suerte?) y poder predictivo. Devuelve también el gráfico.

    Args:
        simbolo: Símbolo o nombre de la empresa.
    """
    from monitor_mercado.backtest.reporte import explicacion_backtest, grafico_backtest, reporte_backtest

    ctx = contexto()
    try:
        r = ctx.backtest.correr(_simbolo(simbolo))
    except ErrorDatos as e:
        return [_error(e)]
    salida: list[Any] = [reporte_backtest(r) + "\n\n" + explicacion_backtest(r)]
    img = _imagen(grafico_backtest(r, ctx.cfg.rutas.ruta_graficos()))
    if img is not None:
        salida.append(img)
    return salida


@servidor.tool()
def backtest_watchlist(completa: bool = False) -> str:
    """Backtest de toda la watchlist con la conclusión general (tarda varios minutos).

    Args:
        completa: True = los ~89 símbolos de la lista completa.
    """
    from monitor_mercado.backtest.reporte import resumen_backtests

    ctx = contexto()
    simbolos = ctx.cfg.watchlist_completa if completa else ctx.cfg.watchlist_activa
    return resumen_backtests(*ctx.backtest.correr_varios(simbolos))


@servidor.tool()
def validar_grafico(completa: bool = False) -> str:
    """Mide si la lectura del gráfico acertó la dirección del precio en el pasado.

    Args:
        completa: True = la watchlist completa (tarda más).
    """
    from monitor_mercado.backtest.validar_lectura import texto_validacion, validar

    ctx = contexto()
    simbolos = ctx.cfg.watchlist_completa if completa else ctx.cfg.watchlist_activa
    return texto_validacion(validar(ctx.tecnico, simbolos))


@servidor.tool()
def cartera() -> str:
    """Cartera del usuario (mi_cartera.csv): precio, variación del día, ganancia/pérdida desde
    la compra y peso de cada posición."""
    from monitor_mercado.cartera.reporte import texto_cartera

    ctx = contexto()
    if not ctx.cartera.posiciones():
        return (f"No hay posiciones cargadas: falta el archivo {ctx.cartera.ruta.name} "
                "(formato en mi_cartera.ejemplo.csv). Pedile al usuario sus posiciones y usá cargar_cartera.")
    return texto_cartera(ctx.cartera.estado())


@servidor.tool()
def cargar_cartera(csv: str) -> str:
    """Guarda las posiciones del usuario en mi_cartera.csv (reemplaza el archivo).

    Args:
        csv: Contenido en formato CSV con encabezado
            ``simbolo,cantidad,precio_compra,moneda,fecha_compra,nota``.
            precio_compra, fecha_compra (AAAA-MM-DD) y nota pueden ir vacíos.
    """
    from monitor_mercado.cartera.archivo import leer_cartera

    ruta = contexto().cartera.ruta
    anterior = ruta.read_text(encoding="utf-8") if ruta.exists() else None
    ruta.write_text(csv.strip() + "\n", encoding="utf-8")
    try:
        posiciones = leer_cartera(ruta)
    except Exception as e:  # noqa: BLE001 - se vuelve al archivo anterior si el nuevo es inválido
        if anterior is None:
            ruta.unlink()
        else:
            ruta.write_text(anterior, encoding="utf-8")
        return f"⚠️ El CSV no es válido, no se guardó: {e}"
    return f"Cartera guardada: {len(posiciones)} posiciones ({', '.join(p.simbolo for p in posiciones)})."


@servidor.tool()
def resumen_dia(con_noticias: bool = True) -> str:
    """El resumen de cierre de la cartera: resultado del día y total, mejores y peores,
    movimientos grandes, noticias importantes y avisos de concentración.

    Args:
        con_noticias: False = más rápido, sin buscar noticias.
    """
    from monitor_mercado.cartera.reporte import texto_resumen_dia

    ctx = contexto()
    if not ctx.cartera.posiciones():
        return "No hay posiciones cargadas (ver la herramienta cargar_cartera)."
    return texto_resumen_dia(ctx.cartera.resumen_dia(con_noticias), ctx.cfg.cartera.umbral_movimiento)


@servidor.tool()
def glosario(termino: str | None = None) -> str:
    """Definiciones simples de los términos que usa el sistema (RSI, MACD, CCL, EV/EBITDA...).

    Args:
        termino: Término a buscar. Vacío = la lista completa.
    """
    return texto_glosario(termino)


@servidor.tool()
def crear_alerta(alerta: str, nota: str | None = None) -> str:
    """Crea una alerta de precio (avisa por Telegram si el bot está corriendo en la PC del usuario).

    Args:
        alerta: Formato ``SIMBOLO compra|venta llega|sube|baja|var+|var- VALOR [ars] [repetir]``.
            Ej.: "AAPL compra baja 180", "GGAL compra var- 5 repetir", "ALUA.BA compra baja 800 ars".
        nota: Comentario que aparece en el aviso.
    """
    try:
        solicitud = parsear_alerta(alerta.split())
        if nota:
            solicitud = replace(solicitud, nota=nota)
        return formato.mensaje_creada(contexto().servicio.crear(solicitud))
    except ErrorFormato as e:
        return f"{e}\n\n{AYUDA_FORMATO}"
    except (ValueError, ErrorDatos) as e:
        return _error(e)


@servidor.tool()
def listar_alertas(todas: bool = False) -> str:
    """Lista las alertas de precio.

    Args:
        todas: True = incluye las ya cumplidas.
    """
    return formato.mensaje_listado(contexto().servicio.repo.listar(solo_activas=not todas))


@servidor.tool()
def borrar_alerta(id_alerta: int) -> str:
    """Borra una alerta por su número (ver listar_alertas).

    Args:
        id_alerta: Número de la alerta.
    """
    ok = contexto().servicio.repo.borrar(id_alerta)
    return f"Alerta #{id_alerta} borrada." if ok else f"No existe la alerta #{id_alerta}."


@servidor.tool()
def revisar_alertas(forzar: bool = True) -> str:
    """Revisa ahora las alertas activas contra los precios actuales e informa cuáles se cumplieron.

    Args:
        forzar: True = revisa aunque el mercado esté cerrado.
    """
    disparos = contexto().servicio.revisar(forzar=forzar)
    return "\n\n".join([*(formato.mensaje_disparo(d) for d in disparos), formato.mensaje_revision(len(disparos))])


@servidor.tool()
def watchlist() -> str:
    """Las listas de símbolos que sigue el usuario y qué modo está activo."""
    cfg = contexto().cfg
    return (f"Modo activo: {cfg.modo_watchlist}\n"
            f"Prueba ({len(cfg.watchlist_prueba)}): {', '.join(cfg.watchlist_prueba)}\n"
            f"Completa ({len(cfg.watchlist_completa)}): {', '.join(cfg.watchlist_completa)}")


@servidor.tool()
def buscar_simbolo(texto: str) -> str:
    """Encuentra el símbolo de una empresa por su nombre o corrige un símbolo mal escrito.

    Args:
        texto: Nombre de la empresa o símbolo aproximado ("galicia", "mercadolibre", "NVDIA").
    """
    b = contexto().buscador()
    s = b.resolver(texto).upper()
    try:
        contexto().proveedor.cotizacion(s)
    except ErrorDatos:
        return b.mensaje_no_encontrado(texto)
    return f"{b.describir(s)}"


# ---------------------------------------------------------------------------
# Datos crudos: para que Claude pueda responder preguntas más abiertas
# ---------------------------------------------------------------------------

_COLUMNAS_HISTORIAL = {
    "apertura": "apertura", "maximo": "máximo", "minimo": "mínimo", "cierre": "cierre", "volumen": "volumen",
    "sma20": "media20", "sma50": "media50", "sma200": "media200", "rsi14": "rsi14", "macd": "macd",
    "macd_senal": "macd_señal", "atr14": "atr14", "vol_relativo": "vol_rel",
}


@servidor.tool()
def historial_precios(simbolo: str, ruedas: int = 60, semanal: bool = False) -> str:
    """Tabla de precios diarios (o semanales) con los principales indicadores, para mirar
    la evolución con detalle. Las acciones argentinas en pesos vienen en dólares CCL.

    Args:
        simbolo: Símbolo o nombre de la empresa.
        ruedas: Cuántas filas devolver (máximo 500).
        semanal: True = una fila por semana (útil para mirar varios años).
    """
    from monitor_mercado.tecnico.indicadores import calcular_indicadores

    ctx = contexto()
    s = _simbolo(simbolo)
    try:
        df, moneda, _ = ctx.tecnico.datos(s)
    except ErrorDatos as e:
        return _error(e)
    df = calcular_indicadores(df)
    if semanal:
        df = df.resample("W-FRI").agg({**{c: "last" for c in df.columns},
                                       "apertura": "first", "maximo": "max", "minimo": "min", "volumen": "sum"})
        df = df.dropna(subset=["cierre"])
    columnas = [c for c in _COLUMNAS_HISTORIAL if c in df.columns]
    tabla = df[columnas].tail(max(1, min(ruedas, 500))).rename(columns=_COLUMNAS_HISTORIAL)
    tabla.index = tabla.index.strftime("%Y-%m-%d")
    tabla["volumen"] = tabla["volumen"].round(0)
    return (f"{s} — {'semanal' if semanal else 'diario'}, en {moneda} (ajustado por splits y dividendos)\n"
            + tabla.round(4).to_csv())


_FICHA = [
    ("Empresa", "longName"), ("Sector", "sector"), ("Industria", "industry"), ("País", "country"),
    ("Moneda de cotización", "currency"), ("Moneda de los balances", "financialCurrency"),
    ("Precio", "currentPrice"), ("Capitalización", "marketCap"), ("Valor empresa (EV)", "enterpriseValue"),
    ("Mínimo 52 semanas", "fiftyTwoWeekLow"), ("Máximo 52 semanas", "fiftyTwoWeekHigh"),
    ("Beta", "beta"), ("P/E (12 meses)", "trailingPE"), ("P/E esperado", "forwardPE"), ("PEG", "pegRatio"),
    ("EV/EBITDA", "enterpriseToEbitda"), ("Precio / valor libro", "priceToBook"),
    ("Precio / ventas", "priceToSalesTrailing12Months"), ("Ingresos (12 meses)", "totalRevenue"),
    ("EBITDA (12 meses)", "ebitda"), ("Caja", "totalCash"), ("Deuda", "totalDebt"),
    ("Flujo de caja libre", "freeCashflow"), ("Margen bruto", "grossMargins"),
    ("Margen operativo", "operatingMargins"), ("Margen neto", "profitMargins"), ("ROE", "returnOnEquity"),
    ("Crecimiento ingresos (interanual)", "revenueGrowth"), ("Crecimiento ganancias (interanual)", "earningsGrowth"),
    ("Dividendo (rendimiento)", "dividendYield"), ("Payout", "payoutRatio"),
    ("Recomendación de analistas", "recommendationKey"), ("Cantidad de analistas", "numberOfAnalystOpinions"),
    ("Precio objetivo promedio", "targetMeanPrice"), ("Precio objetivo mínimo", "targetLowPrice"),
    ("Precio objetivo máximo", "targetHighPrice"), ("% de acciones en manos de institucionales", "heldPercentInstitutions"),
    ("Acciones vendidas en corto (% del flotante)", "shortPercentOfFloat"),
]
_PORCENTAJES = {"grossMargins", "operatingMargins", "profitMargins", "returnOnEquity", "revenueGrowth",
                "earningsGrowth", "payoutRatio", "heldPercentInstitutions", "shortPercentOfFloat"}
_GRANDES = {"marketCap", "enterpriseValue", "totalRevenue", "ebitda", "totalCash", "totalDebt", "freeCashflow"}


@servidor.tool()
def datos_empresa(simbolo: str) -> str:
    """Ficha de la empresa: qué hace, tamaño, múltiplos, márgenes, crecimiento, deuda, dividendos,
    recomendación y precio objetivo de los analistas.

    Args:
        simbolo: Símbolo o nombre de la empresa.
    """
    ctx = contexto()
    s = _simbolo(simbolo)
    try:
        info = ctx.resultados.fuente.info(s)
    except ErrorDatos as e:
        return _error(e)
    if not info:
        return f"Yahoo no tiene la ficha de {s}."
    lineas = [f"Ficha de {s} (Yahoo Finance)"]
    for etiqueta, clave in _FICHA:
        v = info.get(clave)
        if v in (None, ""):
            continue
        if clave in _PORCENTAJES:
            texto = _pct(v)
        elif clave == "dividendYield":  # Yahoo ya lo da en porcentaje
            texto = f"{_num(v)}%"
        elif clave in _GRANDES:
            texto = _grande(v)
        elif isinstance(v, (int, float)):
            texto = _num(v)
        else:
            texto = str(v)
        lineas.append(f"- {etiqueta}: {texto}")
    descripcion = info.get("longBusinessSummary")
    if descripcion:
        lineas.append(f"\nQué hace: {descripcion}")
    if info.get("currency") and info.get("financialCurrency") and info["currency"] != info["financialCurrency"]:
        lineas.append("\n⚠️ Cotiza y presenta balances en monedas distintas: los múltiplos pueden estar distorsionados.")
    return "\n".join(lineas)


_FILAS_ESTADOS = {
    "resultados": ["Total Revenue", "Gross Profit", "Operating Income", "EBITDA", "Net Income", "Diluted EPS"],
    "balance": ["Cash And Cash Equivalents", "Total Debt", "Net Debt", "Stockholders Equity", "Total Assets"],
    "flujos": ["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow", "Repurchase Of Capital Stock",
               "Cash Dividends Paid"],
}


@servidor.tool()
def estados_contables(simbolo: str) -> str:
    """Estados contables trimestrales (últimos 5-7 trimestres): ingresos, ganancias, márgenes,
    caja, deuda y flujo de fondos.

    Args:
        simbolo: Símbolo o nombre de la empresa.
    """
    ctx = contexto()
    s = _simbolo(simbolo)
    try:
        estados = ctx.resultados.fuente.estados(s)
    except ErrorDatos as e:
        return _error(e)
    salida = [f"Estados trimestrales de {s} (moneda: {estados.moneda or 'sin dato'})"]
    for nombre, tabla in (("resultados", estados.resultados), ("balance", estados.balance),
                          ("flujos", estados.flujos)):
        if tabla is None or tabla.empty:
            continue
        filas = [f for f in _FILAS_ESTADOS[nombre] if f in tabla.index]
        t = tabla.loc[filas].copy()
        t.columns = [pd.Timestamp(c).strftime("%Y-%m-%d") for c in t.columns]
        t = t.map(lambda v: _num(v) if abs(float(v) if pd.notna(v) else 0) < 100 else _grande(v))
        salida.append(f"\n{nombre.upper()}\n{t.to_csv()}")
    return "\n".join(salida)


@servidor.tool()
def comparar_activos(simbolos: list[str], dias: int = 252) -> str:
    """Compara varios activos en el mismo período: rendimiento (1m, 3m, 6m, 1 año y del año),
    volatilidad anual, caída máxima y correlación entre ellos.

    Args:
        simbolos: Lista de símbolos o nombres (ej. ["GGAL", "BMA", "SPY"]).
        dias: Ruedas del período para volatilidad, caída máxima y correlación (252 ≈ 1 año).
    """
    ctx = contexto()
    cierres: dict[str, pd.Series] = {}
    errores = []
    for texto in simbolos[:15]:
        s = _simbolo(texto)
        try:
            df, moneda, _ = ctx.tecnico.datos(s)
        except ErrorDatos as e:
            errores.append(f"{s}: {e}")
            continue
        cierres[f"{s} ({moneda})"] = df["cierre"]
    if not cierres:
        return "\n".join(["No se pudo obtener ningún activo.", *errores])

    lineas = ["Activo | 1 mes | 3 meses | 6 meses | 1 año | en el año | volatilidad anual | caída máxima"]
    for nombre, c in cierres.items():
        c = c.dropna()
        ultimo = c.iloc[-1]

        def ret(ruedas: int, serie: pd.Series = c, ult: float = ultimo) -> str:
            return _pct(ult / serie.iloc[-ruedas - 1] - 1) if len(serie) > ruedas else "-"

        inicio_anio = c[c.index < pd.Timestamp(date(c.index[-1].year, 1, 1))]
        ytd = _pct(ultimo / inicio_anio.iloc[-1] - 1) if len(inicio_anio) else "-"
        periodo = c.tail(dias + 1)
        vol = periodo.pct_change().std() * math.sqrt(252)
        caida = (periodo / periodo.cummax() - 1).min()
        lineas.append(f"{nombre} | {ret(21)} | {ret(63)} | {ret(126)} | {ret(252)} | {ytd} | {_pct(vol)} | {_pct(caida)}")

    if len(cierres) > 1:
        retornos = pd.DataFrame(cierres).dropna().tail(dias + 1).pct_change().dropna()
        lineas.append(f"\nCorrelación de los retornos diarios (últimas {len(retornos)} ruedas):")
        lineas.append(retornos.corr().round(2).to_csv())
    if errores:
        lineas.append("Sin datos: " + "; ".join(errores))
    lineas.append("Las acciones argentinas en pesos se miden en dólares CCL.")
    return "\n".join(lineas)


@servidor.tool()
def dolar_ccl(dias: int = 30) -> str:
    """Dólar contado con liquidación (CCL) implícito, calculado con GGAL (GGAL.BA × 10 / GGAL).

    Args:
        dias: Cuántas ruedas mostrar.
    """
    try:
        ccl = contexto().tecnico.serie_ccl()
    except ErrorDatos as e:
        return _error(e)
    tabla = ccl.tail(max(1, min(dias, 500))).round(2)
    tabla.index = tabla.index.strftime("%Y-%m-%d")
    variacion = _pct(ccl.iloc[-1] / ccl.iloc[-min(len(ccl), dias + 1)] - 1)
    return (f"CCL implícito (GGAL): {_num(ccl.iloc[-1])} al {tabla.index[-1]} "
            f"({variacion} en {len(tabla)} ruedas)\n" + tabla.rename("ccl").to_csv())


# ---------------------------------------------------------------------------
# Análisis entre mercados, amplitud y gestión del riesgo (Murphy, caps. 16 a 18)
# ---------------------------------------------------------------------------

# Cap. 17: la cadena dólar → materias primas → bonos → acciones.
PANORAMA = [
    ("SPY", "S&P 500 (acciones de EE.UU.)"),
    ("RSP", "S&P 500 con igual peso (la acción \"promedio\")"),
    ("IWM", "Empresas chicas (Russell 2000)"),
    ("QQQ", "Nasdaq 100 (tecnología)"),
    ("TLT", "Bonos del Tesoro largos (suben cuando bajan las tasas)"),
    ("^TNX", "Tasa del bono a 10 años (en %)"),
    ("DX-Y.NYB", "Índice del dólar"),
    ("GC=F", "Oro"),
    ("CL=F", "Petróleo"),
    ("DBC", "Canasta de materias primas"),
]


def _rendimientos(c: pd.Series) -> tuple[str, str, str]:
    c = c.dropna()

    def r(n: int) -> str:
        return _pct(c.iloc[-1] / c.iloc[-n - 1] - 1) if len(c) > n else "-"

    return r(21), r(63), r(252)


@servidor.tool()
def fuerza_relativa(simbolo: str, contra: str = "SPY", dias: int = 252) -> str:
    """Fuerza relativa (cap. 17): el precio del activo dividido por el de otro (por defecto el S&P 500).
    Si la línea sube, el activo le gana al otro. Sirve para elegir los sectores y acciones más fuertes.

    Args:
        simbolo: Activo a medir (símbolo o nombre).
        contra: Contra qué compararlo: SPY (mercado), un ETF de sector (XLK, XLF, XLE...) u otra acción.
        dias: Período a mirar.
    """
    ctx = contexto()
    a, b = _simbolo(simbolo), _simbolo(contra)
    try:
        ca, ma, _ = ctx.tecnico.datos(a)
        cb, mb, _ = ctx.tecnico.datos(b)
    except ErrorDatos as e:
        return _error(e)
    linea = (ca["cierre"] / cb["cierre"]).dropna().tail(max(60, dias) + 1)
    if len(linea) < 60:
        return f"No hay suficiente historia en común entre {a} y {b}."
    m50 = linea.rolling(50).mean()
    r1, r3, r12 = _rendimientos(linea)
    ultimo, previo = linea.iloc[-1], linea.iloc[-21]
    tendencia = ("sube (le gana)" if linea.iloc[-1] > m50.iloc[-1] and m50.iloc[-1] > m50.iloc[-21]
                 else "baja (le pierde)" if linea.iloc[-1] < m50.iloc[-1] and m50.iloc[-1] < m50.iloc[-21]
                 else "sin dirección clara")
    maximo = linea.max()
    lineas = [
        f"Fuerza relativa de {a} ({ma}) contra {b} ({mb}): la línea {a}/{b} {tendencia}.",
        f"Variación de la línea: 1 mes {r1}, 3 meses {r3}, 1 año {r12} (positivo = {a} rindió más que {b}).",
        f"La línea está {_pct(ultimo / maximo - 1)} respecto de su máximo del período."
        + (" Está en máximos: el activo lidera." if ultimo >= maximo * 0.98 else ""),
        "Cómo se usa (Murphy, cap. 17): de arriba hacia abajo — primero el mercado, después los sectores con la "
        "línea subiendo, y dentro de ellos las acciones que le ganan a su sector. Una línea de fuerza relativa que "
        "deja de subir es una alerta aunque el precio siga subiendo.",
    ]
    if ultimo < previo and ca["cierre"].iloc[-1] > ca["cierre"].iloc[-21]:
        lineas.append(f"Ojo: {a} subió en el último mes pero menos que {b} (la línea bajó).")
    return "\n".join(lineas)


@servidor.tool()
def panorama_mercado() -> str:
    """Panorama entre mercados y amplitud (caps. 17 y 18): acciones, bonos, tasas, dólar, oro, petróleo y
    materias primas, más cuántas acciones de la watchlist acompañan la tendencia."""
    ctx = contexto()
    filas = ["Activo | 1 mes | 3 meses | 1 año | tendencia (vs. media de 200)"]
    cierres: dict[str, pd.Series] = {}
    for s, nombre in PANORAMA:
        try:
            df, _, _ = ctx.tecnico.datos(s)
        except ErrorDatos:
            filas.append(f"{nombre} ({s}) | sin datos")
            continue
        c = df["cierre"]
        cierres[s] = c
        m200 = c.rolling(200).mean().iloc[-1]
        tend = "alcista" if c.iloc[-1] > m200 else "bajista"
        filas.append(f"{nombre} ({s}) | " + " | ".join(_rendimientos(c)) + f" | {tend}")

    lectura = ["", "Relaciones clásicas (Murphy, cap. 17) para leer la tabla:",
               "• Dólar y materias primas suelen ir al revés (el oro es el más sensible).",
               "• Materias primas y bonos van al revés: materias primas en alza = presión inflacionaria = tasas "
               "más altas.",
               "• Bonos y acciones suelen ir juntos, y los bonos se adelantan: si los bonos hacen techo (las tasas "
               "suben), es una alerta para las acciones. Excepción: en una deflación, bonos suben y acciones bajan.",
               "• Confirmación (cap. 18): una suba es más sana si la acompañan el S&P con igual peso (RSP) y las "
               "empresas chicas (IWM), no solo la tecnología."]
    if "SPY" in cierres:
        for s, txt, plural in (("RSP", "el S&P con igual peso", False), ("IWM", "las empresas chicas", True)):
            if s in cierres:
                rel = (cierres[s] / cierres["SPY"]).dropna()
                if len(rel) > 63:
                    cambio = rel.iloc[-1] / rel.iloc[-64] - 1
                    verbo = ("le ganó", "le perdió") if not plural else ("le ganaron", "le perdieron")
                    lectura.append(f"  → En 3 meses {txt} {verbo[0] if cambio > 0 else verbo[1]} al SPY "
                                   f"({_pct(cambio)}): la suba {'se amplía' if cambio > 0 else 'se concentra en pocas'}"
                                   f"{'' if cambio > 0 else ' acciones grandes'}.")

    # Amplitud (cap. 18) aproximada con la watchlist: % sobre sus medias y máximos vs. mínimos de 52 semanas.
    sobre50 = sobre200 = maximos = minimos = total = 0
    for s in ctx.cfg.watchlist_completa:
        if s.startswith("^"):
            continue
        try:
            df, _, _ = ctx.tecnico.datos(s)
        except ErrorDatos:
            continue
        c = df["cierre"]
        if len(c) < 252:
            continue
        total += 1
        sobre50 += c.iloc[-1] > c.rolling(50).mean().iloc[-1]
        sobre200 += c.iloc[-1] > c.rolling(200).mean().iloc[-1]
        maximos += df["maximo"].iloc[-5:].max() >= df["maximo"].iloc[-252:].max()
        minimos += df["minimo"].iloc[-5:].min() <= df["minimo"].iloc[-252:].min()
    if total:
        lectura += ["", f"Amplitud de tu watchlist ({total} acciones, cap. 18):",
                    f"• {sobre50 / total:.0%} está arriba de su media de 50 ruedas y {sobre200 / total:.0%} arriba "
                    "de la de 200. Más de 70% suele ser mercado sobrecomprado; menos de 30%, sobrevendido.",
                    f"• {maximos} marcaron un máximo de 52 semanas en la última semana y {minimos} un mínimo. Si el "
                    "índice sube pero cada vez menos acciones hacen máximos, la suba se debilita."]
    return "\n".join(filas + lectura)


@servidor.tool()
def plan_de_riesgo(simbolo: str, capital: float, riesgo_pct: float = 1.0, entrada: float | None = None) -> str:
    """Gestión del riesgo (cap. 16): dónde iría el stop según el gráfico, cuántas acciones comprar para no
    arriesgar más que un % del capital, y si la relación ganancia/riesgo llega al 3 a 1 que pide el libro.
    Es un ejercicio educativo, no una recomendación.

    Args:
        simbolo: Símbolo o nombre de la empresa.
        capital: Capital total de la cuenta (en la moneda del análisis).
        riesgo_pct: Cuánto del capital se acepta perder si sale mal (el libro dice no más de 5%; muchos usan 1-2%).
        entrada: Precio de entrada. Vacío = el precio actual.
    """
    ctx = contexto()
    try:
        a = ctx.tecnico.analizar(_simbolo(simbolo))
    except ErrorDatos as e:
        return _error(e)
    l = a.lectura
    if l is None:
        return "No hay historia suficiente para leer el gráfico."
    precio = entrada or l.precio
    if not l.soportes:
        return (f"{a.simbolo} está en mínimos del último año: no hay un soporte debajo para ubicar el stop. "
                "Según el libro, sin un nivel claro que anule la idea no se puede medir el riesgo.")
    soporte = l.soportes[0].precio
    stop = soporte - 0.5 * float(l.datos["atr14"].iloc[-1])  # un poco debajo del soporte, fuera del "ruido"
    riesgo_accion = precio - stop
    if riesgo_accion <= 0:
        return f"El precio de entrada ({_num(precio)}) ya está debajo del soporte: el gráfico no avala la compra."
    perdida_max = capital * riesgo_pct / 100
    por_riesgo = int(perdida_max // riesgo_accion)
    por_tope = int(capital * 0.15 // precio)  # cap. 16: no más de 10-15% del capital en un solo activo
    cantidad = min(por_riesgo, por_tope)
    metas = [r.precio for r in l.resistencias if r.precio > precio]
    metas += [f.objetivo for f in l.figuras if f.sesgo > 0 and f.objetivo and f.objetivo > precio]
    meta = min(metas) if metas else None
    lineas = [
        f"Plan de riesgo para {a.simbolo} ({a.moneda}) — ejercicio educativo, no es una recomendación.",
        f"• Entrada: {_num(precio)}. Stop: {_num(stop)} (medio día de volatilidad debajo del soporte de "
        f"{_num(soporte)}; el libro pide ponerlo detrás de un soporte válido y evitar los números redondos).",
        f"• Riesgo por acción: {_num(riesgo_accion)} ({riesgo_accion / precio:.1%}). Con un capital de "
        f"{_num(capital, 0)} y {riesgo_pct:g}% de riesgo, la pérdida máxima aceptada es {_num(perdida_max)}: "
        f"alcanzaría para {por_riesgo} acciones.",
    ]
    if por_tope < por_riesgo:
        lineas.append(f"• Pero eso sería {por_riesgo * precio / capital:.0%} del capital en un solo activo, y el libro "
                      f"sugiere no pasar de 10-15%: tope de {por_tope} acciones.")
    lineas.append(f"• Cantidad sugerida por las reglas: {cantidad} acciones ({_num(cantidad * precio)}, "
                  f"{cantidad * precio / capital:.0%} del capital); si toca el stop se pierden "
                  f"{_num(cantidad * riesgo_accion)}.")
    if meta:
        rr = (meta - precio) / riesgo_accion
        lineas.append(f"• Primera meta: {_num(meta)} ({meta / precio - 1:+.1%}). Relación ganancia/riesgo: "
                      f"{rr:.1f} a 1 " + ("— cumple el mínimo de 3 a 1 del libro." if rr >= 3 else
                                           "— no llega al 3 a 1 que pide el libro: un trader esperaría una "
                                           "entrada más cerca del soporte."))
    else:
        lineas.append("• No hay resistencias arriba (máximos del año): la meta queda abierta; el libro sugiere "
                      "ir subiendo el stop a medida que el precio avanza.")
    lineas.append("Regla del libro: primero se ubica el stop según el gráfico y después se calcula la cantidad; "
                  "nunca al revés. Después de una racha ganadora es cuando menos conviene agrandar posiciones.")
    return "\n".join(lineas) + pie_de_mensaje()


def main() -> None:
    """Punto de entrada: ``monitor-claude``."""
    # El protocolo usa stdout: cualquier print accidental lo rompería. Los logs van a stderr y al archivo.
    sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None
    servidor.run()


if __name__ == "__main__":
    main()
