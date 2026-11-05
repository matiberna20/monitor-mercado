"""Tablas compartidas por el panel y la exportación a Excel."""

from datetime import date, timedelta

import pytest

from monitor_mercado import tablas
from monitor_mercado.cartera.servicio import ServicioCartera
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.db import crear_motor
from monitor_mercado.diario.modelos import TipoMovimiento
from monitor_mercado.diario.parser import parsear_movimiento
from monitor_mercado.diario.repositorio import RepositorioDiario
from monitor_mercado.diario.servicio import ServicioDiario
from monitor_mercado.dividendos.servicio import Cobro, ProximoCobro, ResumenDividendos


@pytest.fixture
def armado(tmp_path, proveedor):
    proveedor.fijar("AAPL", 110, cierre=100)
    proveedor.fijar("NVDA", 50)
    ruta = tmp_path / "c.csv"
    ruta.write_text("simbolo,cantidad,precio_compra,moneda,fecha_compra,nota\n"
                    "AAPL,10,100,USD,2026-01-02,\nNVDA,4,,USD,,\n", encoding="utf-8")
    cfg = Configuracion()
    motor = crear_motor(":memory:")
    diario = ServicioDiario(RepositorioDiario(motor), proveedor, cfg)
    return ServicioCartera(ruta, proveedor, cfg, motor, diario=diario), diario


def test_tabla_cartera_y_evolucion(armado):
    cartera, _ = armado
    estado = cartera.estado()
    t = tablas.tabla_cartera(estado)
    assert list(t["Símbolo"]) == ["AAPL", "NVDA"]
    aapl = t.iloc[0]
    assert aapl["Valor USD"] == 1100 and aapl["Costo USD"] == 1000 and aapl["Resultado %"] == 10
    assert aapl["Var. día %"] == 10 and aapl["Fecha de compra"] == date(2026, 1, 2)

    assert tablas.tabla_evolucion([]).empty
    hoy = date.today()
    cartera.guardar_foto(estado, hoy - timedelta(days=1))
    cartera.guardar_foto(estado, hoy)
    evo = tablas.tabla_evolucion(cartera.historial())
    assert len(evo) == 2 and list(evo.columns) == ["Valor USD", "Invertido USD"]


def test_diario_y_resultado_por_posicion(armado):
    cartera, diario = armado
    diario.registrar(TipoMovimiento.COMPRA, parsear_movimiento(["MSFT", "10", "100", "fecha", "2026-01-01"]))
    diario.registrar(TipoMovimiento.VENTA, parsear_movimiento(["MSFT", "10", "120", "fecha", "2026-02-01"]))
    ops = tablas.tabla_operaciones(diario.repo.listar())
    assert list(ops["Tipo"]) == ["venta", "compra"]  # la más nueva primero
    ventas = tablas.tabla_ventas(diario.estadisticas())
    assert ventas.iloc[0]["Resultado USD"] == pytest.approx(200)

    t = tablas.tabla_resultado_por_posicion(cartera.estado(), diario.realizado_por_simbolo(), {"AAPL": 5.0})
    por = t.set_index("Símbolo")
    assert por.loc["AAPL", "Total USD"] == pytest.approx(105)  # 100 de precio + 5 de dividendos
    assert por.loc["MSFT", "Realizado USD"] == pytest.approx(200) and por.loc["MSFT", "Valor actual USD"] == 0
    assert por.loc["NVDA", "Total USD"] != por.loc["NVDA", "Total USD"]  # NaN: sin costo no se sabe


def test_tablas_vacias_y_dividendos():
    assert tablas.tabla_operaciones([]).empty and tablas.tabla_alertas([]).empty and tablas.tabla_stops([]).empty
    r = ResumenDividendos(
        [Cobro("JPM", date(2026, 10, 6), 1.5, 10, "USD", 15.0)],
        [ProximoCobro("JPM", date(2027, 1, 5), None, 1.5, 10, "USD", 15.0, True)],
    )
    cobrados, proximos = tablas.tabla_dividendos(r)
    assert cobrados.iloc[0]["Monto USD"] == 15 and proximos.iloc[0]["Fecha"] == "estimada"


def test_el_panel_usa_las_tablas_compartidas():
    """El panel no tiene cálculos propios: solo importa streamlit si está instalado."""
    pytest.importorskip("streamlit")
    import monitor_mercado.panel as panel

    assert panel.tablas is tablas and callable(panel.main)
