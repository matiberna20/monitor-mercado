"""Envío simple (sincrónico) de mensajes por Telegram, para el CLI.

El bot usa su propio cliente asincrónico; esta función sirve para mandar un
mensaje desde un script sin levantar el bot completo.
"""

from __future__ import annotations

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

API = "https://api.telegram.org/bot{token}/sendMessage"


class ErrorTelegram(Exception):
    """Telegram rechazó el mensaje (token o chat ID incorrectos, por ejemplo)."""


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception_type(httpx.TransportError),
)
def enviar_mensaje(token: str, chat_id: int, texto: str) -> None:
    """Manda ``texto`` al chat indicado.

    Raises:
        ErrorTelegram: Si Telegram responde con error.
        httpx.TransportError: Si no hay conexión luego de los reintentos.
    """
    respuesta = httpx.post(
        API.format(token=token), json={"chat_id": chat_id, "text": texto}, timeout=20
    )
    datos = respuesta.json()
    if not datos.get("ok"):
        raise ErrorTelegram(datos.get("description", f"HTTP {respuesta.status_code}"))
