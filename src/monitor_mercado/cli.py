"""Interfaz de línea de comandos: ``monitor <comando>``.

Ejemplos:
    monitor crear AAPL compra baja 180
    monitor listar
    monitor borrar 3
    monitor precio ALUA.BA
    monitor revisar --forzar
    monitor validar-watchlist --completa
    monitor probar-telegram
    monitor bot            (deja todo corriendo)
"""

from __future__ import annotations

import logging
import sys
from dataclasses import replace
from datetime import date, timedelta

import typer

from monitor_mercado.alertas.modelos import Moneda
from monitor_mercado.alertas.parser import AYUDA_FORMATO, ErrorFormato, parsear_alerta
from monitor_mercado.aplicacion import Contexto, armar_contexto
from monitor_mercado.aviso_legal import pie_de_mensaje
from monitor_mercado.datos.modelos import ErrorDatos
from monitor_mercado.explicacion import explicacion_completa, texto_glosario
from monitor_mercado.noticias.reporte import linea_senal_final, reporte_noticias
from monitor_mercado.notificaciones import formato
from monitor_mercado.notificaciones.envio import ErrorTelegram, enviar_mensaje
from monitor_mercado.tecnico.grafico import generar_grafico
from monitor_mercado.tecnico.grafico_lectura import grafico_lectura
from monitor_mercado.tecnico.reporte_lectura import texto_lectura
from monitor_mercado.tecnico.reporte import reporte_completo, reporte_resumen

app = typer.Typer(help="Monitor de mercado: alertas de precio por Telegram.", no_args_is_help=True)
log = logging.getLogger(__name__)


def _contexto() -> Contexto:
    # La consola de Windows no siempre usa UTF-8: sin esto, los emojis rompen el print.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return armar_contexto()


def _salir_con_error(mensaje: str) -> None:
    typer.echo(mensaje, err=True)
    raise typer.Exit(code=1)


@app.command()
def crear(
    datos: list[str] = typer.Argument(..., help="SIMBOLO compra|venta llega|sube|baja|var+|var- VALOR [ars] [repetir]"),
    nota: str | None = typer.Option(None, "--nota", "-n", help="Comentario que se incluye en el aviso."),
) -> None:
    """Crea una alerta. Ej.: monitor crear AAPL compra baja 180"""
    ctx = _contexto()
    try:
        solicitud = parsear_alerta(datos)
        if nota:
            solicitud = replace(solicitud, nota=nota)
        resultado = ctx.servicio.crear(solicitud)
    except ErrorFormato as e:
        _salir_con_error(str(e))
    except (ValueError, ErrorDatos) as e:
        _salir_con_error(f"No se pudo crear la alerta: {e}")
    typer.echo(formato.mensaje_creada(resultado))


@app.command()
def listar(todas: bool = typer.Option(False, "--todas", help="Incluir alertas cumplidas.")) -> None:
    """Lista las alertas."""
    ctx = _contexto()
    typer.echo(formato.mensaje_listado(ctx.servicio.repo.listar(solo_activas=not todas)))


@app.command()
def borrar(id_alerta: int = typer.Argument(..., help="ID de la alerta (ver 'monitor listar').")) -> None:
    """Borra una alerta."""
    ctx = _contexto()
    if not ctx.servicio.repo.borrar(id_alerta):
        _salir_con_error(f"No existe la alerta #{id_alerta}.")
    typer.echo(f"Alerta #{id_alerta} borrada.")


@app.command()
def precio(
    simbolo: str,
    ars: bool = typer.Option(False, "--ars", help="Precio en pesos (CEDEAR / BYMA)."),
) -> None:
    """Muestra el precio actual de un activo."""
    ctx = _contexto()
    try:
        p = ctx.servicio.precio_en(simbolo.upper(), Moneda.ARS if ars else Moneda.USD)
    except (ValueError, ErrorDatos) as e:
        _salir_con_error(f"No se pudo obtener el precio: {e}")
    typer.echo(formato.detalle_precio(p) + pie_de_mensaje())


