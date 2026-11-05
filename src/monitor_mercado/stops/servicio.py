"""Casos de uso de los stops: crear, listar y revisar contra el precio actual.

Reutiliza la lógica de las alertas (``alertas.evaluador.evaluar``): un stop es una
alerta repetitiva de "baja de" cuyo nivel se calcula en cada revisión. Eso le da el
mismo comportamiento: solo avisa al cruzar, no repite mientras el precio sigue abajo
y respeta el enfriamiento y el horario de mercado.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from monitor_mercado.alertas.evaluador import condicion_cumplida, evaluar
from monitor_mercado.alertas.modelos import Condicion
from monitor_mercado.cartera.archivo import Posicion
from monitor_mercado.cartera.servicio import ServicioCartera
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.datos.modelos import Cotizacion, ErrorDatos
from monitor_mercado.datos.monedas import ConversorMonedas
from monitor_mercado.datos.proveedor import ProveedorPrecios
from monitor_mercado.mercados import esta_abierto
from monitor_mercado.stops.modelos import Stop, TipoStop
from monitor_mercado.stops.repositorio import RepositorioStops

log = logging.getLogger(__name__)


class ErrorStop(ValueError):
    """El stop no se puede crear (símbolo fuera de la cartera, sin precio de compra, etc.)."""


@dataclass(frozen=True)
class _VistaAlerta:
    """Un stop visto como alerta, para reutilizar ``evaluar``."""

    condicion: Condicion
    umbral: float
    armada: bool
    activa: bool
    repetir: bool
    ultimo_disparo: datetime | None


@dataclass(frozen=True)
class EstadoStop:
    """Un stop con el precio actual (todo en USD)."""

    stop: Stop
    precio: float | None
    referencia: float | None  # precio de compra o máximo
    nivel: float | None  # precio que dispara el aviso
    en_cartera: bool = True

    @property
    def caida(self) -> float | None:
        """Cuánto cayó el precio desde la referencia (fracción, negativa si bajó)."""
        if self.precio is None or not self.referencia:
            return None
        return self.precio / self.referencia - 1

    @property
    def distancia(self) -> float | None:
        """Cuánto le falta al precio para tocar el stop (fracción; negativa si ya lo cruzó)."""
        if self.precio is None or not self.nivel:
            return None
        return self.precio / self.nivel - 1


@dataclass(frozen=True)
class DisparoStop:
    """Un stop que se cumplió en una revisión."""

    estado: EstadoStop
    cotizacion: Cotizacion


class ServicioStops:
    """Crea, lista y revisa stops sobre las posiciones de la cartera."""

    def __init__(
        self, repo: RepositorioStops, proveedor: ProveedorPrecios, cfg: Configuracion, cartera: ServicioCartera
    ) -> None:
        self.repo = repo
        self._proveedor = proveedor
        self._cfg = cfg
        self._cartera = cartera

    # ------------------------------------------------------------ auxiliares
    def _posiciones(self) -> dict[str, Posicion]:
        return {p.simbolo: p for p in self._cartera.posiciones()}

    def _precios_usd(self, simbolos: list[str]) -> dict[str, tuple[Cotizacion, float, float]]:
        """{símbolo: (cotización, precio en USD, USD por unidad de su moneda)}."""
        conversor = ConversorMonedas(self._proveedor, self._cfg.monedas)
        resultado = {}
        for s, c in self._proveedor.cotizaciones(list(dict.fromkeys(simbolos))).items():
            try:
                factor = conversor.a_usd(1.0, c.moneda)
            except ErrorDatos as e:
                log.warning("%s: no se pudo convertir %s a USD: %s", s, c.moneda, e)
                continue
            resultado[s] = (c, c.precio * factor, factor)
        return resultado

    @staticmethod
    def _costo_usd(posicion: Posicion, factor: float) -> float | None:
        """Precio de compra por acción en USD (None si no se conoce)."""
        if posicion.precio_compra is None:
            return None
        return posicion.precio_compra if posicion.moneda == "USD" else posicion.precio_compra * factor

    @classmethod
    def _referencia(cls, stop: Stop, posicion: Posicion, precio: float, factor: float) -> float | None:
        """Precio de compra (stop-loss) o máximo actualizado (trailing). Actualiza ``stop.maximo``."""
        if stop.tipo is TipoStop.STOP_LOSS:
            return cls._costo_usd(posicion, factor)
        if stop.maximo is None:  # arranca en el mayor entre el precio de hoy y el de compra
            stop.maximo = max(precio, cls._costo_usd(posicion, factor) or 0.0)
        stop.maximo = max(stop.maximo, precio)
        return stop.maximo

    # ---------------------------------------------------------------- crear
    def crear(self, simbolo: str, tipo: TipoStop, porcentaje: float) -> EstadoStop:
        """Crea (o reemplaza) el stop de ese tipo para una posición.

        Args:
            porcentaje: Caída que dispara el aviso, en % (10 = 10%).

        Raises:
            ErrorStop: Si el símbolo no está en la cartera, el porcentaje es inválido o,
                para un stop-loss, no hay precio de compra.
            ErrorDatos: Si no se pudo obtener el precio.
        """
        simbolo = simbolo.upper()
        if not 0 < porcentaje < 100:
            raise ErrorStop("El porcentaje tiene que estar entre 0 y 100 (ej. 10 para 10%).")
        posicion = self._posiciones().get(simbolo)
        if posicion is None:
            raise ErrorStop(f"{simbolo} no está en tu cartera (mi_cartera.csv o el diario).")
        precios = self._precios_usd([simbolo])
        if simbolo not in precios:
            raise ErrorDatos(f"{simbolo}: no se pudo obtener el precio actual")
        _, precio, factor = precios[simbolo]
        if tipo is TipoStop.STOP_LOSS and posicion.precio_compra is None:
            raise ErrorStop(f"{simbolo} no tiene precio de compra: cargalo para usar un stop-loss "
                            "(o usá /trailing, que se mide desde el máximo).")

        stop = self.repo.de_simbolo(simbolo, tipo) or Stop(simbolo=simbolo, tipo=tipo)
        stop.porcentaje = porcentaje / 100
        stop.por_defecto = False
        stop.activa = True
        stop.ultimo_disparo = None
        stop.maximo = None  # el trailing vuelve a arrancar desde hoy
        referencia = self._referencia(stop, posicion, precio, factor)
        nivel = referencia * (1 - stop.porcentaje)
        # Igual que las alertas: si ya está por debajo, no avisa enseguida, espera el cruce.
        stop.armada = not condicion_cumplida(Condicion.BAJA_DE, nivel, precio, None)
        stop = self.repo.guardar(stop)
        log.info("Stop creado: %r", stop)
        return EstadoStop(stop, precio, referencia, nivel)

    def borrar(self, id_stop: int) -> bool:
        """Borra un stop. Los creados por defecto se desactivan (si no, se volverían a crear)."""
        stop = self.repo.obtener(id_stop)
        if stop is None:
            return False
        if stop.por_defecto:
            stop.activa = False
            self.repo.guardar(stop)
            return True
        return self.repo.borrar(id_stop)

    # ------------------------------------------------------------ defectos
    def sincronizar_defectos(self, posiciones: list[Posicion]) -> None:
        """Crea los stops por defecto de config.yaml para las posiciones que no tienen uno.

        No pisa un stop que configuraste a mano, ni vuelve a crear uno que borraste.
        Borra los stops por defecto de posiciones que ya no tenés.
        """
        defectos = {TipoStop.STOP_LOSS: self._cfg.cartera.stop_loss_por_defecto,
                    TipoStop.TRAILING: self._cfg.cartera.trailing_por_defecto}
        simbolos = {p.simbolo for p in posiciones}
        for stop in self.repo.listar(solo_activos=False):
            if stop.por_defecto and stop.simbolo not in simbolos:
                self.repo.borrar(stop.id)
        for tipo, pct in defectos.items():
            if not pct:
                continue
            for p in posiciones:
                if tipo is TipoStop.STOP_LOSS and p.precio_compra is None:
                    continue
                if self.repo.de_simbolo(p.simbolo, tipo) is None:
                    # El nivel inicial se completa en la primera revisión (maximo=None).
                    self.repo.guardar(Stop(simbolo=p.simbolo, tipo=tipo, porcentaje=pct / 100, por_defecto=True))

    # -------------------------------------------------------------- listar
    def estados(self) -> list[EstadoStop]:
        """Todos los stops activos con el precio actual."""
        posiciones = self._posiciones()
        self.sincronizar_defectos(list(posiciones.values()))
        stops = self.repo.listar()
        precios = self._precios_usd([s.simbolo for s in stops if s.simbolo in posiciones])
        estados = []
        for stop in stops:
            posicion = posiciones.get(stop.simbolo)
            if posicion is None or stop.simbolo not in precios:
                estados.append(EstadoStop(stop, None, None, None, en_cartera=posicion is not None))
                continue
            _, precio, factor = precios[stop.simbolo]
            referencia = self._referencia(stop, posicion, precio, factor)
            nivel = referencia * (1 - stop.porcentaje) if referencia else None
            estados.append(EstadoStop(stop, precio, referencia, nivel))
        return estados

    # ------------------------------------------------------------- revisar
    def revisar(self, ahora: datetime | None = None, forzar: bool = False) -> list[DisparoStop]:
        """Revisa los stops activos y devuelve los que se cumplieron.

        Args:
            ahora: Momento de la revisión (para tests).
            forzar: Ignorar el horario de mercado.
        """
        ahora = ahora or datetime.now(timezone.utc)
        cfg = self._cfg.alertas
        enfriamiento = timedelta(minutes=cfg.enfriamiento_minutos_repetir)
        posiciones = self._posiciones()
        self.sincronizar_defectos(list(posiciones.values()))
        pendientes = [
            s for s in self.repo.listar()
            if s.simbolo in posiciones and (forzar or not cfg.solo_en_horario_de_mercado
                                            or esta_abierto(s.simbolo, ahora, cfg.margen_minutos_post_cierre))
        ]
        if not pendientes:
            return []
        precios = self._precios_usd([s.simbolo for s in pendientes])
        disparos: list[DisparoStop] = []
        for stop in pendientes:
            if stop.simbolo not in precios:
                continue  # el proveedor ya registró el motivo
            cot, precio, factor = precios[stop.simbolo]
            maximo_antes = stop.maximo
            referencia = self._referencia(stop, posiciones[stop.simbolo], precio, factor)
            if not referencia:
                continue
            nivel = referencia * (1 - stop.porcentaje)
            vista = _VistaAlerta(Condicion.BAJA_DE, nivel, stop.armada, stop.activa, True, stop.ultimo_disparo)
            decision = evaluar(vista, precio, None, ahora, enfriamiento)  # type: ignore[arg-type]
            if decision.armada != stop.armada or decision.disparar or stop.maximo != maximo_antes:
                stop.armada = decision.armada
                if decision.disparar:
                    stop.ultimo_disparo = ahora
                    stop.veces_disparada += 1
                stop = self.repo.guardar(stop)
            if decision.disparar:
                log.info("Stop disparado: %r a %.4f USD", stop, precio)
                disparos.append(DisparoStop(EstadoStop(stop, precio, referencia, nivel), cot))
        return disparos
