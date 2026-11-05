"""Diario de operaciones: costo promedio, resultado realizado, validaciones, importación y comandos."""

from datetime import date
from types import SimpleNamespace

import pytest

from monitor_mercado.alertas.parser import ErrorFormato
from monitor_mercado.cartera.servicio import ServicioCartera
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.db import crear_motor
from monitor_mercado.diario.calculo import ErrorDiario, calcular
from monitor_mercado.diario.modelos import Movimiento, TipoMovimiento
from monitor_mercado.diario.parser import parsear_edicion, parsear_movimiento
from monitor_mercado.diario.reporte import texto_diario
from monitor_mercado.diario.repositorio import RepositorioDiario
from monitor_mercado.diario.servicio import ServicioDiario

C, V = TipoMovimiento.COMPRA, TipoMovimiento.VENTA


def mov(i, fecha, tipo, simbolo, cantidad, precio, comision=0.0, moneda="USD"):
    return Movimiento(id=i, fecha=date.fromisoformat(fecha), tipo=tipo, simbolo=simbolo, cantidad=cantidad,
                      precio=precio, comision=comision, moneda=moneda)


def test_costo_promedio_y_resultado_realizado():
    c = calcular([
        mov(1, "2026-01-10", C, "AAPL", 10, 100, comision=10),  # costo 1010
        mov(2, "2026-02-10", C, "AAPL", 10, 120),  # costo 2210 -> promedio 110,5
        mov(3, "2026-03-10", V, "AAPL", 5, 130, comision=2.5),  # cobra 647,5; costo 552,5
    ])
    [venta] = c.cerradas
    assert venta.costo_promedio == pytest.approx(110.5)
    assert venta.resultado == pytest.approx(95) and venta.resultado_pct == pytest.approx(95 / 552.5)
    [t] = c.abiertas
    assert t.cantidad == 15 and t.costo_promedio == pytest.approx(110.5) and t.desde == date(2026, 1, 10)


def test_vender_todo_y_volver_a_comprar_arranca_de_cero():
    c = calcular([mov(1, "2026-01-01", C, "X", 10, 10), mov(2, "2026-01-02", V, "X", 10, 8),
                  mov(3, "2026-01-03", C, "X", 5, 20)])
    [t] = c.abiertas
    assert t.costo_promedio == pytest.approx(20) and t.desde == date(2026, 1, 3)
    assert c.cerradas[0].resultado == pytest.approx(-20)


def test_no_se_puede_vender_mas_de_lo_que_tenias():
    with pytest.raises(ErrorDiario, match="tenías 10"):
        calcular([mov(1, "2026-01-01", C, "X", 10, 10), mov(2, "2026-01-02", V, "X", 11, 10)])
    # El orden es por fecha: una venta anterior a la compra también falla.
    with pytest.raises(ErrorDiario):
        calcular([mov(1, "2026-01-05", C, "X", 10, 10), mov(2, "2026-01-02", V, "X", 1, 10)])


def test_compra_sin_precio_deja_el_resultado_desconocido():
    c = calcular([mov(1, "2026-01-01", C, "X", 10, None), mov(2, "2026-01-02", V, "X", 4, 10)])
    assert c.cerradas[0].resultado is None and c.abiertas[0].costo_promedio is None


def test_parser():
    s = parsear_movimiento(["aapl.e", "10", "180,5", "comision", "1,2", "fecha", "03/11/2026", "nota", "buen", "precio"])
    assert (s.simbolo, s.cantidad, s.precio, s.comision, s.fecha, s.nota) == \
        ("AAPL", 10, 180.5, 1.2, date(2026, 11, 3), "buen precio")
    assert parsear_movimiento(["ALUA.BA", "5", "800", "comision", "0"]).comision == 0
    with pytest.raises(ErrorFormato, match="Faltan"):
        parsear_movimiento(["AAPL", "10"])
    with pytest.raises(ErrorFormato, match="fecha válida"):
        parsear_movimiento(["AAPL", "1", "1", "fecha", "ayer"])
    assert parsear_edicion(["#3", "precio", "12,5"]) == (3, "precio", 12.5)
    assert parsear_edicion(["3", "nota", "otra", "cosa"]) == (3, "nota", "otra cosa")
    with pytest.raises(ErrorFormato, match="No se puede editar"):
        parsear_edicion(["3", "tipo", "venta"])


def _servicios(tmp_path, proveedor, fuente="diario"):
    cfg = Configuracion.model_validate({"cartera": {"fuente": fuente}})
    motor = crear_motor(":memory:")
    diario = ServicioDiario(RepositorioDiario(motor), proveedor, cfg)
    ruta = tmp_path / "c.csv"
    ruta.write_text("simbolo,cantidad,precio_compra,moneda,fecha_compra,nota\n"
                    "AAPL,10,100,USD,2025-03-15,\nBTC,2,,USD,,sin costo\n", encoding="utf-8")
    return diario, ServicioCartera(ruta, proveedor, cfg, motor, diario=diario), ruta