@app.command()
def revisar(forzar: bool = typer.Option(False, "--forzar", help="Ignorar el horario de mercado.")) -> None:
    """Hace una revisión de alertas y manda los avisos por Telegram (si está configurado)."""
    from monitor_mercado.stops.reporte import mensaje_disparo_stop

    ctx = _contexto()
    textos = [formato.mensaje_disparo(d) for d in ctx.servicio.revisar(forzar=forzar)]
    if ctx.stops is not None:
        textos += [mensaje_disparo_stop(d) for d in ctx.stops.revisar(forzar=forzar)]
    for texto in textos:
        typer.echo(texto + "\n")
        _enviar_telegram(ctx, texto)
    typer.echo(formato.mensaje_revision(len(textos)))


def _enviar_telegram(ctx: Contexto, texto: str) -> None:
    """Manda un texto por Telegram si está configurado (los errores solo se registran)."""
    if not ctx.secretos.telegram_configurado:
        return
    try:
        enviar_mensaje(
            ctx.secretos.telegram_bot_token.get_secret_value(),  # type: ignore[union-attr]
            ctx.secretos.telegram_chat_id,  # type: ignore[arg-type]
            texto,
        )
    except Exception as e:  # noqa: BLE001
        log.error("No se pudo enviar el aviso por Telegram: %s", e)


@app.command("validar-watchlist")
def validar_watchlist(
    completa: bool = typer.Option(False, "--completa", help="Validar la lista completa en vez de la de prueba."),
) -> None:
    """Comprueba que cada símbolo tenga precio y datos recientes en Yahoo."""
    ctx = _contexto()
    simbolos = ctx.cfg.watchlist_completa if completa else ctx.cfg.watchlist_prueba
    limite = date.today() - timedelta(days=7)
    problemas = 0
    typer.echo(f"Validando {len(simbolos)} símbolos...\n")
    for s in simbolos:
        try:
            cot = ctx.proveedor.cotizacion(s)
            ultima = ctx.proveedor.ultima_fecha_operada(s)
        except ErrorDatos as e:
            typer.echo(f"  ❌ {s:10} {e}")
            problemas += 1
            continue
        if ultima is None or ultima < limite:
            typer.echo(f"  ⚠️ {s:10} sin operaciones recientes (última: {ultima}). ¿Dejó de cotizar?")
            problemas += 1
        else:
            typer.echo(f"  ✅ {s:10} {formato.numero(cot.precio)} {cot.moneda}")
    typer.echo(f"\n{len(simbolos) - problemas} OK, {problemas} con problemas.")


@app.command("probar-telegram")
def probar_telegram() -> None:
    """Manda un mensaje de prueba para verificar el token y el chat ID."""
    ctx = _contexto()
    if not ctx.secretos.telegram_configurado:
        _salir_con_error("Faltan TELEGRAM_BOT_TOKEN y/o TELEGRAM_CHAT_ID en el .env (ver README).")
    try:
        enviar_mensaje(
            ctx.secretos.telegram_bot_token.get_secret_value(),  # type: ignore[union-attr]
            ctx.secretos.telegram_chat_id,  # type: ignore[arg-type]
            "✅ Prueba del monitor de mercado: el bot está bien configurado." + pie_de_mensaje(),
        )
    except ErrorTelegram as e:
        _salir_con_error(f"Telegram rechazó el mensaje: {e}")
    typer.echo("Mensaje enviado. Revisá Telegram.")


