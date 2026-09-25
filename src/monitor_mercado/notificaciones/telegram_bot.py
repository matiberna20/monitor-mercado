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
from monitor_mercado.configuracion import Configuracion, Secretos
from monitor_mercado.datos.modelos import ErrorDatos
from monitor_mercado.notificaciones import formato

log = logging.getLogger(__name__)

AYUDA = (
    "Comandos:\n"
    "/alerta SIMBOLO compra|venta sube|baja|var+|var- VALOR [ars] [repetir]\n"
    "/alertas - alertas activas (/alertas todas incluye las cumplidas)\n"
    "/borrar ID - borra una alerta\n"
    "/precio SIMBOLO [ars] - precio actual\n"
    "/revisar - revisa las alertas ahora (ignora el horario de mercado)\n"
    "/chatid - muestra el ID de este chat\n\n" + AYUDA_FORMATO
)

COMANDOS_MENU = [
    BotCommand("alerta", "Crear una alerta"),
    BotCommand("alertas", "Ver alertas"),
    BotCommand("borrar", "Borrar una alerta"),
    BotCommand("precio", "Precio actual"),
    BotCommand("revisar", "Revisar ahora"),
    BotCommand("ayuda", "Ayuda"),
]


def _servicio(context: ContextTypes.DEFAULT_TYPE) -> ServicioAlertas:
    return context.application.bot_data["servicio"]


async def _responder(update: Update, texto: str) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(texto)


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
        await _responder(update, f"No se pudo crear la alerta: {e}")
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
        await _responder(update, f"No se pudo obtener el precio: {e}")
        return
    await _responder(update, formato.detalle_precio(p) + pie_de_mensaje())


async def cmd_revisar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/revisar: revisión manual inmediata."""
    disparos = await _revisar_y_avisar(context, forzar=True)
    await _responder(update, f"Revisión terminada: {disparos} alerta(s) disparada(s).")


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


def construir_bot(cfg: Configuracion, secretos: Secretos, servicio: ServicioAlertas) -> Application:
    """Arma la aplicación del bot con sus comandos y la revisión periódica.

    Si falta TELEGRAM_CHAT_ID, el bot arranca en "modo configuración": solo
    responde /chatid y /start, para que puedas averiguar tu ID.
    """
    if secretos.telegram_bot_token is None:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN en el archivo .env (ver README).")

    app = ApplicationBuilder().token(secretos.telegram_bot_token.get_secret_value()).post_init(_al_iniciar).build()
    app.bot_data["servicio"] = servicio
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
        (["alerta"], cmd_alerta),
        (["alertas"], cmd_alertas),
        (["borrar"], cmd_borrar),
        (["precio"], cmd_precio),
        (["revisar"], cmd_revisar),
    ]:
        app.add_handler(CommandHandler(nombres, funcion, filters=duenio))
    app.add_handler(MessageHandler(~duenio, ignorar_desconocido))

    intervalo = cfg.alertas.intervalo_minutos * 60
    if app.job_queue is None:
        raise RuntimeError("Falta el extra job-queue: pip install 'python-telegram-bot[job-queue]'")
    app.job_queue.run_repeating(tarea_periodica, interval=intervalo, first=15, name="revisar_alertas")
    log.info("Revisión de alertas programada cada %d minutos.", cfg.alertas.intervalo_minutos)
    return app
