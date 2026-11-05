"""Acceso a la tabla de stops."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from monitor_mercado.stops.modelos import Stop, TipoStop


class RepositorioStops:
    """Operaciones CRUD sobre los stops."""

    def __init__(self, motor: Engine) -> None:
        self._sesiones = sessionmaker(motor, expire_on_commit=False)

    def guardar(self, stop: Stop) -> Stop:
        """Inserta o actualiza un stop."""
        with self._sesiones.begin() as s:
            stop = s.merge(stop)
        return stop

    def obtener(self, id_stop: int) -> Stop | None:
        with self._sesiones() as s:
            return s.get(Stop, id_stop)

    def listar(self, solo_activos: bool = True) -> list[Stop]:
        """Stops ordenados por símbolo y tipo."""
        consulta = select(Stop).order_by(Stop.simbolo, Stop.tipo, Stop.id)
        if solo_activos:
            consulta = consulta.where(Stop.activa.is_(True))
        with self._sesiones() as s:
            return list(s.scalars(consulta))

    def de_simbolo(self, simbolo: str, tipo: TipoStop) -> Stop | None:
        """El stop de ese tipo para un símbolo (activo o no), si existe."""
        with self._sesiones() as s:
            return s.scalars(select(Stop).where(Stop.simbolo == simbolo, Stop.tipo == tipo)).first()

    def borrar(self, id_stop: int) -> bool:
        """Elimina un stop. Devuelve False si no existía."""
        with self._sesiones.begin() as s:
            stop = s.get(Stop, id_stop)
            if stop is None:
                return False
            s.delete(stop)
        return True
