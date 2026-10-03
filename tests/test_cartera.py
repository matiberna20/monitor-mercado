from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from monitor_mercado.cartera.archivo import ErrorCartera, leer_cartera, normalizar_simbolo
from monitor_mercado.cartera.noticias_dia import menciona, noticias_importantes, puntuar
from monitor_mercado.cartera.reporte import texto_cartera, texto_resumen_dia
from monitor_mercado.cartera.servicio import ServicioCartera
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.db import crear_motor
from monitor_mercado.noticias.modelos import Noticia
from monitor_mercado.noticias.nombres import ResolutorNombres
from monitor_mercado.notificaciones.telegram_bot import hubo_rueda_hoy

AHORA = datetime(2026, 10, 2, 20, 30, tzinfo=timezone.utc)


def escribir(tmp_path, contenido: str):
    ruta = tmp_path / "cartera.csv"
    ruta.write_text("simbolo,cantidad,precio_compra,moneda,fecha_compra,nota\n" + contenido, encoding="utf-8")
    return ruta


# -------------------------------------------------------------------- archivo
@pytest.mark.parametrize("broker, yahoo", [("AAPL.E", "AAPL"), ("BRK.B.E", "BRK-B"), ("brk.b", "BRK-B"),
                                           ("ALUA.BA", "ALUA.BA"), ("PETR4.SA", "PETR4.SA")])
def test_normalizar_simbolo(broker, yahoo):
    assert normalizar_simbolo(broker) == yahoo


def test_leer_cartera(tmp_path):
    ruta = escribir(tmp_path, "AAPL.E,120,\"302,46\",USD,2025-03-15,\nBTC,100,0,USD,,sin costo\nTS,842,,,,\n")
    aapl, btc, ts = leer_cartera(ruta)
    assert aapl.simbolo == "AAPL" and aapl.precio_compra == pytest.approx(302.46)
    assert aapl.costo == pytest.approx(36295.2) and aapl.fecha_compra == date(2025, 3, 15)
    assert btc.precio_compra is None and btc.costo is None  # 0 = costo desconocido
    assert ts.moneda == "USD"


@pytest.mark.parametrize("fila, error", [("AAPL,0,10,USD,,", "cantidad"), ("AAPL,abc,10,USD,,", "número"),
                                         ("AAPL,1,10,USD,15/03/2025,", "AAAA-MM-DD"),
                                         ("AAPL,1,10,USD,,\nAAPL.E,2,10,USD,,", "dos veces")])
def test_errores_de_archivo(tmp_path, fila, error):
    with pytest.raises(ErrorCartera, match=error):
        leer_cartera(escribir(tmp_path, fila + "\n"))


def test_el_archivo_real_de_la_cartera_es_valido():
    from monitor_mercado.configuracion import RAIZ_PROYECTO

    ruta = RAIZ_PROYECTO / "mi_cartera.csv"
    if not ruta.exists():
        pytest.skip("no hay cartera cargada")
    posiciones = leer_cartera(ruta)
    assert len({p.simbolo for p in posiciones}) == len(posiciones)


# ------------------------------------------------------------------- servicio
def _servicio(tmp_path, proveedor, contenido):
    cfg = Configuracion.model_validate({"cartera": {"concentracion_maxima": 0.5}})
    return ServicioCartera(escribir(tmp_path, contenido), proveedor, cfg, crear_motor(":memory:"))


def test_valuacion_de_la_cartera(tmp_path, proveedor):
    proveedor.fijar("AAPL", 110, cierre=100)  # +10% hoy
    proveedor.fijar("NVDA", 50, cierre=50)
    proveedor.fijar("ALUA.BA", 3200, "ARS", cierre=3200)  # CCL 1600 -> 2 USD
    s = _servicio(tmp_path, proveedor, "AAPL,10,100,USD,,\nNVDA,20,,USD,,\nALUA.BA,100,1.5,USD,,\nXXX,1,1,USD,,\n")
    e = s.estado()
    por = {f.simbolo: f for f in e.posiciones}
    assert por["AAPL"].resultado == pytest.approx(100) and por["AAPL"].resultado_pct == pytest.approx(0.10)
    assert por["AAPL"].resultado_dia == pytest.approx(100)
    assert por["ALUA.BA"].precio == pytest.approx(2.0) and por["ALUA.BA"].resultado == pytest.approx(50)
    assert e.valor == pytest.approx(1100 + 1000 + 200)
    assert e.costo == pytest.approx(1000 + 150)  # NVDA no tiene costo
    assert e.sin_costo == ["NVDA"] and e.sin_precio == ["XXX"]
    assert sum(f.peso for f in e.posiciones) == pytest.approx(1.0)
    assert e.variacion_dia == pytest.approx(100 / 2200)
    texto = texto_cartera(e)
    assert "AAPL" in texto and "NVDA" in texto and "no es una recomendación" in texto


