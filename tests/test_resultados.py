import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import pytest

from monitor_mercado.configuracion import Configuracion
from monitor_mercado.db import crear_motor
from monitor_mercado.noticias.nombres import ResolutorNombres
from monitor_mercado.resultados.comunicado import (
    AnalizadorComunicado, ClienteEdgar, Comunicado, ErrorComunicado, html_a_texto,
)
from monitor_mercado.resultados.datos import ConsensoProximo, Estados, EventoResultados
from monitor_mercado.resultados.evaluacion import Sorpresa, Veredicto, clasificar, evaluar, sorpresa_pct
from monitor_mercado.resultados.metricas import calcular_metricas, elegir_trimestre
from monitor_mercado.resultados.reaccion import calcular_reaccion, precio_base
from monitor_mercado.resultados.reporte import explicacion_resultados, reporte_resultados, texto_calendario
from monitor_mercado.resultados.repositorio import RepositorioResultados
from monitor_mercado.resultados.servicio import ServicioResultados
from monitor_mercado.resultados.valuacion import CacheInfo, valuar

NY = ZoneInfo("America/New_York")
TRIMESTRES = pd.to_datetime(["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"])


def estados_prueba() -> Estados:
    """Empresa que crece 10% interanual y mejora su margen operativo de 20% a 25%."""
    ingresos = [110.0, 105.0, 120.0, 102.0, 100.0]
    operativo = [27.5, 25.0, 30.0, 21.0, 20.0]
    resultados = pd.DataFrame(
        {c: {"Total Revenue": i, "Gross Profit": i * 0.5, "Operating Income": o, "Net Income": o * 0.8,
             "Diluted EPS": o * 0.08, "EBITDA": o + 5}
         for c, i, o in zip(TRIMESTRES, ingresos, operativo)}
    )
    balance = pd.DataFrame({TRIMESTRES[0]: {"Total Debt": 50.0, "Cash And Cash Equivalents": 30.0}})
    flujos = pd.DataFrame({c: {"Operating Cash Flow": 20.0, "Capital Expenditure": -5.0, "Free Cash Flow": 15.0}
                           for c in TRIMESTRES})
    return Estados(resultados, balance, flujos, "USD")


# ------------------------------------------------------------------ métricas
def test_elegir_trimestre():
    assert elegir_trimestre(list(TRIMESTRES), date(2026, 7, 30)) == TRIMESTRES[0]
    assert elegir_trimestre(list(TRIMESTRES), date(2026, 5, 2)) == TRIMESTRES[1]
    assert elegir_trimestre(list(TRIMESTRES), date(2027, 1, 30)) is None  # más de 120 días


def test_metricas():
    e = estados_prueba()
    m = calcular_metricas(e.resultados, e.balance, e.flujos, TRIMESTRES[0])
    assert m.ingresos_yoy == pytest.approx(0.10)
    assert m.ingresos_qoq == pytest.approx(110 / 105 - 1)
    assert m.margen_operativo == pytest.approx(0.25)
    assert m.margen_operativo_hace_un_anio == pytest.approx(0.20)
    assert m.deuda_neta == pytest.approx(20)
    assert m.fcf_12m == pytest.approx(60)
    assert m.ebitda_12m == pytest.approx(27.5 + 25 + 30 + 21 + 20)
    assert m.deuda_neta_sobre_ebitda == pytest.approx(20 / m.ebitda_12m)


def test_metricas_de_banco_sin_margen_bruto():
    e = estados_prueba()
    banco = e.resultados.drop(index=["Gross Profit", "Operating Income"])
    m = calcular_metricas(banco, None, None, TRIMESTRES[0])
    assert m.margen_bruto is None and m.margen_operativo is None and m.margen_neto is not None
    assert m.deuda_neta is None and m.fcf is None


# ------------------------------------------------------------------ reacción
def _cierres(valores, inicio="2026-07-27"):
    return pd.Series(valores, index=pd.bdate_range(inicio, periods=len(valores)), dtype=float)


