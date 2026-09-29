"""Fuentes de noticias: RSS públicos (sin clave) y APIs opcionales (con clave gratis).

Se usan solo fuentes que ofrecen sus titulares para este uso (RSS públicos y APIs
oficiales). No se scrapean sitios como Bloomberg, cuyos términos lo prohíben.

| Fuente          | Clave        | Cobertura                                      |
|-----------------|--------------|------------------------------------------------|
| Yahoo Finance   | no           | Titulares por ticker de EE.UU. (en inglés)     |
| Google News     | no           | Búsqueda por nombre de empresa, en el idioma   |
|                 |              | del mercado (medios argentinos, brasileños...) |
| SEC EDGAR       | no (*)       | Hechos relevantes 8-K de empresas de EE.UU.    |
| Finnhub         | sí (gratis)  | Noticias por ticker de EE.UU.                  |
| Marketaux       | sí (gratis)  | Noticias por ticker, varios mercados           |
| NewsAPI         | sí (gratis)  | Búsqueda en miles de medios (uso personal)     |

(*) La SEC exige identificarse con un mail de contacto en cada consulta.
"""

from __future__ import annotations

import logging
import re
from calendar import timegm
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import quote_plus

import feedparser
import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from monitor_mercado.noticias.modelos import Noticia

log = logging.getLogger(__name__)

AGENTE = "Mozilla/5.0 (monitor-mercado; uso personal)"

_reintentar_red = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=15),
    retry=retry_if_exception_type(httpx.TransportError),
)


class ErrorFuente(Exception):
    """Una fuente de noticias no respondió o respondió con error."""


class FuenteNoticias(Protocol):
    """Interfaz común de todas las fuentes."""

    nombre: str

    def aplica(self, simbolo: str) -> bool:
        """Si esta fuente tiene sentido para el símbolo (ej. Yahoo solo EE.UU.)."""
        ...

    def buscar(self, simbolo: str, empresa: str, desde: datetime) -> list[Noticia]:
        """Titulares publicados desde ``desde`` (UTC)."""
        ...


def es_de_eeuu(simbolo: str) -> bool:
    """True para tickers que cotizan en EE.UU. (sin sufijo de otra bolsa)."""
    return "." not in simbolo and not simbolo.startswith("^") and "=" not in simbolo


def _fecha_entrada(entrada: feedparser.FeedParserDict) -> datetime | None:
    estructura = entrada.get("published_parsed") or entrada.get("updated_parsed")
    if not estructura:
        return None
    return datetime.fromtimestamp(timegm(estructura), tz=timezone.utc)


def _desde_rss(simbolo: str, contenido: str | bytes, nombre_fuente: str, desde: datetime) -> list[Noticia]:
    """Convierte un feed RSS/Atom en noticias (función pura: testeable sin red)."""
    feed = feedparser.parse(contenido)
    noticias = []
    for e in feed.entries:
        fecha = _fecha_entrada(e)
        titulo = (e.get("title") or "").strip()
        if not titulo or fecha is None or fecha < desde:
            continue
        medio = e.get("source", {}).get("title") if isinstance(e.get("source"), dict) else None
        noticias.append(
            Noticia(
                simbolo=simbolo,
                titulo=titulo,
                fuente=f"{nombre_fuente}: {medio}" if medio else nombre_fuente,
                url=e.get("link", ""),
                publicada=fecha,
                resumen=_sin_html(e.get("summary", ""))[:500],
            )
        )
    return noticias


def _sin_html(texto: str) -> str:
    """Quita etiquetas HTML simples de un resumen de RSS."""
    return re.sub(r"<[^>]+>", " ", texto).replace("&nbsp;", " ").strip()


@_reintentar_red
def _descargar(url: str, **kwargs) -> httpx.Response:
    respuesta = httpx.get(url, timeout=20, follow_redirects=True, **kwargs)
    if respuesta.status_code >= 400:
        raise ErrorFuente(f"HTTP {respuesta.status_code} en {url.split('?')[0]}")
    return respuesta


class YahooRSS:
    """Titulares de Yahoo Finance por ticker (solo EE.UU.)."""

    nombre = "Yahoo Finance"
    URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={s}&region=US&lang=en-US"

    def aplica(self, simbolo: str) -> bool:
        return es_de_eeuu(simbolo)

    def buscar(self, simbolo: str, empresa: str, desde: datetime) -> list[Noticia]:
        r = _descargar(self.URL.format(s=quote_plus(simbolo)), headers={"User-Agent": AGENTE})
        return _desde_rss(simbolo, r.content, self.nombre, desde)


class GoogleNewsRSS:
    """Búsqueda de Google News por nombre de empresa, en el idioma de su mercado."""

    nombre = "Google News"
    URL = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"
    IDIOMAS = {
        "es": ("es-419", "AR", "AR:es-419"),
        "pt": ("pt-BR", "BR", "BR:pt-419"),
        "en": ("en-US", "US", "US:en"),
    }

    def __init__(self, idioma_por_simbolo: dict[str, str] | None = None) -> None:
        self._idiomas = {k.upper(): v for k, v in (idioma_por_simbolo or {}).items()}

    def idioma(self, simbolo: str) -> str:
        """Idioma de búsqueda: configurado, o según la bolsa del símbolo."""
        if simbolo in self._idiomas:
            return self._idiomas[simbolo]
        if simbolo.endswith(".BA"):
            return "es"
        if simbolo.endswith(".SA"):
            return "pt"
        return "en"

    def aplica(self, simbolo: str) -> bool:
        return not simbolo.startswith("^")

    def buscar(self, simbolo: str, empresa: str, desde: datetime) -> list[Noticia]:
        hl, gl, ceid = self.IDIOMAS[self.idioma(simbolo)]
        dias = max(1, (datetime.now(timezone.utc) - desde).days)
        consulta = quote_plus(f'"{empresa}" when:{dias}d')
        r = _descargar(self.URL.format(q=consulta, hl=hl, gl=gl, ceid=ceid), headers={"User-Agent": AGENTE})
        return _desde_rss(simbolo, r.content, self.nombre, desde)


