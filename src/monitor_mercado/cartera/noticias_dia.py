"""Selección de las noticias importantes del día para tu cartera (sin IA, con reglas).

Cómo se decide qué es "importante":
1. El titular tiene que nombrar a la empresa (o su símbolo). Yahoo, por ejemplo,
   mezcla notas generales del mercado que no hablan de ella.
2. Suman puntos las palabras que suelen mover precios: resultados, guidance,
   adquisiciones, demandas, cambios de recomendación de analistas, dividendos...
3. Suman puntos las acciones que más se movieron hoy: la noticia puede explicar
   el movimiento.
4. Máximo 2 noticias por acción, para que el resumen no lo acapare una sola.

Son reglas simples: pueden dejar afuera algo importante o incluir algo menor.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from monitor_mercado.noticias.fuentes import FuenteNoticias, buscar_en_todas
from monitor_mercado.noticias.modelos import Noticia
from monitor_mercado.noticias.nombres import ResolutorNombres

log = logging.getLogger(__name__)

PALABRAS_CLAVE = re.compile(
    r"\b("
    # inglés
    r"earnings|results|revenue|profit|loss|guidance|outlook|forecast|beats?|miss(es|ed)?|upgrade[sd]?|"
    r"downgrade[sd]?|price target|acquir\w*|acquisition|merger|deal|lawsuit|sues?|probe|investigation|sec|fda|"
    r"approv\w*|dividend|split|buyback|repurchase|layoffs?|ceo|resign\w*|bankrupt\w*|default|tariffs?|"
    r"sanctions?|record|plunge[sd]?|soar(s|ed)?|surge[sd]?|tumble[sd]?|crash\w*|rall(y|ies|ied)|"
    # español
    r"resultados?|ganancias?|balance|adquisici\w+|fusi\w+|demanda|dividendos?|despidos|r[eé]cord|"
    r"licitaci\w+|regulaci\w+|desplom\w+|dispar\w+|"
    # portugués
    r"lucro|aquisi\w+|dividendos"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NoticiaDestacada:
    """Una noticia elegida para el resumen."""

    simbolo: str
    noticia: Noticia
    puntos: float


def menciona(titulo: str, simbolo: str, empresa: str) -> bool:
    """True si el titular nombra a la empresa (primera palabra del nombre) o al símbolo."""
    t = titulo.lower()
    base = simbolo.split(".")[0].split("-")[0].lower()
    palabra = empresa.split()[0].lower() if empresa else base
    return bool(re.search(rf"\b{re.escape(palabra)}", t) or re.search(rf"\b{re.escape(base)}\b", t))


def puntuar(noticia: Noticia, variacion_dia: float | None, ahora: datetime) -> float:
    """Puntaje de importancia de una noticia (más alto = más importante)."""
    puntos = 1.0
    puntos += 2.0 * min(len(PALABRAS_CLAVE.findall(noticia.titulo)), 2)
    if ahora - noticia.publicada <= timedelta(hours=12):
        puntos += 1.0
    if variacion_dia is not None:
        puntos += min(abs(variacion_dia) * 40, 4.0)  # un movimiento de 10% suma el máximo
    return puntos


def noticias_importantes(
    fuentes: list[FuenteNoticias],
    nombres: ResolutorNombres,
    variaciones: dict[str, float | None],
    maximo: int = 8,
    por_simbolo: int = 2,
    ahora: datetime | None = None,
) -> list[NoticiaDestacada]:
    """Busca las noticias de las últimas 24 hs de cada activo y elige las más importantes."""
    ahora = ahora or datetime.now(timezone.utc)

    def buscar(simbolo: str) -> list[NoticiaDestacada]:
        try:
            empresa = nombres.nombre(simbolo)
            encontradas, _ = buscar_en_todas(fuentes, simbolo, empresa, dias=1)
        except Exception as e:  # noqa: BLE001 - una fuente rota no frena el resumen
            log.warning("%s: no se pudieron buscar noticias: %s", simbolo, e)
            return []
        recientes = [n for n in encontradas if ahora - n.publicada <= timedelta(hours=26)
                     and menciona(n.titulo, simbolo, empresa)]
        puntuadas = sorted((NoticiaDestacada(simbolo, n, puntuar(n, variaciones.get(simbolo), ahora))
                            for n in recientes), key=lambda d: -d.puntos)
        return puntuadas[:por_simbolo]

    with ThreadPoolExecutor(max_workers=6) as pool:
        todas = [d for lista in pool.map(buscar, list(variaciones)) for d in lista]
    return sorted(todas, key=lambda d: -d.puntos)[:maximo]
