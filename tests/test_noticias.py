import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from monitor_mercado.configuracion import ConfigNoticias
from monitor_mercado.db import crear_motor
from monitor_mercado.noticias.fuentes import GoogleNewsRSS, _desde_rss, buscar_en_todas, es_de_eeuu
from monitor_mercado.noticias.modelos import Clasificacion, Noticia, Sentimiento
from monitor_mercado.noticias.nombres import ResolutorNombres, limpiar_nombre
from monitor_mercado.noticias.reporte import reporte_noticias
from monitor_mercado.noticias.repositorio import RepositorioNoticias
from monitor_mercado.noticias.sentimiento import ClasificadorClaude, ErrorSentimiento
from monitor_mercado.noticias.servicio import NoticiaEvaluada, ServicioNoticias, agregar, peso_noticia

AHORA = datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc)

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Aluar aumenta sus exportaciones - Ámbito</title><link>https://a/1</link>
<pubDate>Mon, 28 Sep 2026 10:00:00 GMT</pubDate><source url="https://ambito.com">Ámbito</source>
<description>&lt;b&gt;Récord&lt;/b&gt; de ventas</description></item>
<item><title>Noticia vieja</title><link>https://a/2</link><pubDate>Mon, 01 Jun 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


def noticia(titulo="Apple sube", dias=0.0, simbolo="AAPL") -> Noticia:
    return Noticia(simbolo, titulo, "Prueba", "https://x", AHORA - timedelta(days=dias))


# ------------------------------------------------------------------ fuentes
def test_parseo_rss_filtra_por_fecha_y_limpia_html():
    [n] = _desde_rss("ALUA.BA", RSS, "Google News", AHORA - timedelta(days=7))
    assert n.titulo.startswith("Aluar aumenta")
    assert n.fuente == "Google News: Ámbito"
    assert "<b>" not in n.resumen and "Récord" in n.resumen


def test_mismo_titular_de_dos_medios_es_una_sola_noticia():
    a = noticia("Aluar aumenta sus exportaciones - Ámbito")
    b = noticia("Aluar aumenta sus exportaciones - El Cronista")
    assert a.id == b.id


def test_idioma_por_mercado():
    g = GoogleNewsRSS({"GGAL": "es"})
    assert g.idioma("ALUA.BA") == "es" and g.idioma("PETR4.SA") == "pt"
    assert g.idioma("GGAL") == "es" and g.idioma("AAPL") == "en"
    assert es_de_eeuu("BRK-B") and not es_de_eeuu("VOW3.DE") and not es_de_eeuu("^IXIC")


def test_una_fuente_caida_no_frena_a_las_demas():
    class Buena:
        nombre = "Buena"
        def aplica(self, s): return True
        def buscar(self, s, e, d): return [noticia()]

    class Rota:
        nombre = "Rota"
        def aplica(self, s): return True
        def buscar(self, s, e, d): raise ValueError("caída")

    noticias, errores = buscar_en_todas([Rota(), Buena()], "AAPL", "Apple", 7)
    assert len(noticias) == 1 and "Rota" in errores[0]


def test_limpiar_nombre():
    assert limpiar_nombre("Apple Inc.") == "Apple"
    assert limpiar_nombre("Aluar Aluminio Argentino S.A.") == "Aluar Aluminio Argentino"
    assert limpiar_nombre("NVIDIA Corporation") == "NVIDIA"


def test_nombres_manuales_tienen_prioridad(tmp_path):
    r = ResolutorNombres(tmp_path / "n.json", {"alua.ba": "Aluar"})
    assert r.nombre("ALUA.BA") == "Aluar"


# ----------------------------------------------------------------- agregado
def test_peso_baja_con_la_antiguedad():
    c = Clasificacion(Sentimiento.POSITIVA, 0.8, 1.0, "f", "e")
    assert peso_noticia(c, AHORA, AHORA, 2) == pytest.approx(1.0)
    assert peso_noticia(c, AHORA - timedelta(days=2), AHORA, 2) == pytest.approx(0.5)


def test_agregado_ponderado():
    pos = Clasificacion(Sentimiento.POSITIVA, 1.0, 1.0, "f", "e")
    neg = Clasificacion(Sentimiento.NEGATIVA, -1.0, 1.0, "f", "e")
    puntaje, cobertura = agregar([NoticiaEvaluada(noticia(), pos, 3.0), NoticiaEvaluada(noticia(), neg, 1.0)])
    assert puntaje == pytest.approx(0.5)
    assert cobertura == pytest.approx(1.0)
    assert agregar([NoticiaEvaluada(noticia(), None)]) == (None, 0.0)


