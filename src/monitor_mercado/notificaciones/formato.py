"""Textos de los mensajes (Telegram y consola)."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from monitor_mercado.alertas.modelos import Alerta, Condicion, Moneda, Operacion
from monitor_mercado.alertas.servicio import Disparo, PrecioEvaluado, ResultadoCreacion
from monitor_mercado.aviso_legal import pie_de_mensaje

ZONA_LOCAL = ZoneInfo("America/Argentina/Buenos_Aires")

_ICONO = {Operacion.COMPRA: "🟢", Operacion.VENTA: "🔴"}
_DESCRIPCION = {
    Condicion.SUBE_DE: "sube de",
    Condicion.BAJA_DE: "baja de",
    Condicion.VARIACION_SUBE: "sube en el día",
    Condicion.VARIACION_BAJA: "cae en el día",
}


def numero(valor: float, decimales: int = 2) -> str:
    """Formato argentino: 27.160,50."""
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


def monto(valor: float, moneda: Moneda | str) -> str:
    """Monto con su moneda: "US$ 180,00" o "$ 27.160,00"."""
    prefijo = "$" if str(moneda) == "ARS" else "US$"
    return f"{prefijo} {numero(valor)}"


def descripcion_condicion(alerta: Alerta) -> str:
    """Ej.: "baja de US$ 180,00" o "cae en el día 5,00%"."""
    if alerta.condicion.es_porcentual:
        return f"{_DESCRIPCION[alerta.condicion]} {numero(alerta.umbral)}%"
    return f"{_DESCRIPCION[alerta.condicion]} {monto(alerta.umbral, alerta.moneda)}"


def linea_alerta(alerta: Alerta) -> str:
    """Una línea por alerta para los listados."""
    extras = []
    if alerta.repetir:
        extras.append("🔁 repetir")
    if not alerta.armada and alerta.activa:
        extras.append("⏳ en espera de cruce")
    if not alerta.activa:
        extras.append("✅ cumplida")
    sufijo = f" ({', '.join(extras)})" if extras else ""
    return (
        f"#{alerta.id} {_ICONO[alerta.operacion]} {alerta.operacion.value.upper()} "
        f"{alerta.simbolo} si {descripcion_condicion(alerta)}{sufijo}"
    )


def detalle_precio(p: PrecioEvaluado) -> str:
    """Precio en la moneda de la alerta, con el precio nativo si es distinto."""
    cot = p.cotizacion
    texto = f"{cot.simbolo}: {monto(p.precio, p.moneda)}"
    if cot.moneda != p.moneda.value:
        texto += f" (cotiza {numero(cot.precio)} {cot.moneda})"
    if cot.variacion_pct is not None:
        texto += f" | día: {cot.variacion_pct:+.2f}%".replace(".", ",")
    return texto


def mensaje_disparo(d: Disparo) -> str:
    """Aviso de alerta cumplida."""
    a = d.alerta
    hora = d.precio.cotizacion.obtenida_en.astimezone(ZONA_LOCAL).strftime("%d/%m %H:%M")
    siguiente = (
        "La alerta se repite: vuelve a avisar cuando el precio cruce de nuevo."
        if a.repetir
        else "La alerta quedó desactivada."
    )
    nota = f"\nNota: {a.nota}" if a.nota else ""
    return (
        f"{_ICONO[a.operacion]} ALERTA DE {a.operacion.value.upper()} #{a.id}\n"
        f"{a.simbolo} {descripcion_condicion(a)}\n"
        f"Precio: {detalle_precio(d.precio)}\n"
        f"Consultado: {hora} (hora Argentina){nota}\n"
        f"{siguiente}" + pie_de_mensaje()
    )


def mensaje_creada(r: ResultadoCreacion) -> str:
    """Confirmación de alerta creada."""
    texto = f"Alerta creada:\n{linea_alerta(r.alerta)}\nAhora: {detalle_precio(r.precio_actual)}"
    if r.aviso:
        texto += f"\n\n{r.aviso}"
    return texto


def mensaje_listado(alertas: list[Alerta]) -> str:
    """Listado de alertas."""
    if not alertas:
        return "No hay alertas."
    return "Alertas:\n" + "\n".join(linea_alerta(a) for a in alertas)