def test_registrar_editar_borrar_y_estadisticas(tmp_path, proveedor):
    diario, cartera, _ = _servicios(tmp_path, proveedor)
    a = diario.registrar(C, parsear_movimiento(["AAPL", "10", "100", "fecha", "2026-01-01"]))
    diario.registrar(C, parsear_movimiento(["NVDA", "10", "50", "fecha", "2026-01-01"]))
    diario.registrar(V, parsear_movimiento(["AAPL", "4", "150", "fecha", "2026-02-01"]))  # +200
    v = diario.registrar(V, parsear_movimiento(["NVDA", "10", "40", "fecha", "2026-02-01"]))  # -100
    with pytest.raises(ErrorDiario):
        diario.registrar(V, parsear_movimiento(["AAPL", "100", "1"]))
    with pytest.raises(ErrorDiario):  # bajar la compra a 2 acciones deja la venta de 4 sin respaldo
        diario.editar(a.id, "cantidad", 2.0)
    with pytest.raises(ErrorDiario):
        diario.borrar(a.id)

    e = diario.estadisticas(no_realizado=50.0)
    assert e.realizado == pytest.approx(100) and e.tasa_aciertos == pytest.approx(0.5)
    assert e.ganancia_promedio == pytest.approx(200) and e.perdida_promedio == pytest.approx(-100)
    assert e.mejores()[0].venta.movimiento.simbolo == "AAPL"
    assert diario.realizado_por_simbolo() == {"AAPL": pytest.approx(200), "NVDA": pytest.approx(-100)}

    diario.editar(v.id, "precio", 45.0)
    assert diario.estadisticas().realizado == pytest.approx(150)
    assert diario.borrar(v.id) and not diario.borrar(999)

    # La cartera se calcula desde el diario.
    [p] = [p for p in cartera.posiciones() if p.simbolo == "AAPL"]
    assert p.cantidad == 6 and p.precio_compra == pytest.approx(100)

    texto = texto_diario(diario.repo.listar(), diario.estadisticas(50.0))
    for parte in ("Diario de operaciones", "Realizado", "No realizado", "aciertos", "no es una recomendación"):
        assert parte in texto


def test_venta_en_pesos_se_pasa_a_dolares(tmp_path, proveedor):
    diario, _, _ = _servicios(tmp_path, proveedor)
    diario.registrar(C, parsear_movimiento(["ALUA.BA", "100", "800"]))
    diario.registrar(V, parsear_movimiento(["ALUA.BA", "100", "960"]))  # +16.000 pesos = +10 USD (CCL 1600)
    assert diario.repo.listar()[0].moneda == "ARS"
    assert diario.estadisticas().realizado == pytest.approx(10)


def test_importar_desde_la_cartera(tmp_path, proveedor):
    diario, cartera, ruta = _servicios(tmp_path, proveedor)
    importadas, salteadas = diario.importar_cartera(ruta)
    assert [m.simbolo for m in importadas] == ["AAPL", "BTC"] and salteadas == []
    assert importadas[0].fecha == date(2025, 3, 15) and importadas[1].precio is None
    _, salteadas = diario.importar_cartera(ruta)  # no duplica
    assert salteadas == ["AAPL", "BTC"]
    assert {p.simbolo: p.precio_compra for p in cartera.posiciones()} == {"AAPL": 100, "BTC": None}


def test_con_fuente_archivo_la_cartera_sigue_leyendo_el_csv(tmp_path, proveedor):
    diario, cartera, _ = _servicios(tmp_path, proveedor, fuente="archivo")
    diario.registrar(C, parsear_movimiento(["NVDA", "1", "1"]))
    assert {p.simbolo for p in cartera.posiciones()} == {"AAPL", "BTC"}


def test_comandos_de_telegram(tmp_path, proveedor, servicio):
    from tests.test_bot import _llamar
    from monitor_mercado.notificaciones import telegram_bot as bot

    diario, cartera, ruta = _servicios(tmp_path, proveedor)
    ctx = SimpleNamespace(diario=diario, cartera=cartera, cfg=SimpleNamespace(
        cartera=SimpleNamespace(ruta=lambda: ruta)))
    [r], _ = _llamar(bot.cmd_compre, servicio, ["AAPL", "10", "100", "nota", "prueba"], ctx=ctx)
    assert "Compra registrada" in r and "prueba" in r
    [r], _ = _llamar(bot.cmd_vendi, servicio, ["AAPL", "20", "100"], ctx=ctx)
    assert "tenías 10" in r
    [r], _ = _llamar(bot.cmd_vendi, servicio, ["AAPL", "5", "110"], ctx=ctx)
    assert "Venta registrada" in r
    [r], _ = _llamar(bot.cmd_editar_op, servicio, ["2", "precio", "120"], ctx=ctx)
    assert "corregida" in r
    [r], _ = _llamar(bot.cmd_editar_op, servicio, ["99", "precio", "120"], ctx=ctx)
    assert "No existe" in r
    proveedor.fijar("AAPL", 100)
    [r], _ = _llamar(bot.cmd_diario, servicio, [], ctx=ctx)
    assert "+US$ 100" in r and "aciertos: 100%" in r
    [r], _ = _llamar(bot.cmd_borrar_op, servicio, ["2"], ctx=ctx)
    assert "borrada" in r
    [r], _ = _llamar(bot.cmd_importar_diario, servicio, [], ctx=ctx)
    assert "Importé 1" in r and "AAPL" in r  # AAPL ya tenía operaciones