@app.command()
def analizar(
    simbolo: str,
    grafico: bool = typer.Option(True, "--grafico/--sin-grafico", help="Generar el gráfico PNG."),
    explicar: bool = typer.Option(True, "--explicar/--sin-explicar", help="Agregar el resumen para aprender."),
) -> None:
    """Análisis completo: técnico, noticias, señal final y explicación."""
    ctx = _contexto()
    try:
        r = ctx.analisis_completo(simbolo)
    except ErrorDatos as e:
        _salir_con_error(f"No se pudo analizar: {e}")
    if r.tecnico.lectura is not None:
        typer.echo(texto_lectura(r.tecnico.simbolo, r.tecnico.lectura, r.tecnico.moneda) + "\n")
    typer.echo(reporte_completo(r.tecnico, con_pie=False))
    if r.noticias is not None:
        typer.echo("\n" + reporte_noticias(r.noticias, maximo=5, con_pie=False))
    typer.echo("\n" + linea_senal_final(r.final) + pie_de_mensaje())
    if explicar:
        typer.echo("\n" + explicacion_completa(r.tecnico, r.noticias, r.final))
    if grafico:
        ruta = generar_grafico(r.tecnico, ctx.cfg.rutas.ruta_graficos(), ctx.cfg.tecnico.ruedas_grafico)
        typer.echo(f"\nGráfico de indicadores: {ruta}")
        if r.tecnico.lectura is not None:
            ruta = grafico_lectura(r.tecnico.simbolo, r.tecnico.lectura, r.tecnico.moneda,
                                   ctx.cfg.rutas.ruta_graficos())
            typer.echo(f"Gráfico anotado (lectura del trader): {ruta}")


@app.command("validar-grafico")
def validar_grafico(
    completa: bool = typer.Option(False, "--completa", help="Usar la watchlist completa (tarda más)."),
) -> None:
    """¿La lectura del gráfico anticipó la dirección del precio en el pasado?"""
    from monitor_mercado.backtest.validar_lectura import texto_validacion, validar

    ctx = _contexto()
    simbolos = ctx.cfg.watchlist_completa if completa else ctx.cfg.watchlist_activa
    typer.echo(texto_validacion(validar(ctx.tecnico, simbolos)))


@app.command()
def grafico(simbolo: str) -> None:
    """Lectura del gráfico como un trader: tendencia, soportes, resistencias, figuras y escenarios."""
    ctx = _contexto()
    try:
        a = ctx.tecnico.analizar(simbolo)
    except ErrorDatos as e:
        _salir_con_error(f"No se pudo analizar: {e}")
    if a.lectura is None:
        _salir_con_error("No se pudo leer el gráfico (historia insuficiente).")
    typer.echo(texto_lectura(a.simbolo, a.lectura, a.moneda))
    typer.echo(f"\nGráfico: {grafico_lectura(a.simbolo, a.lectura, a.moneda, ctx.cfg.rutas.ruta_graficos())}")


@app.command()
def noticias(simbolo: str) -> None:
    """Noticias recientes de un activo con su sentimiento."""
    ctx = _contexto()
    if ctx.noticias is None:
        _salir_con_error("Las noticias están desactivadas en config.yaml (noticias.habilitado).")
    typer.echo(reporte_noticias(ctx.noticias.analizar(simbolo)))


@app.command()
def resultados(
    simbolo: str,
    fecha: str | None = typer.Option(None, "--fecha", help="Presentación más cercana a esta fecha (AAAA-MM-DD)."),
    explicar: bool = typer.Option(True, "--explicar/--sin-explicar", help="Agregar el resumen para aprender."),
) -> None:
    """Análisis de la última presentación de resultados de una empresa."""
    from datetime import date as _date

    from monitor_mercado.resultados.reporte import explicacion_resultados, reporte_resultados

    ctx = _contexto()
    try:
        r = ctx.resultados.analizar(simbolo, _date.fromisoformat(fecha) if fecha else None)
    except ErrorDatos as e:
        _salir_con_error(f"No se pudo analizar: {e}")
    typer.echo(reporte_resultados(r))
    if explicar:
        typer.echo("\n" + explicacion_resultados(r))


@app.command()
def calendario() -> None:
    """Próximas presentaciones de resultados de las empresas que seguís."""
    from monitor_mercado.resultados.reporte import texto_calendario

    ctx = _contexto()
    seguidas = ctx.resultados.repo.seguidas()
    typer.echo(texto_calendario(ctx.resultados.proximas(seguidas), seguidas))


