"""Exportación a Excel: hojas, contenido, degradación y envío por Telegram."""

import asyncio
from datetime import date
from types import SimpleNamespace

import openpyxl
import pytest

from monitor_mercado.cartera.servicio import ServicioCartera
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.db import crear_motor
from monitor_mercado.diario.modelos import TipoMovimiento
from monitor_mercado.diario.parser import parsear_movimiento
from monitor_mercado.diario.repositorio import RepositorioDiario
from monitor_mercado.diario.servicio import ServicioDiario
from monitor_mercado.dividendos.servicio import Cobro, ResumenDividendos, RendimientoTotal
from monitor_mercado.exportar import exportar


def armar_ctx(tmp_path, proveedor, dividendos_fallan=False):
    proveedor.fijar("AAPL", 110, cierre=100)
    ruta = tmp_path / "c.csv"
    ruta.write_text("simbolo,cantidad,precio_compra,moneda,fecha_compra,nota\nAAPL,10,100,USD,,\n", encoding="utf-8")
    cfg = Configuracion()
    motor = crear_motor(":memory:")
    diario = ServicioDiario(RepositorioDiario(motor), proveedor, cfg)
    diario.registrar(TipoMovimiento.COMPRA, parsear_movimiento(["MSFT", "2", "100", "fecha", "2026-01-01"]))
    diario.registrar(TipoMovimiento.VENTA, parsear_movimiento(["MSFT", "2", "150", "fecha", "2026-02-01"]))

    class Dividendos:
        def resumen(self):
            if dividendos_fallan:
                raise RuntimeError("Yahoo caído")
            return ResumenDividendos([Cobro("AAPL", date(2026, 8, 10), 0.26, 10, "USD", 2.6)], [])

    rendimiento = RendimientoTotal(100, 1000, 2.6, 2.6, {"AAPL": 2.6}, [])
    return SimpleNamespace(cartera=ServicioCartera(ruta, proveedor, cfg, motor), diario=diario,
                           dividendos=Dividendos(), rendimiento=lambda e: rendimiento,
                           cfg=SimpleNamespace(rutas=SimpleNamespace(ruta_exports=lambda: tmp_path / "exports")))


def _hoja(libro, nombre):
    filas = list(libro[nombre].iter_rows(values_only=True))
    return filas[0], filas[1:]


def test_excel_con_todas_las_hojas(tmp_path, proveedor):
    ruta = exportar(armar_ctx(tmp_path, proveedor), tmp_path / "exports")
    assert ruta.parent == tmp_path / "exports" and ruta.name.startswith("cartera_") and ruta.suffix == ".xlsx"
    libro = openpyxl.load_workbook(ruta)
    assert libro.sheetnames == ["Cartera", "Operaciones", "Dividendos", "Resultado por posición", "Notas"]

    encabezado, filas = _hoja(libro, "Cartera")
    fila = dict(zip(encabezado, filas[0]))
    assert fila["Símbolo"] == "AAPL" and fila["Valor USD"] == 1100 and fila["Resultado USD"] == 100

    encabezado, filas = _hoja(libro, "Operaciones")
    assert [dict(zip(encabezado, f))["Tipo"] for f in filas] == ["venta", "compra"]

    encabezado, filas = _hoja(libro, "Dividendos")
    assert dict(zip(encabezado, filas[0]))["Estado"] == "cobrado"

    encabezado, filas = _hoja(libro, "Resultado por posición")
    por = {f[0]: dict(zip(encabezado, f)) for f in filas}
    assert por["AAPL"]["Total USD"] == pytest.approx(102.6) and por["MSFT"]["Realizado USD"] == pytest.approx(100)

    _, notas = _hoja(libro, "Notas")
    assert any("no es una recomendación" in (n[0] or "") for n in notas)
    assert libro["Cartera"].freeze_panes == "A2"


def test_si_fallan_los_dividendos_exporta_igual(tmp_path, proveedor):
    libro = openpyxl.load_workbook(exportar(armar_ctx(tmp_path, proveedor, dividendos_fallan=True), tmp_path))
    _, filas = _hoja(libro, "Dividendos")
    assert "Yahoo caído" in filas[0][0]


def test_comando_telegram_manda_el_archivo(tmp_path, proveedor, servicio):
    from tests.test_bot import MensajeFalso
    from monitor_mercado.notificaciones import telegram_bot as bot

    class MensajeConArchivos(MensajeFalso):
        async def reply_document(self, document, filename, caption):
            self.respuestas.append(f"[archivo {filename} {len(document.read())} bytes]")

    mensaje = MensajeConArchivos()
    update = SimpleNamespace(effective_message=mensaje, effective_chat=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"ctx": armar_ctx(tmp_path, proveedor)}))
    asyncio.run(bot.cmd_exportar(update, context))
    assert mensaje.respuestas[0] == "Armando el Excel..."
    assert mensaje.respuestas[1].startswith("[archivo cartera_") and ".xlsx" in mensaje.respuestas[1]