class SecEdgar:
    """Últimos 8-K (hechos relevantes) presentados ante la SEC. Requiere mail de contacto."""

    nombre = "SEC EDGAR"
    URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={s}&type=8-K"
           "&dateb=&owner=include&count=10&output=atom")

    def __init__(self, contacto: str) -> None:
        self._agente = f"monitor-mercado uso-personal {contacto}"

    def aplica(self, simbolo: str) -> bool:
        return es_de_eeuu(simbolo)

    def buscar(self, simbolo: str, empresa: str, desde: datetime) -> list[Noticia]:
        r = _descargar(self.URL.format(s=quote_plus(simbolo)), headers={"User-Agent": self._agente})
        noticias = _desde_rss(simbolo, r.content, self.nombre, desde)
        return [Noticia(n.simbolo, f"{empresa} presentó un {n.titulo}", n.fuente, n.url, n.publicada, n.resumen)
                for n in noticias]


class Finnhub:
    """Noticias por ticker de Finnhub (plan gratuito, EE.UU.)."""

    nombre = "Finnhub"

    def __init__(self, clave: str) -> None:
        self._clave = clave

    def aplica(self, simbolo: str) -> bool:
        return es_de_eeuu(simbolo)

    def buscar(self, simbolo: str, empresa: str, desde: datetime) -> list[Noticia]:
        hoy = datetime.now(timezone.utc).date()
        r = _descargar(
            "https://finnhub.io/api/v1/company-news",
            params={"symbol": simbolo, "from": desde.date().isoformat(), "to": hoy.isoformat(),
                    "token": self._clave},
        )
        return [
            Noticia(simbolo, n["headline"], f"{self.nombre}: {n.get('source', '')}", n.get("url", ""),
                    datetime.fromtimestamp(n["datetime"], tz=timezone.utc), n.get("summary", "")[:500])
            for n in r.json() if n.get("headline")
        ]


class Marketaux:
    """Noticias por ticker de Marketaux (plan gratuito)."""

    nombre = "Marketaux"

    def __init__(self, clave: str) -> None:
        self._clave = clave

    def aplica(self, simbolo: str) -> bool:
        return not simbolo.startswith("^")

    def buscar(self, simbolo: str, empresa: str, desde: datetime) -> list[Noticia]:
        r = _descargar(
            "https://api.marketaux.com/v1/news/all",
            params={"symbols": simbolo.split(".")[0], "filter_entities": "true",
                    "published_after": desde.strftime("%Y-%m-%dT%H:%M"), "api_token": self._clave},
        )
        return [
            Noticia(simbolo, n["title"], f"{self.nombre}: {n.get('source', '')}", n.get("url", ""),
                    datetime.fromisoformat(n["published_at"].replace("Z", "+00:00")),
                    (n.get("description") or "")[:500])
            for n in r.json().get("data", []) if n.get("title")
        ]


class NewsAPI:
    """Búsqueda por nombre de empresa en NewsAPI (plan gratuito para uso personal)."""

    nombre = "NewsAPI"

    def __init__(self, clave: str) -> None:
        self._clave = clave

    def aplica(self, simbolo: str) -> bool:
        return not simbolo.startswith("^")

    def buscar(self, simbolo: str, empresa: str, desde: datetime) -> list[Noticia]:
        r = _descargar(
            "https://newsapi.org/v2/everything",
            params={"q": f'"{empresa}"', "from": desde.date().isoformat(), "sortBy": "publishedAt",
                    "pageSize": 20, "apiKey": self._clave},
        )
        return [
            Noticia(simbolo, n["title"], f"{self.nombre}: {n.get('source', {}).get('name', '')}",
                    n.get("url", ""), datetime.fromisoformat(n["publishedAt"].replace("Z", "+00:00")),
                    (n.get("description") or "")[:500])
            for n in r.json().get("articles", []) if n.get("title")
        ]


def buscar_en_todas(
    fuentes: list[FuenteNoticias], simbolo: str, empresa: str, dias: int
) -> tuple[list[Noticia], list[str]]:
    """Consulta todas las fuentes aplicables. Devuelve noticias sin duplicar y errores."""
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    vistas: dict[str, Noticia] = {}
    errores: list[str] = []
    for fuente in fuentes:
        if not fuente.aplica(simbolo):
            continue
        try:
            for n in fuente.buscar(simbolo, empresa, desde):
                vistas.setdefault(n.id, n)  # mismo titular en dos fuentes = una noticia
        except (ErrorFuente, httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("%s: la fuente %s falló: %s", simbolo, fuente.nombre, e)
            errores.append(f"{fuente.nombre}: {e}")
    return sorted(vistas.values(), key=lambda n: n.publicada, reverse=True), errores
