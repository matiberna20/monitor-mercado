"""Herramientas que Claude puede usar para responder: cada una consulta un servicio existente.

En vez de pasarle toda la base de datos en el prompt, Claude pide solo lo que necesita
(la cartera, un precio, noticias...) y el sistema le devuelve el mismo texto que verías
con el comando de Telegram correspondiente.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Callable
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from monitor_mercado.aplicacion import Contexto

log = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")

_SIMBOLO = {"type": "string", "description": "Símbolo en formato Yahoo (AAPL, GGAL, ALUA.BA, BRK-B) o nombre de la empresa."}


def _herramienta(nombre: str, descripcion: str, propiedades: dict | None = None) -> dict:
    propiedades = propiedades or {}
    return {
        "name": nombre,
        "description": descripcion,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": propiedades,
            "required": list(propiedades),
            "additionalProperties": False,
        },
    }


HERRAMIENTAS = [
    _herramienta("ver_cartera", "Posiciones de la cartera del usuario: precio, variación del día, ganancia o "
                 "pérdida desde la compra, peso de cada una, total y dividendos (rendimiento total)."),
    _herramienta("evolucion_cartera", "Variación del valor total de la cartera en los últimos N días (usa las fotos "
                 "de cierre guardadas). Sirve para '¿cómo me fue esta semana / este mes?'.",
                 {"dias": {"type": "integer", "description": "Días hacia atrás (7 = una semana)."}}),
    _herramienta("precio", "Precio actual (con demora de 15-20 min) y variación del día de un activo.",
                 {"simbolo": _SIMBOLO}),
    _herramienta("noticias", "Noticias de los últimos días de un activo.", {"simbolo": _SIMBOLO}),
    _herramienta("resultados_empresa", "Último resultado trimestral de una empresa contra lo esperado.",
                 {"simbolo": _SIMBOLO}),
    _herramienta("diario_operaciones", "Compras y ventas registradas por el usuario, resultado realizado, tasa de "
                 "aciertos, mejores y peores operaciones. Símbolo vacío = todas.",
                 {"simbolo": {"type": "string", "description": "Símbolo, o cadena vacía para todas."}}),
    _herramienta("alertas_y_stops", "Alertas de precio activas y stops (stop-loss y trailing) del usuario."),
    _herramienta("dividendos", "Dividendos cobrados en el último año y próximos cobros de la cartera."),
]


class EjecutorHerramientas:
    """Ejecuta las herramientas contra los servicios del contexto."""

    def __init__(self, ctx: Contexto) -> None:
        self._ctx = ctx
        self._funciones: dict[str, Callable[[dict], str]] = {
            "ver_cartera": self._cartera,
            "evolucion_cartera": self._evolucion,
            "precio": self._precio,
            "noticias": self._noticias,
            "resultados_empresa": self._resultados,
            "diario_operaciones": self._diario,
            "alertas_y_stops": self._alertas,
            "dividendos": self._dividendos,
        }

    def ejecutar(self, nombre: str, entrada: dict) -> tuple[str, bool]:
        """Devuelve (texto, es_error). Nunca lanza: los errores se le informan a Claude."""
        funcion = self._funciones.get(nombre)
        if funcion is None:
            return f"No existe la herramienta '{nombre}'.", True
        try:
            return funcion(entrada or {}), False
        except Exception as e:  # noqa: BLE001 - un dato que falla no corta la respuesta
            log.warning("Asistente: falló %s(%s): %s", nombre, entrada, e)
            return f"No se pudo obtener el dato: {e}", True

    def _simbolo(self, entrada: dict) -> str:
        texto = str(entrada.get("simbolo", "")).strip()
        if not texto:
            raise ValueError("falta el símbolo")
        return self._ctx.buscador().resolver(texto).upper()

    # ---------------------------------------------------------------- funciones
    def _cartera(self, _: dict) -> str:
        from monitor_mercado.cartera.reporte import texto_cartera

        estado = self._ctx.cartera.estado()
        return texto_cartera(estado, self._ctx.rendimiento(estado))

    def _evolucion(self, entrada: dict) -> str:
        from monitor_mercado.cartera.reporte import pct, usd

        dias = max(1, min(int(entrada.get("dias") or 7), 3650))
        estado = self._ctx.cartera.estado()
        variacion = self._ctx.cartera.variacion_desde(estado, dias, datetime.now(NY).date())
        if variacion is None:
            return (f"No hay una foto de cierre de hace {dias} días (se guardan desde que corre el resumen diario). "
                    f"Valor actual: {usd(estado.valor)}; hoy: {pct(estado.variacion_dia)}.")
        return (f"Valor actual {usd(estado.valor)}. Variación en {dias} días: {pct(variacion)}. "
                f"Hoy: {pct(estado.variacion_dia)} ({usd(estado.resultado_dia, True)}).")

    def _precio(self, entrada: dict) -> str:
        from monitor_mercado.alertas.modelos import Moneda
        from monitor_mercado.notificaciones.formato import detalle_precio

        return detalle_precio(self._ctx.servicio.precio_en(self._simbolo(entrada), Moneda.USD))

    def _noticias(self, entrada: dict) -> str:
        from monitor_mercado.noticias.reporte import reporte_noticias

        if self._ctx.noticias is None:
            return "Las noticias están desactivadas en config.yaml."
        return reporte_noticias(self._ctx.noticias.analizar(self._simbolo(entrada)), maximo=8, con_pie=False)

    def _resultados(self, entrada: dict) -> str:
        from monitor_mercado.resultados.reporte import reporte_resultados

        return reporte_resultados(self._ctx.resultados.analizar(self._simbolo(entrada)))

    def _diario(self, entrada: dict) -> str:
        from monitor_mercado.notificaciones.telegram_bot import texto_diario_completo

        simbolo = str(entrada.get("simbolo", "")).strip()
        return texto_diario_completo(self._ctx, self._ctx.buscador().resolver(simbolo).upper() if simbolo else None)

    def _alertas(self, _: dict) -> str:
        from monitor_mercado.notificaciones.formato import mensaje_listado
        from monitor_mercado.stops.reporte import texto_stops

        partes = [mensaje_listado(self._ctx.servicio.repo.listar())]
        if self._ctx.stops is not None:
            partes.append(texto_stops(self._ctx.stops.estados()))
        return "\n\n".join(partes)

    def _dividendos(self, _: dict) -> str:
        from monitor_mercado.dividendos.reporte import texto_dividendos

        return texto_dividendos(self._ctx.dividendos.resumen())
