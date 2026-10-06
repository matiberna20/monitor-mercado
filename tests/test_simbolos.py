import asyncio
from types import SimpleNamespace

import pytest

from monitor_mercado.datos.modelos import SimboloSinDatos
from monitor_mercado.notificaciones.telegram_bot import _error, con_simbolo
from monitor_mercado.simbolos import BuscadorSimbolos

NOMBRES = {"NVDA": "NVIDIA", "GGAL": "Grupo Financiero Galicia", "BMA": "Banco Macro", "MELI": "Mercado Libre",
           "ALUA.BA": "Aluar", "AAPL": "Apple"}
B = BuscadorSimbolos(["NVDA", "GGAL", "BMA", "MELI", "ALUA.BA", "AAPL", "AMD"], NOMBRES)


@pytest.mark.parametrize("texto, simbolo", [
    ("nvda", "NVDA"), ("NVIDIA", "NVDA"), ("nvidia", "NVDA"), ("galicia", "GGAL"), ("Mercado Libre", "MELI"),
    ("mercadolibre", "MELI"), ("aluar", "ALUA.BA"), ("macro", "BMA"),
    ("TSLA", "TSLA"),  # desconocido pero posible: se deja igual para que lo pruebe Yahoo
])
def test_resolver(texto, simbolo):
    assert B.resolver(texto) == simbolo


def test_palabras_genericas_no_identifican():
    # "grupo", "financiero", "banco" aparecen en muchas empresas: no deben resolver a ninguna.
    assert B.resolver("grupo") == "GRUPO"
    assert B.resolver("banco") == "BANCO"


def test_sugerencias_por_error_de_tipeo():
    assert B.sugerencias("NVDIA")[0] == "NVDA"
    assert "MELI" in B.sugerencias("mercadolibr")
    assert B.sugerencias("ZZZZZZ") == []


def test_mensaje_no_encontrado():
    texto = B.mensaje_no_encontrado("nvdia")
    assert "No encontré \"NVDIA\"" in texto and "¿Quisiste decir NVDA (NVIDIA)?" in texto


def test_seguir_rechaza_simbolos_inexistentes():
    from monitor_mercado.notificaciones.telegram_bot import cmd_seguir

    respuestas, seguidos = [], []

    class Mensaje:
        async def reply_text(self, texto):
            respuestas.append(texto)

    def cotizacion(s):
        if s != "NVDA":
            raise SimboloSinDatos(s)

    ctx = SimpleNamespace(buscador=lambda: B, proveedor=SimpleNamespace(cotizacion=cotizacion),
                          resultados=SimpleNamespace(repo=SimpleNamespace(seguir=lambda s: seguidos.append(s) or True)))
    for texto in ("NVDIA", "NVDA"):
        context = SimpleNamespace(args=[texto], application=SimpleNamespace(bot_data={"ctx": ctx}))
        asyncio.run(cmd_seguir(SimpleNamespace(effective_message=Mensaje()), context))
    assert seguidos == ["NVDA"]
    assert "¿Quisiste decir NVDA" in respuestas[0] and "Ahora seguís NVDA" in respuestas[1]


def test_bot_traduce_nombres_y_sugiere():
    recibidos = []

    async def comando(update, context):
        recibidos.append(context.args[0])

    ctx = SimpleNamespace(buscador=lambda: B)
    context = SimpleNamespace(args=["nvidia"], application=SimpleNamespace(bot_data={"ctx": ctx}))
    asyncio.run(con_simbolo(comando)(None, context))
    assert recibidos == ["NVDA"]
    assert "¿Quisiste decir NVDA" in _error(context, "NVDIA", SimboloSinDatos("x"), "No se pudo analizar")
    assert _error(context, "NVDA", ValueError("otro"), "No se pudo analizar") == "No se pudo analizar: otro"