@app.command()
def seguir(simbolo: str) -> None:
    """Empezar a seguir los resultados de una empresa."""
    ctx = _contexto()
    simbolo = ctx.buscador().resolver(simbolo)
    try:  # se verifica que el símbolo exista antes de agregarlo
        ctx.proveedor.cotizacion(simbolo)
    except ErrorDatos:
        _salir_con_error(ctx.buscador().mensaje_no_encontrado(simbolo))
    nuevo = ctx.resultados.repo.seguir(simbolo)
    typer.echo(f"Ahora seguís {simbolo.upper()}." if nuevo else f"Ya seguías {simbolo.upper()}.")


@app.command()
def dejar(simbolo: str) -> None:
    """Dejar de seguir los resultados de una empresa."""
    ctx = _contexto()
    ok = ctx.resultados.repo.dejar(simbolo)
    typer.echo(f"Dejaste de seguir {simbolo.upper()}." if ok else f"No seguías {simbolo.upper()}.")


@app.command()
def seguidas() -> None:
    """Empresas cuyos resultados seguís."""
    ctx = _contexto()
    typer.echo(", ".join(ctx.resultados.repo.seguidas()) or "Ninguna.")


@app.command("actualizar-sectores")
def actualizar_sectores() -> None:
    """Descarga sector, industria y múltiplos de toda la watchlist (para elegir pares)."""
    from monitor_mercado.resultados.valuacion import CacheInfo

    ctx = _contexto()
    cache = CacheInfo(ctx.cfg.rutas.ruta_cache_info(), ctx.resultados.fuente)
    simbolos = [s for s in ctx.cfg.watchlist_completa if not s.startswith("^")]
    typer.echo(f"Consultando {len(simbolos)} empresas (tarda unos minutos)...")
    for s in simbolos:
        try:
            i = cache.obtener(s)
            typer.echo(f"  {s:10} {i.get('sector') or '-'} / {i.get('industry') or '-'}")
        except ErrorDatos as e:
            typer.echo(f"  {s:10} error: {e}")


@app.command()
def backtest(
    simbolo: str,
    explicar: bool = typer.Option(True, "--explicar/--sin-explicar", help="Agregar el resumen para aprender."),
) -> None:
    """Prueba la señal técnica contra el pasado (con costos y walk-forward)."""
    from monitor_mercado.backtest.reporte import explicacion_backtest, grafico_backtest, reporte_backtest

    ctx = _contexto()
    try:
        r = ctx.backtest.correr(simbolo)
    except ErrorDatos as e:
        _salir_con_error(f"No se pudo hacer el backtest: {e}")
    typer.echo(reporte_backtest(r))
    if explicar:
        typer.echo("\n" + explicacion_backtest(r))
    typer.echo(f"\nGráfico: {grafico_backtest(r, ctx.cfg.rutas.ruta_graficos())}")


@app.command("backtest-watchlist")
def backtest_watchlist(
    completa: bool = typer.Option(False, "--completa", help="Usar la watchlist completa."),
) -> None:
    """Backtest de todos los activos de la watchlist y conclusión general."""
    from monitor_mercado.backtest.reporte import resumen_backtests

    ctx = _contexto()
    simbolos = ctx.cfg.watchlist_completa if completa else ctx.cfg.watchlist_activa
    typer.echo(f"Corriendo el backtest de {len(simbolos)} activos...\n")
    typer.echo(resumen_backtests(*ctx.backtest.correr_varios(simbolos)))


@app.command()
def cartera() -> None:
    """Estado de tu cartera: ganancia o pérdida de cada posición y del total."""
    from monitor_mercado.cartera.reporte import texto_cartera

    ctx = _contexto()
    estado = ctx.cartera.estado()
    typer.echo(texto_cartera(estado, ctx.rendimiento(estado)))


@app.command()
def preguntar(pregunta: list[str] = typer.Argument(..., help="La pregunta, en lenguaje natural.")) -> None:
    """Pregunta en lenguaje natural (usa la API de Claude). Ej.: monitor preguntar ¿cómo me fue esta semana?"""
    ctx = _contexto()
    typer.echo(ctx.asistente.responder(" ".join(pregunta)))


