"""Rebalanceo: pesos objetivo por símbolo y por grupo, tolerancia y comisiones."""

import pytest
from pydantic import ValidationError

from monitor_mercado.cartera.rebalanceo import grupo_de, planificar
from monitor_mercado.cartera.reporte import texto_rebalanceo
from monitor_mercado.cartera.servicio import ServicioCartera
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.db import crear_motor


def _estado(tmp_path, proveedor, rebalanceo):
    # Cartera de 10.000: AAPL 5.000 (50%), GGAL 3.000 (30%), ALUA.BA 2.000 (20%).
    proveedor.fijar("AAPL", 100)
    proveedor.fijar("GGAL", 40)  # también fija el CCL: 6400*10/40 = 1600
    proveedor.fijar("ALUA.BA", 1600, "ARS")
    ruta = tmp_path / "c.csv"
    ruta.write_text("simbolo,cantidad,precio_compra,moneda,fecha_compra,nota\n"
                    "AAPL,50,,USD,,\nGGAL,75,,USD,,\nALUA.BA,2000,,ARS,,\n", encoding="utf-8")
    cfg = Configuracion.model_validate({"rebalanceo": rebalanceo})
    s = ServicioCartera(ruta, proveedor, cfg, crear_motor(":memory:"))
    return s.estado(), cfg, s


def test_por_simbolo_con_tolerancia(tmp_path, proveedor):
    estado, cfg, _ = _estado(tmp_path, proveedor, {"tolerancia": 0.05,
                                                   "objetivos": {"AAPL": 0.40, "GGAL": 0.33, "ALUA.BA": 0.27}})
    plan = planificar(estado, cfg)
    por = {a.clave: a for a in plan.ajustes}
    assert por["AAPL"].monto == pytest.approx(-1000) and por["AAPL"].acciones == pytest.approx(-10)
    assert por["AAPL"].fuera_de_tolerancia
    assert not por["GGAL"].fuera_de_tolerancia  # 30% vs 33%: dentro de ±5
    assert por["ALUA.BA"].fuera_de_tolerancia and por["ALUA.BA"].monto == pytest.approx(700)
    # Comisiones de referencia: EE.UU. 0,1%, BYMA 0,6%.
    assert por["AAPL"].comision == pytest.approx(1.0) and por["ALUA.BA"].comision == pytest.approx(4.2)
    assert [a.clave for a in plan.a_ejecutar] == ["AAPL", "ALUA.BA"]
    texto = texto_rebalanceo(plan)
    assert "vender US$ 1.000" in texto and "comprar US$ 700" in texto and "no se ejecuta nada" in texto


def test_por_grupo_propio_y_por_bolsa(tmp_path, proveedor):
    reb = {"grupos": {"Argentina": ["GGAL", "ALUA.BA"]}, "objetivos": {"Argentina": 0.40, "EE.UU.": 0.60}}
    estado, cfg, _ = _estado(tmp_path, proveedor, reb)
    assert grupo_de("GGAL", cfg.rebalanceo.grupos) == "Argentina"
    assert grupo_de("MSFT", cfg.rebalanceo.grupos) == "EE.UU."
    plan = planificar(estado, cfg)
    por = {a.clave: a for a in plan.ajustes}
    assert por["Argentina"].es_grupo and set(por["Argentina"].simbolos) == {"GGAL", "ALUA.BA"}
    assert por["Argentina"].peso_actual == pytest.approx(0.5) and por["Argentina"].monto == pytest.approx(-1000)
    assert por["EE.UU."].monto == pytest.approx(1000) and por["EE.UU."].acciones is None
    assert plan.peso_sin_objetivo == pytest.approx(0)


def test_avisa_claves_desconocidas_y_lo_que_no_tiene_objetivo(tmp_path, proveedor):
    estado, cfg, s = _estado(tmp_path, proveedor, {"objetivos": {"AAPL": 0.5, "TSLA": 0.1}})
    plan = s.rebalanceo()
    assert plan.desconocidos == ["TSLA"] and plan.peso_sin_objetivo == pytest.approx(0.5)
    assert plan.a_ejecutar == []
    texto = texto_rebalanceo(plan)
    assert "TSLA" in texto and "no tiene objetivo" in texto and "dentro de la tolerancia" in texto


def test_sin_objetivos():
    from monitor_mercado.cartera.rebalanceo import PlanRebalanceo

    assert "No definiste" in texto_rebalanceo(PlanRebalanceo([], 0, 0.05, 0, 0, [], []))


def test_config_invalida():
    with pytest.raises(ValidationError, match="suman más de 1"):
        Configuracion.model_validate({"rebalanceo": {"objetivos": {"A": 0.7, "B": 0.5}}})
    with pytest.raises(ValidationError, match="de 0 a 1"):
        Configuracion.model_validate({"rebalanceo": {"objetivos": {"A": 20}}})
