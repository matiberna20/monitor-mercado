"""Aviso legal único, incluido en todas las salidas del sistema."""

AVISO_LEGAL = (
    "⚠️ Insumo informativo y probabilístico, no es una recomendación de inversión."
)

AVISO_DEMORA = (
    "Los precios de fuentes gratuitas pueden tener 15-20 minutos de demora."
)


def pie_de_mensaje() -> str:
    """Texto que se agrega al final de cada aviso o reporte."""
    return f"\n\n{AVISO_LEGAL}\n{AVISO_DEMORA}"