@app.command()
def estres() -> None:
    """Prueba de estrés: pérdida estimada si el mercado cae 10/20/30% o el dólar sube 30%."""
    from monitor_mercado.riesgo.reporte import texto_estres

    ctx = _contexto()
    try:
        typer.echo(texto_estres(ctx.estres.correr()))
    except Exception as e:  # noqa: BLE001
        _salir_con_error(f"No se pudo correr la prueba de estrés: {e}")


@app.command()
def dividendos() -> None:
    """Dividendos de tu cartera: próximos cobros, cobrados en el último año y rendimiento total."""
    from monitor_mercado.dividendos.reporte import texto_dividendos

    ctx = _contexto()
    try:
        resumen = ctx.dividendos.resumen()
    except Exception as e:  # noqa: BLE001
        _salir_con_error(f"No se pudieron consultar los dividendos: {e}")
    typer.echo(texto_dividendos(resumen, ctx.rendimiento(ctx.cartera.estado())))


@app.command("resumen-dia")
def resumen_dia(
    enviar: bool = typer.Option(False, "--enviar", help="Mandarlo también por Telegram."),
    sin_noticias: bool = typer.Option(False, "--sin-noticias", help="Más rápido: sin buscar noticias."),
) -> None:
    """Resumen de cierre de tu cartera (el mismo que llega automáticamente)."""
    from monitor_mercado.cartera.reporte import texto_resumen_dia

    ctx = _contexto()
    resumen = ctx.cartera.resumen_dia(not sin_noticias)
    texto = texto_resumen_dia(resumen, ctx.cfg.cartera.umbral_movimiento, ctx.rendimiento(resumen.estado))
    typer.echo(texto)
    if enviar and ctx.secretos.telegram_configurado:
        from monitor_mercado.notificaciones.telegram_bot import partir_mensaje

        for parte in partir_mensaje(texto):
            enviar_mensaje(ctx.secretos.telegram_bot_token.get_secret_value(),  # type: ignore[union-attr]
                           ctx.secretos.telegram_chat_id, parte)  # type: ignore[arg-type]
        typer.echo("\nEnviado por Telegram.")


def _crear_stop(simbolo: str, porcentaje: float, tipo_txt: str) -> None:
    from monitor_mercado.stops.modelos import TipoStop
    from monitor_mercado.stops.reporte import mensaje_creado
    from monitor_mercado.stops.servicio import ErrorStop

    ctx = _contexto()
    tipo = TipoStop.STOP_LOSS if tipo_txt == "stop" else TipoStop.TRAILING
    try:
        estado = ctx.stops.crear(ctx.buscador().resolver(simbolo), tipo, porcentaje)
    except (ErrorStop, ErrorDatos) as e:
        _salir_con_error(f"No se pudo crear el stop: {e}")
    typer.echo(mensaje_creado(estado))


@app.command()
def stop(
    simbolo: str,
    porcentaje: float = typer.Argument(..., help="Caída desde tu precio de compra, en % (ej. 10)."),
) -> None:
    """Stop-loss: avisa si una posición cae X% desde tu precio de compra."""
    _crear_stop(simbolo, porcentaje, "stop")


@app.command()
def trailing(
    simbolo: str,
    porcentaje: float = typer.Argument(..., help="Caída desde el máximo, en % (ej. 8)."),
) -> None:
    """Trailing stop: avisa si una posición cae X% desde su máximo desde que la tenés."""
    _crear_stop(simbolo, porcentaje, "trailing")


@app.command()
def stops() -> None:
    """Lista tus stops con el precio actual y cuánto le falta a cada uno."""
    from monitor_mercado.stops.reporte import texto_stops

    ctx = _contexto()
    typer.echo(texto_stops(ctx.stops.estados()))


@app.command("borrar-stop")
def borrar_stop(id_stop: int = typer.Argument(..., help="ID del stop (ver 'monitor stops').")) -> None:
    """Borra un stop."""
    ctx = _contexto()
    if not ctx.stops.borrar(id_stop):
        _salir_con_error(f"No existe el stop #{id_stop}.")
    typer.echo(f"Stop #{id_stop} borrado.")


