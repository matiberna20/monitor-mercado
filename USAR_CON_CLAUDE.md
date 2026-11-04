# Usar el monitor desde Claude

El mismo sistema que usás por Telegram y por la terminal ahora se puede usar **conversando con
Claude**. Claude tiene acceso a todas las funciones del monitor como "herramientas" (por un
servidor MCP) y las combina para responder preguntas en lenguaje natural:

- "¿Cómo viene GGAL? ¿Está cerca de algún soporte?"
- "¿Qué pasó hoy con mi cartera y por qué cayó MELI?"
- "Compará YPF, PBR y XOM en el último año"
- "¿NVDA está cara contra sus pares? Mostrame sus últimos balances"
- "¿Cuándo presentan resultados las empresas que sigo?"
- "Avisame si AAPL baja de 180"

Claude puede sumar lo que sabe y lo que busca en la web (macro, elecciones, tasas) a los datos de
tu sistema, y explicarte cada cosa con más detalle que el bot.

> ⚠️ **No es asesoramiento financiero.** Igual que el bot, es un insumo informativo.

---

## Qué puede hacer Claude con tu monitor

**Lo mismo que el bot** (mismos cálculos, mismo código):

| Bot de Telegram | Herramienta para Claude |
|---|---|
| `/precio` | `precio` |
| `/analisis` | `analizar` (con el gráfico anotado como imagen) |
| `/grafico` · `/validar_grafico` | `grafico` · `validar_grafico` |
| `/resumen` | `resumen_watchlist` |
| `/noticias` | `noticias` |
| `/resultados` · `/calendario` | `resultados` · `calendario` |
| `/seguir` · `/dejar` · `/seguidas` | `seguir_empresa` · `dejar_de_seguir` · `empresas_seguidas` |
| `/backtest` · `/backtest_resumen` | `backtest` · `backtest_watchlist` |
| `/cartera` · `/resumen_dia` | `cartera` · `resumen_dia` |
| `/alerta` · `/alertas` · `/borrar` · `/revisar` | `crear_alerta` · `listar_alertas` · `borrar_alerta` · `revisar_alertas` |
| `/glosario` | `glosario` |

**Datos nuevos** (para responder preguntas más abiertas):

| Herramienta | Qué da |
|---|---|
| `historial_precios` | Tabla de precios diarios o semanales con medias, RSI, MACD, ATR y volumen |
| `datos_empresa` | Ficha: qué hace, capitalización, múltiplos, márgenes, crecimiento, deuda, dividendos, recomendación y precio objetivo de los analistas |
| `estados_contables` | Ingresos, ganancias, caja, deuda y flujo de fondos de los últimos trimestres |
| `comparar_activos` | Rendimiento 1m/3m/6m/1 año/en el año, volatilidad, caída máxima y correlación entre varios activos |
| `dolar_ccl` | Evolución del CCL implícito (GGAL) |
| `buscar_simbolo` | Encuentra el símbolo por el nombre de la empresa |
| `watchlist` · `cargar_cartera` | Ver tus listas · cargar tu cartera pegándola en el chat |

---

## Opción 1: en Claude Code en la nube (claude.ai/code)

El repositorio ya trae todo configurado (`.mcp.json` y `CLAUDE.md`). Hay que ajustar dos cosas
del **entorno** una sola vez (menú del entorno en la barra de título de la sesión → *Edit*):

1. **Acceso a la red:** en *Network access*, agregá en *Allowed domains* (dejando tildado
   *Allow package managers*):
   ```
   *.yahoo.com
   news.google.com
   *.sec.gov
   ```
   Sin esto, Claude no puede bajar precios ni noticias.
2. **Setup script:** reemplazalo por:
   ```bash
   cd /home/user/monitor-mercado && python3 -m venv .venv && .venv/bin/pip install -e ".[claude,dev]"
   ```
   Si no lo cambiás, igual funciona: la primera vez que Claude usa el monitor lo instala solo
   (tarda alrededor de un minuto).

Después abrí una sesión nueva sobre este repositorio y preguntá lo que quieras. Si Claude Code
pregunta si confiás en el servidor MCP `monitor-mercado` del proyecto, aceptá.

**Diferencias con tu PC:**
- La sesión en la nube **no queda prendida**: no hay avisos automáticos por Telegram ni resumen
  de las 17:20. Para eso sigue estando el bot en tu PC.
- Tu `mi_cartera.csv` y tu `.env` **no están en la nube** (no se suben a git, a propósito). Si
  preguntás por tu cartera, Claude te pide las posiciones y las guarda solo para esa sesión.
- Las alertas y empresas seguidas que crees en la nube se pierden al cerrar la sesión.

## Opción 2: en tu PC con Windows

### Con Claude Code (terminal)
En la carpeta del proyecto:
```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[claude,dev]"
claude mcp add monitor-mercado --scope local -- "$PWD\.venv\Scripts\monitor-claude.exe"
```
(El `.mcp.json` del repo usa `sh`, que no existe en Windows; el comando de arriba lo reemplaza
para tu PC.) Ahí sí tenés tu cartera, tu `.env` y tus alertas reales.

### Con Claude Desktop (la aplicación)
1. Instalá el extra: `.\.venv\Scripts\python.exe -m pip install -e ".[claude]"`
2. En Claude Desktop: *Settings → Developer → Edit Config*. Se abre `claude_desktop_config.json`.
3. Pegá esto, cambiando la ruta por la de tu carpeta (con barras dobles `\\`):
   ```json
   {
     "mcpServers": {
       "monitor-mercado": {
         "command": "C:\\Users\\TU_USUARIO\\creando software\\.venv\\Scripts\\monitor-claude.exe"
       }
     }
   }
   ```
4. Cerrá y abrí Claude Desktop. En el chat vas a ver el ícono de herramientas con `monitor-mercado`.

El bot de Telegram y el servidor para Claude pueden estar abiertos al mismo tiempo: usan la misma
base de datos, así que una alerta creada desde Claude la revisa el bot.

---

## Para probar que funciona

Preguntale a Claude: *"Usá el monitor y decime el precio de AAPL"*. Si responde que Yahoo no tiene
datos de AAPL, es la red (ver Opción 1, paso 1), no el programa.
