"""Textos de los stops (Telegram y consola)."""

from __future__ import annotations

from monitor_mercado.aviso_legal import pie_de_mensaje
from monitor_mercado.cartera.reporte import pct
from monitor_mercado.notificaciones.formato import monto, numero
from monitor_mercado.stops.modelos import TipoStop
from monitor_mercado.stops.servicio import DisparoStop, EstadoStop

NOMBRE = {TipoStop.STOP_LOSS: "Stop-loss", TipoStop.TRAILING: "Trailing stop"}
DESDE = {TipoStop.STOP_LOSS: "tu precio de compra", TipoStop.TRAILING: "su máximo"}


def _usd(v: float | None) -> str:
    return "s/d" if v is None else monto(v, "USD")


def linea_stop(e: EstadoStop) -> str:
    """Una línea por stop para el listado."""
    s = e.stop
    texto = f"#{s.id} {s.simbolo} · {NOMBRE[s.tipo]} {numero(100 * s.porcentaje, 1)}%"
    if s.por_defecto:
        texto += " (por defecto)"
    if not e.en_cartera:
        return texto + " · ya no está en tu cartera"
    if e.precio is None:
        return texto + " · sin precio disponible"
    texto += (f" · {DESDE[s.tipo]} {_usd(e.referencia)} → avisa en {_usd(e.nivel)}"
              f" · hoy {_usd(e.precio)} ({pct(e.caida)})")
    if e.distancia is not None:
        texto += " · ⚠️ por debajo del stop" if e.distancia < 0 else f" · le falta {pct(-e.distancia)}"
    if not s.armada:
        texto += " · ⏳ en espera de que vuelva a subir"
    return texto


def texto_stops(estados: list[EstadoStop]) -> str:
    """Listado de stops."""
    if not estados:
        return ("No tenés stops. Creá uno con /stop AAPL 10 (cae 10% desde tu compra) o /trailing AAPL 8 "
                "(cae 8% desde su máximo).")
    return "🛑 Tus stops:\n" + "\n".join(linea_stop(e) for e in estados) + pie_de_mensaje()


def mensaje_creado(e: EstadoStop) -> str:
    """Confirmación de stop creado."""
    s = e.stop
    texto = (f"{NOMBRE[s.tipo]} guardado:\n{linea_stop(e)}\n\n"
             f"Te aviso si {s.simbolo} cae {numero(100 * s.porcentaje, 1)}% desde {DESDE[s.tipo]}.")
    if s.tipo is TipoStop.TRAILING:
        texto += " El máximo se actualiza solo en cada revisión, mientras el mercado está abierto."
    if not s.armada:
        texto += ("\n\nEl precio ya está por debajo del stop: no aviso ahora, aviso cuando vuelva a subir "
                  "y cruce de nuevo.")
    return texto + pie_de_mensaje()


def mensaje_disparo_stop(d: DisparoStop) -> str:
    """Aviso de stop cumplido."""
    e, s = d.estado, d.estado.stop
    precio = _usd(e.precio)
    if d.cotizacion.moneda != "USD":
        precio += f" (cotiza {numero(d.cotizacion.precio)} {d.cotizacion.moneda})"
    return (
        f"🛑 {NOMBRE[s.tipo].upper()} #{s.id}: {s.simbolo}\n"
        f"Cayó {pct(e.caida)} desde {DESDE[s.tipo]} ({_usd(e.referencia)}).\n"
        f"Precio: {precio} · nivel del stop: {_usd(e.nivel)} ({numero(100 * s.porcentaje, 1)}%)\n"
        "Es un aviso: no se vendió nada. El stop sigue activo y vuelve a avisar si el precio sube y cruza "
        "de nuevo." + pie_de_mensaje()
    )
