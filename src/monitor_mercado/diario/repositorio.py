"""Acceso a la tabla de operaciones."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from monitor_mercado.diario.modelos import Movimiento


class RepositorioDiario:
    """Operaciones CRUD sobre el diario."""

    def __init__(self, motor: Engine) -> None:
        self._sesiones = sessionmaker(motor, expire_on_commit=False)

    def guardar(self, movimiento: Movimiento) -> Movimiento:
        with self._sesiones.begin() as s:
            movimiento = s.merge(movimiento)
        return movimiento

    def obtener(self, id_mov: int) -> Movimiento | None:
        with self._sesiones() as s:
            return s.get(Movimiento, id_mov)

    def listar(self, simbolo: str | None = None) -> list[Movimiento]:
        """Movimientos en orden cronológico (de más viejo a más nuevo)."""
        consulta = select(Movimiento).order_by(Movimiento.fecha, Movimiento.id)
        if simbolo:
            consulta = consulta.where(Movimiento.simbolo == simbolo.upper())
        with self._sesiones() as s:
            return list(s.scalars(consulta))

    def borrar(self, id_mov: int) -> bool:
        with self._sesiones.begin() as s:
            mov = s.get(Movimiento, id_mov)
            if mov is None:
                return False
            s.delete(mov)
        return True