@app.command()
def tamano(
    simbolo: str,
    entrada: float = typer.Option(..., "--entrada", "-e", help="Precio de entrada (moneda del activo)."),
    stop_: float = typer.Option(..., "--stop", "-s", help="Precio del stop (moneda del activo)."),
    riesgo: str = typer.Option(..., "--riesgo", "-r", help="'1%' del capital o un monto en USD (ej. 500)."),
    capital: float | None = typer.Option(None, "--capital", "-c", help="Capital en USD (por defecto, tu cartera)."),
) -> None:
    """Calculadora de tamaño de posición: cuántas acciones comprar según tu riesgo."""
    from monitor_mercado.riesgo.reporte import texto_tamano
    from monitor_mercado.riesgo.tamano import parsear_tamano

    def texto(x: float) -> str:  # con coma decimal: "820.125" se leería como miles
        return f"{x}".replace(".", ",")

    ctx = _contexto()
    args = [ctx.buscador().resolver(simbolo), "entrada", texto(entrada), "stop", texto(stop_), "riesgo", riesgo]
    if capital is not None:
        args += ["capital", texto(capital)]
    try:
        typer.echo(texto_tamano(ctx.tamano.calcular(parsear_tamano(args))))
    except (ErrorFormato, ValueError, ErrorDatos) as e:
        _salir_con_error(f"No se pudo calcular: {e}")


@app.command()
def rebalanceo() -> None:
    """Qué comprar o vender para volver a los pesos objetivo de config.yaml (solo sugiere)."""
    from monitor_mercado.cartera.reporte import texto_rebalanceo

    ctx = _contexto()
    typer.echo(texto_rebalanceo(ctx.cartera.rebalanceo()))


def _registrar(datos: list[str], tipo_txt: str) -> None:
    from monitor_mercado.diario.calculo import ErrorDiario
    from monitor_mercado.diario.modelos import TipoMovimiento
    from monitor_mercado.diario.parser import parsear_movimiento
    from monitor_mercado.diario.reporte import texto_registrado

    ctx = _contexto()
    tipo = TipoMovimiento.COMPRA if tipo_txt == "compre" else TipoMovimiento.VENTA
    if datos:
        datos = [ctx.buscador().resolver(datos[0]), *datos[1:]]
    try:
        typer.echo(texto_registrado(ctx.diario.registrar(tipo, parsear_movimiento(datos))))
    except (ErrorFormato, ErrorDiario) as e:
        _salir_con_error(str(e))


@app.command()
def compre(
    datos: list[str] = typer.Argument(..., help="SIMBOLO CANTIDAD PRECIO [comision X] [fecha AAAA-MM-DD] [nota TEXTO]"),
) -> None:
    """Registra una compra en el diario. Ej.: monitor compre AAPL 10 180,5 nota soporte"""
    _registrar(datos, "compre")


@app.command()
def vendi(
    datos: list[str] = typer.Argument(..., help="SIMBOLO CANTIDAD PRECIO [comision X] [fecha AAAA-MM-DD] [nota TEXTO]"),
) -> None:
    """Registra una venta en el diario. Ej.: monitor vendi AAPL 5 210"""
    _registrar(datos, "vendi")


@app.command()
def diario(simbolo: str | None = typer.Argument(None, help="Solo las operaciones de este símbolo.")) -> None:
    """Tus operaciones, resultado realizado y no realizado, aciertos, mejores y peores."""
    from monitor_mercado.notificaciones.telegram_bot import texto_diario_completo

    ctx = _contexto()
    typer.echo(texto_diario_completo(ctx, simbolo.upper() if simbolo else None))