def test_presentacion_despues_del_cierre_usa_el_cierre_del_mismo_dia():
    c = _cierres([100, 100, 100, 100, 110, 111, 112, 113, 114])  # jueves 30/07 = índice 3
    despues_del_cierre = datetime(2026, 7, 30, 16, 5, tzinfo=NY)
    assert precio_base(c, despues_del_cierre) == pd.Timestamp("2026-07-30")
    [r1, *_] = calcular_reaccion(c, None, despues_del_cierre)
    assert r1.accion == pytest.approx(0.10)


def test_presentacion_antes_de_abrir_usa_la_rueda_anterior():
    c = _cierres([100, 100, 100, 90, 91, 92])
    antes_de_abrir = datetime(2026, 7, 30, 7, 0, tzinfo=NY)
    assert precio_base(c, antes_de_abrir) == pd.Timestamp("2026-07-29")
    [r1, *_] = calcular_reaccion(c, None, antes_de_abrir)
    assert r1.accion == pytest.approx(-0.10)


def test_reaccion_descuenta_al_indice():
    c = _cierres([100, 100, 100, 100, 105, 105])
    indice = _cierres([100, 100, 100, 100, 103, 103])
    [r1, *_] = calcular_reaccion(c, indice, datetime(2026, 7, 30, 16, 5, tzinfo=NY))
    assert r1.anormal == pytest.approx(0.02)


def test_sin_ruedas_posteriores_no_hay_reaccion():
    c = _cierres([100, 100, 100, 100])
    assert calcular_reaccion(c, None, datetime(2026, 7, 30, 16, 5, tzinfo=NY)) == []


# ---------------------------------------------------------------- evaluación
def test_clasificacion_de_sorpresas():
    assert clasificar(sorpresa_pct(2.02, 1.89), 0.02) is Sorpresa.BEAT
    assert clasificar(sorpresa_pct(1.90, 1.89), 0.02) is Sorpresa.EN_LINEA
    assert clasificar(sorpresa_pct(1.70, 1.89), 0.02) is Sorpresa.MISS
    assert clasificar(sorpresa_pct(None, 1.89), 0.02) is Sorpresa.SIN_DATO
    assert sorpresa_pct(-0.5, -1.0) == pytest.approx(0.5)  # perdió menos de lo esperado = mejor


def test_veredicto_combina_factores():
    e = estados_prueba()
    m = calcular_metricas(e.resultados, e.balance, e.flujos, TRIMESTRES[0])
    bueno = evaluar(0.07, 0.02, m, [], guidance="subio", tono="positivo")
    malo = evaluar(-0.10, -0.03, m, [], guidance="bajo", tono="negativo")
    assert bueno.veredicto is Veredicto.MEJOR and malo.veredicto is Veredicto.PEOR
    assert {f.nombre for f in bueno.factores} >= {"EPS vs. consenso", "Guidance", "Margen operativo (interanual)"}


def test_guidance_pesa_tanto_como_la_sorpresa():
    # Superó el consenso pero bajó sus proyecciones: queda "en línea".
    ev = evaluar(0.05, None, None, [], guidance="bajo")
    assert ev.veredicto is Veredicto.EN_LINEA


# ----------------------------------------------------------------- valuación
class FuenteInfoFalsa:
    def __init__(self, infos):
        self.infos = infos

    def info(self, s):
        return self.infos[s]


def test_valuacion_contra_mediana_de_pares(tmp_path):
    infos = {
        "AAPL": {"trailingPE": 38, "forwardPE": 34, "industry": "Consumer Electronics", "currency": "USD",
                 "financialCurrency": "USD"},
        "MSFT": {"trailingPE": 30, "forwardPE": 28, "industry": "Software", "currency": "USD", "financialCurrency": "USD"},
        "SONY": {"trailingPE": 20, "forwardPE": -5, "industry": "Consumer Electronics", "currency": "USD",
                 "financialCurrency": "USD"},
    }
    cache = CacheInfo(tmp_path / "i.json", FuenteInfoFalsa(infos))
    v = valuar("AAPL", cache, {"AAPL": ["MSFT", "SONY"]}, [])
    pe = next(x for x in v.multiplos if x.nombre.startswith("P/E (últimos"))
    assert pe.pares == pytest.approx(25) and pe.lectura == "más cara que sus pares"
    forward = next(x for x in v.multiplos if x.nombre.startswith("P/E esperado"))
    assert forward.cantidad_pares == 1  # el P/E negativo de SONY se descarta


