"""Bot de Telegram: comandos para manejar alertas y revisión periódica de precios.

Un solo proceso hace las dos cosas: atiende tus comandos y, con el JobQueue de
python-telegram-bot (que usa APScheduler por dentro), revisa los precios cada
``intervalo_minutos``. Así no hace falta coordinar dos programas.

Seguridad: los comandos solo responden a TELEGRAM_CHAT_ID. Cualquier otra
persona que encuentre el bot no recibe respuesta (y queda registrado en el log).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram import BotCommand, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from monitor_mercado.alertas.modelos import Moneda
from monitor_mercado.alertas.parser import AYUDA_FORMATO, ErrorFormato, parsear_alerta
from monitor_mercado.alertas.servicio import ServicioAlertas
from monitor_mercado.aviso_legal import pie_de_mensaje
from monitor_mercado.datos.modelos import ErrorDatos, SimboloSinDatos
from monitor_mercado.explicacion import explicacion_completa, texto_glosario
from monitor_mercado.noticias.reporte import linea_senal_final, reporte_noticias
from monitor_mercado.backtest.reporte import (
    explicacion_backtest, grafico_backtest, reporte_backtest, resumen_backtests,
)
from monitor_mercado.cartera.reporte import texto_cartera, texto_resumen_dia
from monitor_mercado.notificaciones import formato
from monitor_mercado.resultados.reporte import (
    explicacion_resultados, mensaje_previo, reporte_resultados, texto_calendario,
)
from monitor_mercado.tecnico.grafico_lectura import grafico_lectura
from monitor_mercado.tecnico.reporte_lectura import texto_lectura
from monitor_mercado.tecnico.reporte import reporte_completo, reporte_resumen

if TYPE_CHECKING:
    from monitor_mercado.aplicacion import Contexto

log = logging.getLogger(__name__)

AYUDA = (
    "Comandos:\n"
    "/alerta SIMBOLO compra|venta llega|sube|baja|var+|var- VALOR [ars] [repetir] [nota TEXTO]\n"
    "/alertas - alertas activas (/alertas todas incluye las cumplidas)\n"
    "/borrar ID - borra una alerta\n"
    "/precio SIMBOLO [ars] - precio actual\n"
    "/revisar - revisa las alertas ahora (ignora el horario de mercado)\n"
    "/grafico SIMBOLO - lectura del gráfico como un trader: tendencia, soportes, resistencias, figuras y escenarios\n"
    "/analisis SIMBOLO - lo anterior + indicadores, noticias y explicación para aprender\n"
    "/validar_grafico - ¿la lectura del gráfico acertó en el pasado?\n"
    "/resumen - tendencia de toda la watchlist (/resumen completa para los 89)\n"
    "/noticias SIMBOLO - noticias recientes con su sentimiento\n"
    "/glosario [TERMINO] - definiciones (ej. /glosario rsi)\n"
    "/resultados SIMBOLO - último resultado trimestral vs. lo esperado\n"
    "/calendario - próximas presentaciones de las empresas que seguís\n"
    "/seguir SIMBOLO · /dejar SIMBOLO · /seguidas - empresas con aviso de resultados\n"
    "/backtest SIMBOLO - ¿la señal le gana a comprar y mantener? (10 años, con costos)\n"
    "/backtest_resumen [completa] - backtest de toda la watchlist\n"
    "/cartera - ganancia o pérdida de cada posición de tu cartera\n"
    "/resumen_dia - el resumen de cierre (llega solo cada día hábil a las 17:20 hora Argentina)\n"
    "/chatid - muestra el ID de este chat\n\n" + AYUDA_FORMATO
)

COMANDOS_MENU = [
    BotCommand("grafico", "Lectura del gráfico como un trader"),
    BotCommand("cartera", "Tu cartera: ganancias y pérdidas"),
    BotCommand("resumen_dia", "Resumen de cierre de tu cartera"),
    BotCommand("alerta", "Crear una alerta"),
    BotCommand("alertas", "Ver alertas"),
    BotCommand("borrar", "Borrar una alerta"),
    BotCommand("precio", "Precio actual"),
    BotCommand("revisar", "Revisar ahora"),
    BotCommand("analisis", "Análisis técnico de un activo"),
    BotCommand("resumen", "Tendencia de la watchlist"),
    BotCommand("noticias", "Noticias con sentimiento"),
    BotCommand("glosario", "Definiciones para aprender"),
    BotCommand("resultados", "Resultados de una empresa"),
    BotCommand("calendario", "Próximas presentaciones"),
    BotCommand("seguir", "Seguir resultados de una empresa"),
    BotCommand("seguidas", "Empresas que seguís"),
    BotCommand("backtest", "Probar la señal contra el pasado"),
    BotCommand("backtest_resumen", "Backtest de la watchlist"),
    BotCommand("ayuda", "Ayuda"),
]


def _servicio(context: ContextTypes.DEFAULT_TYPE) -> ServicioAlertas:
    return context.application.bot_data["servicio"]


LIMITE_TELEGRAM = 4000  # Telegram rechaza mensajes de más de 4096 caracteres


def partir_mensaje(texto: str, limite: int = LIMITE_TELEGRAM) -> list[str]:
    """Divide un texto largo en partes, cortando entre líneas."""
    partes, actual = [], ""
    for linea in texto.split("\n"):
        while len(linea) > limite:  # línea gigante: se corta a la fuerza
            partes.append(linea[:limite])
            linea = linea[limite:]
        if len(actual) + len(linea) + 1 > limite:
            partes.append(actual)
            actual = linea
        else:
            actual = f"{actual}\n{linea}" if actual else linea
    if actual:
        partes.append(actual)
    return partes


async def _responder(update: Update, texto: str) -> None:
    if update.effective_message:
        for parte in partir_mensaje(texto):
            await update.effective_message.reply_text(parte)


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start y /ayuda."""
    await _responder(update, AYUDA + pie_de_mensaje())


