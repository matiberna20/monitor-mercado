"""Stop-loss y trailing stop: creación, cruce, enfriamiento, defectos y comandos."""

from datetime import datetime, timedelta, timezone

import pytest

from monitor_mercado.cartera.servicio import ServicioCartera
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.db import crear_motor
from monitor_mercado.stops.modelos import TipoStop
from monitor_mercado.stops.reporte import mensaje_disparo_stop, texto_stops
from monitor_mercado.stops.repositorio import RepositorioStops
from monitor_mercado.stops.servicio import ErrorStop, ServicioStops

# Jueves 5/11/2026, 10:00 de Nueva York (mercado abierto).
ABIERTO = datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)


def armar(tmp_path, proveedor, contenido="AAPL,10,100,USD,,\nNVDA,5,,USD,,\n", **cartera):
    ruta = tmp_path / "cartera.csv"
    ruta.write_text("simbolo,cantidad,precio_compra,moneda,fecha_compra,nota\n" + contenido, encoding="utf-8")
    cfg = Configuracion.model_validate({"cartera": cartera, "alertas": {"enfriamiento_minutos_repetir": 60}})
    motor = crear_motor(":memory:")
    servicio_cartera = ServicioCartera(ruta, proveedor, cfg, motor)
    return ServicioStops(RepositorioStops(motor), proveedor, cfg, servicio_cartera)


def test_stop_loss_avisa_al_cruzar_y_no_repite(tmp_path, proveedor):
    proveedor.fijar("AAPL", 105)
    s = armar(tmp_path, proveedor)
    estado = s.crear("aapl", TipoStop.STOP_LOSS, 10)
    assert estado.nivel == pytest.approx(90) and estado.stop.armada

    proveedor.fijar("AAPL", 95)
    assert s.revisar(ABIERTO) == []
    proveedor.fijar("AAPL", 89)
    [d] = s.revisar(ABIERTO)
    assert d.estado.caida == pytest.approx(-0.11)
    assert "STOP-LOSS" in mensaje_disparo_stop(d) and "no se vendió nada" in mensaje_disparo_stop(d)
    # Sigue abajo: no vuelve a avisar.
    assert s.revisar(ABIERTO + timedelta(hours=2)) == []
    # Rebota por encima y vuelve a caer (pasado el enfriamiento): avisa otra vez.
    proveedor.fijar("AAPL", 92)
    assert s.revisar(ABIERTO + timedelta(hours=3)) == []
    proveedor.fijar("AAPL", 88)
    assert len(s.revisar(ABIERTO + timedelta(hours=4))) == 1


def test_trailing_sigue_al_maximo(tmp_path, proveedor):
    proveedor.fijar("NVDA", 100)
    s = armar(tmp_path, proveedor)
    s.crear("NVDA", TipoStop.TRAILING, 10)  # sin precio de compra: igual se puede
    proveedor.fijar("NVDA", 150)
    assert s.revisar(ABIERTO) == []  # nuevo máximo: el stop sube a 135
    proveedor.fijar("NVDA", 136)
    assert s.revisar(ABIERTO) == []
    proveedor.fijar("NVDA", 134)
    [d] = s.revisar(ABIERTO)
    assert d.estado.referencia == pytest.approx(150) and d.estado.nivel == pytest.approx(135)


def test_respeta_el_horario_de_mercado(tmp_path, proveedor):
    proveedor.fijar("AAPL", 100)
    s = armar(tmp_path, proveedor)
    s.crear("AAPL", TipoStop.STOP_LOSS, 5)
    proveedor.fijar("AAPL", 80)
    sabado = datetime(2026, 11, 7, 18, 0, tzinfo=timezone.utc)
    assert s.revisar(sabado) == []
    assert len(s.revisar(sabado, forzar=True)) == 1


def test_si_ya_esta_abajo_espera_el_cruce(tmp_path, proveedor):
    proveedor.fijar("AAPL", 80)
    s = armar(tmp_path, proveedor)
    assert not s.crear("AAPL", TipoStop.STOP_LOSS, 10).stop.armada
    assert s.revisar(ABIERTO) == []


