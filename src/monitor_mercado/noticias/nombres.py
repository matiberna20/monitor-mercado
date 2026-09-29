"""Nombre de la empresa de cada símbolo, para buscar noticias por nombre.

Google News busca por texto: "AAPL" trae menos resultados que "Apple". El nombre
sale de config.yaml (``noticias.nombres``) o, si no está, de Yahoo Finance, y se
guarda en data/nombres.json para no volver a consultarlo.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import yfinance as yf

log = logging.getLogger(__name__)

# Sufijos societarios que empeoran la búsqueda ("Apple Inc." -> "Apple").
_SUFIJOS = re.compile(
    r"[,.]?\s+(inc|corp|corporation|co|company|ltd|limited|plc|s\.?a\.?|sa|ag|nv|n\.v\.|se|"
    r"holdings?|group|class [a-c]|\(the\))\.?$",
    re.IGNORECASE,
)


def limpiar_nombre(nombre: str) -> str:
    """Quita sufijos como "Inc.", "S.A.", "Corporation" (puede haber varios)."""
    anterior = None
    nombre = nombre.strip()
    while anterior != nombre:
        anterior = nombre
        nombre = _SUFIJOS.sub("", nombre).strip(" ,.")
    return nombre


class ResolutorNombres:
    """Resuelve y cachea el nombre de empresa de cada símbolo."""

    def __init__(self, archivo: Path, manuales: dict[str, str] | None = None) -> None:
        self._archivo = archivo
        self._manuales = {k.upper(): v for k, v in (manuales or {}).items()}
        self._cache: dict[str, str] = {}
        if archivo.exists():
            try:
                self._cache = json.loads(archivo.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log.warning("No se pudo leer %s; se regenera.", archivo)

    def nombre(self, simbolo: str) -> str:
        """Nombre para buscar noticias (el símbolo mismo si no se encuentra otro)."""
        simbolo = simbolo.upper()
        if simbolo in self._manuales:
            return self._manuales[simbolo]
        if simbolo in self._cache:
            return self._cache[simbolo]
        try:
            info = yf.Ticker(simbolo).info
            crudo = info.get("shortName") or info.get("longName") or ""
        except Exception as e:  # noqa: BLE001 - yfinance falla de muchas formas
            log.warning("%s: no se pudo obtener el nombre de la empresa: %s", simbolo, e)
            return simbolo.split(".")[0]
        nombre = limpiar_nombre(crudo) or simbolo.split(".")[0]
        self._cache[simbolo] = nombre
        self._archivo.parent.mkdir(parents=True, exist_ok=True)
        self._archivo.write_text(json.dumps(self._cache, ensure_ascii=False, indent=1), encoding="utf-8")
        return nombre
