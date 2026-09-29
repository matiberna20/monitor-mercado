"""Acceso a las noticias guardadas en SQLite."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from monitor_mercado.noticias.modelos import Clasificacion, Noticia, NoticiaGuardada, ResumenNoticias


class RepositorioNoticias:
    """Guarda noticias y sus clasificaciones para no clasificarlas dos veces."""

    def __init__(self, motor: Engine) -> None:
        self._sesiones = sessionmaker(motor, expire_on_commit=False)

    def clasificadas(self, ids: list[str]) -> dict[str, Clasificacion]:
        """Clasificaciones ya guardadas para los ids pedidos."""
        if not ids:
            return {}
        with self._sesiones() as s:
            filas = s.scalars(select(NoticiaGuardada).where(NoticiaGuardada.id.in_(ids)))
            return {f.id: c for f in filas if (c := f.clasificacion()) is not None}

    def guardar(self, noticia: Noticia, clasificacion: Clasificacion | None, modelo: str | None) -> None:
        """Inserta o actualiza una noticia con su clasificación."""
        with self._sesiones.begin() as s:
            s.merge(
                NoticiaGuardada(
                    id=noticia.id,
                    simbolo=noticia.simbolo,
                    titulo=noticia.titulo,
                    fuente=noticia.fuente[:100],
                    url=noticia.url,
                    publicada=noticia.publicada.astimezone(timezone.utc).replace(tzinfo=None),
                    sentimiento=clasificacion.sentimiento.value if clasificacion else None,
                    puntaje=clasificacion.puntaje if clasificacion else None,
                    relevancia=clasificacion.relevancia if clasificacion else None,
                    factor=clasificacion.factor if clasificacion else None,
                    explicacion=clasificacion.explicacion if clasificacion else None,
                    modelo=modelo if clasificacion else None,
                    clasificada_en=datetime.now(timezone.utc).replace(tzinfo=None) if clasificacion else None,
                )
            )

    def guardar_resumen(self, simbolo: str, texto: str) -> None:
        """Guarda el último resumen general de un activo."""
        with self._sesiones.begin() as s:
            s.merge(ResumenNoticias(simbolo=simbolo, texto=texto,
                                    generado_en=datetime.now(timezone.utc).replace(tzinfo=None)))

    def resumen(self, simbolo: str) -> str | None:
        """Último resumen guardado de un activo."""
        with self._sesiones() as s:
            fila = s.get(ResumenNoticias, simbolo)
            return fila.texto if fila else None
