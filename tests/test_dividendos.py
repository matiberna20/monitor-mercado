"""Dividendos: cobrados, próximos, rendimiento total y degradación si falla la fuente."""

from datetime import date
from types import SimpleNamespace

import pytest

from monitor_mercado.cartera.reporte import texto_cartera, texto_resumen_dia
from monitor_mercado.cartera.servicio import ServicioCartera
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.db import crear_motor
from monitor_mercado.diario.modelos import TipoMovimiento
from monitor_mercado.diario.parser import parsear_movimiento
from monitor_mercado.diario.repositorio import RepositorioDiario
from monitor_mercado.diario.servicio import ServicioDiario
from monitor_mercado.dividendos.fuente import Anunciado, Dividendo
from monitor_mercado.dividendos.reporte import texto_dividendos
from monitor_mercado.dividendos.servicio import ServicioDividendos

HOY = date(2026, 11, 5)


class FuenteFalsa:
    def __init__(self, historiales, anuncios=None, falla=()):
        self.historiales, self.anuncios, self.falla = historiales, anuncios or {}, set(falla)

    def historial(self, s):
        if s in self.falla:
            raise RuntimeError("Yahoo caído")
        return self.historiales.get(s, [])

    def anunciado(self, s):
        return self.anuncios.get(s)


def trimestral(monto, *fechas):
    return [Dividendo(date.fromisoformat(f), monto) for f in fechas]


def armar(tmp_path, proveedor, fuente, contenido, fuente_cartera="archivo"):
    ruta = tmp_path / "c.csv"
    ruta.write_text("simbolo,cantidad,precio_compra,moneda,fecha_compra,nota\n" + contenido, encoding="utf-8")
    cfg = Configuracion.model_validate({"cartera": {"fuente": fuente_cartera}})
    motor = crear_motor(":memory:")
    diario = ServicioDiario(RepositorioDiario(motor), proveedor, cfg)
    cartera = ServicioCartera(ruta, proveedor, cfg, motor, diario=diario)
    return ServicioDividendos(fuente, proveedor, cfg, cartera, diario), cartera, diario


def test_cobrados_proximos_y_rendimiento(tmp_path, proveedor):
    proveedor.fijar("JPM", 110)
    proveedor.fijar("MSFT", 500)
    proveedor.fijar("NVDA", 100)
    fuente = FuenteFalsa(
        {"JPM": trimestral(1.0, "2025-10-06", "2026-01-06", "2026-04-06", "2026-07-06", "2026-10-06"),
         "MSFT": trimestral(0.8, "2025-11-20", "2026-02-19", "2026-05-21", "2026-08-20")},
        anuncios={"MSFT": Anunciado(date(2026, 11, 19), date(2026, 12, 10))},
    )
    # JPM comprada en marzo: cobra abril, julio y octubre. MSFT sin fecha: últimos 12 meses.
    s, cartera, _ = armar(tmp_path, proveedor, fuente,
                          "JPM,10,100,USD,2026-03-01,\nMSFT,5,400,USD,,\nNVDA,1,90,USD,,\n")
    r = s.resumen(HOY)
    por = {}
    for c in r.cobrados:
        por[c.simbolo] = por.get(c.simbolo, 0) + c.monto_usd
    assert por == {"JPM": pytest.approx(30), "MSFT": pytest.approx(16)}  # MSFT: 4 pagos x 0,8 x 5
    prox = {p.simbolo: p for p in r.proximos}
    assert prox["MSFT"].fecha_ex == date(2026, 11, 19) and not prox["MSFT"].estimado
    assert prox["JPM"].estimado and prox["JPM"].fecha_ex == date(2027, 1, 5)  # cada ~92 días
    assert "NVDA" not in prox
    assert prox["MSFT"].monto_usd == pytest.approx(4.0)

    estado = cartera.estado()
    rt = s.rendimiento_total(estado, HOY)
    assert rt.por_simbolo == {"JPM": pytest.approx(30), "MSFT": pytest.approx(16)}
    assert rt.sin_fecha == ["MSFT"]
    # Precio: JPM +100, MSFT +500, NVDA +10 = 610; dividendos 46; costo 1000+2000+90.
    assert rt.total == pytest.approx(656) and rt.total_pct == pytest.approx(656 / 3090)

    texto = texto_dividendos(r, rt)
    for parte in ("Próximos cobros", "fecha estimada", "Cobrados en los últimos 12 meses", "retenciones",
                  "Rendimiento total", "no es una recomendación"):
        assert parte in texto
    assert "Rendimiento total (precio + dividendos)" in texto_cartera(estado, rt)


