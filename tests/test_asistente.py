"""Asistente en lenguaje natural: loop de herramientas, tope diario, errores y bot (sin llamar a la API)."""

from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from monitor_mercado.asistente.herramientas import HERRAMIENTAS, EjecutorHerramientas
from monitor_mercado.asistente.servicio import SISTEMA, ServicioAsistente
from monitor_mercado.configuracion import ConfigAsistente
from monitor_mercado.db import crear_motor


def texto(t):
    return SimpleNamespace(type="text", text=t)


def uso_herramienta(id_, nombre, entrada):
    return SimpleNamespace(type="tool_use", id=id_, name=nombre, input=entrada)


def respuesta(stop, *bloques):
    return SimpleNamespace(stop_reason=stop, content=list(bloques),
                           usage=SimpleNamespace(input_tokens=100, output_tokens=20))


class ClienteFalso:
    """Imita client.beta.messages.create devolviendo respuestas en orden y guardando los pedidos."""

    def __init__(self, *respuestas, error=None):
        self.respuestas, self.pedidos, self.error = list(respuestas), [], error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.pedidos.append({**kwargs, "messages": list(kwargs["messages"])})  # copia: la lista sigue creciendo
        if self.error:
            raise self.error
        return self.respuestas.pop(0)


class EjecutorFalso:
    def __init__(self):
        self.llamadas = []

    def ejecutar(self, nombre, entrada):
        self.llamadas.append((nombre, entrada))
        if nombre == "precio" and entrada.get("simbolo") == "XXX":
            return "No se pudo obtener el dato: sin datos", True
        return f"datos de {nombre}", False


def asistente(cliente, ejecutor=None, **cfg):
    return ServicioAsistente(cliente, ejecutor or EjecutorFalso(), ConfigAsistente(**cfg), crear_motor(":memory:"))


def test_loop_con_herramientas():
    cliente = ClienteFalso(
        respuesta("tool_use", texto("Busco los datos."), uso_herramienta("t1", "ver_cartera", {}),
                  uso_herramienta("t2", "precio", {"simbolo": "XXX"})),
        respuesta("end_turn", texto("Esta semana tu cartera subió 2%.")),
    )
    ejecutor = EjecutorFalso()
    r = asistente(cliente, ejecutor, modelo="claude-opus-5-5", max_tokens=1234, esfuerzo="low").responder(
        "¿cómo me fue esta semana?")
    assert r.startswith("Esta semana tu cartera subió 2%.") and "no es una recomendación" in r
    assert [n for n, _ in ejecutor.llamadas] == ["ver_cartera", "precio"]

    primero, segundo = cliente.pedidos
    assert primero["model"] == "claude-opus-5-5" and primero["max_tokens"] == 1234
    assert primero["output_config"] == {"effort": "low"} and primero["tools"] is HERRAMIENTAS
    assert "Nunca des recomendaciones" in primero["system"]
    # Los dos resultados vuelven juntos, en un solo mensaje, y el error va marcado.
    resultados = segundo["messages"][-1]["content"]
    assert [x["tool_use_id"] for x in resultados] == ["t1", "t2"]
    assert "is_error" not in resultados[0] and resultados[1]["is_error"] is True


def test_tope_diario_y_sin_clave():
    a = asistente(ClienteFalso(*[respuesta("end_turn", texto("ok"))] * 3), consultas_por_dia=2)
    assert a.responder("a").startswith("ok") and a.responder("b").startswith("ok")
    assert "tope de 2 preguntas" in a.responder("c")
    assert a.consultas_hoy() == 2

    sin_clave = asistente(None)
    assert not sin_clave.disponible and "ANTHROPIC_API_KEY" in sin_clave.responder("hola")
    assert "desactivadas" in asistente(ClienteFalso(), habilitado=False).responder("hola")


def test_corta_si_necesita_demasiadas_vueltas_y_maneja_rechazos():
    infinito = [respuesta("tool_use", uso_herramienta(f"t{i}", "ver_cartera", {})) for i in range(3)]
    assert "demasiados pasos" in asistente(ClienteFalso(*infinito), max_vueltas=3).responder("x")
    assert "No puedo responder" in asistente(ClienteFalso(respuesta("refusal"))).responder("x")
    cortada = asistente(ClienteFalso(respuesta("max_tokens", texto("Tu cartera..."))))
    assert "quedó cortada" in cortada.responder("x")


