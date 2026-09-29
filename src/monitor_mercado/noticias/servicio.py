"""Caso de uso de noticias: buscar -> clasificar (solo lo nuevo) -> puntaje agregado.

Cómo se agrega el sentimiento de varias noticias en un solo número:
    puntaje = Σ (puntaje_i × peso_i) / Σ peso_i
    peso_i  = relevancia_i × 0,5 ^ (antigüedad_en_días / vida_media)

Es decir, pesan más las noticias que hablan directamente de la empresa y las más
recientes (con vida media de 2 días, una noticia de hace 2 días pesa la mitad que
una de hoy). La "cobertura" indica cuánta información hubo: con una sola noticia
poco relevante el puntaje existe, pero casi no debería influir.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from monitor_mercado.configuracion import ConfigNoticias
from monitor_mercado.noticias.fuentes import FuenteNoticias, buscar_en_todas
from monitor_mercado.noticias.modelos import Clasificacion, Noticia
from monitor_mercado.noticias.nombres import ResolutorNombres
from monitor_mercado.noticias.repositorio import RepositorioNoticias
from monitor_mercado.noticias.sentimiento import ClasificadorClaude, ErrorSentimiento

log = logging.getLogger(__name__)

# Suma de pesos a partir de la cual se considera que hay información suficiente.
PESO_PARA_COBERTURA_TOTAL = 3.0


@dataclass(frozen=True)
class NoticiaEvaluada:
    """Una noticia con su clasificación (None si no se pudo clasificar)."""

    noticia: Noticia
    clasificacion: Clasificacion | None
    peso: float = 0.0


@dataclass(frozen=True)
class AnalisisNoticias:
    """Resultado del análisis de noticias de un activo."""

    simbolo: str
    empresa: str
    noticias: list[NoticiaEvaluada]
    puntaje: float | None  # -1 a +1, None si no hay nada clasificado
    cobertura: float  # 0 a 1: cuánta información relevante y reciente hubo
    resumen: str | None
    avisos: list[str] = field(default_factory=list)

    @property
    def clasificadas(self) -> list[NoticiaEvaluada]:
        """Solo las noticias con clasificación, de mayor a menor peso."""
        return sorted((n for n in self.noticias if n.clasificacion), key=lambda n: -n.peso)


def peso_noticia(clasificacion: Clasificacion, publicada: datetime, ahora: datetime, vida_media: float) -> float:
    """Peso de una noticia según su relevancia y su antigüedad."""
    dias = max(0.0, (ahora - publicada).total_seconds() / 86400)
    return clasificacion.relevancia * 0.5 ** (dias / vida_media)


def agregar(evaluadas: list[NoticiaEvaluada]) -> tuple[float | None, float]:
    """Puntaje ponderado y cobertura (0 a 1) de un conjunto de noticias."""
    con_peso = [(n.clasificacion.puntaje, n.peso) for n in evaluadas if n.clasificacion and n.peso > 0]
    total = sum(p for _, p in con_peso)
    if total == 0:
        return None, 0.0
    puntaje = sum(s * p for s, p in con_peso) / total
    return puntaje, min(1.0, total / PESO_PARA_COBERTURA_TOTAL)


class ServicioNoticias:
    """Orquesta fuentes, clasificador y repositorio."""

    def __init__(
        self,
        fuentes: list[FuenteNoticias],
        clasificador: ClasificadorClaude | None,
        repo: RepositorioNoticias,
        nombres: ResolutorNombres,
        cfg: ConfigNoticias,
    ) -> None:
        self.fuentes = fuentes
        self.clasificador = clasificador
        self._repo = repo
        self._nombres = nombres
        self._cfg = cfg

    @property
    def con_sentimiento(self) -> bool:
        """True si hay clave de Claude para clasificar."""
        return self.clasificador is not None

    def analizar(self, simbolo: str, ahora: datetime | None = None) -> AnalisisNoticias:
        """Busca y clasifica las noticias recientes de un activo."""
        simbolo = simbolo.upper()
        ahora = ahora or datetime.now(timezone.utc)
        empresa = self._nombres.nombre(simbolo)
        avisos: list[str] = []

        noticias, errores = buscar_en_todas(self.fuentes, simbolo, empresa, self._cfg.dias)
        noticias = noticias[: self._cfg.max_noticias]
        if errores:
            avisos.append("Algunas fuentes fallaron: " + "; ".join(errores))

        ya = self._repo.clasificadas([n.id for n in noticias])
        nuevas = [n for n in noticias if n.id not in ya]
        resumen = self._repo.resumen(simbolo)

        if nuevas and self.clasificador is not None:
            try:
                resultado = self.clasificador.clasificar(empresa, simbolo, nuevas)
                ya.update(resultado.clasificaciones)
                for n in nuevas:
                    self._repo.guardar(n, resultado.clasificaciones.get(n.id), self.clasificador.modelo)
                if resultado.resumen:
                    resumen = resultado.resumen
                    self._repo.guardar_resumen(simbolo, resumen)
            except ErrorSentimiento as e:
                log.warning("%s: no se pudieron clasificar las noticias: %s", simbolo, e)
                avisos.append(f"No se pudo calcular el sentimiento: {e}")
        elif self.clasificador is None and self._cfg.usar_claude:
            avisos.append("Sentimiento desactivado: falta ANTHROPIC_API_KEY en el .env (ver README).")

        evaluadas = [
            NoticiaEvaluada(
                n, ya.get(n.id),
                peso_noticia(ya[n.id], n.publicada, ahora, self._cfg.vida_media_dias) if n.id in ya else 0.0,
            )
            for n in noticias
        ]
        puntaje, cobertura = agregar(evaluadas)
        return AnalisisNoticias(simbolo, empresa, evaluadas, puntaje, cobertura, resumen, avisos)