def test_resumen_con_concentracion_y_semana(tmp_path, proveedor):
    proveedor.fijar("AAPL", 110, cierre=100)
    proveedor.fijar("NVDA", 10, cierre=10)
    s = _servicio(tmp_path, proveedor, "AAPL,10,100,USD,,\nNVDA,1,5,USD,,\n")
    hace_una_semana = datetime.now(timezone.utc).date() - timedelta(days=8)
    s.guardar_foto(s.estado(), hace_una_semana)
    proveedor.fijar("AAPL", 121, cierre=110)
    r = s.resumen_dia(con_noticias=False)
    assert [f.simbolo for f in r.concentradas] == ["AAPL"]
    assert r.variacion_semana == pytest.approx((1210 + 10) / (1100 + 10) - 1)
    texto = texto_resumen_dia(r)
    for parte in ("Mejores del día", "Todas tus posiciones", "Concentración", "Últimos 7 días", "no es una recomendación"):
        assert parte in texto


# ------------------------------------------------------------------- noticias
def test_el_titular_tiene_que_nombrar_a_la_empresa():
    assert menciona("Nike plans layoffs despite profit", "NKE", "Nike")
    assert menciona("Why is INTC stock volatile?", "INTC", "Intel")
    assert not menciona("3 cheap growth stocks to buy now", "NKE", "Nike")
    assert menciona("Berkshire buys more Chevron", "BRK-B", "Berkshire Hathaway")


def test_puntaje_premia_palabras_clave_y_movimientos():
    normal = Noticia("X", "Nike opens a store", "f", "u", AHORA - timedelta(hours=20))
    clave = Noticia("X", "Nike earnings beat, plans layoffs", "f", "u", AHORA - timedelta(hours=20))
    assert puntuar(clave, 0.0, AHORA) > puntuar(normal, 0.0, AHORA)
    assert puntuar(normal, 0.08, AHORA) > puntuar(normal, 0.0, AHORA)


def test_noticias_importantes_maximo_por_simbolo(tmp_path):
    class Fuente:
        nombre = "F"

        def aplica(self, s):
            return True

        def buscar(self, s, e, d):
            return [Noticia(s, f"{e} earnings news {i}", "f", "u", AHORA - timedelta(hours=1)) for i in range(5)] + \
                   [Noticia(s, "Unrelated market story", "f", "u", AHORA)]

    nombres = ResolutorNombres(tmp_path / "n.json", {"NKE": "Nike", "AAPL": "Apple"})
    elegidas = noticias_importantes([Fuente()], nombres, {"NKE": 0.05, "AAPL": 0.0}, maximo=10, ahora=AHORA)
    assert len(elegidas) == 4  # 2 por empresa, la nota que no las nombra se descarta
    assert elegidas[0].simbolo == "NKE"  # la que más se movió va primero


# ---------------------------------------------------------------- calendario
def test_no_hay_resumen_los_fines_de_semana_ni_feriados():
    class Almacen:
        def __init__(self, ultimo):
            self.ultimo = ultimo

        def obtener(self, s, forzar=False):
            return pd.DataFrame({"cierre": [1.0]}, index=pd.to_datetime([self.ultimo]))

    class Ctx:
        def __init__(self, ultimo):
            self.tecnico = type("T", (), {"almacen": Almacen(ultimo)})()

    viernes, sabado = date(2026, 10, 2), date(2026, 10, 3)
    assert hubo_rueda_hoy(Ctx(viernes), viernes)
    assert not hubo_rueda_hoy(Ctx(viernes), sabado)
    assert not hubo_rueda_hoy(Ctx(date(2026, 10, 1)), viernes)  # feriado: el último dato es de ayer
