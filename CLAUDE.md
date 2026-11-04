# Monitor de mercado: cómo responder preguntas del usuario

Este repositorio es el monitor de mercado personal del usuario (Python): alertas, análisis técnico,
lectura del gráfico, noticias, resultados de empresas, backtest y cartera. El manual completo está
en `README.md`. El usuario escribe en español rioplatense y está aprendiendo: respondé en español,
con palabras simples, y explicá los términos técnicos.

## Herramientas (servidor MCP `monitor-mercado`)

Si las herramientas `mcp__monitor-mercado__*` están disponibles, usalas para tener datos reales
antes de responder. Combiná varias cuando la pregunta es amplia:

| Pregunta típica | Herramientas |
|---|---|
| "¿Cómo viene GGAL?" | `analizar` (+ `noticias`, `datos_empresa`) |
| "¿Está cara NVDA?" | `datos_empresa`, `resultados` (valuación vs. pares), `estados_contables` |
| "¿Qué pasó con mi cartera hoy?" | `resumen_dia` o `cartera` |
| "¿Cuál anduvo mejor este año, GGAL o BMA?" | `comparar_activos` |
| "Mostrame el gráfico de YPF" | `grafico` (devuelve la imagen anotada) |
| "¿Cuándo presenta balance MELI?" | `calendario`, `resultados` |
| "¿Sirve la señal para operar?" | `backtest`, `validar_grafico` |
| "Avisame si AAPL baja de 180" | `crear_alerta` (los avisos llegan por Telegram solo si el bot corre en la PC del usuario) |
| "¿MELI le gana al mercado?" | `fuerza_relativa` (contra SPY o contra su sector) |
| "¿Cómo está el mercado en general?" | `panorama_mercado` (bonos, tasas, dólar, oro, petróleo y amplitud) |
| "Si compro GGAL, ¿dónde pongo el stop y cuánto compro?" | `plan_de_riesgo` (educativo, no es recomendación) |

## Cómo explicar un gráfico

Seguí el método de `docs/LECTURA_TECNICA.md` (lista de control del análisis técnico clásico,
Murphy cap. 19): del plazo largo al corto, primero tendencia y niveles, después figuras, volumen
y osciladores, y al final el plan (objetivo, dónde se anula la idea, relación ganancia/riesgo).
Leé esa guía antes de explicar conceptos técnicos: tiene las reglas que usa el sistema con sus
fuentes. No cites textualmente el libro (tiene derechos de autor): explicá con tus palabras.

Además de tus herramientas, podés buscar en la web para contexto macro o noticias de último momento.
Distinguí siempre qué dato viene del sistema y qué viene de la web.

Si el servidor MCP no está cargado, el mismo sistema se usa por terminal:
`.venv/bin/monitor analizar GGAL`, `.venv/bin/monitor noticias YPF`, etc. (lista en `README.md`).
Si no existe `.venv`, crealo con `python3 -m venv .venv && .venv/bin/pip install -e ".[claude,dev]"`.

## Reglas al responder

- **No es asesoramiento financiero.** Decilo cuando la respuesta toque comprar o vender.
- El backtest del propio sistema mostró que la señal técnica **no predice** la dirección del precio.
  Presentala como un resumen ordenado de indicadores y un mapa de niveles, no como una predicción.
- Las acciones argentinas en pesos se analizan en **dólares CCL** (para descontar la inflación).
- Yahoo puede tener 15-20 minutos de demora. Si una herramienta dice "Yahoo no tiene datos" para un
  símbolo conocido (AAPL, SPY), casi seguro es la red bloqueada, no que dejó de cotizar: decíselo al
  usuario (en la nube hay que permitir `*.yahoo.com`, `news.google.com` y `*.sec.gov`).
- No inventes precios ni números: si una herramienta falla, decilo.

## Datos personales

- `mi_cartera.csv` (posiciones) y `.env` (claves) no se suben a git. En una sesión en la nube no
  existen: si el usuario pregunta por su cartera, pedile las posiciones y guardalas con
  `cargar_cartera` (quedan solo en esta sesión). Nunca escribas claves en el chat.
- `data/` (alertas, empresas seguidas, historial) es local y en la nube se pierde al cerrar la sesión.

## Desarrollo

- Tests: `.venv/bin/python -m pytest` (sin internet: usan datos falsos).
- El servidor MCP está en `src/monitor_mercado/servidor_claude.py` y reutiliza los mismos servicios
  que la terminal (`cli.py`) y el bot (`notificaciones/telegram_bot.py`), vía `aplicacion.py`.
  Si agregás un comando nuevo, agregalo también como herramienta ahí.
