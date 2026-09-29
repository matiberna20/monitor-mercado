"""Textos de noticias y de la señal final."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from monitor_mercado.aviso_legal import pie_de_mensaje
from monitor_mercado.noticias.modelos import Sentimiento
from monitor_mercado.noticias.servicio import AnalisisNoticias
from monitor_mercado.notificaciones.formato import numero
from monitor_mercado.senal_final import SenalFinal
from monitor_mercado.tecnico.reporte import ICONO

ZONA = ZoneInfo("America/Argentina/Buenos_Aires")
ICONO_SENT = {Sentimiento.POSITIVA: "🟢", Sentimiento.NEGATIVA: "🔴", Sentimiento.NEUTRA: "⚪"}


def reporte_noticias(n: AnalisisNoticias, maximo: int = 10, con_pie: bool = True) -> str:
    """Titulares más relevantes con su sentimiento y el tono general."""
    lineas = [f"📰 Noticias de {n.simbolo} ({n.empresa})"]
    if n.puntaje is not None:
        tono = "positivo" if n.puntaje > 0.1 else "negativo" if n.puntaje < -0.1 else "neutro"
        lineas.append(
            f"Tono general: {tono} ({numero(n.puntaje, 2)}) · cobertura {numero(100 * n.cobertura, 0)}% · "
            f"{len(n.clasificadas)} noticias clasificadas"
        )
    if n.resumen:
        lineas += ["", n.resumen]

    clasificadas = n.clasificadas[:maximo]
    if clasificadas:
        lineas += ["", "Más relevantes:"]
        for e in clasificadas:
            c = e.clasificacion
            fecha = e.noticia.publicada.astimezone(ZONA).strftime("%d/%m")
            lineas.append(f"{ICONO_SENT[c.sentimiento]} {fecha} {e.noticia.titulo}")
            lineas.append(f"   ↳ {c.factor}: {c.explicacion}")
    elif n.noticias:
        lineas += ["", "Titulares (sin clasificar):"]
        for e in n.noticias[:maximo]:
            lineas.append(f"• {e.noticia.publicada.astimezone(ZONA):%d/%m} {e.noticia.titulo}")
    else:
        lineas += ["", "No se encontraron noticias recientes."]

    for aviso in n.avisos:
        lineas += ["", f"ℹ️ {aviso}"]
    lineas += ["", "La clasificación la hace un modelo de lenguaje (Claude) y puede equivocarse: "
               "leé la noticia completa antes de decidir."]
    return "\n".join(lineas) + (pie_de_mensaje() if con_pie else "")


def linea_senal_final(f: SenalFinal) -> str:
    """Resumen de una línea de la señal combinada."""
    if f.peso_noticias == 0:
        return f"Señal final (solo técnica): {ICONO[f.tendencia]} {f.tendencia.value.upper()} · confianza {f.confianza}/100"
    extra = "" if f.coinciden is None else " · técnico y noticias coinciden" if f.coinciden else \
        " · ⚠️ técnico y noticias se contradicen"
    return (f"Señal final (técnico {numero(100 * (1 - f.peso_noticias), 0)}% + noticias "
            f"{numero(100 * f.peso_noticias, 0)}%): {ICONO[f.tendencia]} {f.tendencia.value.upper()} · "
            f"confianza {f.confianza}/100{extra}")