def test_pares_automaticos_por_industria(tmp_path):
    infos = {"AAPL": {"industry": "Consumer Electronics"}, "SONY": {"industry": "Consumer Electronics"},
             "MSFT": {"industry": "Software"}}
    cache = CacheInfo(tmp_path / "i.json", FuenteInfoFalsa(infos))
    for s in infos:
        cache.obtener(s)
    assert valuar("AAPL", cache, {}, ["AAPL", "SONY", "MSFT"]).pares == ["SONY"]


def test_monedas_distintas_omiten_multiplos_de_balance(tmp_path):
    infos = {"GGAL": {"trailingPE": 105, "forwardPE": 5.3, "priceToBook": 9.8, "currency": "USD",
                      "financialCurrency": "ARS"}}
    v = valuar("GGAL", CacheInfo(tmp_path / "i.json", FuenteInfoFalsa(infos)), {}, [])
    nombres = {x.nombre for x in v.multiplos}
    assert "Precio / valor libro" not in nombres and "P/E esperado (próximos 12 meses)" in nombres
    assert any("balances están en ARS" in a for a in v.avisos)


# ---------------------------------------------------------------- comunicado
def test_html_a_texto():
    texto = html_a_texto("<html><style>x{}</style><p>Ingresos &amp; ventas</p><p>récord</p></html>")
    assert "x{}" not in texto  # el CSS se descarta
    assert [l.strip() for l in texto.splitlines() if l.strip()] == ["Ingresos & ventas", "récord"]


def _sec_falsa(peticion: httpx.Request) -> httpx.Response:
    url = str(peticion.url)
    assert "contacto@ejemplo.com" in peticion.headers["User-Agent"]  # la SEC exige identificarse
    if url.endswith("company_tickers.json"):
        return httpx.Response(200, json={"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}})
    if "submissions" in url:
        return httpx.Response(200, json={"filings": {"recent": {
            "form": ["10-Q", "8-K", "8-K"], "filingDate": ["2026-08-01", "2026-07-30", "2026-06-01"],
            "items": ["", "2.02,9.01", "5.07"], "accessionNumber": ["x", "0000320193-26-000070", "y"],
            "primaryDocument": ["q.htm", "aapl-8k.htm", "z.htm"]}}})
    if url.endswith("index.json"):
        return httpx.Response(200, json={"directory": {"item": [{"name": "aapl-8k.htm"}, {"name": "a8-kex991.htm"}]}})
    if url.endswith("a8-kex991.htm"):
        return httpx.Response(200, text="<p>Apple reports third quarter results. " + "Revenue grew. " * 60 + "</p>")
    return httpx.Response(404)


def test_edgar_encuentra_el_anexo_99_1(tmp_path):
    http = httpx.Client(transport=httpx.MockTransport(_sec_falsa),
                        headers={"User-Agent": "monitor-mercado contacto@ejemplo.com"})
    doc = ClienteEdgar("contacto@ejemplo.com", tmp_path / "ciks.json", http).buscar("AAPL", date(2026, 7, 30))
    assert doc.formulario == "8-K" and doc.url.endswith("a8-kex991.htm")
    assert doc.texto.startswith("Apple reports third quarter results")
    with pytest.raises(ErrorComunicado):
        ClienteEdgar("contacto@ejemplo.com", tmp_path / "ciks.json", http).buscar("MSFT", date(2026, 7, 30))


def test_analizador_de_comunicado_con_cliente_falso():
    respuesta = {"resumen": "Buen trimestre.", "tono": "positivo", "guidance": "subio",
                 "guidance_detalle": "Espera crecer 10%.", "positivos": ["a", "b", "c", "d", "e"],
                 "negativos": [], "veredicto_modelo": "mejor", "justificacion": "Superó."}
    pedidos = []

    def crear(**kw):
        pedidos.append(kw)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(respuesta))],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    cliente = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=crear)))
    doc = Comunicado("8-K", date(2026, 7, 30), "u", "texto")
    a = AnalizadorComunicado(cliente).analizar("Apple", doc, {"sorpresa_eps": 0.07})
    assert a.guidance == "subio" and len(a.positivos) == 4
    assert "instrucciones" in pedidos[0]["system"]


