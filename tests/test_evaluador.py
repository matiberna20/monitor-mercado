from datetime import datetime, timedelta, timezone

import pytest

from monitor_mercado.alertas.evaluador import condicion_cumplida, evaluar
from monitor_mercado.alertas.modelos import Alerta, Condicion, Moneda, Operacion

AHORA = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)
UNA_HORA = timedelta(hours=1)


def alerta(condicion=Condicion.BAJA_DE, umbral=100.0, repetir=False, armada=True, ultimo=None) -> Alerta:
    return Alerta(
        simbolo="AAPL", operacion=Operacion.COMPRA, condicion=condicion, umbral=umbral,
        moneda=Moneda.USD, repetir=repetir, activa=True, armada=armada, ultimo_disparo=ultimo,
    )


@pytest.mark.parametrize(
    "condicion, umbral, precio, variacion, esperado",
    [
        (Condicion.SUBE_DE, 100, 100, None, True),  # tocar el umbral cuenta
        (Condicion.SUBE_DE, 100, 99.99, None, False),
        (Condicion.BAJA_DE, 100, 100, None, True),
        (Condicion.BAJA_DE, 100, 100.01, None, False),
        (Condicion.VARIACION_SUBE, 3, 0, 3.5, True),
        (Condicion.VARIACION_SUBE, 3, 0, 2.9, False),
        (Condicion.VARIACION_BAJA, 3, 0, -3.0, True),
        (Condicion.VARIACION_BAJA, 3, 0, 3.0, False),  # subir 3% no es caer 3%
        (Condicion.VARIACION_BAJA, 3, 0, None, False),  # sin dato no se dispara
    ],
)
def test_condicion_cumplida(condicion, umbral, precio, variacion, esperado):
    assert condicion_cumplida(condicion, umbral, precio, variacion) is esperado


def test_alerta_simple_se_dispara_y_se_desactiva():
    d = evaluar(alerta(), precio=99, variacion_pct=None, ahora=AHORA, enfriamiento=UNA_HORA)
    assert d.disparar and not d.activa


def test_alerta_no_se_dispara_si_no_cumple():
    d = evaluar(alerta(), precio=101, variacion_pct=None, ahora=AHORA, enfriamiento=UNA_HORA)
    assert not d.disparar and d.activa and d.armada


def test_alerta_desarmada_espera_el_cruce():
    a = alerta(armada=False)
    # Sigue cumpliendo (el precio ya estaba abajo al crearla): no avisa ni se arma.
    d = evaluar(a, 95, None, AHORA, UNA_HORA)
    assert not d.disparar and not d.armada
    # El precio vuelve a subir por encima del umbral: se arma.
    d = evaluar(a, 105, None, AHORA, UNA_HORA)
    assert not d.disparar and d.armada


def test_alerta_repetitiva_queda_activa_y_desarmada():
    d = evaluar(alerta(repetir=True), 99, None, AHORA, UNA_HORA)
    assert d.disparar and d.activa and not d.armada


def test_alerta_repetitiva_respeta_el_enfriamiento():
    reciente = alerta(repetir=True, ultimo=AHORA - timedelta(minutes=30))
    assert not evaluar(reciente, 99, None, AHORA, UNA_HORA).disparar
    vieja = alerta(repetir=True, ultimo=AHORA - timedelta(minutes=61))
    assert evaluar(vieja, 99, None, AHORA, UNA_HORA).disparar


def test_enfriamiento_con_fecha_sin_zona_horaria():
    # SQLite devuelve las fechas sin zona horaria: no debe fallar la resta.
    a = alerta(repetir=True, ultimo=(AHORA - timedelta(minutes=10)).replace(tzinfo=None))
    assert not evaluar(a, 99, None, AHORA, UNA_HORA).disparar
