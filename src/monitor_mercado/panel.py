"""Panel web local con Streamlit: `monitor panel` (se abre en el navegador, en http://localhost:8501).

Lee la misma base de datos y usa los mismos servicios que el bot y la terminal
(``armar_contexto``) y las mismas tablas que la exportación a Excel (``tablas.py``):
acá no hay cálculos propios, solo presentación.

Requiere la dependencia opcional: pip install -e ".[panel]"
"""

from __future__ import annotations

import streamlit as st

from monitor_mercado import tablas
from monitor_mercado.aviso_legal import AVISO_DEMORA, AVISO_LEGAL

MINUTOS_CACHE = 5


@st.cache_resource
def contexto():
    """Los servicios se arman una sola vez por sesión del panel."""
    from monitor_mercado.aplicacion import armar_contexto

    return armar_contexto()


@st.cache_data(ttl=MINUTOS_CACHE * 60, show_spinner="Valuando tu cartera...")
def estado_cartera():
    return contexto().cartera.estado()


@st.cache_data(ttl=MINUTOS_CACHE * 60, show_spinner="Buscando dividendos...")
def rendimiento_total():
    return contexto().rendimiento(estado_cartera())


@st.cache_data(ttl=12 * 3600, show_spinner="Buscando dividendos...")
def resumen_dividendos():
    return contexto().dividendos.resumen()


@st.cache_data(ttl=3600, show_spinner="Simulando escenarios (la primera vez baja el historial de cada acción)...")
def prueba_estres():
    return contexto().estres.correr()


def _dinero(v: float | None) -> str:
    return "s/d" if v is None else f"US$ {v:,.0f}".replace(",", ".")


def _porcentaje(v: float | None) -> str:
    return "s/d" if v is None else f"{100 * v:+.1f}%".replace(".", ",")


def _seguro(funcion, mensaje: str):
    """Corre una consulta; si falla (sin internet, Yahoo caído), muestra el aviso y sigue."""
    try:
        return funcion()
    except Exception as e:  # noqa: BLE001
        st.warning(f"{mensaje}: {e}")
        return None


def encabezado(estado, rendimiento) -> None:
    columnas = st.columns(4)
    columnas[0].metric("Valor de la cartera", _dinero(estado.valor))
    columnas[1].metric("Hoy", _dinero(estado.resultado_dia), _porcentaje(estado.variacion_dia))
    columnas[2].metric("Desde la compra (precio)", _dinero(estado.resultado), _porcentaje(estado.resultado_pct))
    if rendimiento is not None and rendimiento.dividendos:
        columnas[3].metric("Rendimiento total (+ dividendos)", _dinero(rendimiento.total),
                           _porcentaje(rendimiento.total_pct))
    else:
        columnas[3].metric("Dividendos cobrados", _dinero(0))
    if estado.sin_precio:
        st.caption(f"Sin cotización: {', '.join(estado.sin_precio)}.")


def pestana_cartera(estado) -> None:
    tabla = tablas.tabla_cartera(estado)
    st.dataframe(tabla, hide_index=True, use_container_width=True)
    pesos = tabla.dropna(subset=["Peso %"]).set_index("Símbolo")["Peso %"]
    if not pesos.empty:
        st.subheader("Peso de cada posición (%)")
        st.bar_chart(pesos)
    limite = contexto().cfg.cartera.concentracion_maxima
    concentradas = [f.simbolo for f in estado.posiciones if f.peso > limite]
    if concentradas:
        st.warning(f"Concentración: {', '.join(concentradas)} pesa más del {limite:.0%} de la cartera.")


def pestana_evolucion() -> None:
    evolucion = tablas.tabla_evolucion(contexto().cartera.historial())
    if evolucion.empty:
        st.info("Todavía no hay historia: se guarda un punto por día con el resumen de cierre (o /resumen_dia).")
        return
    st.line_chart(evolucion)


