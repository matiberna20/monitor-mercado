"""Carga y validación de la configuración (config.yaml) y de los secretos (.env).

Se usa pydantic para validar: si falta un dato o tiene un tipo incorrecto, el
programa falla al arrancar con un mensaje claro, y no horas después en medio de
una revisión de precios.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/monitor_mercado/configuracion.py -> la raíz del proyecto está dos niveles arriba.
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]


class ConfigAlertas(BaseModel):
    """Parámetros del ciclo de revisión de alertas."""

    intervalo_minutos: int = Field(5, ge=1, le=1440)
    solo_en_horario_de_mercado: bool = True
    margen_minutos_post_cierre: int = Field(20, ge=0)
    enfriamiento_minutos_repetir: int = Field(60, ge=0)


class ConfigMonedas(BaseModel):
    """Parámetros de conversión de monedas."""

    dolar_ars: Literal["ccl", "oficial"] = "ccl"
    ccl_accion_local: str = "GGAL.BA"
    ccl_adr: str = "GGAL"
    ccl_ratio: float = Field(10, gt=0)
    simbolos_byma: dict[str, str] = Field(default_factory=dict)


class ConfigAvisos(BaseModel):
    """Canal de salida de los avisos."""

    canal: Literal["telegram"] = "telegram"


class ConfigRutas(BaseModel):
    """Rutas de archivos locales (relativas a la raíz del proyecto)."""

    base_de_datos: str = "data/monitor.db"
    logs: str = "logs"

    def ruta_base_de_datos(self) -> Path:
        """Devuelve la ruta absoluta del archivo SQLite."""
        return _absoluta(self.base_de_datos)

    def ruta_logs(self) -> Path:
        """Devuelve la ruta absoluta de la carpeta de logs."""
        return _absoluta(self.logs)


class Configuracion(BaseModel):
    """Configuración completa del sistema (contenido de config.yaml)."""

    modo_watchlist: Literal["prueba", "completa"] = "prueba"
    watchlist_prueba: list[str] = Field(default_factory=list)
    watchlist_completa: list[str] = Field(default_factory=list)
    alertas: ConfigAlertas = Field(default_factory=ConfigAlertas)
    monedas: ConfigMonedas = Field(default_factory=ConfigMonedas)
    avisos: ConfigAvisos = Field(default_factory=ConfigAvisos)
    rutas: ConfigRutas = Field(default_factory=ConfigRutas)

    @property
    def watchlist_activa(self) -> list[str]:
        """Watchlist según el modo elegido, sin duplicados y en mayúsculas."""
        lista = self.watchlist_prueba if self.modo_watchlist == "prueba" else self.watchlist_completa
        return list(dict.fromkeys(s.strip().upper() for s in lista))


class Secretos(BaseSettings):
    """Claves y tokens leídos de variables de entorno o del archivo .env."""

    model_config = SettingsConfigDict(
        env_file=RAIZ_PROYECTO / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: int | None = None

    @property
    def telegram_configurado(self) -> bool:
        """True si hay token y chat ID para mandar mensajes."""
        return self.telegram_bot_token is not None and self.telegram_chat_id is not None


def _absoluta(ruta: str) -> Path:
    p = Path(ruta)
    return p if p.is_absolute() else RAIZ_PROYECTO / p


def cargar_configuracion(ruta: Path | None = None) -> Configuracion:
    """Lee y valida config.yaml.

    Args:
        ruta: Ruta al YAML. Por defecto, ``config.yaml`` en la raíz del proyecto.

    Raises:
        FileNotFoundError: Si el archivo no existe.
        pydantic.ValidationError: Si algún valor es inválido.
    """
    ruta = ruta or RAIZ_PROYECTO / "config.yaml"
    with open(ruta, encoding="utf-8") as f:
        datos = yaml.safe_load(f) or {}
    return Configuracion.model_validate(datos)


def cargar_secretos() -> Secretos:
    """Lee los secretos desde el entorno / .env."""
    return Secretos()
