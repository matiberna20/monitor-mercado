"""Prueba de estrés: beta, escenarios, correlaciones y reporte."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from monitor_mercado.cartera.servicio import ServicioCartera
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.datos.modelos import SimboloSinDatos
from monitor_mercado.db import crear_motor
from monitor_mercado.riesgo.estres import ServicioEstres, calcular_beta, retornos_semanales
from monitor_mercado.riesgo.reporte import texto_estres

FECHAS = pd.date_range("2024-01-01", periods=600, freq="B")


def precios(retornos_diarios) -> pd.DataFrame:
    return pd.DataFrame({"cierre": 100 * np.cumprod(1 + retornos_diarios)}, index=FECHAS)


def test_beta_de_un_activo_que_duplica_al_mercado():
    rng = np.random.default_rng(1)
    mercado = rng.normal(0, 0.01, len(FECHAS))
    rm = retornos_semanales(precios(mercado)["cierre"], 104)
    ra = retornos_semanales(precios(2 * mercado)["cierre"], 104)
    assert len(rm) == 104
    assert calcular_beta(ra, rm) == pytest.approx(2, abs=0.15)
    assert calcular_beta(ra.iloc[:10], rm) is None  # muy pocas semanas


class AlmacenFalso:
    def __init__(self, series):
        self.series = series

    def obtener(self, s, forzar=False):
        if s not in self.series:
            raise SimboloSinDatos(s)
        return self.series[s]


def test_escenarios_y_riesgo(tmp_path, proveedor):
    rng = np.random.default_rng(7)
    mercado = rng.normal(0, 0.01, len(FECHAS))
    local = rng.normal(0, 0.02, len(FECHAS))
    almacen = AlmacenFalso({
        "SPY": precios(mercado), "^MERV": precios(local),
        "NVDA": precios(2 * mercado), "JNJ": precios(0.5 * mercado + rng.normal(0, 0.002, len(FECHAS))),
        "ALUA.BA": precios(local),
    })
    proveedor.fijar("NVDA", 100)
    proveedor.fijar("JNJ", 100)
    proveedor.fijar("ALUA.BA", 1600, "ARS")  # 1 USD
    proveedor.fijar("XXX", 50)  # sin historial: beta 1
    ruta = tmp_path / "c.csv"
    ruta.write_text("simbolo,cantidad,precio_compra,moneda,fecha_compra,nota\n"
                    "NVDA,40,,USD,,\nJNJ,40,,USD,,\nALUA.BA,1000,,ARS,,\nXXX,20,,USD,,\n", encoding="utf-8")
    cfg = Configuracion()
    cartera = ServicioCartera(ruta, proveedor, cfg, crear_motor(":memory:"))
    r = ServicioEstres(almacen, cartera, proveedor, cfg).correr()

    por = {p.simbolo: p for p in r.posiciones}
    assert r.valor == pytest.approx(4000 + 4000 + 1000 + 1000)
    assert por["NVDA"].beta == pytest.approx(2, abs=0.2) and por["NVDA"].referencia == "SPY"
    assert por["ALUA.BA"].beta == pytest.approx(1, abs=0.05) and por["ALUA.BA"].referencia == "^MERV"
    assert por["XXX"].beta_estimada and por["XXX"].beta == 1
    assert por["ALUA.BA"].en_pesos and not por["NVDA"].en_pesos

    caida_20, dolar = r.escenarios[1], r.escenarios[-1]
    assert caida_20.nombre == "Mercado −20%"
    esperado = -0.2 * (por["NVDA"].beta * 4000 + por["JNJ"].beta * 4000 + por["ALUA.BA"].beta * 1000 + 1000)
    assert caida_20.perdida == pytest.approx(esperado)
    assert caida_20.aportes[0][0] == "NVDA"  # la que más pierde
    assert dolar.perdida == pytest.approx(-1000 * (1 - 1 / 1.3))
    assert [s for s, _ in dolar.aportes] == ["ALUA.BA"]

    # Correlaciones: NVDA (beta 2) aporta más riesgo que su peso; JNJ menos.
    assert por["NVDA"].aporte_riesgo > por["NVDA"].peso and por["JNJ"].aporte_riesgo < por["JNJ"].peso
    assert sum(p.aporte_riesgo for p in r.posiciones if p.aporte_riesgo is not None) == pytest.approx(1)
    assert r.var_mensual_pct < 0 and r.volatilidad_anual > 0

    texto = texto_estres(r)
    for parte in ("Mercado −10%", "Dólar +30%", "Un mes malo", "se supuso 1", "no una predicción",
                  "no es una recomendación"):
        assert parte in texto


def test_comando_telegram_degrada_si_falla(servicio):
    from tests.test_bot import _llamar
    from monitor_mercado.notificaciones import telegram_bot as bot

    class Roto:
        def correr(self):
            raise RuntimeError("Yahoo caído")

    respuestas, _ = _llamar(bot.cmd_estres, servicio, [], ctx=SimpleNamespace(estres=Roto()))
    assert "No se pudo correr la prueba de estrés: Yahoo caído" in respuestas[-1]