async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/chatid: muestra el ID del chat (para completar el .env)."""
    chat_id = update.effective_chat.id if update.effective_chat else "?"
    await _responder(
        update, f"Tu chat ID es: {chat_id}\nCopialo en el .env como TELEGRAM_CHAT_ID={chat_id}"
    )


async def cmd_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/alerta ...: crea una alerta."""
    try:
        solicitud = parsear_alerta(context.args or [])
        resultado = await asyncio.to_thread(_servicio(context).crear, solicitud)
    except ErrorFormato as e:
        await _responder(update, str(e))
        return
    except (ValueError, ErrorDatos) as e:
        await _responder(update, _error(context, (context.args or [""])[0], e, "No se pudo crear la alerta"))
        return
    await _responder(update, formato.mensaje_creada(resultado))


async def cmd_alertas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/alertas [todas]: lista las alertas."""
    todas = bool(context.args) and context.args[0].lower() == "todas"
    alertas = _servicio(context).repo.listar(solo_activas=not todas)
    await _responder(update, formato.mensaje_listado(alertas))


async def cmd_borrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/borrar ID: elimina una alerta."""
    try:
        id_alerta = int((context.args or [""])[0].lstrip("#"))
    except ValueError:
        await _responder(update, "Uso: /borrar ID (el número que aparece en /alertas)")
        return
    borrada = _servicio(context).repo.borrar(id_alerta)
    await _responder(update, f"Alerta #{id_alerta} borrada." if borrada else f"No existe la alerta #{id_alerta}.")


async def cmd_precio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/precio SIMBOLO [ars]: precio actual."""
    args = context.args or []
    if not args:
        await _responder(update, "Uso: /precio SIMBOLO [ars]")
        return
    moneda = Moneda.ARS if len(args) > 1 and args[1].lower() in ("ars", "pesos") else Moneda.USD
    try:
        p = await asyncio.to_thread(_servicio(context).precio_en, args[0].upper(), moneda)
    except (ValueError, ErrorDatos) as e:
        await _responder(update, _error(context, args[0], e, "No se pudo obtener el precio"))
        return
    await _responder(update, formato.detalle_precio(p) + pie_de_mensaje())


async def cmd_revisar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/revisar: revisión manual inmediata."""
    disparos = await _revisar_y_avisar(context, forzar=True)
    await _responder(update, formato.mensaje_revision(disparos))


def _ctx(context: ContextTypes.DEFAULT_TYPE) -> Contexto:
    return context.application.bot_data["ctx"]