# ------------------------------------------------------------------ servicio
class FuenteResultadosFalsa:
    def __init__(self, eventos):
        self._eventos = eventos

    def eventos(self, s, limite=12):
        return self._eventos

    def consenso(self, s):
        return ConsensoProximo(date(2026, 10, 29), 1.98, 115.0, "USD", 30)

    def estados(self, s):
        return estados_prueba()

    def info(self, s):
        return {"trailingPE": 30, "currency": "USD", "financialCurrency": "USD"}


class AlmacenFalso:
    def obtener(self, s):
        return pd.DataFrame({"cierre": _cierres([100, 100, 100, 100, 104, 105, 106], "2026-07-27").values},
                            index=pd.bdate_range("2026-07-27", periods=7))


def _servicio(tmp_path, eventos):
    cfg = Configuracion.model_validate({"resultados": {"aviso_previo_horas": 36}})
    repo = RepositorioResultados(crear_motor(":memory:"))
    fuente = FuenteResultadosFalsa(eventos)
    return ServicioResultados(fuente, repo, AlmacenFalso(), CacheInfo(tmp_path / "i.json", fuente),
                              ResolutorNombres(tmp_path / "n.json", {"AAPL": "Apple"}), cfg)


def test_analisis_completo_con_consenso_guardado(tmp_path):
    ev = EventoResultados(datetime(2026, 7, 30, 16, 5, tzinfo=NY), 1.89, 2.02)
    s = _servicio(tmp_path, [ev])
    s.repo.guardar_consenso("AAPL", date(2026, 7, 30), 1.89, 108.0, "USD")
    r = s.analizar("AAPL")
    assert r.clase_eps is Sorpresa.BEAT
    assert r.sorpresa_ingresos == pytest.approx(110 / 108 - 1)
    assert r.reacciones[0].accion == pytest.approx(0.04)
    texto = reporte_resultados(r)
    assert "MEJOR DE LO ESPERADO" in texto and "no es una recomendación de inversión" in texto
    assert "Sin análisis del comunicado" in texto  # sin SEC ni Claude se avisa qué falta
    assert "Explicación para aprender" in explicacion_resultados(r)


def test_calendario_avisa_una_sola_vez_antes_y_despues(tmp_path):
    ahora = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
    proxima = EventoResultados(datetime(2026, 7, 30, 16, 5, tzinfo=NY), 1.89, None)
    s = _servicio(tmp_path, [proxima])
    s.repo.seguir("AAPL")
    [(tipo, dato)] = s.revisar_calendario(ahora)
    assert tipo == "previo" and dato.simbolo == "AAPL"
    assert s.revisar_calendario(ahora) == []  # no repite el aviso
    assert s.repo.consenso("AAPL", date(2026, 10, 29)).ingresos == 115.0  # guardó el consenso

    publicado = EventoResultados(proxima.fecha, 1.89, 2.02)
    s.fuente._eventos = [publicado]
    despues = ahora + timedelta(days=2)
    [(tipo, reporte)] = s.revisar_calendario(despues)
    assert tipo == "resultado" and reporte.clase_eps is Sorpresa.BEAT
    assert s.revisar_calendario(despues) == []


def test_seguir_y_dejar(tmp_path):
    repo = RepositorioResultados(crear_motor(":memory:"))
    assert repo.seguir("aapl") and not repo.seguir("AAPL")
    assert repo.seguidas() == ["AAPL"]
    assert repo.dejar("AAPL") and not repo.dejar("AAPL")
    assert "No seguís" in texto_calendario([], [])