@app.command("editar-op")
def editar_op(
    id_mov: int = typer.Argument(..., help="ID de la operación (ver 'monitor diario')."),
    campo: str = typer.Argument(..., help="fecha, simbolo, cantidad, precio, comision, moneda o nota."),
    valor: list[str] = typer.Argument(..., help="Nuevo valor."),
) -> None:
    """Corrige un campo de una operación del diario."""
    from monitor_mercado.diario.calculo import ErrorDiario
    from monitor_mercado.diario.parser import parsear_edicion
    from monitor_mercado.diario.reporte import linea_movimiento

    ctx = _contexto()
    try:
        mov = ctx.diario.editar(*parsear_edicion([str(id_mov), campo, *valor]))
    except (ErrorFormato, ErrorDiario) as e:
        _salir_con_error(str(e))
    except KeyError:
        _salir_con_error(f"No existe la operación #{id_mov}.")
    typer.echo("Operación corregida:\n" + linea_movimiento(mov))


@app.command("borrar-op")
def borrar_op(id_mov: int = typer.Argument(..., help="ID de la operación (ver 'monitor diario').")) -> None:
    """Borra una operación del diario."""
    from monitor_mercado.diario.calculo import ErrorDiario

    ctx = _contexto()
    try:
        ok = ctx.diario.borrar(id_mov)
    except ErrorDiario as e:
        _salir_con_error(f"No se puede borrar: {e}")
    if not ok:
        _salir_con_error(f"No existe la operación #{id_mov}.")
    typer.echo(f"Operación #{id_mov} borrada.")


@app.command("importar-diario")
def importar_diario() -> None:
    """Carga las posiciones de mi_cartera.csv en el diario como compras (no duplica)."""
    from monitor_mercado.notificaciones.telegram_bot import texto_importacion

    ctx = _contexto()
    ruta = ctx.cfg.cartera.ruta()
    if not ruta.exists():
        _salir_con_error(f"No encontré {ruta}.")
    typer.echo(texto_importacion(*ctx.diario.importar_cartera(ruta)))


@app.command()
def glosario(termino: str | None = typer.Argument(None, help="Término a buscar (ej. rsi).")) -> None:
    """Definiciones de los términos que usa el sistema."""
    typer.echo(texto_glosario(termino))


@app.command()
def resumen(
    completa: bool = typer.Option(False, "--completa", help="Usar la watchlist completa."),
) -> None:
    """Señal técnica de todos los activos de la watchlist."""
    ctx = _contexto()
    simbolos = ctx.cfg.watchlist_completa if completa else ctx.cfg.watchlist_activa
    analisis, errores = ctx.tecnico.resumen(simbolos)
    typer.echo(reporte_resumen(analisis, errores))


@app.command()
def descargar(
    completa: bool = typer.Option(False, "--completa", help="Usar la watchlist completa."),
) -> None:
    """Descarga o actualiza el historial de precios de la watchlist."""
    ctx = _contexto()
    simbolos = ctx.cfg.watchlist_completa if completa else ctx.cfg.watchlist_activa
    m = ctx.cfg.monedas
    simbolos = list(dict.fromkeys([*simbolos, m.ccl_accion_local, m.ccl_adr]))  # para el CCL
    typer.echo(f"Descargando {len(simbolos)} símbolos (la primera vez tarda un poco)...\n")
    for s, estado in ctx.tecnico.almacen.actualizar_varios(simbolos).items():
        typer.echo(f"  {'✅' if estado.startswith('ok') else '❌'} {s:10} {estado}")
    typer.echo(f"\nDatos guardados en: {ctx.tecnico.almacen.carpeta}")


@app.command()
def bot() -> None:
    """Arranca el bot y la revisión periódica (dejalo corriendo)."""
    from monitor_mercado.notificaciones.telegram_bot import construir_bot

    ctx = _contexto()
    try:
        aplicacion = construir_bot(ctx)
    except RuntimeError as e:
        _salir_con_error(str(e))
    typer.echo("Bot corriendo. Cerrá esta ventana o apretá Ctrl+C para detenerlo.")
    aplicacion.run_polling()


@app.command()
def formato_alerta() -> None:
    """Muestra el formato para crear alertas."""
    typer.echo(AYUDA_FORMATO)


if __name__ == "__main__":
    app()
