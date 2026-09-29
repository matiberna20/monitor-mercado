from datetime import date

import pytest

from monitor_mercado.explicacion import explicacion_completa, texto_glosario
from monitor_mercado.noticias.servicio import AnalisisNoticias
from monitor_mercado.senal_final import combinar
from monitor_mercado.tecnico.indicadores import calcular_indicadores
from monitor_mercado.tecnico.patrones import patrones_recientes
from monitor_mercado.tecnico.senal import Senal, SenalPorReglas, Tendencia
from monitor_mercado.tecnico.servicio import Analisis


def senal(puntaje: float, confianza: int = 60) -> Senal:
    t = Tendencia.ALCISTA if puntaje >= 0.2 else Tendencia.BAJISTA if puntaje <= -0.2 else Tendencia.NEUTRAL
    return Senal(date(2026, 9, 29), t, puntaje, confianza, "test")


def noticias(puntaje, cobertura=1.0) -> AnalisisNoticias:
    return AnalisisNoticias("X", "X", [], puntaje, cobertura, None)


def test_sin_noticias_la_final_es_la_tecnica():
    f = combinar(senal(0.5), None, 0.3, 0.2)
    assert f.puntaje == 0.5 and f.peso_noticias == 0 and f.coinciden is None


def test_noticias_pesan_segun_cobertura():
    llena = combinar(senal(0.0), noticias(1.0, cobertura=1.0), 0.3, 0.2)
    poca = combinar(senal(0.0), noticias(1.0, cobertura=0.1), 0.3, 0.2)
    assert llena.puntaje == pytest.approx(0.3)
    assert poca.puntaje == pytest.approx(0.03)


def test_contradiccion_baja_la_confianza():
    coinciden = combinar(senal(0.6, 70), noticias(0.6), 0.3, 0.2)
    se_contradicen = combinar(senal(0.6, 70), noticias(-0.6), 0.3, 0.2)
    assert coinciden.coinciden and not se_contradicen.coinciden
    assert se_contradicen.confianza < coinciden.confianza


def _analisis(datos_ohlcv, tendencia, en_ccl=False) -> Analisis:
    df = calcular_indicadores(datos_ohlcv(300, tendencia=tendencia))
    return Analisis("TEST", "USD", df, SenalPorReglas().generar(df), patrones_recientes(df), en_ccl=en_ccl)


def test_explicacion_tiene_todas_las_secciones(datos_ohlcv):
    a = _analisis(datos_ohlcv, 0.004, en_ccl=True)
    final = combinar(a.senal, noticias(0.5), 0.3, 0.2)
    texto = explicacion_completa(a, noticias(0.5), final)
    for seccion in ("La idea general", "Medias móviles", "RSI", "MACD", "Bollinger",
                    "Volumen y volatilidad", "dólares CCL", "Noticias", "En resumen", "NO te dice"):
        assert seccion in texto, seccion
    assert "alineación alcista" in texto
    assert "no es una recomendación de inversión" in texto


def test_explicacion_bajista_describe_alineacion_bajista(datos_ohlcv):
    texto = explicacion_completa(_analisis(datos_ohlcv, -0.004))
    assert "alineación bajista" in texto
    assert "Noticias" not in texto  # sin noticias no aparece esa sección


def test_glosario_busca_sin_tildes_y_por_prefijo():
    assert texto_glosario("volátil").startswith("📖 VOLATILIDAD")
    assert "No tengo" in texto_glosario("criptomoneda")
