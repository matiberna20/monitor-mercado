"""Tests de la lectura del gráfico con figuras dibujadas a mano."""

import numpy as np
import pandas as pd
import pytest

from monitor_mercado.tecnico.grafico_lectura import grafico_lectura
from monitor_mercado.tecnico.indicadores import calcular_indicadores
from monitor_mercado.tecnico.lectura import (
    estructura, figuras, giro_en_curso, leer_grafico, niveles, umbral_zigzag, zigzag,
)
from monitor_mercado.tecnico.reporte_lectura import texto_lectura


def dibujar(puntos: list[tuple[int, float]], ruido: float = 0.002, semilla: int = 0) -> pd.DataFrame:
    """Une puntos (rueda, precio) con rectas: así se "dibuja" una figura de libro."""
    xs, ys = zip(*puntos)
    cierre = np.interp(np.arange(xs[-1] + 1), xs, ys)
    cierre = cierre * (1 + np.random.default_rng(semilla).normal(0, ruido, len(cierre)))
    apertura = np.concatenate([[cierre[0]], cierre[:-1]])
    df = pd.DataFrame({
        "apertura": apertura,
        "maximo": np.maximum(apertura, cierre) * 1.003,
        "minimo": np.minimum(apertura, cierre) * 0.997,
        "cierre": cierre,
        "volumen": 1_000_000.0,
    }, index=pd.bdate_range("2025-01-01", periods=len(cierre)))
    return calcular_indicadores(df)


def test_zigzag_encuentra_los_giros():
    df = dibujar([(0, 100), (30, 130), (60, 110), (90, 140), (120, 120)])
    g = zigzag(df, 0.05)
    assert [x.tipo for x in g] == ["L", "H", "L", "H"]
    assert g[1].precio == pytest.approx(130, rel=0.02) and g[3].precio == pytest.approx(140, rel=0.02)
    assert [x.etiqueta for x in g[2:]] == ["HL", "HH"]


def test_estructura_alcista_bajista_y_rango():
    sube = zigzag(dibujar([(0, 100), (30, 130), (60, 110), (90, 140), (120, 120), (150, 150)]), 0.05)
    assert estructura(sube)[0] == 1
    baja = zigzag(dibujar([(0, 150), (30, 120), (60, 140), (90, 110), (120, 130), (150, 100)]), 0.05)
    assert estructura(baja)[0] == -1
    rango = zigzag(dibujar([(0, 100), (30, 120), (60, 100), (90, 120), (120, 100), (150, 120)]), 0.05)
    assert estructura(rango, tolerancia=0.02)[0] == 0


def test_el_tramo_en_curso_cuenta():
    # El último giro confirmado es un mínimo y el precio ya superó el máximo anterior.
    df = dibujar([(0, 100), (30, 130), (60, 110), (90, 145)])
    g = zigzag(df, 0.05)
    actual = giro_en_curso(df, g)
    assert actual is not None and actual.tipo == "H" and actual.precio > 140


def test_doble_techo_confirmado():
    df = dibujar([(0, 80), (40, 120), (60, 100), (80, 120.5), (100, 92)])
    figs = figuras(df, zigzag(df, 0.06), 0.06)
    doble = next(f for f in figs if f.nombre == "Doble techo")
    assert doble.estado == "confirmada" and doble.sesgo == -1
    assert doble.linea == pytest.approx(100, rel=0.02)
    assert doble.objetivo == pytest.approx(80, rel=0.05)  # cuello - (techo - cuello)


def test_doble_techo_superado_se_descarta():
    df = dibujar([(0, 80), (40, 120), (60, 100), (80, 120.5), (95, 108), (110, 130)])
    nombres = {f.nombre for f in figuras(df, zigzag(df, 0.06), 0.06)}
    assert "Doble techo" not in nombres


def test_hombro_cabeza_hombro():
    df = dibujar([(0, 80), (20, 110), (35, 100), (55, 125), (75, 100), (95, 111), (115, 92)])
    figs = figuras(df, zigzag(df, 0.06), 0.06)
    hch = next(f for f in figs if f.nombre == "Hombro-cabeza-hombro")
    assert hch.estado == "confirmada" and hch.sesgo == -1


def test_triangulo_ascendente():
    df = dibujar([(0, 90), (20, 120), (40, 100), (60, 120.5), (80, 108), (90, 116)])
    figs = figuras(df, zigzag(df, 0.05), 0.05)
    assert any(f.nombre == "Triángulo ascendente" and f.estado == "en formación" for f in figs)


def test_soportes_y_resistencias_agrupan_toques():
    df = dibujar([(0, 100), (20, 120), (40, 100.5), (60, 120.3), (80, 99.8), (100, 110)])
    lista = niveles(df, zigzag(df, 0.05))
    fuertes = [n for n in lista if n.toques >= 2]
    precios = sorted(round(n.precio) for n in fuertes)
    assert precios[0] == pytest.approx(100, abs=2) and precios[-1] == pytest.approx(120, abs=2)


def test_umbral_se_adapta_a_la_volatilidad():
    tranquila = dibujar([(0, 100), (300, 110)], ruido=0.003)
    volatil = dibujar([(0, 100), (300, 110)], ruido=0.04)
    assert umbral_zigzag(volatil) > umbral_zigzag(tranquila)


def test_lectura_completa_texto_y_grafico(tmp_path):
    df = dibujar([(0, 100), (40, 130), (70, 115), (110, 145), (140, 128), (180, 160), (200, 150), (220, 158)])
    l = leer_grafico(df)
    assert l.direccion == "ALCISTA"
    assert l.soportes and l.invalidacion == pytest.approx(l.soportes[0].precio)
    texto = texto_lectura("TEST", l, "USD")
    for parte in ("Estructura", "Soportes y resistencias", "Escenario alcista", "Escenario bajista",
                  "se anula", "no es una recomendación"):
        assert parte in texto
    ruta = grafico_lectura("TEST", l, "USD", tmp_path)
    assert ruta.exists() and ruta.stat().st_size > 20_000


def test_validacion_no_mira_el_futuro_y_concluye(datos_ohlcv):
    from monitor_mercado.backtest.validar_lectura import texto_validacion, validar

    class Tecnico:
        def datos(self, s):
            return datos_ohlcv(900, tendencia=0.0005, semilla=hash(s) % 100), "USD", False

    v = validar(Tecnico(), ["A", "B"], horizonte=20, paso=20)
    assert len(v.lecturas) > 20 and set(v.lecturas["simbolo"]) == {"A", "B"}
    texto = texto_validacion(v)
    assert "Conclusión" in texto and "no es una recomendación" in texto


def test_lectura_bajista():
    df = dibujar([(0, 160), (40, 130), (70, 145), (110, 115), (140, 128), (180, 100), (200, 110), (220, 103)])
    l = leer_grafico(df)
    assert l.direccion == "BAJISTA" and l.estructura == -1