def test_usa_el_diario_para_saber_cuantas_tenias(tmp_path, proveedor):
    proveedor.fijar("JPM", 110)
    fuente = FuenteFalsa({"JPM": trimestral(1.0, "2026-04-06", "2026-07-06", "2026-10-06")})
    s, cartera, diario = armar(tmp_path, proveedor, fuente, "", fuente_cartera="diario")
    diario.registrar(TipoMovimiento.COMPRA, parsear_movimiento(["JPM", "10", "100", "fecha", "2026-03-01"]))
    diario.registrar(TipoMovimiento.COMPRA, parsear_movimiento(["JPM", "10", "100", "fecha", "2026-08-01"]))
    r = s.resumen(HOY)
    assert [c.cantidad for c in r.cobrados] == [20, 10, 10]  # octubre con 20, abril y julio con 10
    assert s.rendimiento_total(cartera.estado(), HOY).dividendos == pytest.approx(40)


def test_moneda_local_y_fuente_caida(tmp_path, proveedor):
    proveedor.fijar("ALUA.BA", 1600, "ARS")
    proveedor.fijar("AAPL", 100)
    fuente = FuenteFalsa({"ALUA.BA": trimestral(160, "2026-06-01")}, falla={"AAPL"})
    s, _, _ = armar(tmp_path, proveedor, fuente, "ALUA.BA,100,1000,ARS,,\nAAPL,1,90,USD,,\n")
    r = s.resumen(HOY)
    assert r.cobrados[0].monto_usd == pytest.approx(10)  # 160 x 100 pesos / 1600
    assert r.errores == ["AAPL"] and "No se pudieron consultar: AAPL" in texto_dividendos(r)


def test_contexto_degrada_si_falla(tmp_path, proveedor):
    from monitor_mercado.aplicacion import Contexto

    class Roto:
        def rendimiento_total(self, estado):
            raise RuntimeError("sin red")

    ctx = Contexto.__new__(Contexto)
    ctx.dividendos = Roto()
    assert ctx.rendimiento(None) is None


def test_resumen_de_cierre_incluye_el_rendimiento(tmp_path, proveedor):
    proveedor.fijar("JPM", 110, cierre=100)
    fuente = FuenteFalsa({"JPM": trimestral(1.0, "2026-10-06")})
    s, cartera, _ = armar(tmp_path, proveedor, fuente, "JPM,10,100,USD,2026-03-01,\n")
    r = cartera.resumen_dia(con_noticias=False)
    texto = texto_resumen_dia(r, rendimiento=s.rendimiento_total(r.estado, HOY))
    assert "Dividendos cobrados desde la compra" in texto and "retenciones" in texto


def test_comando_telegram(tmp_path, proveedor, servicio):
    from tests.test_bot import _llamar
    from monitor_mercado.notificaciones import telegram_bot as bot

    proveedor.fijar("JPM", 110)
    s, cartera, _ = armar(tmp_path, proveedor, FuenteFalsa({"JPM": trimestral(1.0, "2026-10-06")}),
                          "JPM,10,100,USD,2026-03-01,\n")
    ctx = SimpleNamespace(dividendos=s, cartera=cartera, rendimiento=lambda e: s.rendimiento_total(e, HOY))
    respuestas, _ = _llamar(bot.cmd_dividendos, servicio, [], ctx=ctx)
    assert "Dividendos de tu cartera" in respuestas[-1]
    respuestas, _ = _llamar(bot.cmd_cartera, servicio, [], ctx=ctx)
    assert "Rendimiento total" in respuestas[-1]