@pytest.mark.parametrize("error, mensaje", [
    (anthropic.AuthenticationError("x", response=httpx.Response(401, request=httpx.Request("POST", "http://a")),
                                   body=None), "no es válida"),
    (anthropic.RateLimitError("x", response=httpx.Response(429, request=httpx.Request("POST", "http://a")),
                              body=None), "limitando"),
    (anthropic.APIConnectionError(request=httpx.Request("POST", "http://a")), "conectar"),
])
def test_errores_de_la_api(error, mensaje):
    assert mensaje in asistente(ClienteFalso(error=error)).responder("x")


def test_herramientas_bien_definidas():
    nombres = {h["name"] for h in HERRAMIENTAS}
    assert len(nombres) == len(HERRAMIENTAS)
    for h in HERRAMIENTAS:
        esquema = h["input_schema"]
        assert h["strict"] and esquema["additionalProperties"] is False
        assert set(esquema["required"]) == set(esquema["properties"])
    assert "Nunca des recomendaciones de compra, venta" in SISTEMA


def test_ejecutor_contra_servicios_reales(tmp_path, proveedor, servicio):
    from monitor_mercado.cartera.servicio import ServicioCartera
    from monitor_mercado.configuracion import Configuracion

    proveedor.fijar("AAPL", 110, cierre=100)
    ruta = tmp_path / "c.csv"
    ruta.write_text("simbolo,cantidad,precio_compra,moneda,fecha_compra,nota\nAAPL,10,100,USD,,\n", encoding="utf-8")
    cfg = Configuracion()
    ctx = SimpleNamespace(
        cartera=ServicioCartera(ruta, proveedor, cfg, crear_motor(":memory:")), servicio=servicio,
        rendimiento=lambda e: None, buscador=lambda: SimpleNamespace(resolver=lambda t: t), stops=None,
        noticias=None,
    )
    e = EjecutorHerramientas(ctx)
    texto_cartera, error = e.ejecutar("ver_cartera", {})
    assert not error and "AAPL" in texto_cartera
    texto_precio, error = e.ejecutar("precio", {"simbolo": "aapl"})
    assert not error and "US$ 110,00" in texto_precio
    assert e.ejecutar("precio", {"simbolo": "NOEXISTE"})[1] is True  # el error vuelve como dato, no rompe
    assert e.ejecutar("noticias", {"simbolo": "AAPL"}) == ("Las noticias están desactivadas en config.yaml.", False)
    assert "No hay una foto" in e.ejecutar("evolucion_cartera", {"dias": 7})[0]
    assert e.ejecutar("inventada", {})[1] is True


def test_bot_responde_texto_libre(servicio):
    from tests.test_bot import _llamar
    from monitor_mercado.notificaciones import telegram_bot as bot

    a = asistente(ClienteFalso(respuesta("end_turn", texto("NVDA cayó 7% hoy por la venta de chips."))))
    respuestas, _ = _llamar(bot.responder_pregunta, servicio, [], ctx=SimpleNamespace(asistente=a))
    # _llamar arma un mensaje sin texto: no responde nada.
    assert respuestas == []

    import asyncio

    from tests.test_bot import BotFalso, MensajeFalso

    mensaje = MensajeFalso()
    mensaje.text = "¿qué pasó con NVDA hoy?"
    bot_falso = BotFalso()
    bot_falso.send_chat_action = lambda **k: asyncio.sleep(0)
    update = SimpleNamespace(effective_message=mensaje, effective_chat=SimpleNamespace(id=1))
    context = SimpleNamespace(bot=bot_falso, application=SimpleNamespace(bot_data={"ctx": SimpleNamespace(asistente=a)}))
    asyncio.run(bot.responder_pregunta(update, context))
    assert mensaje.respuestas[0].startswith("NVDA cayó 7%")
