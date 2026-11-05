"""Responde preguntas en lenguaje natural con Claude y tool use.

Cada pregunta es independiente (no hay memoria entre mensajes): así cada consulta
cuesta poco y es predecible. Claude decide qué herramientas usar, el sistema las
ejecuta contra los servicios reales y Claude arma la respuesta con esos datos.

Control de costos: modelo, esfuerzo y tope de tokens configurables, un máximo de
vueltas de herramientas por pregunta y un tope de consultas por día guardado en la
base (sobrevive a reinicios del bot).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from monitor_mercado.aviso_legal import AVISO_LEGAL, pie_de_mensaje
from monitor_mercado.configuracion import ConfigAsistente
from monitor_mercado.db import Base

log = logging.getLogger(__name__)
AR = ZoneInfo("America/Argentina/Buenos_Aires")

SISTEMA = f"""Sos el asistente de un sistema personal de seguimiento de inversiones. Respondés preguntas \
del dueño de la cartera por Telegram.

Reglas:
- Usá las herramientas para obtener los datos reales (cartera, precios, noticias, resultados, diario, alertas, \
dividendos) antes de responder. No inventes números: si un dato no está disponible, decilo.
- Nunca des recomendaciones de compra, venta o mantener, ni precios objetivo, ni le digas qué hacer con su \
plata. Si te lo piden, explicá que no podés recomendar operaciones y ofrecé los datos y el contexto que sí \
tenés (variaciones, noticias, resultados, riesgos de concentración).
- Respondé en español rioplatense, breve y claro, en texto plano (sin Markdown, sin tablas): se lee en el celular.
- Montos en dólares salvo que el usuario pida otra cosa. Los precios tienen 15-20 minutos de demora.
- Este aviso se agrega solo al final de tu respuesta: "{AVISO_LEGAL}". No hace falta que lo repitas."""


class UsoAsistente(Base):
    """Cuántas preguntas se hicieron cada día (para el tope diario)."""

    __tablename__ = "asistente_uso"

    fecha: Mapped[date] = mapped_column(primary_key=True)
    consultas: Mapped[int] = mapped_column(default=0)


@dataclass(frozen=True)
class Respuesta:
    """Texto final y datos de uso (para el registro)."""

    texto: str
    herramientas: list[str]
    tokens_entrada: int = 0
    tokens_salida: int = 0


class ServicioAsistente:
    """Orquesta la conversación con Claude y la ejecución de herramientas."""

    def __init__(self, cliente, ejecutor, cfg: ConfigAsistente, motor: Engine) -> None:
        """
        Args:
            cliente: ``anthropic.Anthropic`` (o un objeto falso en los tests). None = sin clave.
            ejecutor: ``EjecutorHerramientas``.
        """
        self._cliente = cliente
        self._ejecutor = ejecutor
        self._cfg = cfg
        self._sesiones = sessionmaker(motor, expire_on_commit=False)

    @property
    def disponible(self) -> bool:
        return self._cliente is not None

    # ---------------------------------------------------------------- tope
    def _hoy(self) -> date:
        return datetime.now(AR).date()

    def consultas_hoy(self) -> int:
        with self._sesiones() as s:
            uso = s.get(UsoAsistente, self._hoy())
            return uso.consultas if uso else 0

    def _sumar_consulta(self) -> None:
        with self._sesiones.begin() as s:
            uso = s.get(UsoAsistente, self._hoy()) or UsoAsistente(fecha=self._hoy(), consultas=0)
            uso.consultas += 1
            s.merge(uso)

    # ------------------------------------------------------------- responder
    def responder(self, pregunta: str) -> str:
        """Responde una pregunta. Nunca lanza: los problemas se explican en el texto."""
        if self._cliente is None:
            return ("Para responder preguntas en lenguaje natural hace falta la clave de la API de Claude: cargá "
                    "ANTHROPIC_API_KEY en el .env (ver README, sección 'Preguntas en lenguaje natural') y reiniciá el "
                    "bot. Mientras tanto podés usar los comandos (/ayuda).")
        if not self._cfg.habilitado:
            return "Las preguntas en lenguaje natural están desactivadas (config.yaml → asistente.habilitado)."
        if self.consultas_hoy() >= self._cfg.consultas_por_dia:
            return (f"Llegaste al tope de {self._cfg.consultas_por_dia} preguntas por hoy (config.yaml → "
                    "asistente.consultas_por_dia). Mañana se renueva; mientras tanto podés usar los comandos.")
        self._sumar_consulta()
        try:
            r = self._conversar(pregunta.strip()[:2000])
        except Exception as e:  # noqa: BLE001 - se clasifica abajo
            return self._mensaje_error(e)
        log.info("Asistente: %d herramientas (%s), %d tokens de entrada, %d de salida",
                 len(r.herramientas), ", ".join(r.herramientas), r.tokens_entrada, r.tokens_salida)
        return r.texto + pie_de_mensaje()

    def _conversar(self, pregunta: str) -> Respuesta:
        from monitor_mercado.asistente.herramientas import HERRAMIENTAS

        mensajes: list[dict] = [{"role": "user", "content": pregunta}]
        usadas: list[str] = []
        entrada = salida = 0
        for _ in range(self._cfg.max_vueltas):
            r = self._cliente.beta.messages.create(
                model=self._cfg.modelo,
                max_tokens=self._cfg.max_tokens,
                system=SISTEMA,
                tools=HERRAMIENTAS,
                messages=mensajes,
                output_config={"effort": self._cfg.esfuerzo},
                # Si el modelo declina por sus filtros de seguridad, la API reintenta con otro modelo.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            entrada += getattr(r.usage, "input_tokens", 0) or 0
            salida += getattr(r.usage, "output_tokens", 0) or 0

            if r.stop_reason == "refusal":
                return Respuesta("No puedo responder esa pregunta. Probá reformularla o usá los comandos (/ayuda).",
                                 usadas, entrada, salida)
            mensajes.append({"role": "assistant", "content": r.content})
            if r.stop_reason == "pause_turn":
                continue
            pedidos = [b for b in r.content if b.type == "tool_use"]
            if r.stop_reason != "tool_use" or not pedidos:
                texto = "\n".join(b.text for b in r.content if b.type == "text").strip()
                if r.stop_reason == "max_tokens":
                    texto += "\n\n(La respuesta quedó cortada por el límite de tokens: asistente.max_tokens.)"
                return Respuesta(texto or "No encontré una respuesta.", usadas, entrada, salida)

            resultados = []
            for p in pedidos:
                usadas.append(p.name)
                texto, es_error = self._ejecutor.ejecutar(p.name, p.input)
                resultados.append({"type": "tool_result", "tool_use_id": p.id, "content": texto[:20000],
                                   **({"is_error": True} if es_error else {})})
            mensajes.append({"role": "user", "content": resultados})

        return Respuesta("La pregunta necesitó demasiados pasos y la corté para no gastar de más "
                         "(asistente.max_vueltas). Probá con una pregunta más concreta.", usadas, entrada, salida)

    @staticmethod
    def _mensaje_error(e: Exception) -> str:
        import anthropic

        if isinstance(e, anthropic.AuthenticationError):
            return "La clave ANTHROPIC_API_KEY no es válida. Revisala en el .env."
        if isinstance(e, anthropic.PermissionDeniedError):
            return "La clave de la API no tiene permiso para usar ese modelo (config.yaml → asistente.modelo)."
        if isinstance(e, anthropic.NotFoundError):
            return "El modelo configurado no existe (config.yaml → asistente.modelo)."
        if isinstance(e, anthropic.RateLimitError):
            return "La API de Claude está limitando las consultas en este momento. Probá en un rato."
        if isinstance(e, anthropic.BadRequestError):
            log.error("Asistente: pedido inválido: %s", e)
            return f"La API rechazó la consulta: {e.message}"
        if isinstance(e, anthropic.APIStatusError):
            return f"La API de Claude respondió con un error ({e.status_code}). Probá en un rato."
        if isinstance(e, anthropic.APIConnectionError):
            return "No me pude conectar con la API de Claude (¿hay internet?). Probá en un rato."
        log.exception("Asistente: error inesperado", exc_info=e)
        return f"Ocurrió un error inesperado al responder: {e}"
