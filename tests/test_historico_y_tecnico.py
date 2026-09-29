from datetime import datetime

import pandas as pd
import pytest

from monitor_mercado.datos.modelos import ErrorDatos, SimboloSinDatos
from monitor_mercado.notificaciones.telegram_bot import partir_mensaje
from monitor_mercado.tecnico.grafico import generar_grafico
from monitor_mercado.tecnico.historico import AlmacenHistorico
from monitor_mercado.tecnico.servicio import ServicioTecnico, moneda_nativa


class FuenteFalsa:
    """Devuelve series fijadas a mano y registra las descargas."""

    def __init__(self, series: dict[str, pd.DataFrame]) -> None:
        self.series = series
        self.pedidos: list[tuple[str, datetime | None]] = []
        self.falla = False

    def descargar(self, simbolo, desde, anios):
        self.pedidos.append((simbolo, desde))
        if self.falla:
            raise ErrorDatos("sin conexión")
        if simbolo not in self.series:
            raise SimboloSinDatos(simbolo)
        df = self.series[simbolo]
        return df if desde is None else df[df.index >= pd.Timestamp(desde)]


def test_descarga_inicial_e_incremental(tmp_path, datos_ohlcv):
    df = datos_ohlcv(300)
    fuente = FuenteFalsa({"AAPL": df.iloc[:250]})
    almacen = AlmacenHistorico(tmp_path, fuente, refresco_horas=0.000001)
    assert len(almacen.obtener("AAPL")) == 250
    assert fuente.pedidos[-1][1] is None  # primera vez: toda la historia

    fuente.series["AAPL"] = df  # aparecen ruedas nuevas
    actualizado = almacen.obtener("AAPL")
    assert len(actualizado) == 300 and not actualizado.index.duplicated().any()
    assert fuente.pedidos[-1][1] is not None  # segunda vez: incremental


def test_cache_reciente_no_descarga(tmp_path, datos_ohlcv):
    fuente = FuenteFalsa({"AAPL": datos_ohlcv(100)})
    almacen = AlmacenHistorico(tmp_path, fuente, refresco_horas=6)
    almacen.obtener("AAPL")
    almacen.obtener("AAPL")
    assert len(fuente.pedidos) == 1


def test_si_falla_la_descarga_usa_lo_guardado(tmp_path, datos_ohlcv):
    fuente = FuenteFalsa({"AAPL": datos_ohlcv(100)})
    almacen = AlmacenHistorico(tmp_path, fuente)
    almacen.obtener("AAPL")
    fuente.falla = True
    assert len(almacen.obtener("AAPL", forzar=True)) == 100
    with pytest.raises(ErrorDatos):
        almacen.obtener("MSFT")


def test_moneda_nativa():
    assert moneda_nativa("ALUA.BA") == "ARS"
    assert moneda_nativa("BARC.L") == "GBp"
    assert moneda_nativa("^IXIC") == "puntos"
    assert moneda_nativa("AAPL") == "USD"


def test_accion_argentina_se_analiza_en_ccl(tmp_path, cfg, datos_ohlcv):
    base = datos_ohlcv(300)
    ars = base.copy()
    for col in ("apertura", "maximo", "minimo", "cierre"):
        ars[col] = base[col] * 1000  # "ALUA" en pesos = 1000 x su valor en dólares
    ggal_ba = base.copy()
    ggal_ba[["apertura", "maximo", "minimo", "cierre"]] = 100.0  # CCL constante = 100*10/1 = 1000
    ggal = base.copy()
    ggal[["apertura", "maximo", "minimo", "cierre"]] = 1.0
    fuente = FuenteFalsa({"ALUA.BA": ars, "GGAL.BA": ggal_ba, "GGAL": ggal})
    servicio = ServicioTecnico(AlmacenHistorico(tmp_path, fuente), cfg)
    a = servicio.analizar("ALUA.BA")
    assert a.en_ccl and a.moneda == "USD (CCL)"
    assert a.ultimo["cierre"] == pytest.approx(base["cierre"].iloc[-1])


def test_historia_corta_da_error(tmp_path, cfg, datos_ohlcv):
    servicio = ServicioTecnico(AlmacenHistorico(tmp_path, FuenteFalsa({"NUEVA": datos_ohlcv(30)})), cfg)
    with pytest.raises(ErrorDatos, match="ruedas"):
        servicio.analizar("NUEVA")


def test_genera_grafico_png(tmp_path, cfg, datos_ohlcv):
    servicio = ServicioTecnico(AlmacenHistorico(tmp_path, FuenteFalsa({"AAPL": datos_ohlcv(300)})), cfg)
    ruta = generar_grafico(servicio.analizar("AAPL"), tmp_path / "graficos")
    assert ruta.exists() and ruta.stat().st_size > 10_000


def test_partir_mensaje_respeta_el_limite():
    texto = "\n".join(f"linea {i} " + "x" * 50 for i in range(200))
    partes = partir_mensaje(texto, limite=1000)
    assert all(len(p) <= 1000 for p in partes)
    assert "\n".join(partes) == texto
