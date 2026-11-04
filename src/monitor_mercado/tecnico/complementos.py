"""Herramientas de lectura del gráfico tomadas del análisis técnico clásico.

Referencia: John J. Murphy, *Análisis técnico de los mercados financieros* (las reglas
están escritas con palabras propias; entre paréntesis, el capítulo donde se explican).

Cada función recibe el DataFrame con indicadores (y los giros del zigzag cuando hace
falta) y devuelve un resultado con su explicación. Ninguna mira el futuro: usan solo
los datos hasta la última rueda.

- Filtro de ruptura: 1% más allá del nivel o dos cierres seguidos (cap. 4).
- Retrocesos del 33-38%, 50% y 62-66% del último tramo (cap. 4).
- Números redondos como soportes y resistencias psicológicos (cap. 4).
- Líneas de tendencia: dos puntos para trazarla, un tercero para validarla (cap. 4).
- Huecos (gaps) de separación, de escape y de agotamiento; isla de giro (cap. 4).
- Día de giro clave y giro semanal (caps. 4 y 8).
- Tres grados de tendencia: principal, intermedia y corta (caps. 2, 4 y 8).
- Volumen acumulado (OBV) y sus divergencias (cap. 7).
- Osciladores: estocástico lento, RSI con zonas 70/30 (80/20 en tendencia), oscilaciones
  fallidas y momento; siempre subordinados a la tendencia (cap. 10).
- Regla de las 4 semanas (canal de 20 ruedas) y medias semanales de 10 y 40 (cap. 9).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


def _n(valor: float) -> str:
    d = 2 if abs(valor) >= 1 else 3
    return f"{valor:,.{d}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _p(valor: float, decimales: int = 1) -> str:
    return f"{100 * valor:+.{decimales}f}%".replace(".", ",")


# ------------------------------------------------------------ filtro de ruptura
FILTRO_PCT = 0.01  # cap. 4: 1% para niveles de corto plazo (3% para los de largo plazo)


def ruptura_confirmada(cierres: pd.Series, nivel: float, hacia_arriba: bool,
                       filtro: float = FILTRO_PCT) -> bool:
    """¿El precio rompió ``nivel`` de forma válida?

    Murphy pide un cierre (no alcanza con tocarlo durante el día) y además un filtro para
    evitar las rupturas falsas: cerrar al menos un ``filtro`` más allá del nivel, o dos
    cierres seguidos del otro lado.
    """
    if len(cierres) == 0:
        return False
    c = cierres.to_numpy(float)
    if hacia_arriba:
        if c[-1] >= nivel * (1 + filtro):
            return True
        return bool(len(c) >= 2 and c[-1] > nivel and c[-2] > nivel)
    if c[-1] <= nivel * (1 - filtro):
        return True
    return bool(len(c) >= 2 and c[-1] < nivel and c[-2] < nivel)


# ------------------------------------------------------------------ retrocesos
NIVELES_RETROCESO = (0.333, 0.382, 0.5, 0.618, 0.667)


@dataclass(frozen=True)
class Retrocesos:
    """Niveles de retroceso del último tramo importante."""

    desde: float  # comienzo del tramo
    hasta: float  # extremo del tramo
    alcista: bool  # el tramo medido fue de suba
    niveles: dict[float, float]
    retrocedido: float  # fracción del tramo que el precio ya devolvió (0 a 1+)
    texto: str


def retrocesos(precio: float, giros: list, en_curso=None) -> Retrocesos | None:
    """Mide cuánto devolvió el precio del último tramo (cap. 4: 1/3, 1/2 y 2/3; 38% y 62% de Fibonacci).

    El tramo es el último movimiento completo entre dos giros. Si el tramo en curso ya superó
    al anterior (nuevo máximo o nuevo mínimo), se mide desde ese extremo.
    """
    if len(giros) < 2:
        return None
    a, b = giros[-2], giros[-1]
    if en_curso is not None and en_curso.tipo != b.tipo:
        # El precio se alejó del último giro: el tramo vigente es b → extremo en curso.
        a, b = b, en_curso
    alcista = b.precio > a.precio
    rango = b.precio - a.precio
    if rango == 0:
        return None
    niveles = {f: b.precio - f * rango for f in NIVELES_RETROCESO}
    retro = (b.precio - precio) / rango
    sentido = "suba" if alcista else "baja"
    if retro <= 0.05:
        estado = (f"el precio está en el extremo del tramo de {sentido} ({_n(a.precio)} → {_n(b.precio)}): todavía "
                  "no corrigió")
    elif retro < 0.333:
        estado = f"devolvió el {retro:.0%} del tramo de {sentido}: una corrección chica, normal en una tendencia"
    elif retro <= 0.667:
        estado = (f"devolvió el {retro:.0%} del tramo de {sentido}: está en la zona típica de corrección "
                  "(entre un tercio y dos tercios), donde muchas tendencias retoman")
    elif retro < 1:
        estado = (f"devolvió el {retro:.0%} del tramo de {sentido}: pasó el 66%, y según la regla clásica eso "
                  "aumenta las chances de que no sea una corrección sino un cambio de tendencia")
    else:
        estado = f"devolvió todo el tramo de {sentido} (y más): el movimiento anterior quedó anulado"
    texto = (f"Retrocesos del tramo {_n(a.precio)} → {_n(b.precio)}: 38% en {_n(niveles[0.382])}, 50% en "
             f"{_n(niveles[0.5])}, 62% en {_n(niveles[0.618])}. Hoy {estado}.")
    return Retrocesos(a.precio, b.precio, alcista, niveles, float(retro), texto)


# ------------------------------------------------------------ números redondos
def numeros_redondos(precio: float) -> tuple[float, float]:
    """Número redondo más cercano debajo y arriba del precio (cap. 4: 10, 25, 50, 100...).

    El "paso" depende del tamaño del precio: para 353 son las centenas y medias centenas
    (300, 350, 400); para 47 son 45 y 50; para 0,8 son 0,75 y 1.
    """
    if precio <= 0:
        return precio, precio
    magnitud = 10 ** math.floor(math.log10(precio))
    paso = magnitud / 2 if precio / magnitud < 5 else magnitud
    abajo = math.floor(precio / paso) * paso
    arriba = abajo + paso
    if math.isclose(abajo, precio):
        abajo -= paso
    return float(abajo), float(arriba)


def texto_redondos(precio: float) -> str:
    abajo, arriba = numeros_redondos(precio)
    cerca = [r for r in (abajo, arriba) if abs(r / precio - 1) <= 0.03]
    base = (f"Números redondos cercanos: {_n(abajo)} y {_n(arriba)}. Mucha gente pone órdenes en esos precios, "
            "así que suelen frenar subas y bajas.")
    if cerca:
        base += f" El precio está a menos de 3% de {_n(cerca[0])}: atención a esa zona."
    return base


# ---------------------------------------------------------- líneas de tendencia
@dataclass(frozen=True)
class LineaTendencia:
    """Recta que une dos mínimos ascendentes (o dos máximos descendentes)."""

    alcista: bool
    pos_inicio: int
    precio_inicio: float
    pendiente: float  # en logaritmo por rueda
    toques: int  # veces que el precio la tocó y rebotó (incluye los dos puntos que la definen)
    valor_actual: float
    rota: bool
    pendiente_mensual: float  # variación por mes de la línea
    empinada: bool
    texto: str

    @property
    def valida(self) -> bool:
        """Murphy: dos puntos la trazan, un tercer toque la valida."""
        return self.toques >= 3

    def valor_en(self, pos: int) -> float:
        return self.precio_inicio * math.exp(self.pendiente * (pos - self.pos_inicio))


def lineas_tendencia(df: pd.DataFrame, giros: list) -> list[LineaTendencia]:
    """Línea de tendencia alcista (bajo los mínimos) y bajista (sobre los máximos) vigentes.

    Se traza en escala logarítmica (porcentajes), como recomienda el libro para tendencias
    largas. Un toque cuenta si el mínimo (o máximo) del día queda a menos de media volatilidad
    diaria de la línea.
    """
    resultado = []
    atr = float(df["atr14"].iloc[-1])
    precio = float(df["cierre"].iloc[-1])
    tolerancia_log = 0.5 * atr / precio
    n = len(df)
    for tipo, alcista in (("L", True), ("H", False)):
        puntos = [g for g in giros if g.tipo == tipo]
        if len(puntos) < 2:
            continue
        p1, p2 = puntos[-2], puntos[-1]
        if alcista and p2.precio <= p1.precio or not alcista and p2.precio >= p1.precio:
            continue
        pendiente = (math.log(p2.precio) - math.log(p1.precio)) / (p2.pos - p1.pos)
        x = np.arange(p1.pos, n)
        linea = np.log(p1.precio) + pendiente * (x - p1.pos)
        extremo = np.log(df["minimo" if alcista else "maximo"].to_numpy(float)[p1.pos:])
        dist = (extremo - linea) if alcista else (linea - extremo)
        # Un toque es un acercamiento a la línea seguido de un rebote (se cuentan los grupos de días).
        cerca = dist <= tolerancia_log
        toques = int(np.sum(cerca[1:] & ~cerca[:-1])) + int(cerca[0])
        cierres = df["cierre"].iloc[p2.pos:]
        valores = pd.Series(np.exp(linea[p2.pos - p1.pos:]), index=cierres.index)
        # Rota = cierre 1% del otro lado de la línea, o dos cierres seguidos del otro lado (cap. 4).
        rel = (cierres / valores).to_numpy(float)
        quiebres = [k for k in range(1, len(rel)) if ruptura_confirmada(pd.Series(rel[:k + 1]), 1.0, not alcista)]
        rota = bool(quiebres) and ruptura_confirmada(pd.Series(rel), 1.0, not alcista)
        hace = len(rel) - 1 - quiebres[0] if quiebres else None
        mensual = math.exp(pendiente * 21) - 1
        atr_pct = atr / precio
        # Empinada: sube más de ~1,5 veces la volatilidad diaria por semana (ritmo difícil de sostener).
        empinada = abs(mensual) > 6 * atr_pct
        valor = float(np.exp(linea[-1]))
        nombre = "alcista (une mínimos cada vez más altos)" if alcista else "bajista (une máximos cada vez más bajos)"
        partes = [f"Línea de tendencia {nombre}: hoy pasa por {_n(valor)} y tiene {toques} toque(s)"]
        partes.append("ya está validada (3 o más toques)" if toques >= 3
                      else "todavía es tentativa (el libro pide un tercer toque para validarla)")
        if rota and hace is not None and hace > 30:
            # Rota hace tiempo: ya no es una señal nueva, pero el libro dice que las líneas rotas cambian de rol.
            partes.append(f"el precio la rompió hace {hace} ruedas, así que ya no es una señal nueva; ahora suele "
                          f"funcionar como {'resistencia' if alcista else 'soporte'} si el precio vuelve a acercarse")
            rota = False
        elif rota:
            partes.append("el precio la rompió al cierre, con filtro: es una de las primeras señales de que la "
                          "tendencia puede estar cambiando")
        elif empinada:
            partes.append(f"es muy empinada ({_p(mensual, 0)} por mes): un ritmo así rara vez se sostiene, y si se "
                          "rompe puede ser solo un ajuste a una tendencia más lenta")
        resultado.append(LineaTendencia(alcista, p1.pos, p1.precio, pendiente, toques, valor, rota, mensual,
                                        empinada, "; ".join(partes) + "."))
    return resultado


# ----------------------------------------------------------------------- huecos
@dataclass(frozen=True)
class Hueco:
    fecha: pd.Timestamp
    alcista: bool
    desde: float  # borde del hueco más cercano al precio previo
    hasta: float  # borde del hueco del lado nuevo
    tipo: str  # separación / escape / agotamiento / común
    cerrado: bool
    texto: str


def huecos(df: pd.DataFrame, ruedas: int = 60) -> tuple[list[Hueco], str | None]:
    """Huecos (gaps) de las últimas ``ruedas`` y si hubo una isla de giro (cap. 4).

    - Separación: aparece al salir de un rango o figura, con volumen alto. No suele cerrarse.
    - Escape (o de medida): en plena tendencia; suele estar cerca de la mitad del movimiento.
    - Agotamiento: después de una suba (o baja) larga, y el precio lo cierra a los pocos días.
    """
    hi, lo, ci = df["maximo"].to_numpy(float), df["minimo"].to_numpy(float), df["cierre"].to_numpy(float)
    vol = df["vol_relativo"].to_numpy(float) if "vol_relativo" in df else np.ones(len(df))
    n = len(df)
    lista: list[Hueco] = []
    min_tam = 0.003  # huecos de menos de 0,3% no se cuentan (ruido)
    for i in range(max(21, n - ruedas), n):
        arriba = lo[i] > hi[i - 1] * (1 + min_tam)
        abajo = hi[i] < lo[i - 1] * (1 - min_tam)
        if not (arriba or abajo):
            continue
        borde_viejo = hi[i - 1] if arriba else lo[i - 1]
        borde_nuevo = lo[i] if arriba else hi[i]
        despues = lo[i + 1:] if arriba else hi[i + 1:]
        cerrado = bool(len(despues) and (despues.min() <= borde_viejo if arriba else despues.max() >= borde_viejo))
        rango_previo_hi, rango_previo_lo = hi[i - 20:i].max(), lo[i - 20:i].min()
        sale_de_rango = (ci[i] > rango_previo_hi) if arriba else (ci[i] < rango_previo_lo)
        movimiento_previo = ci[i - 1] / ci[max(0, i - 40)] - 1
        extendido = movimiento_previo > 0.15 if arriba else movimiento_previo < -0.15
        if extendido and cerrado and len(despues) <= 10:
            tipo = "agotamiento"
        elif sale_de_rango and vol[i] >= 1.5 and not extendido:
            tipo = "separación"
        elif extendido or sale_de_rango:
            tipo = "escape"
        else:
            tipo = "común"
        explicacion = {
            "separación": "marca el comienzo de un movimiento (sale de un rango con volumen alto)",
            "escape": "aparece en plena tendencia y suele marcar más o menos la mitad del movimiento",
            "agotamiento": "llegó tarde, después de un movimiento largo, y el precio ya lo cerró: suele anticipar "
                           "el final del movimiento",
            "común": "no tiene un significado especial",
        }[tipo]
        sentido = "alcista" if arriba else "bajista"
        estado = "ya se cerró" if cerrado else ("sigue abierto y funciona como soporte" if arriba
                                                else "sigue abierto y funciona como resistencia")
        lista.append(Hueco(df.index[i], arriba, float(borde_viejo), float(borde_nuevo), tipo, cerrado,
                           f"{df.index[i]:%d/%m} hueco {sentido} de {tipo} entre {_n(min(borde_viejo, borde_nuevo))} "
                           f"y {_n(max(borde_viejo, borde_nuevo))}: {explicacion}; {estado}."))
    # Isla de giro: un hueco en un sentido y, pocas ruedas después, otro en el sentido contrario, de modo
    # que las ruedas del medio quedan "aisladas" (ningún precio de afuera las toca).
    isla = None
    pos = {h.fecha: df.index.get_loc(h.fecha) for h in lista}
    for a in lista:
        for b in lista:
            i, j = pos[a.fecha], pos[b.fecha]
            if not 0 < j - i <= 15 or a.alcista == b.alcista:
                continue
            if a.alcista and lo[i:j].min() > max(hi[i - 1], hi[j]):
                isla = (f"Isla de giro bajista: un hueco alcista el {a.fecha:%d/%m} y un hueco bajista el "
                        f"{b.fecha:%d/%m} dejaron unas ruedas \"aisladas\" arriba. Suele marcar un techo.")
            if not a.alcista and hi[i:j].max() < min(lo[i - 1], lo[j]):
                isla = (f"Isla de giro alcista: un hueco bajista el {a.fecha:%d/%m} y un hueco alcista el "
                        f"{b.fecha:%d/%m} dejaron unas ruedas \"aisladas\" abajo. Suele marcar un piso.")
    return lista, isla


# ------------------------------------------------------------ días de giro clave
def dia_de_giro(df: pd.DataFrame, ruedas: int = 5) -> tuple[int, str | None]:
    """Día de giro clave en las últimas ``ruedas`` (cap. 4).

    Arriba: marca un máximo de 20 ruedas y cierra debajo del cierre anterior. Abajo: marca un
    mínimo de 20 ruedas y cierra arriba del cierre anterior. Pesa más si es "día externo"
    (supera el máximo y el mínimo del día anterior) y con volumen alto.
    """
    n = len(df)
    for i in range(n - 1, max(21, n - ruedas) - 1, -1):
        u, a = df.iloc[i], df.iloc[i - 1]
        max20 = df["maximo"].iloc[i - 20:i].max()
        min20 = df["minimo"].iloc[i - 20:i].min()
        externo = u["maximo"] > a["maximo"] and u["minimo"] < a["minimo"]
        vol = float(u.get("vol_relativo", 1.0) or 1.0)
        extra = []
        if externo:
            extra.append("además fue un día externo (superó el máximo y el mínimo del día anterior)")
        if vol >= 1.5:
            extra.append(f"con volumen alto ({vol:.1f} veces el promedio)".replace(".", ","))
        detalle = (": " + " y ".join(extra)) if extra else ""
        if u["maximo"] > max20 and u["cierre"] < a["cierre"]:
            return -1, (f"día de giro bajista el {df.index[i]:%d/%m}: marcó un nuevo máximo de un mes pero cerró más "
                        f"abajo que el día anterior{detalle}. Es una advertencia de corto plazo, no una señal por sí sola")
        if u["minimo"] < min20 and u["cierre"] > a["cierre"]:
            return 1, (f"día de giro alcista el {df.index[i]:%d/%m}: marcó un nuevo mínimo de un mes pero cerró más "
                       f"arriba que el día anterior{detalle}. Si el volumen es muy alto se llama \"clímax vendedor\"")
    return 0, None


def semanal(df: pd.DataFrame) -> pd.DataFrame:
    """Barras semanales (cierre del viernes) a partir de las diarias."""
    return df.resample("W-FRI").agg({"apertura": "first", "maximo": "max", "minimo": "min", "cierre": "last",
                                     "volumen": "sum"}).dropna(subset=["cierre"])


def giro_semanal(df: pd.DataFrame) -> tuple[int, str | None]:
    """Giro semanal (cap. 8): nuevo máximo de 13 semanas y cierre semanal más bajo (o al revés)."""
    s = semanal(df)
    if len(s) < 15:
        return 0, None
    u, a = s.iloc[-1], s.iloc[-2]
    if u["maximo"] > s["maximo"].iloc[-14:-1].max() and u["cierre"] < a["cierre"]:
        return -1, ("giro semanal bajista: esta semana hizo un máximo de 3 meses pero cierra por debajo de la "
                    "semana anterior. En gráficos semanales estos giros pesan más que en los diarios")
    if u["minimo"] < s["minimo"].iloc[-14:-1].min() and u["cierre"] > a["cierre"]:
        return 1, ("giro semanal alcista: esta semana hizo un mínimo de 3 meses pero cierra por encima de la "
                   "semana anterior. En gráficos semanales estos giros pesan más que en los diarios")
    return 0, None


# ------------------------------------------------------- tres grados de tendencia
@dataclass(frozen=True)
class GradosTendencia:
    principal: int
    intermedia: int
    corta: int
    texto: str


_PALABRA = {1: "alcista", -1: "bajista", 0: "lateral"}


def grados_tendencia(df: pd.DataFrame, estructura_intermedia: int) -> GradosTendencia:
    """Tendencia principal (meses/años), intermedia (3 semanas a 3 meses) y corta (días) (caps. 2 y 4).

    - Principal: gráfico semanal, precio contra la media de 40 semanas y su pendiente.
    - Intermedia: la estructura de máximos y mínimos del zigzag diario.
    - Corta: precio contra la media de 20 ruedas y el momento de 10 ruedas.
    """
    s = semanal(df)
    principal = 0
    if len(s) >= 45:
        m40 = s["cierre"].rolling(40).mean()
        sube = m40.iloc[-1] > m40.iloc[-5]
        if s["cierre"].iloc[-1] > m40.iloc[-1] and sube:
            principal = 1
        elif s["cierre"].iloc[-1] < m40.iloc[-1] and not sube:
            principal = -1
    c = df["cierre"]
    momento = c.iloc[-1] - c.iloc[-11] if len(c) > 11 else 0
    corta = 0
    if c.iloc[-1] > df["sma20"].iloc[-1] and momento > 0:
        corta = 1
    elif c.iloc[-1] < df["sma20"].iloc[-1] and momento < 0:
        corta = -1
    texto = (f"Tendencia principal (meses): {_PALABRA[principal]}; intermedia (semanas): "
             f"{_PALABRA[estructura_intermedia]}; corta (días): {_PALABRA[corta]}.")
    if principal == 1 and estructura_intermedia <= 0:
        texto += " Es decir, una tendencia de fondo alcista que está corrigiendo: suele ser una pausa, no un giro."
    elif principal == -1 and estructura_intermedia >= 0:
        texto += " Es decir, una tendencia de fondo bajista con un rebote en el medio: hay que ver si se sostiene."
    elif principal == estructura_intermedia == corta != 0:
        texto += f" Las tres coinciden: es el escenario {_PALABRA[principal]} más claro."
    return GradosTendencia(principal, estructura_intermedia, corta, texto)


# ------------------------------------------------------------------- volumen OBV
def obv(df: pd.DataFrame) -> pd.Series:
    """Volumen acumulado (On Balance Volume): suma el volumen de los días de suba y resta el de los de baja."""
    signo = np.sign(df["cierre"].diff().fillna(0))
    return (signo * df["volumen"]).cumsum()


def divergencia_obv(df: pd.DataFrame, giros: list) -> tuple[int, str | None]:
    """El precio hace un nuevo máximo (o mínimo) y el volumen acumulado no lo acompaña (cap. 7)."""
    serie = obv(df).to_numpy(float)
    for tipo in ("H", "L"):
        g = [x for x in giros if x.tipo == tipo][-2:]
        if len(g) < 2 or len(df) - g[1].pos > 40:
            continue
        o0, o1 = serie[g[0].pos], serie[g[1].pos]
        if tipo == "H" and g[1].precio > g[0].precio and o1 < o0:
            return -1, ("el precio hizo un máximo más alto pero el volumen acumulado (OBV) no: la suba se hizo con "
                        "menos compradores. El libro dice que el volumen suele anticiparse al precio")
        if tipo == "L" and g[1].precio < g[0].precio and o1 > o0:
            return 1, ("el precio hizo un mínimo más bajo pero el volumen acumulado (OBV) no: la caída se hizo con "
                       "menos vendedores, señal de que la presión vendedora se agota")
    return 0, None


# -------------------------------------------------------------------- osciladores
@dataclass(frozen=True)
class Osciladores:
    voto: int
    textos: list[str] = field(default_factory=list)


def estocastico(df: pd.DataFrame, periodo: int = 14) -> tuple[pd.Series, pd.Series]:
    """Estocástico lento (cap. 10): %K suavizado 3 ruedas y %D = media de 3 de ese %K."""
    lo = df["minimo"].rolling(periodo).min()
    hi = df["maximo"].rolling(periodo).max()
    k_rapido = 100 * (df["cierre"] - lo) / (hi - lo).replace(0, np.nan)
    k = k_rapido.rolling(3).mean()
    return k, k.rolling(3).mean()


def osciladores(df: pd.DataFrame, tendencia: int, ruedas_desde_ruptura: int | None) -> Osciladores:
    """Lectura de los osciladores subordinada a la tendencia (cap. 10).

    - Sobrecompra/sobreventa: RSI 70/30 (80/20 cuando hay tendencia), estocástico 80/20.
    - Las mejores señales: oscilación fallida del RSI y cruce del estocástico desde una zona extrema.
    - Al comienzo de una tendencia nueva (poco después de una ruptura) los osciladores se ignoran:
      quedan "sobrecomprados" mucho tiempo.
    """
    textos: list[str] = []
    voto = 0
    rsi = df["rsi14"]
    r = float(rsi.iloc[-1])
    alto, bajo = (80, 20) if tendencia != 0 else (70, 30)
    k, d = estocastico(df)
    kv, dv = float(k.iloc[-1]), float(d.iloc[-1])
    temprano = ruedas_desde_ruptura is not None and ruedas_desde_ruptura <= 15
    if r >= alto or kv >= 80:
        textos.append(f"Sobrecompra: RSI {r:.0f}, estocástico {kv:.0f}. Subió mucho en poco tiempo y puede pedir "
                      "una pausa" + (", aunque recién empezó un movimiento nuevo y en esa etapa los osciladores "
                                     "suelen quedar arriba mucho tiempo: el libro aconseja no darles peso todavía"
                                     if temprano else ""))
    elif r <= bajo or kv <= 20:
        textos.append(f"Sobreventa: RSI {r:.0f}, estocástico {kv:.0f}. Cayó mucho en poco tiempo y puede rebotar"
                      + (", aunque recién empezó un movimiento nuevo: el libro aconseja no darles peso todavía"
                         if temprano else ""))
    else:
        textos.append(f"Osciladores en zona neutral (RSI {r:.0f}, estocástico {kv:.0f}).")

    # Oscilación fallida del RSI (Wilder): el segundo pico arriba de 70 no supera al primero y el RSI
    # perfora el valle entre ambos (o al revés abajo de 30).
    tramo = rsi.iloc[-30:].to_numpy(float)
    if len(tramo) == 30 and not np.isnan(tramo).any():
        picos = [i for i in range(1, 29) if tramo[i] > tramo[i - 1] and tramo[i] >= tramo[i + 1]]
        valles = [i for i in range(1, 29) if tramo[i] < tramo[i - 1] and tramo[i] <= tramo[i + 1]]
        arriba = [i for i in picos if tramo[i] > 70]
        if len(arriba) >= 2 and tramo[arriba[-1]] < tramo[arriba[-2]]:
            entre = [v for v in valles if arriba[-2] < v < arriba[-1]]
            if entre and tramo[-1] < tramo[entre[-1]]:
                voto = -1
                textos.append("Oscilación fallida bajista del RSI: el segundo pico en sobrecompra no superó al "
                              "primero y el RSI perforó el valle intermedio. Es la señal del RSI que más valora el "
                              "libro.")
        abajo = [i for i in valles if tramo[i] < 30]
        if len(abajo) >= 2 and tramo[abajo[-1]] > tramo[abajo[-2]]:
            entre = [p for p in picos if abajo[-2] < p < abajo[-1]]
            if entre and tramo[-1] > tramo[entre[-1]]:
                voto = 1
                textos.append("Oscilación fallida alcista del RSI: el segundo mínimo en sobreventa fue más alto que "
                              "el primero y el RSI superó el pico intermedio. Es la señal del RSI que más valora el "
                              "libro.")
    # Cruce del estocástico desde zona extrema.
    if len(k) > 2 and not np.isnan([k.iloc[-2], d.iloc[-2], kv, dv]).any():
        if k.iloc[-2] > d.iloc[-2] and kv < dv and dv > 80:
            textos.append("El estocástico cruzó hacia abajo desde sobrecompra (%K bajo la %D arriba de 80).")
            voto = voto or -1
        elif k.iloc[-2] < d.iloc[-2] and kv > dv and dv < 20:
            textos.append("El estocástico cruzó hacia arriba desde sobreventa (%K sobre la %D debajo de 20).")
            voto = voto or 1
    # Histograma del MACD: avisa antes que el cruce de líneas.
    h = df["macd_hist"].iloc[-3:].to_numpy(float) if "macd_hist" in df else np.array([])
    if len(h) == 3 and not np.isnan(h).any():
        if h[-1] > 0 and h[-1] < h[-2] < h[-3]:
            textos.append("El histograma del MACD sigue positivo pero baja: el impulso alcista se está frenando.")
        elif h[-1] < 0 and h[-1] > h[-2] > h[-3]:
            textos.append("El histograma del MACD sigue negativo pero sube: el impulso bajista se está frenando.")
    # Regla del libro: los osciladores no se usan para operar contra la tendencia principal.
    if tendencia != 0 and voto == -tendencia:
        textos.append("Ojo: esta señal va contra la tendencia; el libro recomienda usarla para proteger ganancias, "
                      "no para apostar al giro.")
        voto = 0
    if temprano:
        voto = 0
    return Osciladores(voto, textos)


# ------------------------------------------------- regla de las 4 semanas y medias
def regla_4_semanas(df: pd.DataFrame) -> tuple[int, str]:
    """Regla de Donchian (cap. 9): compra al superar el máximo de 4 semanas, venta al perder el mínimo.

    Devuelve la dirección de la última señal y cuántas ruedas tiene.
    """
    hi20 = df["maximo"].rolling(20).max().shift(1)
    lo20 = df["minimo"].rolling(20).min().shift(1)
    c = df["cierre"]
    arriba = (c > hi20).to_numpy()
    abajo = (c < lo20).to_numpy()
    ultimo_a = np.flatnonzero(arriba)
    ultimo_b = np.flatnonzero(abajo)
    ia = ultimo_a[-1] if len(ultimo_a) else -1
    ib = ultimo_b[-1] if len(ultimo_b) else -1
    if ia < 0 and ib < 0:
        return 0, "sin rupturas de 4 semanas"
    if ia > ib:
        return 1, (f"la última señal de la regla de las 4 semanas fue de compra (superó el máximo de 4 semanas "
                   f"hace {len(df) - 1 - ia} ruedas)")
    return -1, (f"la última señal de la regla de las 4 semanas fue de venta (perdió el mínimo de 4 semanas "
                f"hace {len(df) - 1 - ib} ruedas)")


def ruedas_desde_ruptura(df: pd.DataFrame) -> int | None:
    """Ruedas desde que empezó el movimiento actual: la última vez que la regla de las 4 semanas
    cambió de dirección (por ejemplo, la primera ruptura de un máximo de 4 semanas después de una
    señal de venta). Repetir mínimos dentro de una baja no cuenta como movimiento nuevo.
    """
    hi20 = df["maximo"].rolling(20).max().shift(1)
    lo20 = df["minimo"].rolling(20).min().shift(1)
    c = df["cierre"]
    senal = pd.Series(np.where(c > hi20, 1, np.where(c < lo20, -1, 0)), index=df.index)
    senal = senal.replace(0, np.nan).ffill()
    cambios = np.flatnonzero((senal != senal.shift()).to_numpy() & senal.notna().to_numpy())
    return int(len(df) - 1 - cambios[-1]) if len(cambios) > 1 else None


def adx(df: pd.DataFrame, periodo: int = 14) -> pd.DataFrame:
    """DMI y ADX de Wilder (cap. 15): +DI, -DI y ADX con el suavizado de Wilder."""
    hi, lo, c = df["maximo"], df["minimo"], df["cierre"]
    sube, baja = hi.diff(), -lo.diff()
    dm_mas = sube.where((sube > baja) & (sube > 0), 0.0)
    dm_menos = baja.where((baja > sube) & (baja > 0), 0.0)
    rango = pd.concat([hi - lo, (hi - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    alfa = 1 / periodo
    tr = rango.ewm(alpha=alfa, adjust=False).mean()
    di_mas = 100 * dm_mas.ewm(alpha=alfa, adjust=False).mean() / tr
    di_menos = 100 * dm_menos.ewm(alpha=alfa, adjust=False).mean() / tr
    dx = 100 * (di_mas - di_menos).abs() / (di_mas + di_menos).replace(0, np.nan)
    return pd.DataFrame({"di_mas": di_mas, "di_menos": di_menos, "adx": dx.ewm(alpha=alfa, adjust=False).mean()})


@dataclass(frozen=True)
class Regimen:
    """¿El mercado está en tendencia o en rango? Define qué herramientas sirven (caps. 10 y 15)."""

    tendencia: bool
    adx: float
    texto: str


def regimen(df: pd.DataFrame) -> Regimen:
    """ADX subiendo y alto = tendencia (sirven medias y rupturas); bajo o bajando = rango (sirven osciladores)."""
    d = adx(df)
    a, a5 = float(d["adx"].iloc[-1]), float(d["adx"].iloc[-6])
    mas, menos = float(d["di_mas"].iloc[-1]), float(d["di_menos"].iloc[-1])
    lado = "compradores (+DI arriba de -DI)" if mas > menos else "vendedores (-DI arriba de +DI)"
    bajando = a < a5 - 0.5
    if a >= 20 and not bajando:
        texto = (f"ADX {a:.0f}{' y subiendo' if a > a5 + 0.5 else ''}: hay tendencia, dominada por los {lado}. En "
                 "esta etapa funcionan mejor las medias móviles y las rupturas; los osciladores dan falsas alarmas "
                 "de \"sobrecompra\" o \"sobreventa\"")
        return Regimen(True, a, texto)
    if a >= 25 and bajando:
        texto = (f"ADX {a:.0f} pero bajando: hubo tendencia (de los {lado}) y se está cansando; suele venir una "
                 "pausa o un rango, y los osciladores vuelven a ser útiles")
        return Regimen(False, a, texto)
    texto = (f"ADX {a:.0f}{' y bajando' if a < a5 else ''}: no hay una tendencia fuerte. En rangos funcionan mejor "
             "los osciladores (RSI, estocástico) que las medias móviles, que dan señales falsas")
    return Regimen(False, a, texto)


# ------------------------------------------------------------------ velas japonesas
@dataclass(frozen=True)
class Vela:
    fecha: pd.Timestamp
    nombre: str
    sesgo: int
    filtrada: bool  # True si el estocástico la acompaña (filtro del cap. 12)
    texto: str


def velas(df: pd.DataFrame, ruedas: int = 3) -> list[Vela]:
    """Patrones de velas de giro y continuación (cap. 12), en las últimas ``ruedas``.

    - Exigen tendencia previa (medida con la media de 10 ruedas): un patrón alcista de giro solo
      tiene sentido después de una baja, y uno bajista después de una suba.
    - Filtro del libro: un patrón de giro vale más si el estocástico %D está en zona extrema
      (arriba de 80 para los bajistas, debajo de 20 para los alcistas).
    """
    o, h, l, c = (df[x].to_numpy(float) for x in ("apertura", "maximo", "minimo", "cierre"))
    cuerpo = np.abs(c - o)
    cuerpo_medio = pd.Series(cuerpo).rolling(20).mean().to_numpy()
    m10 = df["cierre"].rolling(10).mean().to_numpy()
    _, d = estocastico(df)
    dv = d.to_numpy(float)
    n = len(df)
    encontradas: list[Vela] = []

    def tendencia(i: int) -> int:
        """Tendencia previa a la rueda i: el cierre contra la media de 10 y su pendiente."""
        if i < 15 or np.isnan(m10[i - 1]):
            return 0
        if c[i - 1] > m10[i - 1] and m10[i - 1] > m10[i - 6]:
            return 1
        if c[i - 1] < m10[i - 1] and m10[i - 1] < m10[i - 6]:
            return -1
        return 0

    def larga(i: int) -> bool:
        return cuerpo[i] >= 1.3 * cuerpo_medio[i] if not np.isnan(cuerpo_medio[i]) else False

    def corta(i: int) -> bool:
        return cuerpo[i] <= 0.5 * cuerpo_medio[i] if not np.isnan(cuerpo_medio[i]) else False

    def agregar(i: int, nombre: str, sesgo: int, explicacion: str) -> None:
        filtrada = bool(not np.isnan(dv[i]) and ((sesgo < 0 and dv[i] > 80) or (sesgo > 0 and dv[i] < 20)))
        extra = (" El estocástico está en zona extrema y la acompaña (es la combinación que recomienda el libro)."
                 if filtrada else " El estocástico no está en zona extrema: el libro le da menos peso.")
        encontradas.append(Vela(df.index[i], nombre, sesgo, filtrada,
                                f"{df.index[i]:%d/%m} {nombre}: {explicacion}.{extra}"))

    for i in range(max(25, n - ruedas), n):
        t = tendencia(i - 1 if i >= 2 else i)
        blanca, negra = c[i] > o[i], c[i] < o[i]
        # Nube oscura y línea penetrante (2 velas).
        if t == 1 and c[i - 1] > o[i - 1] and larga(i - 1) and negra and o[i] > h[i - 1] \
                and c[i] < (o[i - 1] + c[i - 1]) / 2 and c[i] > o[i - 1]:
            agregar(i, "nube oscura", -1, "después de una suba, abrió arriba del máximo anterior y cerró debajo "
                                          "de la mitad de la vela blanca previa: los vendedores tomaron el control")
        if t == -1 and c[i - 1] < o[i - 1] and larga(i - 1) and blanca and o[i] < l[i - 1] \
                and c[i] > (o[i - 1] + c[i - 1]) / 2 and c[i] < o[i - 1]:
            agregar(i, "línea penetrante", 1, "después de una baja, abrió debajo del mínimo anterior y cerró arriba "
                                              "de la mitad de la vela negra previa: entraron compradores")
        # Estrella vespertina / matutina (3 velas).
        if i >= 2:
            j, k = i - 2, i - 1
            if tendencia(j) == 1 and c[j] > o[j] and larga(j) and corta(k) and min(o[k], c[k]) > c[j] \
                    and negra and c[i] < (o[j] + c[j]) / 2:
                agregar(i, "estrella vespertina", -1, "vela blanca larga, una vela chica que \"salta\" arriba y una "
                                                      "vela negra que cierra debajo de la mitad de la primera. Es de "
                                                      "los patrones de giro más confiables")
            if tendencia(j) == -1 and c[j] < o[j] and larga(j) and corta(k) and max(o[k], c[k]) < c[j] \
                    and blanca and c[i] > (o[j] + c[j]) / 2:
                agregar(i, "estrella matutina", 1, "vela negra larga, una vela chica que \"salta\" abajo y una vela "
                                                   "blanca que cierra arriba de la mitad de la primera. Es de los "
                                                   "patrones de giro más confiables")
        # Doji: apertura y cierre casi iguales; lápida y libélula.
        rango = h[i] - l[i]
        if rango > 0 and cuerpo[i] <= 0.1 * rango:
            sup, inf = h[i] - max(o[i], c[i]), min(o[i], c[i]) - l[i]
            if t == 1 and sup >= 0.7 * rango:
                agregar(i, "doji lápida", -1, "abrió y cerró casi en el mínimo después de subir mucho en el día: "
                                              "rechazo de los precios altos")
            elif t == -1 and inf >= 0.7 * rango:
                agregar(i, "doji libélula", 1, "abrió y cerró casi en el máximo después de caer mucho en el día: "
                                               "rechazo de los precios bajos")
            elif t != 0:
                agregar(i, "doji", 0, "apertura y cierre casi iguales: indecisión. Después de una tendencia avisa "
                                      "que el impulso se frena")
    # Tres métodos ascendentes / descendentes (continuación, 5 o más velas).
    for i in range(max(25, n - ruedas), n):
        for largo in (3, 4, 5):
            j = i - largo - 1
            if j < 20:
                continue
            medio = range(j + 1, i)
            if c[j] > o[j] and larga(j) and c[i] > o[i] and larga(i) and c[i] > c[j] \
                    and all(l[m] >= l[j] and h[m] <= h[j] and corta(m) for m in medio):
                agregar(i, "tres métodos ascendentes", 1, "una vela blanca larga, unas velas chicas que corrigen "
                                                          "sin perder su mínimo y otra vela blanca larga que la supera: "
                                                          "pausa dentro de una suba")
                break
            if c[j] < o[j] and larga(j) and c[i] < o[i] and larga(i) and c[i] < c[j] \
                    and all(h[m] <= h[j] and l[m] >= l[j] and corta(m) for m in medio):
                agregar(i, "tres métodos descendentes", -1, "una vela negra larga, unas velas chicas que rebotan sin "
                                                            "superar su máximo y otra vela negra larga que la perfora: "
                                                            "pausa dentro de una baja")
                break
    return encontradas


def medias_semanales(df: pd.DataFrame) -> tuple[int, str]:
    """Medias de 10 y 40 semanas (caps. 8 y 9): la tendencia principal en el gráfico semanal."""
    s = semanal(df)
    if len(s) < 42:
        return 0, "sin historia suficiente para las medias semanales"
    m10, m40 = s["cierre"].rolling(10).mean().iloc[-1], s["cierre"].rolling(40).mean().iloc[-1]
    c = s["cierre"].iloc[-1]
    if c > m10 > m40:
        return 1, f"en el gráfico semanal el precio está arriba de las medias de 10 ({_n(m10)}) y 40 semanas ({_n(m40)})"
    if c < m10 < m40:
        return -1, f"en el gráfico semanal el precio está debajo de las medias de 10 ({_n(m10)}) y 40 semanas ({_n(m40)})"
    return 0, f"en el gráfico semanal las medias de 10 ({_n(m10)}) y 40 semanas ({_n(m40)}) no muestran una dirección clara"
