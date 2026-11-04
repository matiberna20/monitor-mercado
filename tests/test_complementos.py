"""Herramientas clásicas de lectura (Murphy): casos armados a mano, sin internet."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from monitor_mercado.tecnico import complementos as comp
from monitor_mercado.tecnico.indicadores import calcular_indicadores
from monitor_mercado.tecnico.lectura import Giro, leer_grafico


def _df(cierres, apertura=None, maximo=None, minimo=None, volumen=None) -> pd.DataFrame:
    c = np.asarray(cierres, float)
    o = np.asarray(apertura if apertura is not None else np.r_[c[0], c[:-1]], float)
    h = np.asarray(maximo if maximo is not None else np.maximum(o, c) * 1.005, float)
    lo = np.asarray(minimo if minimo is not None else np.minimum(o, c) * 0.995, float)
    v = np.asarray(volumen if volumen is not None else np.full(len(c), 1e6), float)
    df = pd.DataFrame({"apertura": o, "maximo": h, "minimo": lo, "cierre": c, "volumen": v},
                      index=pd.date_range("2024-01-01", periods=len(c), freq="B", name="fecha"))
    return calcular_indicadores(df)


# ------------------------------------------------------------- filtro de ruptura
@pytest.mark.parametrize("cierres, arriba, esperado", [
    ([99, 101.5], True, True),  # 1,5% arriba: rompe con un solo cierre
    ([99, 100.5], True, False),  # 0,5% arriba y un solo cierre: no alcanza
    ([100.3, 100.5], True, True),  # dos cierres seguidos arriba: rompe
    ([101, 98.5], False, True),
    ([101, 99.5], False, False),
])
def test_filtro_de_ruptura(cierres, arriba, esperado):
    assert comp.ruptura_confirmada(pd.Series(cierres), 100.0, arriba) is esperado


# --------------------------------------------------------------------- retrocesos
def test_retrocesos_zona_normal_y_cambio_de_tendencia():
    giros = [Giro(0, pd.Timestamp("2024-01-01"), 100.0, "L"), Giro(10, pd.Timestamp("2024-01-15"), 200.0, "H")]
    r = comp.retrocesos(150.0, giros)
    assert r.niveles[0.5] == pytest.approx(150) and r.niveles[0.382] == pytest.approx(161.8)
    assert r.retrocedido == pytest.approx(0.5) and "zona típica" in r.texto
    assert "cambio de tendencia" in comp.retrocesos(125.0, giros).texto  # devolvió 75%


@pytest.mark.parametrize("precio, abajo, arriba", [(353.8, 350, 400), (47.2, 45, 50), (0.82, 0.8, 0.9),
                                                    (1234, 1000, 1500), (31.69, 30, 35)])
def test_numeros_redondos(precio, abajo, arriba):
    assert comp.numeros_redondos(precio) == pytest.approx((abajo, arriba))


# --------------------------------------------------------------- líneas de tendencia
def _giros(df):
    from monitor_mercado.tecnico.lectura import umbral_zigzag, zigzag

    return zigzag(df, umbral_zigzag(df))


def test_linea_de_tendencia_alcista_valida_y_rota():
    # Subida en escalones (mínimos cada vez más altos) y al final una caída fuerte.
    tramo = []
    base = 100.0
    for _ in range(6):
        tramo += list(np.linspace(base, base * 1.12, 12)) + list(np.linspace(base * 1.12, base * 1.05, 6))
        base *= 1.05
    sube = _df(tramo)
    lineas = comp.lineas_tendencia(sube, _giros(sube))
    alcista = next(x for x in lineas if x.alcista)
    assert alcista.toques >= 2 and not alcista.rota

    cae = _df(tramo + list(np.linspace(tramo[-1], tramo[-1] * 0.9, 6)))
    alcista = next(x for x in comp.lineas_tendencia(cae, _giros(cae)) if x.alcista)
    assert alcista.rota and "rompió" in alcista.texto


# --------------------------------------------------------------------------- huecos
def test_hueco_de_separacion_e_isla():
    c = [100.0] * 40 + [110, 111, 112] + [100, 99, 99]
    o = list(c)
    h = [x * 1.005 for x in c]
    lo = [x * 0.995 for x in c]
    v = [1e6] * 40 + [3e6, 1e6, 1e6, 3e6, 1e6, 1e6]
    df = _df(c, o, h, lo, v)
    lista, isla = comp.huecos(df)
    arriba = next(x for x in lista if x.alcista)
    assert arriba.tipo == "separación" and arriba.cerrado
    assert isla is not None and "Isla de giro bajista" in isla


# ------------------------------------------------------------------ día de giro clave
def test_dia_de_giro_bajista():
    c = list(np.linspace(100, 120, 40))
    o, h, lo = list(c), [x * 1.005 for x in c], [x * 0.995 for x in c]
    # Último día: abre en un máximo nuevo y cierra debajo del cierre anterior.
    o[-1], h[-1], lo[-1], c[-1] = 122.0, 123.0, 116.0, 117.0
    voto, texto = comp.dia_de_giro(_df(c, o, h, lo))
    assert voto == -1 and "día de giro bajista" in texto and "día externo" in texto


# ----------------------------------------------------------------- osciladores y ADX
def test_osciladores_no_van_contra_la_tendencia():
    df = _df(list(np.linspace(100, 200, 150)) + list(np.linspace(200, 185, 6)))
    o = comp.osciladores(df, tendencia=1, ruedas_desde_ruptura=None)
    assert o.voto >= 0  # una señal bajista de oscilador no vota contra una tendencia alcista


def test_adx_detecta_tendencia_y_rango():
    tendencia = _df(np.linspace(100, 200, 120))
    assert comp.regimen(tendencia).tendencia
    rng = np.random.default_rng(1)
    lateral = _df(100 + rng.normal(0, 1, 120))
    assert not comp.regimen(lateral).tendencia


def test_estrella_vespertina_con_tendencia_previa():
    c = list(np.linspace(100, 130, 40))
    o = [x - 0.3 for x in c]
    h = [x + 0.5 for x in c]
    lo = [x - 0.8 for x in o]
    # Vela blanca larga, estrella arriba y vela negra que cierra debajo de la mitad de la primera.
    o += [130, 134.7, 133.5]
    c += [134, 134.8, 130.5]
    h += [134.2, 135.5, 133.8]
    lo += [129.8, 134.2, 130.2]
    velas = comp.velas(_df(c, o, h, lo))
    assert any(v.nombre == "estrella vespertina" and v.sesgo == -1 for v in velas)


def test_grados_de_tendencia_correccion_en_tendencia_alcista():
    df = _df(list(np.linspace(50, 150, 400)) + list(np.linspace(150, 135, 25)))
    g = comp.grados_tendencia(df, estructura_intermedia=-1)
    assert g.principal == 1 and "corrigiendo" in g.texto


# ------------------------------------------------------------------- lectura completa
def test_lectura_incluye_las_herramientas_nuevas(datos_ohlcv):
    df = calcular_indicadores(datos_ohlcv(400))
    lectura = leer_grafico(df)
    e = lectura.extras
    assert e is not None and e.grados.texto and e.regimen.texto and e.redondos
    assert {"tendencia_principal", "linea_tendencia", "osciladores", "obv"} <= set(lectura.votos)


def test_doble_techo_exige_tendencia_previa_y_separacion():
    # Dos máximos iguales pegados (menos de un mes) y sin tendencia previa: no es doble techo.
    c = [100.0] * 60 + [104, 108, 104, 100, 104, 108, 104, 100] + [100.0] * 5
    lectura = leer_grafico(_df(c))
    assert not any(f.nombre == "Doble techo" for f in lectura.figuras)
