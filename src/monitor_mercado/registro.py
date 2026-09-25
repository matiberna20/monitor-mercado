"""Configuración de logs: a consola y a un archivo rotativo en logs/."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMATO = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def configurar_logs(carpeta: Path, nivel: int = logging.INFO) -> None:
    """Configura el logging raíz.

    Args:
        carpeta: Carpeta donde se escribe ``monitor.log`` (se crea si no existe).
        nivel: Nivel mínimo de los mensajes propios.
    """
    carpeta.mkdir(parents=True, exist_ok=True)
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    raiz.handlers.clear()

    formato = logging.Formatter(FORMATO)
    consola = logging.StreamHandler()
    consola.setFormatter(formato)
    archivo = RotatingFileHandler(
        carpeta / "monitor.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    archivo.setFormatter(formato)
    raiz.addHandler(consola)
    raiz.addHandler(archivo)

    # httpx registra cada URL en nivel INFO, y la URL de Telegram contiene el
    # token del bot: lo subimos a WARNING para que el token no quede en los logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # yfinance imprime mucho ruido ("possibly delisted", etc.); los errores
    # relevantes los registramos nosotros con más contexto.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
