"""Lectura del gráfico "como un trader técnico" (chartismo + estructura + volumen).

Pasos, en el orden en que un trader mira un gráfico:
1. Puntos de giro (zigzag): los máximos y mínimos que importan, ignorando el ruido.
2. Estructura (teoría de Dow): ¿hace máximos y mínimos más altos (alcista), más
   bajos (bajista) o mezclados (lateral)?
3. Soportes y resistencias: precios donde el gráfico giró varias veces.
4. Canal de tendencia: dirección y pendiente de los últimos meses.
5. Figuras chartistas: doble techo/piso, hombro-cabeza-hombro, triángulos, rango,
   bandera; con su objetivo medido y el nivel que las invalida.
6. Rupturas, volumen (acumulación/distribución) y divergencias del RSI.
7. Síntesis: sesgo, convicción y escenarios ("si rompe X, objetivo Y").

Todo son reglas fijas aplicadas al precio: describen probabilidades y escenarios,
nunca certezas.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

VENTANA = 260  # ~1 año de ruedas para buscar giros y niveles


def _n(valor: float, decimales: int | None = None) -> str:
    """Número en formato argentino (12.345,67); 3 decimales para precios menores a 1."""
    d = decimales if decimales is not None else (2 if abs(valor) >= 1 else 3)
    return f"{valor:,.{d}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _pct(valor: float) -> str:
    return f"{100 * valor:+.0f}%"


# --------------------------------------------------------------------- giros
@dataclass(frozen=True)
class Giro:
    """Un punto de giro: máximo (H) o mínimo (L)."""

    pos: int  # posición dentro del DataFrame recortado
    fecha: pd.Timestamp
    precio: float
    tipo: str  # "H" o "L"
    etiqueta: str = ""  # HH / LH / HL / LL respecto del giro anterior del mismo tipo


def umbral_zigzag(df: pd.DataFrame) -> float:
    """Movimiento mínimo para contar como giro: ~2,5 veces la volatilidad diaria (entre 3% y 15%)."""
    atr_pct = float(df["atr14"].iloc[-1] / df["cierre"].iloc[-1]) if "atr14" in df else 0.02
    return float(np.clip(2.5 * atr_pct, 0.03, 0.15))


def zigzag(df: pd.DataFrame, umbral: float) -> list[Giro]:
    """Máximos y mínimos alternados separados por al menos ``umbral`` (fracción)."""
    alto, bajo = df["maximo"].to_numpy(float), df["minimo"].to_numpy(float)
    fechas = df.index

    def giro(i: int, tipo: str) -> Giro:
        return Giro(i, fechas[i], float(alto[i] if tipo == "H" else bajo[i]), tipo)

    giros: list[Giro] = []
    direccion = 0  # 0 = todavía sin tendencia, 1 = tramo de suba, -1 = tramo de baja
    max_i = min_i = 0
    for i in range(1, len(df)):
        if direccion == 0:
            # Al principio se espera el primer movimiento grande para saber hacia dónde va.
            if alto[i] > alto[max_i]:
                max_i = i
            if bajo[i] < bajo[min_i]:
                min_i = i
            if alto[max_i] >= bajo[min_i] * (1 + umbral):
                if min_i < max_i:
                    giros.append(giro(min_i, "L"))
                    direccion = 1
                else:
                    giros.append(giro(max_i, "H"))
                    direccion = -1
        elif direccion == 1:
            # En suba: se sigue el máximo; si el precio cae "umbral" desde ahí, ese máximo fue un giro.
            if alto[i] > alto[max_i]:
                max_i = i
            elif bajo[i] <= alto[max_i] * (1 - umbral):
                giros.append(giro(max_i, "H"))
                direccion, min_i = -1, i
        else:
            if bajo[i] < bajo[min_i]:
                min_i = i
            elif alto[i] >= bajo[min_i] * (1 + umbral):
                giros.append(giro(min_i, "L"))
                direccion, max_i = 1, i
    return _etiquetar(giros)


def _etiquetar(giros: list[Giro]) -> list[Giro]:
    ultimo: dict[str, float] = {}
    salida = []
    for g in giros:
        previo = ultimo.get(g.tipo)
        etiqueta = ""
        if previo is not None:
            if g.tipo == "H":
                etiqueta = "HH" if g.precio > previo else "LH"
            else:
                etiqueta = "HL" if g.precio > previo else "LL"
        salida.append(Giro(g.pos, g.fecha, g.precio, g.tipo, etiqueta))
        ultimo[g.tipo] = g.precio
    return salida


# ----------------------------------------------------------------- estructura
def giro_en_curso(df: pd.DataFrame, giros: list[Giro]) -> Giro | None:
    """El extremo del tramo actual, todavía no confirmado como giro.

    Ej.: si el último giro fue un mínimo y desde ahí el precio subió, el máximo alcanzado
    desde entonces es un "máximo en curso". Sirve para ver si el precio ya superó el
    máximo anterior aunque todavía no haya corregido lo suficiente para confirmarlo.
    """
    if not giros or giros[-1].pos >= len(df) - 1:
        return None
    ultimo = giros[-1]
    tramo = df.iloc[ultimo.pos + 1:]
    if ultimo.tipo == "L":
        i = int(np.argmax(tramo["maximo"].to_numpy()))
        return Giro(ultimo.pos + 1 + i, tramo.index[i], float(tramo["maximo"].iloc[i]), "H", "en curso")
    i = int(np.argmin(tramo["minimo"].to_numpy()))
    return Giro(ultimo.pos + 1 + i, tramo.index[i], float(tramo["minimo"].iloc[i]), "L", "en curso")


def _comparar(nuevo: float, viejo: float, tolerancia: float) -> int:
    """+1 más alto, -1 más bajo, 0 parejo (diferencia menor a la tolerancia)."""
    if nuevo > viejo * (1 + tolerancia):
        return 1
    if nuevo < viejo * (1 - tolerancia):
        return -1
    return 0


def estructura(giros: list[Giro], tolerancia: float = 0.01) -> tuple[int, str]:
    """Tendencia según los dos últimos máximos y mínimos (+1 alcista, -1 bajista, 0 lateral)."""
    altos = [g for g in giros if g.tipo == "H"][-2:]
    bajos = [g for g in giros if g.tipo == "L"][-2:]
    if len(altos) < 2 or len(bajos) < 2:
        return 0, "todavía no hay suficientes giros para definir una estructura"
    a = _comparar(altos[1].precio, altos[0].precio, tolerancia)
    b = _comparar(bajos[1].precio, bajos[0].precio, tolerancia)
    if a >= 0 and b >= 0 and (a + b) > 0:
        return 1, "máximos y mínimos cada vez más altos (estructura alcista)"
    if a <= 0 and b <= 0 and (a + b) < 0:
        return -1, "máximos y mínimos cada vez más bajos (estructura bajista)"
    if a == 0 and b == 0:
        return 0, "máximos y mínimos a la misma altura: el precio se mueve en un rango"
    if b > 0 > a:
        return 0, "mínimos más altos pero máximos más bajos: el precio se está comprimiendo"
    return 0, "máximos más altos pero mínimos más bajos: movimientos cada vez más amplios, sin dirección"


# ------------------------------------------------------- soportes y resistencias
@dataclass(frozen=True)
class Nivel:
    """Zona de soporte o resistencia."""

    precio: float
    toques: int
    ultimo: pd.Timestamp
    origen: str  # "giros", "máximo de 52 semanas", "media de 200"...

    @property
    def fuerza(self) -> str:
        return "fuerte" if self.toques >= 3 else "media" if self.toques == 2 else "débil"


def niveles(df: pd.DataFrame, giros: list[Giro]) -> list[Nivel]:
    """Agrupa los giros cercanos en zonas (tolerancia ~1 ATR o 1,5%)."""
    precio = float(df["cierre"].iloc[-1])
    tolerancia = max(float(df["atr14"].iloc[-1]) * 1.0, precio * 0.015)
    grupos: list[list[Giro]] = []
    for g in sorted(giros, key=lambda g: g.precio):
        if grupos and abs(g.precio - np.mean([x.precio for x in grupos[-1]])) <= tolerancia:
            grupos[-1].append(g)
        else:
            grupos.append([g])
    resultado = [Nivel(float(np.mean([g.precio for g in grupo])), len(grupo), max(g.fecha for g in grupo), "giros")
                 for grupo in grupos]
    extremos = [(float(df["maximo"].max()), "máximo del período"), (float(df["minimo"].min()), "mínimo del período")]
    for valor, origen in extremos:
        if all(abs(n.precio - valor) > tolerancia for n in resultado):
            resultado.append(Nivel(valor, 1, df.index[-1], origen))
    return sorted(resultado, key=lambda n: n.precio)


def mas_cercanos(lista: list[Nivel], precio: float, margen: float) -> tuple[list[Nivel], list[Nivel]]:
    """Soportes (debajo) y resistencias (arriba) más cercanos, de más cerca a más lejos."""
    soportes = sorted((n for n in lista if n.precio < precio - margen), key=lambda n: -n.precio)
    resistencias = sorted((n for n in lista if n.precio > precio + margen), key=lambda n: n.precio)
    return soportes, resistencias


# ---------------------------------------------------------------------- canal
@dataclass(frozen=True)
class Canal:
    """Regresión lineal del precio (en logaritmo) de los últimos meses."""

    ruedas: int
    pendiente_mensual: float  # variación por mes de la línea central
    r2: float  # 0 a 1: qué tan bien describe una recta al precio
    centro: pd.Series
    superior: pd.Series
    inferior: pd.Series
    posicion: float  # 0 = piso del canal, 1 = techo

    @property
    def claro(self) -> bool:
        return self.r2 >= 0.5


def canal(df: pd.DataFrame, ruedas: int = 90) -> Canal:
    """Canal de regresión ±2 desvíos sobre las últimas ``ruedas``."""
    tramo = df["cierre"].iloc[-ruedas:]
    x = np.arange(len(tramo))
    y = np.log(tramo.to_numpy(float))
    pendiente, ordenada = np.polyfit(x, y, 1)
    ajuste = pendiente * x + ordenada
    desvio = float(np.std(y - ajuste))
    r2 = 1 - float(np.sum((y - ajuste) ** 2) / np.sum((y - y.mean()) ** 2)) if np.var(y) > 0 else 0.0
    centro = pd.Series(np.exp(ajuste), index=tramo.index)
    sup, inf = centro * np.exp(2 * desvio), centro * np.exp(-2 * desvio)
    rango = float(sup.iloc[-1] - inf.iloc[-1])
    pos = float((tramo.iloc[-1] - inf.iloc[-1]) / rango) if rango > 0 else 0.5
    return Canal(len(tramo), float(np.exp(pendiente * 21) - 1), r2, centro, sup, inf, pos)


# ------------------------------------------------------------------- figuras
@dataclass(frozen=True)
class Figura:
    """Una figura chartista detectada."""

    nombre: str
    sesgo: int  # +1 alcista, -1 bajista, 0 neutro (depende de la ruptura)
    estado: str  # "confirmada" o "en formación"
    linea: float  # nivel clave (línea cuello, borde del triángulo...)
    objetivo: float | None
    invalidacion: float | None
    explicacion: str
    giros: tuple[Giro, ...] = ()

    def objetivo_alcanzado(self, precio: float) -> bool:
        """True si el precio ya llegó al objetivo medido (la figura "ya cumplió")."""
        if self.objetivo is None or self.estado != "confirmada":
            return False
        return precio >= self.objetivo if self.sesgo > 0 else precio <= self.objetivo if self.sesgo < 0 else False


def _vigentes(figs: list[Figura], precio: float) -> list[Figura]:
    """Descarta las figuras invalidadas: el precio ya superó el nivel que las anula."""
    vigentes = []
    for f in figs:
        if f.invalidacion is not None:
            if f.sesgo < 0 and precio > f.invalidacion:
                continue
            if f.sesgo > 0 and precio < f.invalidacion:
                continue
        vigentes.append(f)
    return vigentes


def _parecidos(a: float, b: float, tol: float) -> bool:
    return abs(a / b - 1) <= tol


def figuras(df: pd.DataFrame, giros: list[Giro], umbral: float) -> list[Figura]:
    """Busca figuras clásicas en los últimos giros."""
    cierre = float(df["cierre"].iloc[-1])
    # "A la misma altura" para un trader: menos de 2-5% de diferencia (según la volatilidad).
    tol = min(0.05, max(0.02, umbral * 0.4))
    encontradas: list[Figura] = []
    ult = giros[-6:]
    recientes = {g.pos for g in giros[-2:]}  # la figura tiene que terminar en uno de los 2 últimos giros

    # Doble techo / doble piso: los dos últimos extremos del mismo tipo a la misma altura.
    altos = [g for g in ult if g.tipo == "H"]
    bajos = [g for g in ult if g.tipo == "L"]
    if len(altos) >= 2:
        h1, h2 = altos[-2], altos[-1]
        valle = [g for g in bajos if h1.pos < g.pos < h2.pos]
        if valle and h2.pos in recientes and _parecidos(h1.precio, h2.precio, tol) and len(df) - h2.pos <= 60:
            cuello = valle[-1].precio
            alto = max(h1.precio, h2.precio)
            confirmada = cierre < cuello
            encontradas.append(Figura(
                "Doble techo", -1, "confirmada" if confirmada else "en formación", cuello,
                cuello - (alto - cuello), alto,
                f"El precio chocó dos veces contra la zona de {_n(alto)} y no pudo superarla. "
                + ("Ya perforó la \"línea cuello\" (el mínimo entre ambos techos): la figura está confirmada."
                   if confirmada else f"Se confirma si cierra debajo de {_n(cuello)} (la línea cuello)."),
                (h1, valle[-1], h2)))
    if len(bajos) >= 2:
        l1, l2 = bajos[-2], bajos[-1]
        pico = [g for g in altos if l1.pos < g.pos < l2.pos]
        if pico and l2.pos in recientes and _parecidos(l1.precio, l2.precio, tol) and len(df) - l2.pos <= 60:
            cuello = pico[-1].precio
            bajo = min(l1.precio, l2.precio)
            confirmada = cierre > cuello
            encontradas.append(Figura(
                "Doble piso", 1, "confirmada" if confirmada else "en formación", cuello,
                cuello + (cuello - bajo), bajo,
                f"El precio rebotó dos veces en la zona de {_n(bajo)}: ahí aparecen compradores. "
                + ("Ya superó la línea cuello (el máximo entre ambos pisos): la figura está confirmada."
                   if confirmada else f"Se confirma si cierra arriba de {_n(cuello)} (la línea cuello)."),
                (l1, pico[-1], l2)))
    # Si aparecen las dos, vale la más reciente (la otra quedó superada por el precio).
    encontradas = _vigentes(encontradas, cierre)
    dobles = [f for f in encontradas if f.nombre.startswith("Doble")]
    if len(dobles) == 2:
        vieja = min(dobles, key=lambda f: f.giros[-1].pos)
        encontradas.remove(vieja)

    # Hombro-cabeza-hombro (y su versión invertida): tres extremos, el del medio más marcado.
    for i in range(len(ult) - 4):
        a, b, c, d, e = ult[i:i + 5]
        if a.tipo == c.tipo == e.tipo == "H" and c.precio > a.precio * (1 + tol / 2) \
                and c.precio > e.precio * (1 + tol / 2) and _parecidos(a.precio, e.precio, tol * 1.5):
            cuello = (b.precio + d.precio) / 2
            confirmada = cierre < cuello
            encontradas.append(Figura(
                "Hombro-cabeza-hombro", -1, "confirmada" if confirmada else "en formación", cuello,
                cuello - (c.precio - cuello), c.precio,
                "Tres máximos con el del medio (la \"cabeza\") más alto: los compradores pierden fuerza. "
                + ("Ya perforó la línea cuello: figura de giro bajista confirmada." if confirmada
                   else f"Se confirma si cierra debajo de {_n(cuello)}."), (a, b, c, d, e)))
        if a.tipo == c.tipo == e.tipo == "L" and c.precio < a.precio * (1 - tol / 2) \
                and c.precio < e.precio * (1 - tol / 2) and _parecidos(a.precio, e.precio, tol * 1.5):
            cuello = (b.precio + d.precio) / 2
            confirmada = cierre > cuello
            encontradas.append(Figura(
                "Hombro-cabeza-hombro invertido", 1, "confirmada" if confirmada else "en formación", cuello,
                cuello + (cuello - c.precio), c.precio,
                "Tres mínimos con el del medio más bajo: los vendedores pierden fuerza. "
                + ("Ya superó la línea cuello: figura de giro alcista confirmada." if confirmada
                   else f"Se confirma si cierra arriba de {_n(cuello)}."), (a, b, c, d, e)))

    # Triángulos y rango: comparan los dos últimos máximos y los dos últimos mínimos.
    if len(altos) >= 2 and len(bajos) >= 2 and min(altos[-2].pos, bajos[-2].pos) >= len(df) - 120:
        h1, h2, l1, l2 = altos[-2], altos[-1], bajos[-2], bajos[-1]
        plano_alto, plano_bajo = _parecidos(h1.precio, h2.precio, 0.02), _parecidos(l1.precio, l2.precio, 0.02)
        techo, piso = h2.precio, l2.precio
        altura = max(h1.precio, h2.precio) - min(l1.precio, l2.precio)
        nombre, sesgo = None, 0
        if plano_alto and l2.precio > l1.precio:
            nombre, sesgo = "Triángulo ascendente", 1
        elif plano_bajo and h2.precio < h1.precio:
            nombre, sesgo = "Triángulo descendente", -1
        elif h2.precio < h1.precio and l2.precio > l1.precio:
            nombre, sesgo = "Triángulo simétrico", 0
        elif plano_alto and plano_bajo:
            nombre, sesgo = "Rango lateral (rectángulo)", 0
        # Techo plano + mínimos más altos se parece a un doble techo, pero un trader lo lee como
        # triángulo ascendente (los compradores siguen presionando). Igual al revés.
        reemplaza = {"Triángulo ascendente": "Doble techo", "Triángulo descendente": "Doble piso"}.get(nombre or "")
        for f in list(encontradas):
            if f.nombre == reemplaza and f.estado == "en formación":
                encontradas.remove(f)
        if nombre and not any(f.nombre.startswith("Doble") for f in encontradas):
            if cierre > techo:
                estado, sesgo_final, objetivo = "confirmada", 1, techo + altura
                texto = f"El precio rompió hacia arriba el techo de {_n(techo)}."
            elif cierre < piso:
                estado, sesgo_final, objetivo = "confirmada", -1, piso - altura
                texto = f"El precio rompió hacia abajo el piso de {_n(piso)}."
            else:
                estado, sesgo_final, objetivo = "en formación", sesgo, None
                texto = f"El precio está encerrado entre {_n(piso)} y {_n(techo)}; la salida marca la dirección."
            explicacion = {
                "Triángulo ascendente": "Techo plano y mínimos cada vez más altos: los compradores presionan "
                                        "contra una misma resistencia. Suele resolverse hacia arriba. ",
                "Triángulo descendente": "Piso plano y máximos cada vez más bajos: los vendedores presionan "
                                         "contra un mismo soporte. Suele resolverse hacia abajo. ",
                "Triángulo simétrico": "Máximos más bajos y mínimos más altos: compradores y vendedores se "
                                       "equilibran. La ruptura puede ser para cualquier lado. ",
                "Rango lateral (rectángulo)": "El precio rebota entre un techo y un piso horizontales: no hay "
                                              "tendencia. ",
            }[nombre]
            encontradas.append(Figura(nombre, sesgo_final, estado, techo if sesgo_final >= 0 else piso, objetivo,
                                      piso if sesgo_final >= 0 else techo, explicacion + texto, (h1, l1, h2, l2)))

    # Bandera: impulso fuerte seguido de una pausa corta y estrecha.
    c = df["cierre"].to_numpy(float)
    if len(c) > 40:
        impulso = c[-12] / c[-30] - 1
        pausa = c[-12:]
        rango_pausa = (pausa.max() - pausa.min()) / pausa.mean()
        if abs(impulso) >= max(0.12, 4 * umbral) and rango_pausa <= abs(impulso) * 0.5:
            alcista = impulso > 0
            borde = float(pausa.max() if alcista else pausa.min())
            confirmada = (cierre > borde * 0.999) if alcista else (cierre < borde * 1.001)
            altura = abs(c[-12] - c[-30])
            encontradas.append(Figura(
                "Bandera alcista" if alcista else "Bandera bajista", 1 if alcista else -1,
                "confirmada" if confirmada else "en formación", borde,
                borde + altura if alcista else borde - altura,
                float(pausa.min() if alcista else pausa.max()),
                f"Después de un movimiento fuerte ({_pct(impulso)} en pocas semanas) el precio hace una pausa "
                "estrecha: muchas veces es un \"descanso\" antes de continuar en la misma dirección."))
    return _vigentes(encontradas, cierre)


# ---------------------------------------------------- volumen y divergencias
def volumen(df: pd.DataFrame, ruedas: int = 20) -> tuple[int, str]:
    """Acumulación (+1) o distribución (-1) según el volumen de días de suba vs. de baja."""
    tramo = df.iloc[-ruedas:]
    sube = tramo.loc[tramo["cierre"] > tramo["cierre"].shift(), "volumen"].sum()
    baja = tramo.loc[tramo["cierre"] < tramo["cierre"].shift(), "volumen"].sum()
    if not baja or not sube:
        return 0, "volumen sin datos suficientes"
    r = sube / baja
    if r >= 1.3:
        return 1, f"en los días de suba se negoció {_n(r, 1)} veces más que en los de baja (acumulación: entran compradores)"
    if r <= 1 / 1.3:
        return -1, f"en los días de baja se negoció {_n(1 / r, 1)} veces más que en los de suba (distribución: salen vendedores)"
    return 0, "el volumen está parejo entre días de suba y de baja"


def divergencia(df: pd.DataFrame, giros: list[Giro]) -> tuple[int, str | None]:
    """Divergencia entre precio y RSI en los dos últimos giros del mismo tipo."""
    rsi = df["rsi14"].to_numpy(float)
    for tipo in ("H", "L"):
        g = [x for x in giros if x.tipo == tipo][-2:]
        if len(g) < 2 or len(df) - g[1].pos > 40 or np.isnan(rsi[g[0].pos]) or np.isnan(rsi[g[1].pos]):
            continue
        r0, r1 = rsi[g[0].pos], rsi[g[1].pos]
        if tipo == "H" and g[1].precio > g[0].precio and r1 < r0 - 3:
            return -1, (f"divergencia bajista: el precio hizo un máximo más alto pero el RSI uno más bajo "
                        f"({r0:.0f} → {r1:.0f}); la suba pierde fuerza")
        if tipo == "L" and g[1].precio < g[0].precio and r1 > r0 + 3:
            return 1, (f"divergencia alcista: el precio hizo un mínimo más bajo pero el RSI uno más alto "
                       f"({r0:.0f} → {r1:.0f}); la caída pierde fuerza")
    return 0, None


def ruptura(df: pd.DataFrame, lista: list[Nivel], ruedas: int = 5) -> tuple[int, str | None]:
    """¿Rompió un nivel en las últimas ruedas? Con volumen es más creíble."""
    c = df["cierre"]
    antes, ahora = float(c.iloc[-ruedas - 1]), float(c.iloc[-1])
    vol = float(df["vol_relativo"].iloc[-ruedas:].max()) if "vol_relativo" in df else 1.0
    con_vol = vol >= 1.3
    for n in lista:
        if n.toques < 2:
            continue
        if antes < n.precio < ahora:
            return (1 if con_vol else 0), (f"rompió la resistencia de {_n(n.precio)} "
                                           + ("con volumen alto (ruptura más creíble)" if con_vol
                                              else "pero sin volumen (puede ser una ruptura falsa)"))
        if antes > n.precio > ahora:
            return (-1 if con_vol else 0), (f"perdió el soporte de {_n(n.precio)} "
                                            + ("con volumen alto (más creíble)" if con_vol
                                               else "pero sin volumen (puede recuperarlo)"))
    return 0, None


# -------------------------------------------------------------------- síntesis
@dataclass(frozen=True)
class Escenario:
    """Qué tiene que pasar y adónde podría ir."""

    disparador: float | None
    objetivo: float | None
    texto: str


@dataclass(frozen=True)
class LecturaGrafico:
    """Resultado completo de la lectura del gráfico."""

    precio: float
    umbral: float
    datos: pd.DataFrame
    giros: list[Giro]
    estructura: int
    estructura_texto: str
    soportes: list[Nivel]
    resistencias: list[Nivel]
    canal: Canal
    figuras: list[Figura]
    volumen: int
    volumen_texto: str
    divergencia: int
    divergencia_texto: str | None
    ruptura: int
    ruptura_texto: str | None
    medias: int
    medias_texto: str
    sesgo: float  # -1 a +1
    escenario_alcista: Escenario
    escenario_bajista: Escenario
    invalidacion: float | None
    votos: dict[str, float] = field(default_factory=dict)

    @property
    def direccion(self) -> str:
        return "ALCISTA" if self.sesgo > 0.25 else "BAJISTA" if self.sesgo < -0.25 else "LATERAL / SIN DEFINICIÓN"

    @property
    def conviccion(self) -> str:
        a = abs(self.sesgo)
        return "alta" if a >= 0.6 else "media" if a >= 0.35 else "baja"


def _medias(df: pd.DataFrame) -> tuple[int, str]:
    u = df.iloc[-1]
    c, m50, m200 = u["cierre"], u["sma50"], u["sma200"]
    if pd.isna(m200):
        return 0, "sin historia suficiente para la media de 200"
    if c > m50 > m200:
        return 1, "el precio está arriba de las medias de 50 y 200, y la de 50 arriba de la de 200"
    if c < m50 < m200:
        return -1, "el precio está debajo de las medias de 50 y 200, y la de 50 debajo de la de 200"
    if c > m200:
        return 0, "el precio está arriba de la media de 200 pero sin alineación clara de medias"
    return 0, "el precio está debajo de la media de 200 pero sin alineación clara de medias"


PESOS = {"estructura": 2.0, "canal": 1.0, "medias": 1.0, "figura": 2.0, "ruptura": 1.5,
         "divergencia": 1.0, "volumen": 0.5}


def leer_grafico(df_completo: pd.DataFrame) -> LecturaGrafico:
    """Lectura completa del gráfico (``df_completo`` = salida de calcular_indicadores)."""
    df = df_completo.iloc[-VENTANA:]
    precio = float(df["cierre"].iloc[-1])
    u = umbral_zigzag(df)
    g = zigzag(df, u)
    actual = giro_en_curso(df, g)
    # El tramo en curso solo cuenta si SUPERA el extremo anterior del mismo tipo (un nuevo
    # máximo más alto o un nuevo mínimo más bajo): eso ya es un dato. Si no lo supera, el
    # tramo todavía no terminó y no dice nada.
    previo = next((x for x in reversed(g) if actual and x.tipo == actual.tipo), None)
    rompe = actual is not None and previo is not None and (
        (actual.tipo == "H" and actual.precio > previo.precio)
        or (actual.tipo == "L" and actual.precio < previo.precio))
    est, est_txt = estructura(g + ([actual] if rompe else []), tolerancia=max(0.01, u * 0.25))
    lista = niveles(df, g)
    margen = float(df["atr14"].iloc[-1]) * 0.25
    soportes, resistencias = mas_cercanos(lista, precio, margen)
    can = canal(df)
    figs = figuras(df, g, u)
    vol, vol_txt = volumen(df)
    div, div_txt = divergencia(df, g)
    rup, rup_txt = ruptura(df, lista)
    med, med_txt = _medias(df)

    voto_canal = float(np.sign(can.pendiente_mensual)) if can.claro and abs(can.pendiente_mensual) > 0.01 else 0.0
    voto_figura = 0.0
    if figs:
        principal = max(figs, key=lambda f: (f.estado == "confirmada", abs(f.sesgo)))
        # En formación pesa la mitad; si ya alcanzó su objetivo, también (ya "cumplió").
        completa = principal.estado == "confirmada" and not principal.objetivo_alcanzado(precio)
        voto_figura = principal.sesgo * (1.0 if completa else 0.5)
    votos = {"estructura": est, "canal": voto_canal, "medias": med, "figura": voto_figura, "ruptura": rup,
             "divergencia": div, "volumen": vol}
    sesgo = sum(PESOS[k] * v for k, v in votos.items()) / sum(PESOS.values())

    # Escenarios con los niveles y objetivos más cercanos.
    obj_alc = [f.objetivo for f in figs if f.sesgo >= 0 and f.objetivo and f.objetivo > precio]
    obj_baj = [f.objetivo for f in figs if f.sesgo <= 0 and f.objetivo and f.objetivo < precio]
    r1 = resistencias[0].precio if resistencias else None
    r2 = resistencias[1].precio if len(resistencias) > 1 else (min(obj_alc) if obj_alc else None)
    s1 = soportes[0].precio if soportes else None
    s2 = soportes[1].precio if len(soportes) > 1 else (max(obj_baj) if obj_baj else None)
    if r1 is None:
        alcista = Escenario(None, float(can.superior.iloc[-1]),
                            "Está en máximos del período: no hay resistencias previas. El techo del canal "
                            f"({_n(can.superior.iloc[-1])}) sirve de referencia.")
    else:
        alcista = Escenario(r1, r2, f"Si supera {_n(r1)} (resistencia más cercana)"
                            + (f", el próximo objetivo es {_n(r2)}." if r2 else ", queda libre hacia arriba."))
    if s1 is None:
        bajista = Escenario(None, float(can.inferior.iloc[-1]),
                            "Está en mínimos del período: no hay soportes previos. El piso del canal "
                            f"({_n(can.inferior.iloc[-1])}) sirve de referencia.")
    else:
        bajista = Escenario(s1, s2, f"Si pierde {_n(s1)} (soporte más cercano)"
                            + (f", el próximo objetivo es {_n(s2)}." if s2 else ", queda libre hacia abajo."))
    # La lectura se invalida si el precio hace lo contrario de lo que indica el sesgo.
    if sesgo > 0.25:
        invalidacion = s1
    elif sesgo < -0.25:
        invalidacion = r1
    else:
        invalidacion = None
    return LecturaGrafico(precio, u, df, g, est, est_txt, soportes[:3], resistencias[:3], can, figs, vol, vol_txt,
                          div, div_txt, rup, rup_txt, med, med_txt, float(sesgo), alcista, bajista, invalidacion,
                          {k: float(v) for k, v in votos.items()})