# -------------------------------------------------------------- clasificador
class ClienteFalso:
    """Imita client.beta.messages.create y registra los pedidos."""

    def __init__(self, respuesta: dict | None = None, stop_reason: str = "end_turn") -> None:
        self.pedidos: list[dict] = []
        self._respuesta = respuesta
        self._stop = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._crear))

    def _crear(self, **kwargs):
        self.pedidos.append(kwargs)
        # Responde una clasificación por cada id que venga en el pedido.
        texto_pedido = kwargs["messages"][0]["content"]
        lista = json.loads(texto_pedido.split("<noticias>\n")[1].split("\n</noticias>")[0])
        datos = self._respuesta or {
            "noticias": [{"id": n["id"], "sentimiento": "positiva", "puntaje": 1.7, "relevancia": 0.9,
                          "factor": "demanda", "explicacion": "Más ventas."} for n in lista]
            + [{"id": "inventado", "sentimiento": "negativa", "puntaje": -1, "relevancia": 1,
                "factor": "x", "explicacion": "x"}],
            "resumen": "Panorama positivo.",
        }
        return SimpleNamespace(
            stop_reason=self._stop,
            content=[SimpleNamespace(type="text", text=json.dumps(datos))],
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )


def test_clasificador_acota_valores_e_ignora_ids_inventados():
    cliente = ClienteFalso()
    r = ClasificadorClaude(cliente=cliente).clasificar("Apple", "AAPL", [noticia()])
    [c] = r.clasificaciones.values()
    assert c.puntaje == 1.0  # 1,7 se acota a 1
    assert "inventado" not in r.clasificaciones
    pedido = cliente.pedidos[0]
    assert pedido["model"] == "claude-opus-5-5"
    assert pedido["output_config"]["format"]["type"] == "json_schema"
    assert "instrucciones" in pedido["system"]  # defensa contra texto malicioso en titulares


def test_clasificador_rechazo_da_error():
    with pytest.raises(ErrorSentimiento):
        ClasificadorClaude(cliente=ClienteFalso(stop_reason="refusal")).clasificar("Apple", "AAPL", [noticia()])


# ------------------------------------------------------------------ servicio
class FuenteFija:
    nombre = "Fija"

    def __init__(self, noticias):
        self.noticias = noticias

    def aplica(self, s):
        return True

    def buscar(self, s, e, d):
        return self.noticias


def _servicio(tmp_path, noticias, cliente):
    repo = RepositorioNoticias(crear_motor(":memory:"))
    return ServicioNoticias(
        [FuenteFija(noticias)],
        ClasificadorClaude(cliente=cliente) if cliente else None,
        repo,
        ResolutorNombres(tmp_path / "n.json", {"AAPL": "Apple"}),
        ConfigNoticias(),
    )


def test_cada_noticia_se_clasifica_una_sola_vez(tmp_path):
    cliente = ClienteFalso()
    s = _servicio(tmp_path, [noticia("A"), noticia("B")], cliente)
    r1 = s.analizar("AAPL", ahora=AHORA)
    r2 = s.analizar("AAPL", ahora=AHORA)
    assert len(cliente.pedidos) == 1  # la segunda vez usa lo guardado
    assert r1.puntaje == pytest.approx(1.0) and r2.puntaje == pytest.approx(1.0)
    assert r2.resumen == "Panorama positivo."


def test_sin_claude_muestra_titulares_sin_puntaje_ni_avisos(tmp_path):
    s = _servicio(tmp_path, [noticia("A")], None)
    r = s.analizar("AAPL", ahora=AHORA)
    assert r.puntaje is None and len(r.noticias) == 1
    assert r.avisos == []  # desactivado a propósito: no se reclama la clave
    texto = reporte_noticias(r)
    assert "Titulares recientes" in texto and "no es una recomendación" in texto
    assert "Claude" not in texto


def test_si_se_pide_claude_sin_clave_se_avisa(tmp_path):
    s = _servicio(tmp_path, [noticia("A")], None)
    s._cfg = ConfigNoticias(usar_claude=True)
    assert "ANTHROPIC_API_KEY" in s.analizar("AAPL", ahora=AHORA).avisos[0]
