from datetime import datetime, timezone

from monitor_mercado.alertas.modelos import Condicion
from monitor_mercado.alertas.parser import parsear_alerta
from monitor_mercado.notificaciones import formato

ABIERTO = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)


def test_parser_llega_deja_la_direccion_sin_resolver():
    s = parsear_alerta(["AAPL", "compra", "llega", "180"])
    assert s.condicion is None


def test_parser_nota_toma_el_resto_del_texto():
    s = parsear_alerta(["NVDA", "compra", "baja", "200", "repetir", "nota", "soporte", "semanal"])
    assert s.repetir and s.nota == "soporte semanal"


def test_llega_desde_arriba_se_guarda_como_baja_de(servicio, proveedor):
    proveedor.fijar("AAPL", 340)
    r = servicio.crear(parsear_alerta(["AAPL", "compra", "llega", "300"]))
    assert r.alerta.condicion is Condicion.BAJA_DE and r.alerta.armada
    assert "baja de" in r.aviso
    proveedor.fijar("AAPL", 299)
    assert len(servicio.revisar(ABIERTO)) == 1


def test_llega_desde_abajo_se_guarda_como_sube_de(servicio, proveedor):
    proveedor.fijar("AAPL", 340)
    r = servicio.crear(parsear_alerta(["AAPL", "venta", "llega", "380"]))
    assert r.alerta.condicion is Condicion.SUBE_DE and r.alerta.armada
    proveedor.fijar("AAPL", 381)
    assert len(servicio.revisar(ABIERTO)) == 1


def test_todas_las_salidas_llevan_aviso_legal(servicio, proveedor):
    proveedor.fijar("AAPL", 340)
    r = servicio.crear(parsear_alerta(["AAPL", "compra", "baja", "300", "nota", "prueba"]))
    textos = [
        formato.mensaje_creada(r),
        formato.mensaje_listado(servicio.repo.listar()),
        formato.mensaje_revision(0),
    ]
    for texto in textos:
        assert "no es una recomendación de inversión" in texto
    assert "Nota: prueba" in textos[0]
