"""Búsqueda tolerante de símbolos: acepta nombres de empresas y sugiere ante errores de tipeo.

Ejemplos:
    "nvidia"   -> NVDA       (por el nombre de la empresa)
    "galicia"  -> GGAL       (por una palabra distintiva del nombre)
    "NVDIA"    -> sin datos, pero sugiere NVDA (por parecido)
"""

from __future__ import annotations

import difflib
import re
import unicodedata

# Palabras que aparecen en muchos nombres y no sirven para identificar una empresa.
_GENERICAS = {
    "grupo", "group", "financiero", "financial", "holdings", "holding", "corporation", "company", "banco",
    "bank", "energy", "trust", "the", "and", "inc", "corp", "international", "technologies", "technology",
    "platforms", "communications", "systems", "shares", "ishares", "fund", "index", "prices",
}


def _normal(texto: str) -> str:
    """Minúsculas, sin tildes ni signos: "Mercado Libre" -> "mercadolibre"."""
    t = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", t)


class BuscadorSimbolos:
    """Resuelve lo que escribe el usuario a un símbolo de Yahoo."""

    def __init__(self, simbolos: list[str], nombres: dict[str, str]) -> None:
        """
        Args:
            simbolos: Símbolos conocidos (watchlist, cartera, empresas seguidas).
            nombres: Símbolo -> nombre de la empresa.
        """
        self.nombres = {s.upper(): n for s, n in nombres.items()}
        self.simbolos = sorted({s.upper() for s in simbolos} | set(self.nombres))
        self._por_nombre: dict[str, str] = {}
        palabras: dict[str, set[str]] = {}
        for s, n in self.nombres.items():
            self._por_nombre.setdefault(_normal(n), s)
            for palabra in re.findall(r"[A-Za-zÀ-ÿ0-9]+", n):
                clave = _normal(palabra)
                if len(clave) >= 4 and clave not in _GENERICAS:
                    palabras.setdefault(clave, set()).add(s)
        # Una palabra identifica a una empresa solo si no la comparte con otra.
        for clave, dueños in palabras.items():
            if len(dueños) == 1:
                self._por_nombre.setdefault(clave, next(iter(dueños)))

    def resolver(self, texto: str) -> str:
        """Símbolo para ``texto``: el mismo si es un símbolo conocido, o el de la empresa nombrada.

        Si no lo reconoce, lo devuelve en mayúsculas tal cual (puede ser un símbolo válido de
        Yahoo que no está en tus listas).
        """
        t = texto.strip().upper()
        if t in self.simbolos:
            return t
        return self._por_nombre.get(_normal(texto), t)

    def sugerencias(self, texto: str, maximo: int = 3) -> list[str]:
        """Símbolos parecidos a ``texto`` (por símbolo o por nombre de la empresa)."""
        t = texto.strip().upper()
        candidatos = difflib.get_close_matches(t, self.simbolos, n=maximo, cutoff=0.6)
        por_nombre = difflib.get_close_matches(_normal(texto), list(self._por_nombre), n=maximo, cutoff=0.75)
        candidatos += [self._por_nombre[c] for c in por_nombre]
        return list(dict.fromkeys(c for c in candidatos if c != t))[:maximo]

    def describir(self, simbolo: str) -> str:
        """ "NVDA (NVIDIA)" si se conoce el nombre."""
        nombre = self.nombres.get(simbolo)
        return f"{simbolo} ({nombre})" if nombre and nombre.upper() != simbolo else simbolo

    def mensaje_no_encontrado(self, texto: str) -> str:
        """Mensaje claro cuando un símbolo no existe, con sugerencias."""
        sugerencias = self.sugerencias(texto)
        partes = [f"No encontré \"{texto.strip().upper()}\" en Yahoo Finance."]
        if sugerencias:
            partes.append("¿Quisiste decir " + " o ".join(self.describir(s) for s in sugerencias) + "?")
        partes.append("Podés escribir el símbolo como en Yahoo (NVDA, GGAL, ALUA.BA, PETR4.SA) o el nombre "
                      "de la empresa (nvidia, galicia).")
        return "\n".join(partes)
