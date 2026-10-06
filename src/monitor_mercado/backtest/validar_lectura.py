"""¿La lectura del gráfico anticipa la dirección del precio? Validación sin mirar el futuro.

Cada ``paso`` ruedas se lee el gráfico usando SOLO los datos disponibles hasta ese
día, y se compara la dirección leída (alcista / bajista / lateral) con lo que hizo
el precio en las ``horizonte`` ruedas siguientes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from monitor_mercado.aviso_legal import pie_de_mensaje
from monitor_mercado.datos.modelos import ErrorDatos
from monitor_mercado.tecnico.indicadores import calcular_indicadores
from monitor_mercado.tecnico.lectura import VENTANA, leer_grafico
from monitor_mercado.tecnico.servicio import ServicioTecnico


@dataclass(frozen=True)
class ValidacionLectura:
    """Resultado de la validación."""

    lecturas: pd.DataFrame  # simbolo, direccion, sesgo, futuro
    horizonte: int

    @property
    def base(self) -> float:
        return float((self.lecturas["futuro"] > 0).mean())

    def por_direccion(self) -> pd.DataFrame:
        g = self.lecturas.groupby("direccion")["futuro"]
        return pd.DataFrame({"casos": g.size(), "subio": g.apply(lambda f: (f > 0).mean()), "medio": g.mean()})

    @property
    def correlacion(self) -> float:
        return float(self.lecturas["sesgo"].rank().corr(self.lecturas["futuro"].rank()))

    def prob_azar(self, repeticiones: int = 5000, semilla: int = 0) -> float | None:
        """Probabilidad de que el azar dé una ventaja alcista-vs-bajista igual o mayor a la observada."""
        alc = self.lecturas.loc[self.lecturas["direccion"] == "ALCISTA", "futuro"]
        baj = self.lecturas.loc[self.lecturas["direccion"] == "BAJISTA", "futuro"]
        if len(alc) < 20 or len(baj) < 20:
            return None
        dif = alc.mean() - baj.mean()
        rng = np.random.default_rng(semilla)
        todos = self.lecturas["futuro"].to_numpy()
        nulas = rng.choice(todos, (repeticiones, len(alc))).mean(1) - rng.choice(todos, (repeticiones, len(baj))).mean(1)
        return float(np.mean(nulas >= dif))


def validar(tecnico: ServicioTecnico, simbolos: list[str], horizonte: int = 20, paso: int = 10) -> ValidacionLectura:
    """Lee el gráfico de cada símbolo en muchas fechas pasadas y mide qué pasó después."""
    filas = []
    for s in simbolos:
        try:
            df, _, _ = tecnico.datos(s)
        except ErrorDatos:
            continue
        ind = calcular_indicadores(df)
        cierre = ind["cierre"].to_numpy()
        for i in range(VENTANA + 200, len(ind) - horizonte, paso):
            l = leer_grafico(ind.iloc[: i + 1])  # solo el pasado de ese día
            filas.append({"simbolo": s, "direccion": l.direccion, "sesgo": l.sesgo,
                          "futuro": cierre[i + horizonte] / cierre[i] - 1})
    return ValidacionLectura(pd.DataFrame(filas, columns=["simbolo", "direccion", "sesgo", "futuro"]), horizonte)


def _p(v: float, signo: bool = False) -> str:
    return (f"{100 * v:+.1f}%" if signo else f"{100 * v:.1f}%").replace(".", ",")


def texto_validacion(v: ValidacionLectura) -> str:
    """Resultado en lenguaje simple, con conclusión explícita."""
    t = v.lecturas
    if t.empty:
        return "No hay historia suficiente para validar la lectura del gráfico." + pie_de_mensaje()
    tabla = v.por_direccion()
    lineas = [
        "🔬 ¿La lectura del gráfico anticipa hacia dónde va el precio?",
        f"{len(t)} lecturas de {t['simbolo'].nunique()} activos, hechas solo con los datos de cada día; se mira "
        f"qué pasó en las {v.horizonte} ruedas siguientes.",
        "",
        f"En general, el precio subió el {_p(v.base)} de las veces.",
    ]
    for direccion, fila in tabla.iterrows():
        lineas.append(f"• Cuando decía {direccion}: subió el {_p(fila['subio'])} de las veces "
                      f"(retorno medio {_p(fila['medio'], True)}, {int(fila['casos'])} casos)")
    lineas.append(f"Correlación entre la lectura y el movimiento siguiente: {v.correlacion:+.2f} "
                  "(0 = ninguna relación)".replace(".", ","))
    prob = v.prob_azar()
    alc = tabla["medio"].get("ALCISTA")
    baj = tabla["medio"].get("BAJISTA")
    lineas += ["", "📌 Conclusión"]
    if prob is not None and alc is not None and baj is not None and alc > baj and prob < 0.05:
        lineas.append("Después de las lecturas alcistas el precio rindió más que después de las bajistas, y es "
                      "difícil que sea azar. Aun así es una sola muestra: seguí validándolo con datos nuevos.")
    else:
        lineas.append("La dirección que marca el gráfico NO anticipó el movimiento de las semanas siguientes "
                      "mejor que el azar. Usá la lectura como mapa de niveles (soportes, resistencias, dónde se "
                      "invalida una idea), no como predicción de suba o baja.")
        if alc is not None and baj is not None and baj > alc:
            lineas.append("Incluso, después de lecturas bajistas el precio rindió más: a corto plazo, las caídas "
                          "fuertes suelen tener rebotes. No conviene \"dar vuelta\" la señal: con una sola muestra "
                          "eso sería sobreajustar.")
    return "\n".join(lineas) + pie_de_mensaje()
