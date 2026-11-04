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
    # Una fila por figura confirmada nueva: ¿llegó al objetivo antes de tocar el nivel que la invalida?
    figuras: pd.DataFrame = None  # type: ignore[assignment]

    def resumen_figuras(self) -> pd.DataFrame:
        """Por figura: casos, % que llegó al objetivo, % invalidada y % sin resolver en 60 ruedas."""
        f = self.figuras
        if f is None or f.empty:
            return pd.DataFrame()
        g = f.groupby("figura")["resultado"]
        return pd.DataFrame({
            "casos": g.size(),
            "objetivo": g.apply(lambda r: (r == "objetivo").mean()),
            "invalidada": g.apply(lambda r: (r == "invalidada").mean()),
        }).sort_values("casos", ascending=False)

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


def _resultado_figura(maximos: np.ndarray, minimos: np.ndarray, sesgo: int, objetivo: float,
                      invalidacion: float) -> str:
    """Recorre las ruedas siguientes: ¿toca primero el objetivo o el nivel que invalida la figura?"""
    for hi, lo in zip(maximos, minimos):
        llega = hi >= objetivo if sesgo > 0 else lo <= objetivo
        invalida = lo <= invalidacion if sesgo > 0 else hi >= invalidacion
        if llega and invalida:
            return "invalidada"  # el mismo día: se toma el peor caso
        if invalida:
            return "invalidada"
        if llega:
            return "objetivo"
    return "sin resolver"


def validar(tecnico: ServicioTecnico, simbolos: list[str], horizonte: int = 20, paso: int = 10,
            plazo_figuras: int = 60) -> ValidacionLectura:
    """Lee el gráfico de cada símbolo en muchas fechas pasadas y mide qué pasó después.

    Además, cada figura confirmada que aparece por primera vez se sigue ``plazo_figuras`` ruedas
    para ver si llegó a su objetivo medido antes de tocar el nivel que la invalida (es lo que el
    libro de Murphy dice que hacen las figuras, más allá de "la dirección" de la lectura).
    """
    filas, figs = [], []
    for s in simbolos:
        try:
            df, _, _ = tecnico.datos(s)
        except ErrorDatos:
            continue
        ind = calcular_indicadores(df)
        cierre = ind["cierre"].to_numpy()
        maximo, minimo = ind["maximo"].to_numpy(), ind["minimo"].to_numpy()
        vistas: set[tuple] = set()
        for i in range(VENTANA + 200, len(ind) - horizonte, paso):
            l = leer_grafico(ind.iloc[: i + 1])  # solo el pasado de ese día
            filas.append({"simbolo": s, "direccion": l.direccion, "sesgo": l.sesgo,
                          "futuro": cierre[i + horizonte] / cierre[i] - 1})
            for f in l.figuras:
                if f.estado != "confirmada" or f.sesgo == 0 or f.objetivo is None or f.invalidacion is None:
                    continue
                clave = (f.nombre, round(f.linea, 4))
                if clave in vistas or f.objetivo_alcanzado(l.precio):
                    continue
                vistas.add(clave)
                fin = min(len(ind), i + 1 + plazo_figuras)
                figs.append({"simbolo": s, "figura": f.nombre, "sin_volumen": f.sin_volumen,
                             "resultado": _resultado_figura(maximo[i + 1:fin], minimo[i + 1:fin], f.sesgo,
                                                            f.objetivo, f.invalidacion)})
    return ValidacionLectura(pd.DataFrame(filas, columns=["simbolo", "direccion", "sesgo", "futuro"]), horizonte,
                             pd.DataFrame(figs, columns=["simbolo", "figura", "sin_volumen", "resultado"]))


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
    figs = v.resumen_figuras()
    if not figs.empty:
        lineas += ["", "📐 Figuras confirmadas: ¿llegaron a su objetivo antes de invalidarse? (60 ruedas)"]
        for nombre, fila in figs.iterrows():
            lineas.append(f"• {nombre}: {int(fila['casos'])} casos · objetivo {_p(fila['objetivo'])} · invalidada "
                          f"{_p(fila['invalidada'])}")
        # Regla del libro: en las rupturas al alza el volumen es imprescindible. ¿Se cumple acá?
        f = v.figuras
        alcistas = f[f["figura"].isin(["Doble piso", "Triple piso", "Hombro-cabeza-hombro invertido",
                                       "Triángulo ascendente", "Triángulo simétrico", "Rango lateral (rectángulo)",
                                       "Cuña descendente"])]
        con, sin = alcistas[~alcistas["sin_volumen"]], alcistas[alcistas["sin_volumen"]]
        if len(con) >= 10 and len(sin) >= 10:
            lineas.append(f"Rupturas al alza con volumen: objetivo {_p((con['resultado'] == 'objetivo').mean())} "
                          f"({len(con)} casos); sin volumen: {_p((sin['resultado'] == 'objetivo').mean())} "
                          f"({len(sin)} casos).")
        lineas.append("Ojo: el objetivo suele estar más lejos que el nivel que invalida la figura, así que una figura "
                      "puede \"servir\" aunque llegue al objetivo menos de la mitad de las veces. Pocos casos = "
                      "resultado poco confiable.")
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
