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


class ConfigTecnico(BaseModel):
    """Parámetros del análisis técnico (Etapa 2)."""

    anios_historia: int = Field(10, ge=1, le=30)
    refresco_horas: float = Field(6, gt=0)
    ars_en_dolares_ccl: bool = True
    umbral_tendencia: float = Field(0.2, gt=0, lt=1)
    ruedas_patrones: int = Field(5, ge=1)
    ruedas_grafico: int = Field(180, ge=30)


class ConfigNoticias(BaseModel):
    """Parámetros de noticias y sentimiento (Etapa 3)."""

    habilitado: bool = True
    usar_claude: bool = False  # clasificar el sentimiento con la API de Claude (pago)
    dias: int = Field(7, ge=1, le=30)
    max_noticias: int = Field(25, ge=1, le=60)
    modelo: str = "claude-opus-5-5"
    esfuerzo: Literal["low", "medium", "high"] = "low"
    peso_en_senal: float = Field(0.3, ge=0, le=1)
    vida_media_dias: float = Field(2.0, gt=0)
    nombres: dict[str, str] = Field(default_factory=dict)
    idiomas: dict[str, Literal["es", "pt", "en"]] = Field(default_factory=dict)
    sec_contacto: str = ""


class ConfigResultados(BaseModel):
    """Parámetros del análisis de resultados (Etapa 4)."""

    empresas: list[str] = Field(default_factory=list)
    pares: dict[str, list[str]] = Field(default_factory=dict)
    revision_horas: float = Field(2, gt=0)
    aviso_previo_horas: float = Field(36, gt=0)
    sec_contacto: str = ""
    usar_claude: bool = False  # resumir el comunicado con la API de Claude (pago)
    modelo: str = "claude-opus-5-5"
    esfuerzo: Literal["low", "medium", "high"] = "medium"


class ConfigBacktest(BaseModel):
    """Parámetros del backtest (Etapa 5)."""

    anios_entrenamiento: int = Field(3, ge=1, le=8)
    anios_prueba: int = Field(1, ge=1, le=3)
    comisiones: dict[str, float] = Field(
        default_factory=lambda: {"EE.UU.": 0.001, "BYMA": 0.006, "B3": 0.003, "Xetra": 0.002, "Londres": 0.002}
    )
    comision_por_defecto: float = Field(0.003, ge=0)
    slippage: float = Field(0.0005, ge=0)
    permitir_corto: bool = False
    horizonte_dias: int = Field(20, ge=1)
    repeticiones_bootstrap: int = Field(2000, ge=100)


class ConfigCartera(BaseModel):
    """Seguimiento de tu cartera real."""

    archivo: str = "mi_cartera.csv"
    resumen_diario: bool = True
    hora_resumen: str = Field("16:20", pattern=r"^\d{1,2}:\d{2}$")  # hora de Nueva York
    noticias_maximas: int = Field(8, ge=0, le=20)
    concentracion_maxima: float = Field(0.25, gt=0, le=1)
    umbral_movimiento: float = Field(0.05, gt=0)

    def ruta(self) -> Path:
        """Ruta absoluta del archivo de cartera."""
        return _absoluta(self.archivo)


class ConfigAvisos(BaseModel):
    """Canal de salida de los avisos."""

    canal: Literal["telegram"] = "telegram"


class ConfigRutas(BaseModel):
    """Rutas de archivos locales (relativas a la raíz del proyecto)."""

    base_de_datos: str = "data/monitor.db"
    historico: str = "data/historico"
    nombres: str = "data/nombres.json"
    cache_info: str = "data/info_empresas.json"
    ciks_sec: str = "data/ciks_sec.json"
    graficos: str = "data/graficos"
    logs: str = "logs"

    def ruta_historico(self) -> Path:
        """Carpeta de los CSV de precios históricos."""
        return _absoluta(self.historico)

    def ruta_nombres(self) -> Path:
        """Archivo con los nombres de empresa ya resueltos."""
        return _absoluta(self.nombres)

    def ruta_cache_info(self) -> Path:
        """Archivo con la información de empresas (sector, múltiplos) cacheada."""
        return _absoluta(self.cache_info)

    def ruta_ciks(self) -> Path:
        """Archivo con los códigos CIK de la SEC."""
        return _absoluta(self.ciks_sec)

    def ruta_graficos(self) -> Path:
        """Carpeta de los gráficos generados."""
        return _absoluta(self.graficos)

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
    tecnico: ConfigTecnico = Field(default_factory=ConfigTecnico)
    noticias: ConfigNoticias = Field(default_factory=ConfigNoticias)
    resultados: ConfigResultados = Field(default_factory=ConfigResultados)
    backtest: ConfigBacktest = Field(default_factory=ConfigBacktest)
    cartera: ConfigCartera = Field(default_factory=ConfigCartera)
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
        env_file=RAIZ_PROYECTO / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # "TELEGRAM_CHAT_ID=" vacío cuenta como "no configurado", no como error.
        env_ignore_empty=True,
    )

    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: int | None = None
    anthropic_api_key: SecretStr | None = None
    finnhub_api_key: SecretStr | None = None
    marketaux_api_key: SecretStr | None = None
    newsapi_key: SecretStr | None = None

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
