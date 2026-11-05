"""Rebalanceo: compara los pesos actuales con los que querés y sugiere qué comprar o vender.

Solo sugiere: no ejecuta nada. Los objetivos se definen en config.yaml:

    rebalanceo:
      tolerancia: 0.05            # solo avisa si te desviás más de 5 puntos
      objetivos:                  # peso objetivo por símbolo o por grupo
        NUGT: 0.20
        Argentina: 0.25
      grupos:                     # grupos propios (opcional)
        Argentina: [GGAL, BMA, YPF, VIST, ALUA.BA]

Cada clave de ``objetivos`` puede ser un símbolo o un grupo. Un símbolo que no está en
ningún grupo propio pertenece al grupo de su bolsa ("EE.UU.", "BYMA", "B3", "Xetra",
"Londres"), así que también podés usar esos nombres como objetivo. Lo que no tiene
objetivo no se toca.
"""

from __future__ import annotations

from dataclasses import dataclass

from monitor_mercado.cartera.servicio import EstadoCartera
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.mercados import mercado_de


@dataclass(frozen=True)
class Ajuste:
    """Lo que habría que hacer con una posición o un grupo."""

    clave: str
    es_grupo: bool
    simbolos: tuple[str, ...]
    peso_actual: float
    peso_objetivo: float
    valor_actual: float
    monto: float  # USD: positivo = comprar, negativo = vender
    comision: float  # USD estimados
    acciones: float | None  # solo para símbolos con precio
    fuera_de_tolerancia: bool

    @property
    def desvio(self) -> float:
        return self.peso_actual - self.peso_objetivo


@dataclass(frozen=True)
class PlanRebalanceo:
    """Todos los ajustes y el contexto para explicarlos."""

    ajustes: list[Ajuste]
    valor_total: float
    tolerancia: float
    suma_objetivos: float
    peso_sin_objetivo: float  # lo que no tiene objetivo (no se toca)
    desconocidos: list[str]  # claves de objetivos que no son ni símbolo ni grupo con posiciones
    superpuestos: list[str]  # símbolos alcanzados por más de un objetivo

    @property
    def a_ejecutar(self) -> list[Ajuste]:
        return [a for a in self.ajustes if a.fuera_de_tolerancia]

    @property
    def comision_total(self) -> float:
        return sum(a.comision for a in self.a_ejecutar)


def grupo_de(simbolo: str, grupos: dict[str, list[str]]) -> str:
    """Grupo propio del símbolo o, si no está en ninguno, el nombre de su bolsa."""
    for nombre, simbolos in grupos.items():
        if simbolo in {s.upper() for s in simbolos}:
            return nombre
    return mercado_de(simbolo).nombre


def comision_de(simbolo: str, cfg: Configuracion) -> float:
    """Comisión de referencia del backtest para la bolsa del símbolo."""
    return cfg.backtest.comisiones.get(mercado_de(simbolo).nombre, cfg.backtest.comision_por_defecto)


def planificar(estado: EstadoCartera, cfg: Configuracion) -> PlanRebalanceo:
    """Arma el plan de rebalanceo (función pura sobre la cartera ya valuada)."""
    rb = cfg.rebalanceo
    con_valor = [f for f in estado.posiciones if f.valor]
    total = estado.valor
    por_simbolo = {f.simbolo: f for f in con_valor}
    grupos = {nombre: [s.upper() for s in lista] for nombre, lista in rb.grupos.items()}
    miembros: dict[str, list[str]] = {}
    for f in con_valor:
        miembros.setdefault(grupo_de(f.simbolo, grupos), []).append(f.simbolo)

    ajustes, desconocidos, alcanzados = [], [], []
    for clave, objetivo in rb.objetivos.items():
        clave_sim = clave.upper()
        if clave_sim in por_simbolo:
            simbolos, es_grupo = [clave_sim], False
        elif clave in miembros:
            simbolos, es_grupo = miembros[clave], True
        elif clave in grupos:  # grupo propio sin posiciones todavía: hay que comprar
            simbolos, es_grupo = [], True
        else:
            desconocidos.append(clave)
            continue
        alcanzados += simbolos
        valor = sum(por_simbolo[s].valor for s in simbolos)
        actual = valor / total if total else 0.0
        monto = objetivo * total - valor
        if simbolos:  # comisión según la bolsa de lo que más pesa del grupo
            principal = max(simbolos, key=lambda s: por_simbolo[s].valor)
        else:
            principal = grupos[clave][0] if grupos.get(clave) else ""
        comision = abs(monto) * (comision_de(principal, cfg) if principal else cfg.backtest.comision_por_defecto)
        precio = por_simbolo[clave_sim].precio if not es_grupo else None
        ajustes.append(Ajuste(
            clave=clave_sim if not es_grupo else clave, es_grupo=es_grupo, simbolos=tuple(simbolos),
            peso_actual=actual, peso_objetivo=objetivo, valor_actual=valor, monto=monto, comision=comision,
            acciones=monto / precio if precio else None,
            fuera_de_tolerancia=abs(actual - objetivo) > rb.tolerancia,
        ))

    vistos = set(alcanzados)
    superpuestos = sorted({s for s in alcanzados if alcanzados.count(s) > 1})
    sin_objetivo = sum(f.valor for f in con_valor if f.simbolo not in vistos)
    return PlanRebalanceo(
        ajustes=sorted(ajustes, key=lambda a: -abs(a.desvio)), valor_total=total, tolerancia=rb.tolerancia,
        suma_objetivos=sum(rb.objetivos.values()), peso_sin_objetivo=sin_objetivo / total if total else 0.0,
        desconocidos=desconocidos, superpuestos=superpuestos,
    )
