from datetime import datetime, timezone

import pytest

from monitor_mercado.configuracion import ConfigMonedas
from monitor_mercado.datos.monedas import ConversorMonedas, simbolo_para_moneda
from monitor_mercado.mercados import esta_abierto, mercado_de

CFG = ConfigMonedas(simbolos_byma={"YPF": "YPFD.BA"})


@pytest.mark.parametrize(
    "simbolo, moneda, esperado",
    [
        ("AAPL", "USD", "AAPL"),
        ("AAPL", "ARS", "AAPL.BA"),  # CEDEAR
        ("BRK-B", "ARS", "BRKB.BA"),  # sin guion en BYMA
        ("YPF", "ARS", "YPFD.BA"),  # reemplazo configurado
        ("ALUA.BA", "ARS", "ALUA.BA"),
        ("ALUA.BA", "USD", "ALUA.BA"),
    ],
)
def test_simbolo_para_moneda(simbolo, moneda, esperado):
    assert simbolo_para_moneda(simbolo, moneda, CFG) == esperado


@pytest.mark.parametrize("simbolo", ["PETR4.SA", "VOW3.DE", "^IXIC"])
def test_pesos_solo_para_byma(simbolo):
    with pytest.raises(ValueError):
        simbolo_para_moneda(simbolo, "ARS", CFG)


def test_conversion_a_usd(proveedor):
    proveedor.fijar("GBPUSD=X", 1.30)
    proveedor.fijar("EURUSD=X", 1.10)
    conv = ConversorMonedas(proveedor, ConfigMonedas())
    assert conv.a_usd(100, "USD") == 100
    assert conv.a_usd(1600, "ARS") == pytest.approx(1.0)  # CCL = 6400*10/40 = 1600
    assert conv.a_usd(463.5, "GBp") == pytest.approx(4.635 * 1.30)  # peniques -> libras -> USD
    assert conv.a_usd(70, "EUR") == pytest.approx(77)


def test_tipo_de_cambio_se_cachea(proveedor):
    conv = ConversorMonedas(proveedor, ConfigMonedas())
    conv.a_usd(1000, "ARS")
    conv.a_usd(2000, "ARS")
    assert proveedor.consultas.count("GGAL.BA") == 1


def test_dolar_oficial(proveedor):
    proveedor.fijar("ARS=X", 1500, "ARS")
    conv = ConversorMonedas(proveedor, ConfigMonedas(dolar_ars="oficial"))
    assert conv.a_usd(3000, "ARS") == pytest.approx(2)


def test_mercado_por_sufijo():
    assert mercado_de("PETR4.SA").nombre == "B3"
    assert mercado_de("AAPL").nombre == "EE.UU."
    assert mercado_de("BARC.L").nombre == "Londres"


def test_horario_de_mercado():
    # Viernes 25/09/2026, 15:45 UTC = 11:45 Nueva York = 12:45 Buenos Aires
    # = 16:45 Londres (en septiembre rige el horario de verano británico, UTC+1).
    viernes = datetime(2026, 9, 25, 15, 45, tzinfo=timezone.utc)
    assert esta_abierto("AAPL", viernes)
    assert esta_abierto("ALUA.BA", viernes)
    assert not esta_abierto("BARC.L", viernes)  # Londres cierra 16:30
    assert esta_abierto("BARC.L", viernes, margen_minutos=20)
    sabado = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)
    assert not esta_abierto("AAPL", sabado)
