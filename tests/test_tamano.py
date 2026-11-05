"""Calculadora de tamaño de posición."""

import pytest

from monitor_mercado.alertas.parser import ErrorFormato
from monitor_mercado.cartera.servicio import ServicioCartera
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.db import crear_motor
from monitor_mercado.riesgo.reporte import texto_tamano
from monitor_mercado.riesgo.tamano import ServicioTamano, calcular, parsear_tamano


def test_parsear():
    s = parsear_tamano(["aapl", "entrada", "200", "stop", "185", "riesgo", "1%"])
    assert (s.simbolo, s.entrada, s.stop, s.riesgo, s.riesgo_es_pct, s.capital) == ("AAPL", 200, 185, 0.01, True, None)
    s = parsear_tamano(["AAPL", "riesgo", "500", "stop", "185,5", "entrada", "200", "capital", "20.000"])
    assert s.riesgo == 500 and not s.riesgo_es_pct and s.stop == 185.5 and s.capital == 20000


@pytest.mark.parametrize("args, error", [
    ([], "Faltan"), (["AAPL", "entrada", "200"], "Falta: stop, riesgo"),
    (["AAPL", "entrada", "200", "stop"], "con su nombre"),
    (["AAPL", "entrada", "200", "stop", "210", "riesgo", "1%"], "por debajo"),
    (["AAPL", "entrada", "200", "stop", "190", "riesgo", "1%", "plazo", "3"], "No entiendo"),
    (["AAPL", "entrada", "200", "stop", "190", "riesgo", "150%"], "menor a 100"),
])
def test_parsear_errores(args, error):
    with pytest.raises(ErrorFormato, match=error):
        parsear_tamano(args)


def test_calcular_puro():
    assert calcular(200, 185, 100_000, 1000) == (66, False)  # 1000 / 15 = 66,6
    assert calcular(200, 190, 1_000, 1000) == (5, True)  # el capital solo paga 5 acciones


def _servicio(tmp_path, proveedor, contenido="", limite=0.25):
    ruta = tmp_path / "c.csv"
    ruta.write_text("simbolo,cantidad,precio_compra,moneda,fecha_compra,nota\n" + contenido, encoding="utf-8")
    cfg = Configuracion.model_validate({"cartera": {"concentracion_maxima": limite}})
    return ServicioTamano(proveedor, cfg, ServicioCartera(ruta, proveedor, cfg, crear_motor(":memory:")))


def test_usa_el_valor_de_la_cartera_y_avisa_concentracion(tmp_path, proveedor):
    proveedor.fijar("AAPL", 200)
    proveedor.fijar("MSFT", 100)
    s = _servicio(tmp_path, proveedor, "MSFT,90,,USD,,\nAAPL,5,,USD,,\n")  # cartera: 9000 + 1000
    c = s.calcular(parsear_tamano(["AAPL", "entrada", "200", "stop", "190", "riesgo", "2%"]))
    assert c.capital == pytest.approx(10_000) and c.riesgo == pytest.approx(200)
    assert c.acciones == 20 and c.monto == pytest.approx(4000) and c.perdida_maxima == pytest.approx(200)
    assert c.peso == pytest.approx((1000 + 4000) / 10_000) and c.supera_limite
    texto = texto_tamano(c)
    assert "Acciones: 20" in texto and "Concentración" in texto and "no es una recomendación" in texto


def test_convierte_la_moneda_del_activo(tmp_path, proveedor):
    proveedor.fijar("ALUA.BA", 800, "ARS")  # CCL 1600
    s = _servicio(tmp_path, proveedor)
    c = s.calcular(parsear_tamano(["ALUA.BA", "entrada", "800", "stop", "640", "riesgo", "100", "capital", "10000"]))
    # Riesgo por acción: 160 pesos = 0,10 USD -> 1000 acciones; monto 1000 * 0,5 USD.
    assert c.acciones == 1000 and c.monto == pytest.approx(500) and not c.supera_limite
    assert "$ 800,00" in texto_tamano(c)


def test_sin_cartera_pide_el_capital(tmp_path, proveedor):
    proveedor.fijar("AAPL", 200)
    with pytest.raises(ValueError, match="capital"):
        _servicio(tmp_path, proveedor).calcular(parsear_tamano(["AAPL", "entrada", "200", "stop", "190",
                                                                "riesgo", "1%"]))


def test_comando_telegram(tmp_path, proveedor, servicio):
    from types import SimpleNamespace

    from tests.test_bot import _llamar
    from monitor_mercado.notificaciones import telegram_bot as bot

    proveedor.fijar("AAPL", 200)
    ctx = SimpleNamespace(tamano=_servicio(tmp_path, proveedor))
    [r], _ = _llamar(bot.cmd_tamano, servicio,
                     ["AAPL", "entrada", "200", "stop", "190", "riesgo", "100", "capital", "50000"], ctx=ctx)
    assert "Acciones: 10" in r
    [r], _ = _llamar(bot.cmd_tamano, servicio, ["AAPL", "entrada", "200"], ctx=ctx)
    assert "Falta" in r