def test_errores_al_crear(tmp_path, proveedor):
    proveedor.fijar("AAPL", 100)
    proveedor.fijar("NVDA", 100)
    s = armar(tmp_path, proveedor)
    with pytest.raises(ErrorStop, match="no está en tu cartera"):
        s.crear("MSFT", TipoStop.STOP_LOSS, 10)
    with pytest.raises(ErrorStop, match="precio de compra"):
        s.crear("NVDA", TipoStop.STOP_LOSS, 10)
    with pytest.raises(ErrorStop, match="entre 0 y 100"):
        s.crear("AAPL", TipoStop.STOP_LOSS, 150)


def test_crear_dos_veces_reemplaza(tmp_path, proveedor):
    proveedor.fijar("AAPL", 100)
    s = armar(tmp_path, proveedor)
    s.crear("AAPL", TipoStop.STOP_LOSS, 10)
    s.crear("AAPL", TipoStop.STOP_LOSS, 20)
    [e] = s.estados()
    assert e.stop.porcentaje == pytest.approx(0.20)


def test_stops_por_defecto_desde_config(tmp_path, proveedor):
    proveedor.fijar("AAPL", 100)
    proveedor.fijar("NVDA", 100)
    s = armar(tmp_path, proveedor, stop_loss_por_defecto=15, trailing_por_defecto=20)
    estados = s.estados()
    tipos = sorted((e.stop.simbolo, e.stop.tipo.value) for e in estados)
    # NVDA no tiene precio de compra: solo trailing.
    assert tipos == [("AAPL", "stop_loss"), ("AAPL", "trailing"), ("NVDA", "trailing")]
    # Borrar uno por defecto lo desactiva y no se vuelve a crear.
    aapl_sl = next(e.stop for e in estados if e.stop.simbolo == "AAPL" and e.stop.tipo is TipoStop.STOP_LOSS)
    assert s.borrar(aapl_sl.id)
    assert len(s.estados()) == 2
    texto = texto_stops(s.estados())
    assert "(por defecto)" in texto and "no es una recomendación" in texto


def test_moneda_local_se_convierte_a_usd(tmp_path, proveedor):
    proveedor.fijar("ALUA.BA", 1600, "ARS")  # CCL 1600 -> 1 USD
    s = armar(tmp_path, proveedor, contenido="ALUA.BA,100,1000,ARS,,\n")
    e = s.crear("ALUA.BA", TipoStop.STOP_LOSS, 10)
    assert e.precio == pytest.approx(1.0) and e.referencia == pytest.approx(1000 / 1600)


def test_comandos_de_telegram(tmp_path, proveedor, servicio):
    from types import SimpleNamespace

    from tests.test_bot import _llamar
    from monitor_mercado.notificaciones import telegram_bot as bot

    proveedor.fijar("AAPL", 100)
    ctx = SimpleNamespace(stops=armar(tmp_path, proveedor), buscador=None)
    [r], _ = _llamar(bot.cmd_stop, servicio, ["AAPL", "10"], ctx=ctx)
    assert "Stop-loss guardado" in r and "US$ 90,00" in r
    [r], _ = _llamar(bot.cmd_trailing, servicio, ["AAPL", "8,5"], ctx=ctx)
    assert "Trailing stop guardado" in r
    [r], _ = _llamar(bot.cmd_stops, servicio, [], ctx=ctx)
    assert r.count("AAPL") == 2
    [r], _ = _llamar(bot.cmd_stop, servicio, ["AAPL"], ctx=ctx)
    assert r.startswith("Uso")
    [r], _ = _llamar(bot.cmd_borrar_stop, servicio, ["1"], ctx=ctx)
    assert "borrado" in r
    # /revisar avisa también los stops.
    proveedor.fijar("AAPL", 50)
    [r], enviados = _llamar(bot.cmd_revisar, servicio, [], ctx=ctx)
    assert "1 alerta(s)" in r and "TRAILING STOP" in enviados[0][1]
