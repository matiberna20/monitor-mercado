"""Utilidades compartidas por los tests: proveedor de precios falso (sin internet)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from monitor_mercado.alertas.repositorio import RepositorioAlertas, crear_motor
from monitor_mercado.alertas.servicio import ServicioAlertas
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.datos.modelos import Cotizacion, SimboloSinDatos


class ProveedorFalso:
    """Devuelve precios fijados a mano. ``precios[simbolo] = (precio, moneda, cierre_anterior)``."""

    def __init__(self) -> None:
        self.precios: dict[str, tuple[float, str, float | None]] = {}
        self.consultas: list[str] = []

    def fijar(self, simbolo: str, precio: float, moneda: str = "USD", cierre: float | None = None) -> None:
        self.precios[simbolo] = (precio, moneda, cierre)

    def cotizacion(self, simbolo: str) -> Cotizacion:
        self.consultas.append(simbolo)
        if simbolo not in self.precios:
            raise SimboloSinDatos(f"{simbolo}: sin datos")
        precio, moneda, cierre = self.precios[simbolo]
        return Cotizacion(simbolo, precio, moneda, cierre, datetime.now(timezone.utc))

    def cotizaciones(self, simbolos: list[str]) -> dict[str, Cotizacion]:
        resultado = {}
        for s in simbolos:
            try:
                resultado[s] = self.cotizacion(s)
            except SimboloSinDatos:
                pass
        return resultado


@pytest.fixture
def proveedor() -> ProveedorFalso:
    p = ProveedorFalso()
    # Datos para el CCL: 6400 * 10 / 40 = 1600 pesos por dólar.
    p.fijar("GGAL.BA", 6400, "ARS")
    p.fijar("GGAL", 40)
    return p


@pytest.fixture
def cfg() -> Configuracion:
    return Configuracion.model_validate(
        {
            "watchlist_prueba": ["AAPL", "ALUA.BA", "BARC.L"],
            "monedas": {"simbolos_byma": {"YPF": "YPFD.BA"}},
            "alertas": {"enfriamiento_minutos_repetir": 60},
        }
    )


@pytest.fixture
def servicio(proveedor: ProveedorFalso, cfg: Configuracion) -> ServicioAlertas:
    return ServicioAlertas(RepositorioAlertas(crear_motor(":memory:")), proveedor, cfg)
