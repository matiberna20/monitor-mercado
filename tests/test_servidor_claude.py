"""Servidor MCP para Claude: cada herramienta responde con datos falsos (sin internet)."""

from __future__ import annotations

import asyncio

import pandas as pd
import pytest

pytest.importorskip("mcp", reason="falta el extra [claude]: pip install -e '.[claude]'")

from monitor_mercado import servidor_claude as sc  # noqa: E402
from monitor_mercado.alertas.repositorio import RepositorioAlertas  # noqa: E402
from monitor_mercado.alertas.servicio import ServicioAlertas  # noqa: E402
from monitor_mercado.aplicacion import Contexto  # noqa: E402
from monitor_mercado.backtest.servicio import ServicioBacktest  # noqa: E402
from monitor_mercado.cartera.servicio import ServicioCartera  # noqa: E402
from monitor_mercado.configuracion import Configuracion, Secretos  # noqa: E402
from monitor_mercado.datos.modelos import SimboloSinDatos  # noqa: E402
from monitor_mercado.db import crear_motor  # noqa: E402
from monitor_mercado.resultados.datos import Estados  # noqa: E402
from monitor_mercado.resultados.repositorio import RepositorioResultados  # noqa: E402
from monitor_mercado.tecnico.historico import AlmacenHistorico  # noqa: E402
from monitor_mercado.tecnico.servicio import ServicioTecnico  # noqa: E402

from .test_historico_y_tecnico import FuenteFalsa  # noqa: E402


class FuenteResultadosFalsa:
    def info(self, simbolo):
        if simbolo != "AAPL":
            raise SimboloSinDatos(simbolo)
        return {"longName": "Apple Inc.", "sector": "Technology", "marketCap": 3.2e12, "trailingPE": 31.5,
                "grossMargins": 0.46, "dividendYield": 0.45, "recommendationKey": "buy",
                "currency": "USD", "financialCurrency": "USD", "longBusinessSummary": "Hace iPhones."}

    def estados(self, simbolo):
        fechas = [pd.Timestamp("2026-09-30"), pd.Timestamp("2026-06-30")]
        resultados = pd.DataFrame({fechas[0]: [100e9, 1.65], fechas[1]: [90e9, 1.40]},
                                  index=["Total Revenue", "Diluted EPS"])
        balance = pd.DataFrame({fechas[0]: [60e9], fechas[1]: [55e9]}, index=["Total Debt"])
        return Estados(resultados, balance, pd.DataFrame(), "USD")


class ResultadosFalsos:
    def __init__(self, motor):
        self.repo = RepositorioResultados(motor)
        self.fuente = FuenteResultadosFalsa()


@pytest.fixture
def ctx(tmp_path, proveedor, datos_ohlcv):
    cfg = Configuracion.model_validate({
        "watchlist_prueba": ["AAPL", "NVDA"],
        "rutas": {"graficos": str(tmp_path / "graficos"), "historico": str(tmp_path / "hist")},
    })
    base = datos_ohlcv(400)
    ggal_ba = base.copy()
    ggal_ba[["apertura", "maximo", "minimo", "cierre"]] = 15000.0
    ggal = base.copy()
    ggal[["apertura", "maximo", "minimo", "cierre"]] = 10.0  # CCL = 15000 * 10 / 10 = 15000
    fuente = FuenteFalsa({"AAPL": base, "NVDA": datos_ohlcv(400, semilla=3), "GGAL.BA": ggal_ba, "GGAL": ggal})
    tecnico = ServicioTecnico(AlmacenHistorico(tmp_path / "hist", fuente), cfg)
    motor = crear_motor(":memory:")
    proveedor.fijar("AAPL", 250.0, cierre=245.0)
    contexto = Contexto(
        cfg=cfg, secretos=Secretos(_env_file=None), proveedor=proveedor,
        servicio=ServicioAlertas(RepositorioAlertas(motor), proveedor, cfg), tecnico=tecnico, noticias=None,
        resultados=ResultadosFalsos(motor), backtest=ServicioBacktest(tecnico, cfg),
        cartera=ServicioCartera(tmp_path / "cartera.csv", proveedor, cfg, motor),
    )
    sc.usar_contexto(contexto)
    yield contexto
    sc.usar_contexto(None)


def llamar(nombre: str, **argumentos):
    """Llama a la herramienta como lo haría Claude, por el protocolo MCP."""
    resultado = asyncio.run(sc.servidor.call_tool(nombre, argumentos))
    assert not resultado.is_error, resultado
    return resultado.content


