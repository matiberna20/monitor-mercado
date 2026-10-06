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
    ctx = _contexto()
    disparos = ctx.servicio.revisar(forzar=forzar)
    for d in disparos:
        texto = formato.mensaje_disparo(d)
        typer.echo(texto + "\n")
        if ctx.secretos.telegram_configurado:
            try:
                enviar_mensaje(
                    ctx.secretos.telegram_bot_token.get_secret_value(),  # type: ignore[union-attr]
                    ctx.secretos.telegram_chat_id,  # type: ignore[arg-type]
                    texto,
                )
            except Exception as e:  # noqa: BLE001
                log.error("No se pudo enviar el aviso por Telegram: %s", e)
    typer.echo(formato.mensaje_revision(len(disparos)))


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
    typer.echo(texto_cartera(ctx.cartera.estado()))


@app.command("resumen-dia")
def resumen_dia(
    enviar: bool = typer.Option(False, "--enviar", help="Mandarlo también por Telegram."),
    sin_noticias: bool = typer.Option(False, "--sin-noticias", help="Más rápido: sin buscar noticias."),
) -> None:
    """Resumen de cierre de tu cartera (el mismo que llega automáticamente)."""
    from monitor_mercado.cartera.reporte import texto_resumen_dia

    ctx = _contexto()
    texto = texto_resumen_dia(ctx.cartera.resumen_dia(not sin_noticias), ctx.cfg.cartera.umbral_movimiento)
    typer.echo(texto)
    if enviar and ctx.secretos.telegram_configurado:
        from monitor_mercado.notificaciones.telegram_bot import partir_mensaje

        for parte in partir_mensaje(texto):
            enviar_mensaje(ctx.secretos.telegram_bot_token.get_secret_value(),  # type: ignore[union-attr]
                           ctx.secretos.telegram_chat_id, parte)  # type: ignore[arg-type]
        typer.echo("\nEnviado por Telegram.")


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
