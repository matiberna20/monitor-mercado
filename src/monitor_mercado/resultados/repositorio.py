"""Acceso a las tablas de resultados."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from monitor_mercado.resultados.comunicado import AnalisisComunicado, analisis_a_json, analisis_desde_json
from monitor_mercado.resultados.modelos import AvisoResultados, ComunicadoGuardado, ConsensoGuardado, EmpresaSeguida


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RepositorioResultados:
    """Empresas seguidas, consensos, avisos enviados y comunicados analizados."""

    def __init__(self, motor: Engine) -> None:
        self._s = sessionmaker(motor, expire_on_commit=False)

    # --- empresas seguidas
    def seguidas(self) -> list[str]:
        """Símbolos seguidos, en orden alfabético."""
        with self._s() as s:
            return sorted(s.scalars(select(EmpresaSeguida.simbolo)))

    def seguir(self, simbolo: str) -> bool:
        """Agrega una empresa. Devuelve False si ya estaba."""
        with self._s.begin() as s:
            if s.get(EmpresaSeguida, simbolo.upper()):
                return False
            s.add(EmpresaSeguida(simbolo=simbolo.upper(), desde=_ahora()))
        return True

    def dejar(self, simbolo: str) -> bool:
        """Quita una empresa. Devuelve False si no estaba."""
        with self._s.begin() as s:
            fila = s.get(EmpresaSeguida, simbolo.upper())
            if fila is None:
                return False
            s.delete(fila)
        return True

    # --- consensos
    def guardar_consenso(self, simbolo: str, fecha: date, eps: float | None, ingresos: float | None,
                         moneda: str | None) -> None:
        """Guarda (o actualiza) el consenso para una presentación futura."""
        with self._s.begin() as s:
            s.merge(ConsensoGuardado(simbolo=simbolo.upper(), fecha_evento=fecha, eps=eps, ingresos=ingresos,
                                     moneda_ingresos=moneda, capturado_en=_ahora()))

    def consenso(self, simbolo: str, fecha: date) -> ConsensoGuardado | None:
        """Consenso guardado para una presentación (tolera ±3 días de diferencia en la fecha)."""
        with self._s() as s:
            filas = s.scalars(select(ConsensoGuardado).where(ConsensoGuardado.simbolo == simbolo.upper()))
            cercanas = [f for f in filas if abs((f.fecha_evento - fecha).days) <= 3]
            return min(cercanas, key=lambda f: abs((f.fecha_evento - fecha).days)) if cercanas else None

    # --- avisos
    def avisado(self, simbolo: str, fecha: date, tipo: str) -> bool:
        """True si ese aviso ya se envió."""
        with self._s() as s:
            return s.get(AvisoResultados, (simbolo.upper(), fecha, tipo)) is not None

    def marcar_avisado(self, simbolo: str, fecha: date, tipo: str) -> None:
        """Registra que el aviso se envió."""
        with self._s.begin() as s:
            s.merge(AvisoResultados(simbolo=simbolo.upper(), fecha_evento=fecha, tipo=tipo, enviado_en=_ahora()))

    # --- comunicados
    def comunicado(self, simbolo: str, fecha: date) -> tuple[AnalisisComunicado, str, str] | None:
        """Análisis guardado, con la URL y el formulario del comunicado."""
        with self._s() as s:
            fila = s.get(ComunicadoGuardado, (simbolo.upper(), fecha))
            return (analisis_desde_json(fila.analisis), fila.url, fila.formulario) if fila else None

    def guardar_comunicado(self, simbolo: str, fecha: date, formulario: str, url: str,
                           analisis: AnalisisComunicado) -> None:
        """Guarda el análisis del comunicado."""
        with self._s.begin() as s:
            s.merge(ComunicadoGuardado(simbolo=simbolo.upper(), fecha_evento=fecha, formulario=formulario, url=url,
                                       analisis=analisis_a_json(analisis)))
