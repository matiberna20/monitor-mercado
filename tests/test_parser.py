import pytest

from monitor_mercado.alertas.modelos import Condicion, Moneda, Operacion
from monitor_mercado.alertas.parser import ErrorFormato, parsear_alerta, parsear_numero


def test_alerta_basica():
    s = parsear_alerta(["aapl", "compra", "baja", "180"])
    assert s.simbolo == "AAPL"
    assert s.operacion is Operacion.COMPRA
    assert s.condicion is Condicion.BAJA_DE
    assert s.umbral == 180
    assert s.moneda is Moneda.USD and not s.repetir


def test_alerta_en_pesos_y_repetitiva_en_cualquier_orden():
    s = parsear_alerta(["GGAL", "venta", "var-", "5", "repetir", "ARS"])
    assert s.condicion is Condicion.VARIACION_BAJA
    assert s.moneda is Moneda.ARS and s.repetir


@pytest.mark.parametrize(
    "texto, esperado",
    [("180", 180), ("180.5", 180.5), ("180,5", 180.5), ("27.000", 27000),
     ("27.000,50", 27000.5), ("1,234.5", 1234.5), ("$27000", 27000), ("5%", 5)],
)
def test_parsear_numero(texto, esperado):
    assert parsear_numero(texto) == pytest.approx(esperado)


@pytest.mark.parametrize(
    "args",
    [
        ["AAPL", "compra", "baja"],  # falta el valor
        ["AAPL", "comprar", "baja", "180"],  # operación inválida
        ["AAPL", "compra", "cruza", "180"],  # condición inválida
        ["AAPL", "compra", "baja", "abc"],  # número inválido
        ["AAPL", "compra", "baja", "-5"],  # número negativo
        ["AAPL", "compra", "baja", "180", "eur"],  # palabra desconocida
    ],
)
def test_errores_de_formato(args):
    with pytest.raises(ErrorFormato):
        parsear_alerta(args)
