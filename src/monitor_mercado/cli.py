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
    typer.echo(reporte_completo(r.tecnico, con_pie=False))
    if r.noticias is not None:
        typer.echo("\n" + reporte_noticias(r.noticias, maximo=5, con_pie=False))
    typer.echo("\n" + linea_senal_final(r.final) + pie_de_mensaje())
    if explicar:
        typer.echo("\n" + explicacion_completa(r.tecnico, r.noticias, r.final))
    if grafico:
        ruta = generar_grafico(r.tecnico, ctx.cfg.rutas.ruta_graficos(), ctx.cfg.tecnico.ruedas_grafico)
        typer.echo(f"\nGráfico: {ruta}")


@app.command()
def noticias(simbolo: str) -> None:
    """Noticias recientes de un activo con su sentimiento."""
    ctx = _contexto()
    if ctx.noticias is None:
        _salir_con_error("Las noticias están desactivadas en config.yaml (noticias.habilitado).")
    typer.echo(reporte_noticias(ctx.noticias.analizar(simbolo)))


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
