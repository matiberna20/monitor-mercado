"""Exportación a Excel: cartera, operaciones, dividendos y resultado por posición.

Usa las mismas tablas que el panel (``tablas.py``). Si una fuente falla (por ejemplo,
Yahoo no responde con los dividendos), esa hoja sale con una nota y el resto se exporta igual.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pandas as pd

from monitor_mercado import tablas
from monitor_mercado.aviso_legal import AVISO_DEMORA, AVISO_LEGAL

if TYPE_CHECKING:
    from monitor_mercado.aplicacion import Contexto

log = logging.getLogger(__name__)
AR = ZoneInfo("America/Argentina/Buenos_Aires")


def _dividendos(resumen) -> pd.DataFrame:
    cobrados, proximos = tablas.tabla_dividendos(resumen)
    cobrados.insert(0, "Estado", "cobrado")
    proximos = proximos.rename(columns={"Por acción (último)": "Por acción", "Monto USD estimado": "Monto USD"})
    proximos.insert(0, "Estado", "próximo")
    return pd.concat([cobrados, proximos], ignore_index=True)


def _nota(texto: str) -> pd.DataFrame:
    return pd.DataFrame({"Nota": [texto]})


def armar_hojas(ctx: Contexto) -> dict[str, pd.DataFrame]:
    """Las hojas del Excel, en orden. Cada fuente que falla deja una nota en vez de cortar la exportación."""
    estado = ctx.cartera.estado()
    hojas: dict[str, pd.DataFrame] = {"Cartera": tablas.tabla_cartera(estado)}

    movimientos = ctx.diario.repo.listar() if ctx.diario is not None else []
    hojas["Operaciones"] = tablas.tabla_operaciones(movimientos) if movimientos else _nota(
        "El diario está vacío: registrá operaciones con /compre y /vendi o importá tu cartera con /importar_diario.")

    try:
        hojas["Dividendos"] = _dividendos(ctx.dividendos.resumen())
    except Exception as e:  # noqa: BLE001
        log.warning("Exportar: sin dividendos: %s", e)
        hojas["Dividendos"] = _nota(f"No se pudieron consultar los dividendos: {e}")

    rendimiento = ctx.rendimiento(estado)
    realizado = ctx.diario.realizado_por_simbolo() if ctx.diario is not None else {}
    hojas["Resultado por posición"] = tablas.tabla_resultado_por_posicion(
        estado, realizado, rendimiento.por_simbolo if rendimiento is not None else {})

    momento = datetime.now(AR)
    hojas["Notas"] = pd.DataFrame({"Nota": [
        f"Exportado el {momento:%d/%m/%Y %H:%M} (hora Argentina).",
        "Montos en USD; lo que cotiza en otra moneda se pasa al tipo de cambio de hoy (pesos al CCL).",
        "Resultado realizado: costo promedio ponderado, con comisiones. Dividendos: sin impuestos ni retenciones.",
        "Porcentajes expresados como número (5 = 5%).",
        AVISO_LEGAL, AVISO_DEMORA,
    ]})
    return hojas


def guardar_excel(hojas: dict[str, pd.DataFrame], ruta: Path) -> Path:
    """Escribe las hojas con encabezado fijo y columnas a medida."""
    from openpyxl.utils import get_column_letter

    ruta.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(ruta, engine="openpyxl") as escritor:
        for nombre, tabla in hojas.items():
            tabla.to_excel(escritor, sheet_name=nombre[:31], index=False)
            hoja = escritor.sheets[nombre[:31]]
            hoja.freeze_panes = "A2"
            for i, columna in enumerate(tabla.columns, start=1):
                largo = max([len(str(columna)), *(len(str(v)) for v in tabla[columna].head(200))])
                hoja.column_dimensions[get_column_letter(i)].width = min(max(10, largo + 2), 60)
    return ruta


def exportar(ctx: Contexto, carpeta: Path) -> Path:
    """Genera ``cartera_AAAA-MM-DD_HHMM.xlsx`` en ``carpeta`` y devuelve la ruta."""
    nombre = f"cartera_{datetime.now(AR):%Y-%m-%d_%H%M}.xlsx"
    return guardar_excel(armar_hojas(ctx), carpeta / nombre)
