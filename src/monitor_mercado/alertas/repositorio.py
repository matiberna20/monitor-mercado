"""Acceso a la base SQLite de alertas (crear, listar, borrar, actualizar).

Patrón "repositorio": todo el SQL vive acá, y el resto del código trabaja con
objetos ``Alerta``. Cada operación abre y cierra su propia sesión, lo que es
seguro cuando el bot y la revisión periódica corren en hilos distintos.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from monitor_mercado.alertas.modelos import Alerta
from monitor_mercado.db import crear_motor

__all__ = ["RepositorioAlertas", "crear_motor"]


class RepositorioAlertas:
    """Operaciones CRUD sobre las alertas."""

    def __init__(self, motor: Engine) -> None:
        self._sesiones = sessionmaker(motor, expire_on_commit=False)

    def guardar(self, alerta: Alerta) -> Alerta:
        """Inserta o actualiza una alerta y la devuelve con su ``id``."""
        with self._sesiones.begin() as s:
            alerta = s.merge(alerta)
        return alerta

    def obtener(self, id_alerta: int) -> Alerta | None:
        """Busca una alerta por id."""
        with self._sesiones() as s:
            return s.get(Alerta, id_alerta)

    def listar(self, solo_activas: bool = True) -> list[Alerta]:
        """Lista alertas ordenadas por símbolo e id."""
        consulta = select(Alerta).order_by(Alerta.simbolo, Alerta.id)
        if solo_activas:
            consulta = consulta.where(Alerta.activa.is_(True))
        with self._sesiones() as s:
            return list(s.scalars(consulta))

    def borrar(self, id_alerta: int) -> bool:
        """Elimina una alerta. Devuelve False si no existía."""
        with self._sesiones.begin() as s:
            alerta = s.get(Alerta, id_alerta)
            if alerta is None:
                return False
            s.delete(alerta)
        return True
