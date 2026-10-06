# Cómo instalar el Monitor de mercado en otra computadora

Este archivo viene junto con el código completo del proyecto. **No hace falta reconstruir
nada:** el código ya está hecho y probado. Solo hay que instalarlo y cargar las claves.

---

## Instrucciones para Claude (pegale esto al Claude de la otra PC)

> Tengo en esta carpeta el proyecto "Monitor de mercado", un sistema en Python ya terminado
> (alertas de precio por Telegram, análisis técnico, noticias, resultados de empresas y
> backtesting). **No cambies ni reescribas el código.** Solo necesito que lo dejes funcionando
> en esta PC. Leé primero `README.md` y `COMO_INSTALAR_EN_OTRA_PC.md`, y después:
>
> 1. Verificá que haya Python 3.11 o superior instalado (`py --version` o `python --version`).
>    Si no está, decime cómo instalarlo desde python.org (marcando "Add python.exe to PATH").
> 2. Creá el entorno virtual en la carpeta del proyecto: `python -m venv .venv`
> 3. Instalá el proyecto: `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`
> 4. Corré los tests: `.\.venv\Scripts\python.exe -m pytest` — tienen que pasar todos.
> 5. Si no existe el archivo `.env`, copiá `.env.example` como `.env` y ayudame a completar
>    `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` (sección 2 del README). Nunca escribas las
>    claves en el chat ni en otros archivos.
> 6. Revisá `config.yaml`: los campos `sec_contacto` tienen un mail; preguntame si lo cambio.
> 7. Si no existe `mi_cartera.csv`, preguntame si quiero cargar mi cartera. Si digo que sí,
>    copiá `mi_cartera.ejemplo.csv` como `mi_cartera.csv` y ayudame a reemplazar las filas de
>    ejemplo (sección 4f del README). Sin ese archivo, todo lo demás funciona igual.
> 8. Probá el envío con `.\.venv\Scripts\monitor.exe probar-telegram` y después arrancá el bot
>    con `iniciar_monitor.bat`.

---

## Qué trae este paquete

- `src/monitor_mercado/` — todo el código (5 etapas terminadas, más cartera, lectura del
  gráfico y buscador de símbolos).
- `tests/` — tests automáticos.
- `config.yaml` — configuración y watchlist.
- `README.md` — manual completo: instalación, comandos de Telegram y terminal, cómo se calcula
  cada cosa y limitaciones.
- `.env.example` — plantilla de las claves.
- `mi_cartera.ejemplo.csv` — plantilla de la cartera.
- `iniciar_monitor.bat` — arranque con doble clic.

## Qué NO trae (a propósito)

| Qué | Por qué | Qué hacer |
|---|---|---|
| `.env` | Tiene las claves (token de Telegram, API keys). Es secreto. | Crear uno nuevo desde `.env.example`, o pasar el `.env` por un medio privado (no por mail ni chats públicos) |
| `mi_cartera.csv` | Tus posiciones: información financiera personal | Crearlo desde `mi_cartera.ejemplo.csv`, o copiar el de la PC original por un medio privado |
| `.venv/` | El entorno de Python no se puede copiar entre PCs | Se crea con los pasos 2 y 3 |
| `data/` | Base de datos con las alertas creadas, historial de precios y gráficos | Se crea sola. Si querés las mismas alertas, copiá la carpeta `data/` de la PC original |
| `logs/` | Registros de esta PC | Se crea sola |

## ⚠️ Importante: un bot, una PC a la vez

Si las dos computadoras usan **el mismo token de Telegram**, no pueden tener el bot corriendo
al mismo tiempo: Telegram le entrega cada mensaje a una sola y aparecen errores de "Conflict".
Opciones:

- Usar el bot en una sola PC por vez, o
- Crear **otro bot** con @BotFather para la segunda PC (otro token), o
- Si el proyecto es para otra persona: que cree su propio bot y use su propio chat ID.

## Historial del proyecto

1. **Etapa 1** — Alertas de precio por Telegram (llega / sube / baja / variación %, en USD o ARS,
   con notas y repetición).
2. **Etapa 2** — Historial de precios, indicadores (medias, RSI, MACD, Bollinger, ATR),
   patrones, señal de tendencia, reportes y gráficos.
3. **Etapa 3** — Noticias (Yahoo, Google News, SEC EDGAR), sentimiento opcional con Claude,
   señal final combinada, resumen "para aprender" y glosario.
4. **Etapa 4** — Resultados trimestrales vs. consenso, calendario con avisos, comunicado
   oficial (SEC EDGAR) y valuación vs. pares.
5. **Etapa 5** — Backtesting con costos, walk-forward, bootstrap y poder predictivo.
6. **Cartera** — Valuación de cada posición y resumen de cierre diario por Telegram con noticias.
7. **Lectura del gráfico** — Estructura, soportes y resistencias, figuras, escenarios, velas
   anotadas y validación histórica (`/grafico`).
8. **Buscador de símbolos** — Acepta nombres de empresas y sugiere ante errores de tipeo.

Hoy el análisis con Claude está **desactivado** (`usar_claude: false` en `config.yaml`), así que
no hace falta `ANTHROPIC_API_KEY` para que todo funcione.
