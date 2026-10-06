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

    async def reply_photo(self, photo, caption: str) -> None:
        self.respuestas.append(f"[foto {len(photo.read())} bytes] {caption}")


class BotFalso:
    def __init__(self) -> None:
        self.enviados: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.enviados.append((chat_id, text))


def _llamar(comando, servicio, args, **bot_data):
    mensaje = MensajeFalso()
    update = SimpleNamespace(effective_message=mensaje, effective_chat=SimpleNamespace(id=CHAT))
    context = SimpleNamespace(
        args=args,
        bot=BotFalso(),
        application=SimpleNamespace(bot_data={"servicio": servicio, "chat_id": CHAT, **bot_data}),
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


def test_analisis_manda_reporte_y_grafico(servicio, cfg, tmp_path, datos_ohlcv):
    from monitor_mercado.tecnico.historico import AlmacenHistorico
    from monitor_mercado.tecnico.servicio import ServicioTecnico
    from tests.test_historico_y_tecnico import FuenteFalsa

    from monitor_mercado.aplicacion import Contexto
    from monitor_mercado.configuracion import Secretos

    cfg.rutas.graficos = str(tmp_path / "graficos")
    tecnico = ServicioTecnico(AlmacenHistorico(tmp_path, FuenteFalsa({"AAPL": datos_ohlcv(300)})), cfg)
    ctx = Contexto(cfg, Secretos(_env_file=None), None, servicio, tecnico, noticias=None)
    respuestas, _ = _llamar(bot.cmd_analisis, servicio, ["aapl"], ctx=ctx)
    assert respuestas[0].startswith("Analizando AAPL")
    assert "lectura del gráfico" in respuestas[1] and "Soportes y resistencias" in respuestas[1]
    assert respuestas[2].startswith("[foto") and "gráfico anotado" in respuestas[2]
    assert "AAPL: tendencia" in respuestas[3] and "Señal final (solo técnica)" in respuestas[3]
    assert "no es una recomendación" in respuestas[3]
    assert "Explicación para aprender" in respuestas[4] and "Cómo lee un gráfico" in respuestas[4]

    respuestas, _ = _llamar(bot.cmd_analisis, servicio, ["NOEXISTE"], ctx=ctx)
    assert "No se pudo analizar" in respuestas[-1]


def test_glosario(servicio):
    [r], _ = _llamar(bot.cmd_glosario, servicio, ["rsi"])
    assert r.startswith("📖 RSI")
    [r], _ = _llamar(bot.cmd_glosario, servicio, [])
    assert "MACD" in r and "CCL" in r


def test_revisar_manda_el_aviso_al_chat(servicio, proveedor):
    proveedor.fijar("AAPL", 340)
    _llamar(bot.cmd_alerta, servicio, ["AAPL", "compra", "baja", "300"])
    proveedor.fijar("AAPL", 290)
    [r], enviados = _llamar(bot.cmd_revisar, servicio, [])
    assert "1 alerta(s) disparada(s)" in r
    [(chat, texto)] = enviados
    assert chat == CHAT and "ALERTA DE COMPRA" in texto