def con_simbolo(funcion):
    """Antes de ejecutar el comando, traduce el primer argumento a un símbolo ("nvidia" -> NVDA)."""

    async def envoltura(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ctx = context.application.bot_data.get("ctx")
        if context.args and ctx is not None:
            context.args[0] = ctx.buscador().resolver(context.args[0])
        await funcion(update, context)

    envoltura.__name__ = funcion.__name__
    return envoltura


def _error(context: ContextTypes.DEFAULT_TYPE, texto: str, e: Exception, prefijo: str) -> str:
    """Mensaje de error; si el símbolo no existe, sugiere los parecidos."""
    ctx = context.application.bot_data.get("ctx")
    if isinstance(e, SimboloSinDatos) and ctx is not None:
        return ctx.buscador().mensaje_no_encontrado(texto)
    return f"{prefijo}: {e}"


async def cmd_analisis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/analisis SIMBOLO: técnico + noticias + señal final + gráfico + explicación."""
    args = context.args or []
    if not args:
        await _responder(update, "Uso: /analisis SIMBOLO   (ej. /analisis GGAL)")
        return
    ctx = _ctx(context)
    await _responder(update, f"Analizando {args[0].upper()} (gráfico, indicadores y noticias)...")
    try:
        r = await asyncio.to_thread(ctx.analisis_completo, args[0])
    except ErrorDatos as e:
        await _responder(update, _error(context, args[0], e, "No se pudo analizar"))
        return
    # 1. Lo principal: la lectura del gráfico, como un trader, con el gráfico anotado.
    await _enviar_lectura(update, ctx, r.tecnico)
    # 2. El detalle de los indicadores y la señal final.
    await _responder(update, "📊 Indicadores\n" + reporte_completo(r.tecnico, con_pie=False) + "\n\n"
                     + linea_senal_final(r.final) + pie_de_mensaje())
    if r.noticias is not None:
        await _responder(update, reporte_noticias(r.noticias, maximo=5, con_pie=False))
    await _responder(update, explicacion_completa(r.tecnico, r.noticias, r.final))


async def _enviar_lectura(update: Update, ctx: Contexto, analisis) -> None:
    """Manda la lectura del gráfico y el gráfico de velas anotado."""
    if analisis.lectura is None:
        await _responder(update, "No se pudo leer el gráfico de este activo (historia insuficiente).")
        return
    await _responder(update, texto_lectura(analisis.simbolo, analisis.lectura, analisis.moneda))
    ruta = await asyncio.to_thread(grafico_lectura, analisis.simbolo, analisis.lectura, analisis.moneda,
                                   ctx.cfg.rutas.ruta_graficos())
    if update.effective_message:
        with open(ruta, "rb") as imagen:
            await update.effective_message.reply_photo(photo=imagen, caption=f"{analisis.simbolo} – gráfico anotado")


async def cmd_grafico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/grafico SIMBOLO: solo la lectura del gráfico (más rápido que /analisis)."""
    args = context.args or []
    if not args:
        await _responder(update, "Uso: /grafico SIMBOLO   (ej. /grafico GGAL)")
        return
    ctx = _ctx(context)
    await _responder(update, f"Leyendo el gráfico de {args[0].upper()}...")
    try:
        analisis = await asyncio.to_thread(ctx.tecnico.analizar, args[0])
    except ErrorDatos as e:
        await _responder(update, _error(context, args[0], e, "No se pudo analizar"))
        return
    await _enviar_lectura(update, ctx, analisis)


async def cmd_noticias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/noticias SIMBOLO: titulares recientes con su sentimiento."""
    args = context.args or []
    if not args:
        await _responder(update, "Uso: /noticias SIMBOLO   (ej. /noticias YPF)")
        return
    ctx = _ctx(context)
    if ctx.noticias is None:
        await _responder(update, "Las noticias están desactivadas en config.yaml.")
        return
    await _responder(update, f"Buscando noticias de {args[0].upper()}...")
    analisis = await asyncio.to_thread(ctx.noticias.analizar, args[0])
    await _responder(update, reporte_noticias(analisis))


async def cmd_resultados(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/resultados SIMBOLO: análisis de la última presentación de resultados."""
    args = context.args or []
    if not args:
        await _responder(update, "Uso: /resultados SIMBOLO   (ej. /resultados AAPL)")
        return
    ctx = _ctx(context)
    await _responder(update, f"Analizando los resultados de {args[0].upper()}...")
    try:
        r = await asyncio.to_thread(ctx.resultados.analizar, args[0])
    except ErrorDatos as e:
        await _responder(update, _error(context, args[0], e, "No se pudo analizar"))
        return
    await _responder(update, reporte_resultados(r))
    await _responder(update, explicacion_resultados(r))


async def cmd_calendario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/calendario: próximas presentaciones de las empresas seguidas."""
    ctx = _ctx(context)
    seguidas = ctx.resultados.repo.seguidas()
    proximas = await asyncio.to_thread(ctx.resultados.proximas, seguidas)
    await _responder(update, texto_calendario(proximas, seguidas))


async def cmd_seguir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/seguir SIMBOLO: avisar cuando presente resultados."""
    if not context.args:
        await _responder(update, "Uso: /seguir SIMBOLO")
        return
    s = context.args[0].upper()
    ctx = _ctx(context)
    try:  # se verifica que el símbolo exista antes de agregarlo
        await asyncio.to_thread(ctx.proveedor.cotizacion, s)
    except ErrorDatos as e:
        await _responder(update, _error(context, s, e, "No se pudo verificar el símbolo"))
        return
    nuevo = ctx.resultados.repo.seguir(s)
    await _responder(update, f"Ahora seguís {s}: te aviso antes y después de que presente resultados."
                     if nuevo else f"Ya seguías {s}.")


async def cmd_dejar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/dejar SIMBOLO: dejar de seguir sus resultados."""
    if not context.args:
        await _responder(update, "Uso: /dejar SIMBOLO")
        return
    s = context.args[0].upper()
    ok = _ctx(context).resultados.repo.dejar(s)
    await _responder(update, f"Dejaste de seguir {s}." if ok else f"No seguías {s}.")


async def cmd_seguidas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/seguidas: empresas cuyos resultados seguís."""
    lista = _ctx(context).resultados.repo.seguidas()
    await _responder(update, "Seguís: " + ", ".join(lista) if lista else "No seguís ninguna empresa.")


async def cmd_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/backtest SIMBOLO: prueba la señal contra el pasado."""
    args = context.args or []
    if not args:
        await _responder(update, "Uso: /backtest SIMBOLO   (ej. /backtest SPY)")
        return
    ctx = _ctx(context)
    await _responder(update, f"Corriendo el backtest de {args[0].upper()} (10 años, con costos)...")
    try:
        r = await asyncio.to_thread(ctx.backtest.correr, args[0])
        ruta = await asyncio.to_thread(grafico_backtest, r, ctx.cfg.rutas.ruta_graficos())
    except ErrorDatos as e:
        await _responder(update, _error(context, args[0], e, "No se pudo hacer el backtest"))
        return
    await _responder(update, reporte_backtest(r))
    if update.effective_message:
        with open(ruta, "rb") as imagen:
            await update.effective_message.reply_photo(photo=imagen, caption=f"{r.simbolo} – señal vs. comprar y mantener")
    await _responder(update, explicacion_backtest(r))


async def cmd_validar_grafico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/validar_grafico: ¿la lectura del gráfico acierta? (sobre la watchlist activa)."""
    from monitor_mercado.backtest.validar_lectura import texto_validacion, validar

    ctx = _ctx(context)
    await _responder(update, "Leyendo miles de gráficos del pasado, puede tardar un minuto...")
    v = await asyncio.to_thread(validar, ctx.tecnico, ctx.cfg.watchlist_activa)
    await _responder(update, texto_validacion(v))


async def cmd_backtest_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/backtest_resumen [completa]: backtest de toda la watchlist."""
    ctx = _ctx(context)
    completa = bool(context.args) and context.args[0].lower() == "completa"
    simbolos = ctx.cfg.watchlist_completa if completa else ctx.cfg.watchlist_activa
    await _responder(update, f"Corriendo el backtest de {len(simbolos)} activos, puede tardar...")
    resultados, errores = await asyncio.to_thread(ctx.backtest.correr_varios, simbolos)
    await _responder(update, resumen_backtests(resultados, errores))


async def cmd_cartera(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/cartera: estado de tu cartera."""
    ctx = _ctx(context)
    await _responder(update, "Valuando tu cartera...")
    estado = await asyncio.to_thread(ctx.cartera.estado)
    await _responder(update, texto_cartera(estado))


async def cmd_resumen_dia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/resumen_dia: el resumen de cierre, a pedido."""
    ctx = _ctx(context)
    await _responder(update, "Armando el resumen (precios y noticias de tus empresas)...")
    resumen = await asyncio.to_thread(ctx.cartera.resumen_dia)
    await _responder(update, texto_resumen_dia(resumen, ctx.cfg.cartera.umbral_movimiento))


def hubo_rueda_hoy(ctx: Contexto, hoy) -> bool:
    """True si hoy operó Wall Street (descarta fines de semana y feriados)."""
    if hoy.weekday() >= 5:
        return False
    try:
        spy = ctx.tecnico.almacen.obtener("SPY", forzar=True)
    except ErrorDatos:
        return True  # ante la duda, se manda igual
    return spy.index[-1].date() == hoy


async def tarea_resumen_dia(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tarea diaria al cierre: manda el resumen de la cartera."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ctx = _ctx(context)
    hoy = datetime.now(ZoneInfo("America/New_York")).date()
    if not await asyncio.to_thread(hubo_rueda_hoy, ctx, hoy):
        log.info("Hoy no hubo rueda: no se manda el resumen.")
        return
    try:
        resumen = await asyncio.to_thread(ctx.cartera.resumen_dia)
    except Exception:  # noqa: BLE001 - no debe tirar el bot
        log.exception("Error armando el resumen diario")
        return
    for parte in partir_mensaje(texto_resumen_dia(resumen, ctx.cfg.cartera.umbral_movimiento)):
        await _enviar(context, context.application.bot_data["chat_id"], parte)


async def tarea_resultados(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tarea periódica: avisos de próximas presentaciones y análisis de las recién publicadas."""
    ctx = _ctx(context)
    chat_id: int = context.application.bot_data["chat_id"]
    try:
        novedades = await asyncio.to_thread(ctx.resultados.revisar_calendario)
    except Exception:  # noqa: BLE001 - no debe tirar el bot
        log.exception("Error revisando el calendario de resultados")
        return
    for tipo, dato in novedades:
        if tipo == "previo":
            await _enviar(context, chat_id, mensaje_previo(dato))
        else:
            for texto in (reporte_resultados(dato), explicacion_resultados(dato)):
                for parte in partir_mensaje(texto):
                    await _enviar(context, chat_id, parte)


async def cmd_glosario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/glosario [TERMINO]: definiciones para aprender."""
    await _responder(update, texto_glosario(" ".join(context.args or []) or None))


async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/resumen: señal técnica de toda la watchlist activa."""
    ctx = _ctx(context)
    completa = bool(context.args) and context.args[0].lower() == "completa"
    simbolos = ctx.cfg.watchlist_completa if completa else ctx.cfg.watchlist_activa
    await _responder(update, f"Analizando {len(simbolos)} activos, puede tardar un poco...")
    analisis, errores = await asyncio.to_thread(ctx.tecnico.resumen, simbolos)
    await _responder(update, reporte_resumen(analisis, errores))


async def ignorar_desconocido(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mensajes de chats no autorizados: no se responde, solo se registra."""
    chat = update.effective_chat
    log.warning("Mensaje ignorado de chat no autorizado: %s", chat.id if chat else "?")


async def _enviar(context: ContextTypes.DEFAULT_TYPE, chat_id: int, texto: str) -> None:
    for intento in range(1, 4):
        try:
            await context.bot.send_message(chat_id=chat_id, text=texto)
            return
        except TelegramError as e:
            log.warning("Fallo al enviar a Telegram (intento %d/3): %s", intento, e)
            await asyncio.sleep(5 * intento)
    log.error("No se pudo enviar el aviso luego de 3 intentos:\n%s", texto)


async def _revisar_y_avisar(context: ContextTypes.DEFAULT_TYPE, forzar: bool = False) -> int:
    chat_id: int = context.application.bot_data["chat_id"]
    try:
        disparos = await asyncio.to_thread(_servicio(context).revisar, None, forzar)
    except Exception:  # noqa: BLE001 - una revisión fallida no debe tirar el bot
        log.exception("Error inesperado en la revisión de alertas")
        return 0
    for d in disparos:
        await _enviar(context, chat_id, formato.mensaje_disparo(d))
    return len(disparos)


async def tarea_periodica(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tarea que corre cada ``intervalo_minutos``."""
    await _revisar_y_avisar(context)


async def manejar_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra errores no manejados de los comandos."""
    log.error("Error en el bot", exc_info=context.error)


async def _al_iniciar(app: Application) -> None:
    await app.bot.set_my_commands(COMANDOS_MENU)
    log.info("Bot iniciado como @%s", app.bot.username)


def construir_bot(ctx: Contexto) -> Application:
    """Arma la aplicación del bot con sus comandos y la revisión periódica.

    Si falta TELEGRAM_CHAT_ID, el bot arranca en "modo configuración": solo
    responde /chatid y /start, para que puedas averiguar tu ID.
    """
    cfg, secretos = ctx.cfg, ctx.secretos
    if secretos.telegram_bot_token is None:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN en el archivo .env (ver README).")

    app = ApplicationBuilder().token(secretos.telegram_bot_token.get_secret_value()).post_init(_al_iniciar).build()
    app.bot_data["servicio"] = ctx.servicio
    app.bot_data["ctx"] = ctx
    app.add_handler(CommandHandler("chatid", cmd_chatid))
    app.add_error_handler(manejar_error)

    if secretos.telegram_chat_id is None:
        log.warning("Falta TELEGRAM_CHAT_ID: modo configuración. Mandale /chatid al bot.")
        app.add_handler(CommandHandler(["start", "ayuda"], cmd_chatid))
        return app

    app.bot_data["chat_id"] = secretos.telegram_chat_id
    duenio = filters.Chat(chat_id=secretos.telegram_chat_id)
    for nombres, funcion in [
        (["start", "ayuda"], cmd_ayuda),
        (["alerta"], con_simbolo(cmd_alerta)),
        (["alertas"], cmd_alertas),
        (["borrar"], cmd_borrar),
        (["precio"], con_simbolo(cmd_precio)),
        (["revisar"], cmd_revisar),
        (["analisis", "analizar"], con_simbolo(cmd_analisis)),
        (["grafico"], con_simbolo(cmd_grafico)),
        (["validar_grafico"], cmd_validar_grafico),
        (["resumen"], cmd_resumen),
        (["noticias"], con_simbolo(cmd_noticias)),
        (["glosario"], cmd_glosario),
        (["resultados"], con_simbolo(cmd_resultados)),
        (["calendario"], cmd_calendario),
        (["seguir"], con_simbolo(cmd_seguir)),
        (["dejar"], con_simbolo(cmd_dejar)),
        (["seguidas"], cmd_seguidas),
        (["backtest"], con_simbolo(cmd_backtest)),
        (["backtest_resumen"], cmd_backtest_resumen),
        (["cartera"], cmd_cartera),
        (["resumen_dia"], cmd_resumen_dia),
    ]:
        app.add_handler(CommandHandler(nombres, funcion, filters=duenio))
    app.add_handler(MessageHandler(~duenio, ignorar_desconocido))

    intervalo = cfg.alertas.intervalo_minutos * 60
    if app.job_queue is None:
        raise RuntimeError("Falta el extra job-queue: pip install 'python-telegram-bot[job-queue]'")
    app.job_queue.run_repeating(tarea_periodica, interval=intervalo, first=15, name="revisar_alertas")
    if ctx.resultados is not None:
        app.job_queue.run_repeating(tarea_resultados, interval=cfg.resultados.revision_horas * 3600, first=60,
                                    name="revisar_resultados")
        log.info("Calendario de resultados revisado cada %s horas.", cfg.resultados.revision_horas)
    if ctx.cartera is not None and cfg.cartera.resumen_diario:
        from datetime import time as hora
        from zoneinfo import ZoneInfo

        h, m = (int(x) for x in cfg.cartera.hora_resumen.split(":"))
        # Corre todos los días; la tarea misma descarta fines de semana y feriados.
        app.job_queue.run_daily(tarea_resumen_dia, time=hora(h, m, tzinfo=ZoneInfo("America/New_York")),
                                name="resumen_cartera")
        log.info("Resumen de cartera programado a las %s (hora de Nueva York).", cfg.cartera.hora_resumen)
    log.info("Revisión de alertas programada cada %d minutos.", cfg.alertas.intervalo_minutos)
    return app
