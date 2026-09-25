from datetime import datetime, timedelta, timezone

import pytest

from monitor_mercado.alertas.modelos import Condicion, Moneda, Operacion
from monitor_mercado.alertas.parser import SolicitudAlerta
from monitor_mercado.datos.modelos import SimboloSinDatos
from monitor_mercado.notificaciones import formato

# Viernes con los mercados de América abiertos.
ABIERTO = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)
SABADO = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)


def solicitud(simbolo="AAPL", condicion=Condicion.BAJA_DE, umbral=180.0, moneda=Moneda.USD, repetir=False):
    return SolicitudAlerta(simbolo, Operacion.COMPRA, condicion, umbral, moneda, repetir)


def test_crear_y_disparar_una_vez(servicio, proveedor):
    proveedor.fijar("AAPL", 200)
    r = servicio.crear(solicitud())
    assert r.alerta.armada and r.aviso is None

    assert servicio.revisar(ABIERTO) == []  # 200 > 180: nada
    proveedor.fijar("AAPL", 179)
    disparos = servicio.revisar(ABIERTO)
    assert len(disparos) == 1
    assert servicio.repo.listar() == []  # quedó desactivada
    assert servicio.revisar(ABIERTO) == []  # no se repite


def test_crear_con_condicion_ya_cumplida_queda_en_espera(servicio, proveedor):
    proveedor.fijar("AAPL", 170)
    r = servicio.crear(solicitud())
    assert not r.alerta.armada and "ya se cumple" in r.aviso
    assert servicio.revisar(ABIERTO) == []
    proveedor.fijar("AAPL", 190)  # vuelve a subir: se arma
    assert servicio.revisar(ABIERTO) == []
    proveedor.fijar("AAPL", 175)  # cruza hacia abajo: avisa
    assert len(servicio.revisar(ABIERTO)) == 1


def test_simbolo_inexistente_no_crea_alerta(servicio):
    with pytest.raises(SimboloSinDatos):
        servicio.crear(solicitud("NOEXISTE"))
    assert servicio.repo.listar(solo_activas=False) == []


def test_alerta_en_usd_sobre_accion_en_pesos(servicio, proveedor):
    proveedor.fijar("ALUA.BA", 1600, "ARS")  # 1600 / CCL 1600 = 1 USD
    servicio.crear(solicitud("ALUA.BA", Condicion.SUBE_DE, umbral=1.2))
    proveedor.fijar("ALUA.BA", 2000, "ARS")  # 1,25 USD
    [d] = servicio.revisar(ABIERTO)
    assert d.precio.precio == pytest.approx(1.25)


def test_alerta_en_pesos_usa_el_cedear(servicio, proveedor):
    proveedor.fijar("AAPL.BA", 27000, "ARS")
    r = servicio.crear(solicitud("AAPL", Condicion.SUBE_DE, umbral=28000, moneda=Moneda.ARS))
    assert r.precio_actual.cotizacion.simbolo == "AAPL.BA"
    proveedor.fijar("AAPL.BA", 28500, "ARS")
    [d] = servicio.revisar(ABIERTO)
    assert d.precio.precio == 28500


def test_no_consulta_con_mercado_cerrado(servicio, proveedor):
    proveedor.fijar("AAPL", 200)
    servicio.crear(solicitud())
    proveedor.fijar("AAPL", 100)
    proveedor.consultas.clear()
    assert servicio.revisar(SABADO) == []
    assert proveedor.consultas == []
    assert len(servicio.revisar(SABADO, forzar=True)) == 1


def test_repetitiva_con_enfriamiento_y_cruce(servicio, proveedor):
    proveedor.fijar("AAPL", 200)
    servicio.crear(solicitud(repetir=True))
    proveedor.fijar("AAPL", 170)
    assert len(servicio.revisar(ABIERTO)) == 1
    assert servicio.revisar(ABIERTO + timedelta(minutes=5)) == []  # sigue abajo: no repite
    proveedor.fijar("AAPL", 190)
    servicio.revisar(ABIERTO + timedelta(minutes=10))  # se re-arma
    proveedor.fijar("AAPL", 170)
    assert servicio.revisar(ABIERTO + timedelta(minutes=15)) == []  # enfriamiento (60 min)
    assert len(servicio.revisar(ABIERTO + timedelta(minutes=70))) == 1
    [a] = servicio.repo.listar()
    assert a.veces_disparada == 2


def test_mensaje_incluye_aviso_legal(servicio, proveedor):
    proveedor.fijar("AAPL", 200)
    servicio.crear(solicitud())
    proveedor.fijar("AAPL", 150)
    [d] = servicio.revisar(ABIERTO)
    texto = formato.mensaje_disparo(d)
    assert "no es una recomendación de inversión" in texto
    assert "US$ 150,00" in texto