def texto(contenido) -> str:
    return "\n".join(c.text for c in contenido if c.type == "text")


def test_todas_las_herramientas_estan_registradas():
    nombres = {t.name for t in asyncio.run(sc.servidor.list_tools())}
    esperadas = {"precio", "analizar", "grafico", "resumen_watchlist", "noticias", "resultados", "calendario",
                 "seguir_empresa", "dejar_de_seguir", "empresas_seguidas", "backtest", "backtest_watchlist",
                 "validar_grafico", "cartera", "cargar_cartera", "resumen_dia", "glosario", "crear_alerta",
                 "listar_alertas", "borrar_alerta", "revisar_alertas", "watchlist", "buscar_simbolo",
                 "historial_precios", "datos_empresa", "estados_contables", "comparar_activos", "dolar_ccl",
                 "fuerza_relativa", "panorama_mercado", "plan_de_riesgo"}
    assert esperadas <= nombres


def test_precio(ctx):
    assert "250" in texto(llamar("precio", simbolo="aapl"))


def test_analizar_devuelve_texto_y_grafico(ctx):
    contenido = llamar("analizar", simbolo="AAPL")
    assert "RSI" in texto(contenido)
    assert any(c.type == "image" for c in contenido)


def test_analizar_simbolo_inexistente_no_rompe(ctx):
    assert "No se pudo" in texto(llamar("analizar", simbolo="ZZZZ"))


def test_alertas_crear_listar_borrar(ctx):
    assert "#1" in texto(llamar("crear_alerta", alerta="AAPL compra baja 200", nota="soporte"))
    assert "AAPL" in texto(llamar("listar_alertas"))
    assert "borrada" in texto(llamar("borrar_alerta", id_alerta=1))
    from monitor_mercado.alertas.parser import AYUDA_FORMATO

    assert AYUDA_FORMATO in texto(llamar("crear_alerta", alerta="AAPL cualquier cosa"))


def test_cartera_vacia_y_carga(ctx):
    assert "No hay posiciones" in texto(llamar("cartera"))
    assert "no se guardó" in texto(llamar("cargar_cartera", csv="simbolo,cantidad\nAAPL,abc"))
    assert not ctx.cartera.ruta.exists()  # un CSV inválido no deja archivo
    ok = texto(llamar("cargar_cartera",
                      csv="simbolo,cantidad,precio_compra,moneda,fecha_compra,nota\nAAPL,10,200,USD,,"))
    assert "1 posiciones" in ok
    assert "AAPL" in texto(llamar("cartera"))


def test_historial_y_comparacion(ctx):
    h = texto(llamar("historial_precios", simbolo="AAPL", ruedas=5))
    assert len(h.strip().splitlines()) == 7 and "rsi14" in h  # título + encabezado + 5 filas
    assert "fecha" in texto(llamar("historial_precios", simbolo="AAPL", ruedas=10, semanal=True))
    c = texto(llamar("comparar_activos", simbolos=["AAPL", "NVDA", "ZZZZ"]))
    assert "AAPL (USD)" in c and "Correlación" in c and "ZZZZ" in c


def test_datos_empresa_y_estados(ctx):
    f = texto(llamar("datos_empresa", simbolo="AAPL"))
    assert "3.20 T" in f and "+46.0%" in f and "Hace iPhones" in f
    e = texto(llamar("estados_contables", simbolo="AAPL"))
    assert "100.00 B" in e and "1.65" in e


def test_fuerza_relativa_y_panorama(ctx):
    fr = texto(llamar("fuerza_relativa", simbolo="NVDA", contra="AAPL"))
    assert "Fuerza relativa de NVDA" in fr and "1 año" in fr
    p = texto(llamar("panorama_mercado"))
    assert "sin datos" in p  # los símbolos del panorama no están en los datos falsos: no rompe


def test_plan_de_riesgo(ctx):
    t = texto(llamar("plan_de_riesgo", simbolo="AAPL", capital=10000, riesgo_pct=1))
    assert ("Stop" in t and "acciones" in t) or "mínimos del último año" in t


def test_dolar_ccl(ctx):
    assert "15,000.00" in texto(llamar("dolar_ccl", dias=5))


def test_seguir_y_glosario(ctx):
    assert "Ahora seguís AAPL" in texto(llamar("seguir_empresa", simbolo="AAPL"))
    assert "AAPL" in texto(llamar("empresas_seguidas"))
    assert texto(llamar("glosario", termino="rsi"))
