"""Tests de los comandos del bot con objetos falsos (sin conectarse a Telegram)."""

import asyncio
from types import SimpleNamespace

from monitor_mercado.notificaciones import telegram_bot as bot

CHAT = 6910675574


class MensajeFalso:
    def __init__(self) -> None:
        self.respuestas: list[str] = []

    async def reply_text(self, texto: str) -> None:
        self.respuestas.append(texto)


class BotFalso:
    def __init__(self) -> None:
        self.enviados: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.enviados.append((chat_id, text))


def _llamar(comando, servicio, args):
    mensaje = MensajeFalso()
    update = SimpleNamespace(effective_message=mensaje, effective_chat=SimpleNamespace(id=CHAT))
    context = SimpleNamespace(
        args=args,
        bot=BotFalso(),
        application=SimpleNamespace(bot_data={"servicio": servicio, "chat_id": CHAT}),
    )
    asyncio.run(comando(update, context))
    return mensaje.respuestas, context.bot.enviados


def test_crear_listar_y_borrar_por_telegram(servicio, proveedor):
    proveedor.fijar("AAPL", 340)
    [r], _ = _llamar(bot.cmd_alerta, servicio, ["AAPL", "compra", "baja", "300"])
    assert "Alerta creada" in r and "#1" in r

    [r], _ = _llamar(bot.cmd_alertas, servicio, [])
    assert "AAPL" in r

    [r], _ = _llamar(bot.cmd_borrar, servicio, ["1"])
    assert "borrada" in r
    assert servicio.repo.listar() == []


def test_errores_se_explican_al_usuario(servicio):
    [r], _ = _llamar(bot.cmd_alerta, servicio, ["AAPL", "compra"])
    assert "Faltan datos" in r
    [r], _ = _llamar(bot.cmd_alerta, servicio, ["NOEXISTE", "compra", "baja", "10"])
    assert "No se pudo crear" in r
    [r], _ = _llamar(bot.cmd_borrar, servicio, ["abc"])
    assert "Uso" in r


def test_revisar_manda_el_aviso_al_chat(servicio, proveedor):
    proveedor.fijar("AAPL", 340)
    _llamar(bot.cmd_alerta, servicio, ["AAPL", "compra", "baja", "300"])
    proveedor.fijar("AAPL", 290)
    [r], enviados = _llamar(bot.cmd_revisar, servicio, [])
    assert "1 alerta(s) disparada(s)" in r
    [(chat, texto)] = enviados
    assert chat == CHAT and "ALERTA DE COMPRA" in texto