def pestana_alertas() -> None:
    ctx = contexto()
    st.subheader("Alertas de precio activas")
    st.dataframe(tablas.tabla_alertas(ctx.servicio.repo.listar()), hide_index=True, use_container_width=True)
    st.subheader("Stops")
    estados = _seguro(ctx.stops.estados, "No se pudieron consultar los precios de los stops")
    if estados is not None:
        st.dataframe(tablas.tabla_stops(estados), hide_index=True, use_container_width=True)


def pestana_diario(estado) -> None:
    ctx = contexto()
    movimientos = ctx.diario.repo.listar()
    if not movimientos:
        st.info("El diario está vacío. Registrá operaciones con /compre y /vendi, o importá tu cartera con "
                "/importar_diario.")
        return
    e = ctx.diario.estadisticas(estado.resultado)
    columnas = st.columns(4)
    columnas[0].metric("Realizado", _dinero(e.realizado))
    columnas[1].metric("No realizado", _dinero(e.no_realizado))
    columnas[2].metric("Tasa de aciertos", "s/d" if e.tasa_aciertos is None else f"{e.tasa_aciertos:.0%}")
    columnas[3].metric("Ganancia / pérdida promedio",
                       f"{_dinero(e.ganancia_promedio)} / {_dinero(e.perdida_promedio)}")
    st.subheader("Ventas cerradas")
    st.dataframe(tablas.tabla_ventas(e), hide_index=True, use_container_width=True)
    st.subheader("Operaciones")
    st.dataframe(tablas.tabla_operaciones(movimientos), hide_index=True, use_container_width=True)


def pestana_dividendos() -> None:
    resumen = _seguro(resumen_dividendos, "No se pudieron consultar los dividendos")
    if resumen is None:
        return
    cobrados, proximos = tablas.tabla_dividendos(resumen)
    st.metric("Cobrados en los últimos 12 meses", _dinero(resumen.total_anual))
    st.subheader("Próximos cobros")
    st.dataframe(proximos, hide_index=True, use_container_width=True)
    st.subheader("Cobrados")
    st.dataframe(cobrados, hide_index=True, use_container_width=True)
    st.caption("No incluye impuestos ni retenciones (en EE.UU. suelen retener el 30% a no residentes).")


def pestana_estres() -> None:
    st.write("Pérdida estimada si el mercado cae o el dólar sube, con la beta y las correlaciones de los últimos "
             "2 años. Es una estimación, no una predicción.")
    if not st.button("Correr la prueba de estrés"):
        return
    resultado = _seguro(prueba_estres, "No se pudo correr la prueba de estrés")
    if resultado is None:
        return
    escenarios, posiciones = tablas.tabla_estres(resultado)
    st.dataframe(escenarios, hide_index=True, use_container_width=True)
    if resultado.var_mensual_pct is not None:
        st.metric("Un mes malo (1 de cada 20)", _porcentaje(resultado.var_mensual_pct),
                  _dinero(resultado.var_mensual_pct * resultado.valor))
    st.dataframe(posiciones, hide_index=True, use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="Monitor de mercado", page_icon="📈", layout="wide")
    st.title("📈 Monitor de mercado")
    with st.sidebar:
        st.caption(AVISO_LEGAL)
        st.caption(AVISO_DEMORA)
        if st.button("Actualizar precios"):
            st.cache_data.clear()
        st.caption(f"Los precios se guardan {MINUTOS_CACHE} minutos para no consultar a Yahoo en cada clic.")

    estado = _seguro(estado_cartera, "No se pudo valuar la cartera")
    if estado is None:
        st.stop()
    encabezado(estado, _seguro(rendimiento_total, "No se pudieron calcular los dividendos"))

    nombres = ["Cartera", "Evolución", "Alertas y stops", "Diario", "Dividendos", "Prueba de estrés"]
    cartera, evolucion, alertas, diario, dividendos, estres = st.tabs(nombres)
    with cartera:
        pestana_cartera(estado)
    with evolucion:
        pestana_evolucion()
    with alertas:
        pestana_alertas()
    with diario:
        pestana_diario(estado)
    with dividendos:
        pestana_dividendos()
    with estres:
        pestana_estres()


if __name__ == "__main__":  # `streamlit run` ejecuta el archivo como script
    main()
