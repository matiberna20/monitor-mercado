# Monitor de mercado

Sistema personal en Python para seguir activos financieros. Se construye por etapas:

| Etapa | Contenido | Estado |
|---|---|---|
| 1 | Alertas de precio por Telegram | ✅ Lista |
| 2 | Datos históricos y análisis técnico | ✅ Lista |
| 3 | Noticias con puntaje de sentimiento | ✅ Lista |
| 4 | Análisis de resultados de empresas | ✅ Lista |
| 5 | Backtesting | ✅ Lista para probar |

> ⚠️ **No es asesoramiento financiero.** Todo lo que produce este sistema es un insumo
> informativo y probabilístico, no una recomendación de inversión. Es un complemento de
> las alertas de TradingView, no un reemplazo.

---

## 1. Instalación

Requisitos: Windows con Python 3.11 o superior (ya está instalado Python 3.12 y Git).

Abrí una terminal (PowerShell) en la carpeta `creando software` y ejecutá:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Esto crea un **entorno virtual** (`.venv`): una copia de Python aislada solo para este
proyecto, para que las librerías no choquen con otros programas. El entorno ya quedó creado,
así que este paso solo hace falta si lo borrás o cambiás de computadora.

Para verificar que todo anda:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

---

## 2. Crear el bot de Telegram (paso a paso)

### 2.1 Crear el bot con BotFather
1. En Telegram buscá **@BotFather** (tiene la tilde azul de verificado).
2. Mandale `/newbot`.
3. Te pide un **nombre** visible, por ejemplo `Mi Monitor de Mercado`.
4. Te pide un **usuario**, que tiene que terminar en `bot`, por ejemplo `jc_monitor_mercado_bot`.
5. BotFather te responde con un **token** parecido a `8123456789:AAH...`. **Es la llave del
   bot: no la compartas ni la subas a internet.**

### 2.2 Cargar el token en el `.env`
1. Copiá el archivo `.env.example` y renombrá la copia como `.env`.
2. Abrilo con el Bloc de notas y pegá el token:
   ```
   TELEGRAM_BOT_TOKEN=8123456789:AAH...
   ```

### 2.3 Averiguar tu chat ID
1. Arrancá el bot: `.\.venv\Scripts\monitor.exe bot`. Va a decir "modo configuración".
2. En Telegram abrí tu bot (buscalo por el usuario que elegiste) y mandale `/chatid`.
3. Te responde con un número. Agregalo al `.env`:
   ```
   TELEGRAM_CHAT_ID=123456789
   ```
4. Cortá el bot (Ctrl+C) y probá el envío:
   ```powershell
   .\.venv\Scripts\monitor.exe probar-telegram
   ```
   Si te llega el mensaje de prueba, ya está configurado.

**Seguridad:** el bot solo responde a tu chat ID. Si otra persona lo encuentra y le
escribe, no recibe respuesta y el intento queda registrado en `logs/monitor.log`.

---

## 3. Configuración (`config.yaml`)

- `modo_watchlist`: `prueba` (10 símbolos) o `completa` (los de tu CSV).
- `alertas.intervalo_minutos`: cada cuánto se consultan los precios (por defecto, 5).
- `alertas.solo_en_horario_de_mercado`: solo consulta cada activo mientras su bolsa está abierta.
- `alertas.enfriamiento_minutos_repetir`: tiempo mínimo entre dos avisos de una alerta repetitiva.
- `monedas.dolar_ars`: `ccl` (por defecto) u `oficial`, para pasar pesos a dólares.

Las claves van **siempre** en `.env`, nunca en `config.yaml`. El `.env` está en `.gitignore`.

---

## 4. Uso

### 4.1 Formato de una alerta

```
SIMBOLO compra|venta llega|sube|baja|var+|var- VALOR [ars] [repetir] [nota TEXTO]
```

| Ejemplo | Significado |
|---|---|
| `AAPL compra llega 300` | Avisame cuando AAPL llegue a US$ 300. La dirección se deduce sola: si hoy está arriba, espera que baje; si está abajo, que suba |
| `NVDA compra baja 200 nota soporte semanal` | Igual que "baja", con un comentario que aparece en el aviso |
| `AAPL compra baja 180` | Avisame si AAPL baja de US$ 180 |
| `NVDA venta sube 250` | Avisame si NVDA sube de US$ 250 |
| `ALUA.BA compra baja 0.45` | Avisame si ALUA vale menos de US$ 0,45 (convertido al CCL) |
| `ALUA.BA compra baja 800 ars` | Avisame si ALUA baja de $ 800 |
| `AAPL venta sube 30.000 ars` | Avisame si el **CEDEAR** de AAPL (AAPL.BA) sube de $ 30.000 |
| `GGAL compra var- 5 repetir` | Avisame **cada vez** que GGAL caiga 5% o más en el día |

- **Moneda:** por defecto, dólares. Las acciones que cotizan en otra moneda se convierten a USD:
  pesos al CCL (GGAL.BA × 10 / GGAL), reales, euros y libras al tipo de cambio de Yahoo.
  Con `ars`, la alerta usa el precio en pesos: el CEDEAR para acciones de EE.UU. y la acción
  local para las argentinas (YPF → YPFD.BA, BRK-B → BRKB.BA).
- **Números:** se aceptan `180,5`, `180.5`, `27.000` y `27.000,50`.
- **Compra/venta:** es una etiqueta para vos (🟢/🔴 en el aviso). No se opera nada.
- **Una vez o repetir:** por defecto la alerta avisa una vez y se desactiva. Con `repetir`
  queda activa: vuelve a avisar solo después de que el precio vuelva a cruzar el umbral y
  haya pasado el tiempo de enfriamiento.
- **Cruce:** si al crear la alerta el precio ya cumple la condición (por ejemplo "baja de 400"
  con AAPL en 335), no avisa enseguida. Queda "en espera" y avisa cuando el precio suba
  por encima de 400 y vuelva a bajar.

### 4.2 Desde Telegram (con el bot corriendo)

| Comando | Qué hace |
|---|---|
| `/alerta AAPL compra baja 180` | Crea una alerta |
| `/alertas` | Lista las alertas activas (`/alertas todas` incluye las cumplidas) |
| `/borrar 3` | Borra la alerta #3 |
| `/precio GGAL` · `/precio AAPL ars` | Precio actual |
| `/revisar` | Revisa las alertas en el momento, aunque el mercado esté cerrado |
| `/ayuda` | Ayuda |

### 4.3 Desde la terminal

```powershell
.\.venv\Scripts\monitor.exe crear AAPL compra baja 180 --nota "zona de soporte"
.\.venv\Scripts\monitor.exe listar
.\.venv\Scripts\monitor.exe borrar 3
.\.venv\Scripts\monitor.exe precio PETR4.SA
.\.venv\Scripts\monitor.exe revisar --forzar
.\.venv\Scripts\monitor.exe validar-watchlist --completa
.\.venv\Scripts\monitor.exe bot
```

### 4.4 Dejarlo corriendo

El bot tiene que estar corriendo para revisar precios y responder comandos. Tenés dos opciones:

- **Manual:** doble clic en `iniciar_monitor.bat`. La ventana tiene que quedar abierta.
- **Automático al prender la PC:** Programador de tareas de Windows → *Crear tarea básica* →
  Desencadenador "Al iniciar sesión" → Acción "Iniciar un programa" → elegí
  `iniciar_monitor.bat`.

Si la computadora se suspende o se apaga, no hay revisiones. Para eso tenés el respaldo de
TradingView.

---

## 4b. Análisis técnico (Etapa 2)

### Lectura del gráfico "como un trader"

| Telegram | Terminal | Qué hace |
|---|---|---|
| `/grafico GGAL` | `monitor grafico GGAL` | Lee el gráfico: estructura, soportes y resistencias, canal, figuras, volumen, escenarios y gráfico de velas anotado |
| `/validar_grafico` | `monitor validar-grafico [--completa]` | Mide si esa lectura acertó la dirección en el pasado |

Qué mira, en el orden en que lo haría un trader:
1. **Giros (zigzag):** los máximos y mínimos que importan. El tamaño mínimo del movimiento se ajusta a
   la volatilidad de cada acción.
2. **Estructura (teoría de Dow):** máximos y mínimos más altos (alcista), más bajos (bajista) o
   mezclados (lateral o compresión). Considera el tramo en curso solo si ya superó el extremo anterior.
3. **Soportes y resistencias:** zonas donde el gráfico giró varias veces. Más toques, más fuerza.
4. **Canal de tendencia:** pendiente mensual y si el precio está cerca del techo o del piso.
5. **Figuras:** doble techo y doble piso, hombro-cabeza-hombro (normal e invertido), triángulos
   ascendente, descendente y simétrico, rango y banderas. Cada una con su línea clave, el
   **objetivo medido** y el **nivel que la invalida**. Se descartan las figuras que el precio ya anuló.
6. **Rupturas** (con o sin volumen), **acumulación o distribución** y **divergencias del RSI**.
7. **Síntesis:** lectura alcista, bajista o lateral con su convicción; escenario alcista, escenario
   bajista y el nivel donde se anula la lectura.

**⚠️ Resultado de la validación (10 activos, 10 años, 2.035 lecturas sin mirar el futuro):** la
dirección de la lectura **no anticipó** el movimiento de las 4 semanas siguientes. Después de una
lectura alcista el precio subió el 56% de las veces; después de una bajista, el 60%; en general, el 58%.
Lo útil de la lectura es el **mapa de niveles**, no la predicción.

### Uso

| Telegram | Terminal | Qué hace |
|---|---|---|
| `/analisis GGAL` | `monitor analizar GGAL` | Reporte completo y gráfico (medias, Bollinger, volumen, RSI, MACD) |
| `/resumen` | `monitor resumen` | Tendencia de toda la watchlist activa, de más alcista a más bajista |
| `/resumen completa` | `monitor resumen --completa` | Lo mismo para los 89 símbolos (tarda más) |
| – | `monitor descargar [--completa]` | Descarga o actualiza el historial |

Los gráficos quedan en `data/graficos/` y los precios históricos en `data/historico/`
(un CSV por activo, que se puede abrir en Excel).

### Cómo se calcula la señal

1. **Datos:** precios diarios de 10 años, ajustados por splits y dividendos.
   **Las acciones argentinas en pesos se pasan a dólares CCL**: en pesos casi todo "sube"
   por la inflación, y eso no es tendencia de la empresa.
2. **Indicadores:** medias móviles de 20/50/200, RSI 14, MACD (12/26/9), Bollinger (20, 2σ),
   ATR, volumen relativo y rendimiento de 3 meses.
3. **Votos:** cada indicador vota de −1 (bajista) a +1 (alcista). Las distancias se miden en
   relación con la volatilidad de cada activo: un 5% es mucho para SPY y poco para NUGT.
4. **Puntaje:** es el promedio ponderado de los votos. Con +0,2 o más la señal es **alcista**;
   con −0,2 o menos, **bajista**; entre ambos valores, **neutral**.
5. **Confianza (0–100):** mide cuánto coinciden los indicadores y si había datos
   suficientes. **No es la probabilidad de que la señal acierte.** Eso lo mide el backtest
   de la Etapa 5.

**Patrones detectados** (en las últimas 5 ruedas): cruce dorado y cruce de la muerte, cruces
del MACD, rupturas de máximos y mínimos de 20 días y de 52 semanas, cierres fuera de las bandas
de Bollinger, compresión de volatilidad, velas envolventes, martillo, estrella fugaz y RSI extremo.

**Listo para machine learning:** la tabla de votos (`tecnico/senal.py → caracteristicas`) se
calcula para cada fecha. Un modelo de ML sería otra clase con los mismos métodos que
`SenalPorReglas`, entrenada sobre esa tabla, sin cambiar el resto del sistema.

### Limitaciones del análisis técnico

- Mira **solo precios pasados**: no sabe de noticias, resultados ni contexto macro
  (eso llega en las Etapas 3 y 4).
- Durante la rueda, la última vela del día está incompleta y cambia hasta el cierre.
- El CCL se calcula con GGAL. Si un día falta ese dato, se usa el del día hábil anterior.
- Las reglas y sus pesos son supuestos razonables, **no están optimizados ni validados** todavía.
  Hasta el backtest, tomá la señal como un resumen ordenado de los indicadores, no como
  una predicción.

---

## 4c. Noticias y sentimiento (Etapa 3)

### Uso

| Telegram | Terminal | Qué hace |
|---|---|---|
| `/noticias YPF` | `monitor noticias YPF` | Titulares de los últimos 7 días, cada uno con su sentimiento y explicación |
| `/analisis YPF` | `monitor analizar YPF` | Suma las noticias y la **señal final** (técnico + noticias) al análisis |
| `/glosario` · `/glosario rsi` | `monitor glosario rsi` | Definiciones de los términos, para aprender |

`/analisis` termina con un **📘 resumen para aprender**. Explica qué es cada indicador y qué
está diciendo hoy, con los números concretos. Lo generan reglas fijas: es gratis y funciona sin
ninguna clave.

### Fuentes

| Fuente | Clave | Qué aporta |
|---|---|---|
| Yahoo Finance (RSS) | no | Titulares por ticker de EE.UU. |
| Google News (RSS) | no | Búsqueda por nombre de empresa: medios argentinos (en español) para `.BA` y ADRs argentinos, brasileños (en portugués) para `.SA` |
| SEC EDGAR | no, pero exige un mail de contacto | Hechos relevantes (8-K) de empresas de EE.UU. Se activa con `noticias.sec_contacto` en `config.yaml` |
| Finnhub, Marketaux, NewsAPI | sí (planes gratuitos) | Más cobertura. Se activan solos al cargar la clave en el `.env` |

No se scrapea ningún sitio (Bloomberg, Reuters, etc.): solo se usan feeds RSS públicos y APIs oficiales.

### Activar el sentimiento con Claude (opcional, hoy desactivado)

**Por defecto está desactivado** (`noticias.usar_claude: false` y `resultados.usar_claude: false`).
Así, las noticias se muestran sin puntaje, la señal final es 100% técnica y `/resultados` da el
link al comunicado oficial para que lo leas vos. Para activarlo, poné esos valores en `true` y
seguí estos pasos:

1. Entrá a **console.anthropic.com** y creá una cuenta.
2. En **Billing**, cargá crédito. Es un servicio **pago por uso**: con unos pocos dólares alcanza
   para mucho tiempo de uso personal (ver costos abajo).
3. En **API Keys**, tocá **Create Key** y copiá la clave (empieza con `sk-ant-`).
4. Abrí el `.env` con el Bloc de notas y pegala después de `ANTHROPIC_API_KEY=`. Guardá.
5. Cerrá y volvé a abrir el bot.

**Costo aproximado:** con el modelo `claude-opus-5-5` y esfuerzo `low`, clasificar los ~25
titulares de un activo cuesta unos pocos centavos de dólar. **Cada noticia se clasifica una
sola vez** y queda guardada: repetir `/noticias` o `/analisis` solo paga las noticias nuevas.
Si querés gastar menos, podés cambiar `noticias.modelo` en `config.yaml` por uno más barato.

### Cómo se calcula

- Claude clasifica cada titular como **positivo, negativo o neutro** según su impacto
  probable sobre el precio de *esa* empresa (una mala noticia para un competidor puede ser
  buena). Para cada uno devuelve un puntaje (−1 a +1), una relevancia (0 a 1), el factor
  que podría mover el precio y una explicación simple.
- **Tono general** = promedio ponderado. Pesan más las noticias relevantes y las recientes:
  una noticia de hace 2 días pesa la mitad que una de hoy.
- **Señal final** = 70% técnica + 30% noticias, como máximo. Si hubo pocas noticias relevantes,
  las noticias pesan menos. Si técnico y noticias se contradicen, **baja la confianza**.

### Limitaciones de las noticias

- El modelo de lenguaje **puede equivocarse** o malinterpretar un titular: leé la nota completa.
- Solo lee **titulares y resúmenes**, no la nota entera.
- Cuando te llega la noticia, muchas veces **el mercado ya la reflejó en el precio**. Por eso
  pesa poco en la señal final.
- Google News puede traer notas que mencionan a la empresa de pasada; la "relevancia"
  intenta filtrarlas.
- `/resumen` sigue siendo solo técnico, para no gastar en clasificar 10 u 89 activos juntos.

---

## 4d. Resultados de empresas (Etapa 4)

### Uso

| Telegram | Terminal | Qué hace |
|---|---|---|
| `/resultados AAPL` | `monitor resultados AAPL` | Último resultado trimestral vs. lo esperado, con explicación para aprender |
| – | `monitor resultados AAPL --fecha 2026-04-30` | Una presentación anterior |
| `/calendario` | `monitor calendario` | Próximas presentaciones de las empresas que seguís |
| `/seguir MELI` · `/dejar MELI` · `/seguidas` | `monitor seguir MELI` … | Qué empresas seguís |
| – | `monitor actualizar-sectores` | Descarga el sector de toda la watchlist, para elegir pares automáticamente |

**Avisos automáticos** (con el bot abierto): cada 2 horas revisa el calendario de las empresas
que seguís. Te avisa **36 horas antes** de cada presentación y, cuando sale el resultado,
**te manda el análisis completo** sin que lo pidas.

### Qué evalúa

1. **Contra lo esperado:** EPS e ingresos vs. el consenso de analistas → *beat / en línea / miss*.
2. **Crecimiento:** interanual (vs. el mismo trimestre del año pasado) y trimestral.
3. **Márgenes:** bruto, operativo y neto, hoy vs. hace un año.
4. **Deuda y caja:** deuda neta, deuda neta / EBITDA y flujo de caja libre.
5. **Reacción del precio:** 1, 3 y 5 ruedas después, descontando lo que hizo el mercado (SPY).
6. **Comunicado oficial** (opcional): Claude lo resume y detecta la **guidance** (si la empresa
   subió o bajó sus proyecciones) y el **tono** de la gerencia.
7. **Valuación:** P/E, EV/EBITDA, precio/valor libro y precio/ventas vs. la mediana de sus pares.
   **Un buen resultado no es lo mismo que una buena compra.**

El **veredicto** (mejor / en línea / peor de lo esperado) es un promedio ponderado de esos
factores. El reporte muestra cada voto. La guidance pesa tanto como la sorpresa, porque el
mercado mira hacia adelante.

### Activar el análisis del comunicado

Necesita dos cosas:
1. `ANTHROPIC_API_KEY` en el `.env` (la misma de la Etapa 3).
2. Un mail de contacto en `config.yaml → resultados.sec_contacto`. La SEC exige que quien
   descarga documentos se identifique; el mail viaja en cada consulta a la SEC.

Cada comunicado se analiza una sola vez y queda guardado.

### Fuentes y limitaciones

| Dato | Fuente | Limitación |
|---|---|---|
| Fecha, EPS estimado y reportado | Yahoo Finance | ALUA.BA casi no tiene cobertura de analistas |
| Consenso de ingresos | Yahoo (solo el próximo trimestre) | El sistema lo **guarda antes** de cada presentación. Para trimestres previos a que empieces a seguir la empresa, no hay dato |
| Estados contables | Yahoo Finance | Aparecen unos días después de la presentación; últimos 5-7 trimestres |
| Comunicado (8-K / 6-K) | SEC EDGAR | Solo empresas que presentan ante la SEC (EE.UU. y ADRs como GGAL, YPF, PBR). No cubre ALUA.BA ni PETR4.SA |
| Múltiplos | Yahoo Finance | Si cotiza en USD pero su balance está en ARS (GGAL, BMA), se omiten los múltiplos que mezclan ambas monedas |

- **Argentina (CNV/Bolsar) y Brasil (CVM/B3)** no ofrecen una API simple. Para las
  empresas con ADR se usa la SEC; para el resto, solo los estados de Yahoo.
- Los balances argentinos están ajustados por inflación (NIC 29), pero Yahoo puede mezclar
  trimestres ajustados y sin ajustar: tomá el crecimiento en pesos con cautela.
- **Datos mensuales:** no se incluyen, porque casi ninguna empresa de la watchlist los publica
  de forma estandarizada.

---

## 4e. Backtesting (Etapa 5)

### Uso

| Telegram | Terminal | Qué hace |
|---|---|---|
| `/backtest SPY` | `monitor backtest SPY` | ¿Seguir la señal le hubiera ganado a comprar y mantener? Con gráfico y explicación |
| `/backtest_resumen` | `monitor backtest-watchlist` | Lo mismo para toda la watchlist, con conclusión general |
| `/backtest_resumen completa` | `monitor backtest-watchlist --completa` | Los 89 símbolos |

### Cómo se prueba (sin hacer trampa)

- **Sin mirar el futuro:** la señal usa datos hasta el cierre del día *t* y la operación se hace en
  la **apertura del día t+1**. Hay un test que lo verifica.
- **Costos:** comisión por mercado (EE.UU. 0,1%, BYMA 0,6%, B3 0,3%, Europa 0,2%) más 0,05% de
  slippage en cada compra y cada venta. Se configuran en `config.yaml → backtest`.
- **Estrategia "solo compra":** compra cuando la señal es alcista, vende y queda en efectivo cuando es
  bajista. Opcionalmente puede ir corto (`permitir_corto: true`).
- **Dos pruebas:**
  1. La señal **tal como la usa el sistema**, sin optimizar nada.
  2. **Walk-forward:** los umbrales se eligen con 3 años y se miden en el año siguiente, que el
     optimizador nunca vio. Después se corre la ventana y se repite. Solo cuentan los años de prueba.
- **Overfitting:** se compara el Sharpe de entrenamiento con el de prueba. Si cae mucho, los
  parámetros aprendieron ruido. También se muestra si los parámetros elegidos son estables.
- **¿Suerte?** Un bootstrap por bloques (2.000 remuestreos) estima la probabilidad de que la
  ventaja sobre comprar y mantener sea azar.
- **Poder predictivo:** correlación entre la señal y el retorno de los 20 días siguientes, y qué
  tan seguido acertó la dirección comparado con el porcentaje de veces que el precio sube en general.

### Resultado (datos al 29/09/2026)

Sobre los 85 activos de la watchlist con al menos 4 años de historia, fuera de muestra y con costos:

- La señal le ganó a comprar y mantener (Sharpe) en **14 de 85**, y en **ninguno** con evidencia
  estadística firme.
- Diferencia típica de Sharpe: **−0,22**. Correlación típica con el retorno de los 20 días siguientes: **−0,08**.
- **Conclusión: la señal técnica NO aporta valor como sistema de compra y venta.** Su única
  ventaja consistente es que **reduce las caídas máximas**, a cambio de rendir menos. Sirve como
  resumen ordenado de los indicadores, no como predicción.

### Sesgos que el backtest no corrige

- **Supervivencia:** la watchlist tiene empresas que hoy existen. Las que quebraron no están, y eso
  favorece a "comprar y mantener".
- **Un solo período:** 10 años son una sola historia de mercado.
- **Diseño de las reglas:** se eligieron conociendo cómo suelen comportarse estos indicadores.
- No incluye impuestos ni el rendimiento del efectivo mientras la estrategia está afuera.
- **Noticias y resultados no se prueban,** porque no hay historial gratuito de noticias clasificadas.

---

## 4f. Tu cartera y el resumen de cierre

### Uso

| Telegram | Terminal | Qué hace |
|---|---|---|
| `/cartera` | `monitor cartera` | Cada posición: precio, variación del día, ganancia/pérdida desde la compra y peso en la cartera |
| `/resumen_dia` | `monitor resumen-dia [--enviar]` | El resumen de cierre, a pedido |

**Automático:** cada día hábil a las **16:20 de Nueva York (17:20 en Argentina)**, con el bot
abierto, llega el resumen de cierre. Trae:
- el valor de la cartera, el resultado del día y el resultado total desde la compra, en % y en US$;
- la variación de los últimos 7 días (desde la segunda semana de uso);
- las 3 mejores y las 3 peores del día, y los movimientos de más de 5%;
- la variación del día de **todas** tus posiciones;
- hasta 8 **noticias importantes** de tus empresas de las últimas 24 horas;
- un aviso si una posición pesa más del 25% de la cartera.

Los fines de semana y los feriados de Wall Street no se manda nada.

### El archivo `mi_cartera.csv`

Está en la carpeta del proyecto y **no se sube a Git**, porque es información personal. Si no
existe (por ejemplo, en otra PC), copiá `mi_cartera.ejemplo.csv` como `mi_cartera.csv`. Se edita con
Excel o con el Bloc de notas:

```
simbolo,cantidad,precio_compra,moneda,fecha_compra,nota
AAPL,120,302.46,USD,,
BTC,100,,USD,,costo no informado por el broker
```

- `precio_compra` es el precio **promedio** por acción. Si lo dejás vacío, la posición se sigue igual
  pero no entra en la ganancia total.
- Se aceptan los símbolos como los muestra el broker (`AAPL.E`, `BRK.B.E`).
- `fecha_compra` (opcional, AAAA-MM-DD) queda guardada para futuras comparaciones.
- Cuando compres o vendas, actualizá el archivo. Los cambios se toman en la siguiente consulta,
  sin reiniciar el bot.

### Cómo se eligen las noticias (sin IA)

1. El titular tiene que nombrar a la empresa o su símbolo.
2. Suman puntos las palabras que suelen mover precios: resultados, guidance, adquisición, demanda,
   cambio de recomendación, dividendos, despidos…
3. Tienen prioridad las acciones que más se movieron en el día.
4. Máximo 2 noticias por empresa. En los ETFs se buscan noticias del tema que siguen (NUGT → mineras
   de oro, SLV → plata, GBTC/BTC → bitcoin).

Son reglas simples: pueden dejar afuera alguna noticia importante.

---

## 4g. Stop-loss y trailing stop

Te avisan por Telegram si una posición de tu cartera cae demasiado. **No venden nada**: son avisos.

| Telegram | Terminal | Qué hace |
|---|---|---|
| `/stop AAPL 10` | `monitor stop AAPL 10` | **Stop-loss:** avisa si AAPL cae 10% desde tu precio de compra |
| `/trailing AAPL 8` | `monitor trailing AAPL 8` | **Trailing stop:** avisa si AAPL cae 8% desde su máximo desde que la tenés |
| `/stops` | `monitor stops` | Lista tus stops con el precio de hoy y cuánto le falta a cada uno |
| `/borrar_stop 3` | `monitor borrar-stop 3` | Borra el stop #3 |

- **Por defecto para toda la cartera:** en `config.yaml → cartera` poné `stop_loss_por_defecto: 15` y/o
  `trailing_por_defecto: 20`. Se aplican a cada posición que no tenga un stop propio. Si borrás uno de
  estos, no se vuelve a crear; si vendés la posición, se borra solo.
- **Un stop de cada tipo por posición:** repetir `/stop AAPL 12` reemplaza el anterior.
- **Funciona como las alertas:** se revisa con el mismo intervalo, solo con el mercado abierto, avisa al
  **cruzar** el nivel (si ya estaba abajo al crearlo, espera a que suba y vuelva a caer), no repite
  mientras el precio sigue abajo y respeta el `enfriamiento_minutos_repetir`. `/revisar` también los revisa.
- **Todo en dólares:** las posiciones en pesos se pasan a USD con el CCL, igual que en `/cartera`.

### Limitaciones de los stops

- El **máximo del trailing** arranca el día que creás el stop (el mayor entre el precio de ese momento y tu
  precio de compra) y se actualiza solo en cada revisión con el mercado abierto. No mira el historial
  anterior, y si el precio sube y baja entre dos revisiones, ese pico no cuenta.
- El stop-loss necesita el **precio de compra**; las posiciones sin costo solo admiten trailing.
- Con precios demorados 15-20 minutos, en una caída rápida el aviso llega cuando el precio ya está más abajo
  del nivel. Para un stop que se ejecute solo, usá la orden stop de tu broker.

---

## 4h. Calculadora de tamaño de posición

Antes de comprar, te dice **cuántas acciones** comprar para que, si el precio toca tu stop, pierdas
exactamente lo que elegiste arriesgar.

| Telegram | Terminal |
|---|---|
| `/tamano AAPL entrada 200 stop 185 riesgo 1%` | `monitor tamano AAPL --entrada 200 --stop 185 --riesgo 1%` |
| `/tamano AAPL entrada 200 stop 185 riesgo 500` | `monitor tamano AAPL -e 200 -s 185 -r 500` |
| `/tamano ALUA.BA entrada 820 stop 760 riesgo 1% capital 20000` | `monitor tamano ALUA.BA -e 820 -s 760 -r 1% -c 20000` |

- **Riesgo:** con `%` es un porcentaje del capital; sin `%`, un monto en dólares.
- **Capital:** por defecto, el valor actual de tu cartera. Con `capital` usás otro monto (en USD).
- **Precios en la moneda del activo,** como en tu broker (pesos para `ALUA.BA`). Se pasan a dólares con el
  CCL o el tipo de cambio de Yahoo, igual que en `/cartera`.
- **Devuelve:** acciones, monto a invertir, pérdida máxima y el peso que tendría ese símbolo en la cartera
  (sumando lo que ya tenías). Avisa si supera el límite de concentración (`cartera.concentracion_maxima`, 25%).

Cuenta: `acciones = riesgo / (entrada − stop)`, redondeado hacia abajo. Si eso cuesta más que el capital,
se calcula con lo que alcanza.

### Limitaciones de la calculadora

- Es solo para **compras** (el stop tiene que estar por debajo de la entrada).
- La pérdida máxima supone que vendés justo en el stop. Si el precio abre con un salto por debajo
  (resultados, noticias con el mercado cerrado), la pérdida real es mayor.
- No descuenta comisiones.
- El peso se calcula sobre el capital (por defecto, el valor de tu cartera hoy), como si la compra se
  hiciera con plata que ya está en la cartera.

---

## 4i. Rebalanceo

Compara los pesos de hoy con los que querés y te dice **qué comprar o vender, y cuánto**, para volver al
objetivo. **No ejecuta nada:** solo sugiere.

| Telegram | Terminal |
|---|---|
| `/rebalanceo` | `monitor rebalanceo` |

Los objetivos van en `config.yaml`:

```yaml
rebalanceo:
  tolerancia: 0.05          # solo avisa si te desviás más de 5 puntos
  objetivos:
    NUGT: 0.20              # un símbolo
    Argentina: 0.25         # un grupo propio
    EE.UU.: 0.50            # el grupo de una bolsa
  grupos:
    Argentina: [GGAL, BMA, YPF, VIST, TS]
```

- Cada objetivo puede ser un **símbolo** o un **grupo**. Los grupos de cada bolsa (`EE.UU.`, `BYMA`, `B3`,
  `Xetra`, `Londres`) existen solos; un símbolo que está en un grupo propio deja de contar en el de su bolsa.
- Lo que **no tiene objetivo no se toca** (el reporte dice cuánto pesa).
- Para los símbolos dice también la cantidad aproximada de acciones; para los grupos, solo el monto (vos
  elegís dentro del grupo).
- Estima las **comisiones** con las de referencia del backtest (`backtest.comisiones`) según la bolsa.

### Limitaciones del rebalanceo

- Usa los precios del momento (con demora) y el CCL para lo que está en pesos.
- No considera impuestos, spread, ni montos mínimos o lotes de cada broker.
- Si un símbolo entra en dos objetivos (por ejemplo, `GGAL` y un grupo que lo incluye), se cuenta dos veces:
  el reporte lo advierte.

---

## 5. Limitaciones (importante)

- **Demora en los precios.** Yahoo Finance (vía `yfinance`) es gratis, pero los precios suelen
  llegar con **15 a 20 minutos de demora**. Además, el sistema revisa cada X minutos. Un
  aviso puede llegar tarde, o no llegar si el precio toca el umbral y vuelve entre dos
  revisiones. Para operaciones sensibles al segundo, usá TradingView o tu broker.
- **yfinance no es una API oficial.** Puede fallar o cambiar sin aviso. El sistema reintenta
  3 veces y registra los errores en `logs/monitor.log`. La estructura permite agregar otra
  fuente (por ejemplo Finnhub) sin tocar el resto.
- **Feriados:** no se contemplan. En un feriado se consulta igual, pero sin generar avisos falsos.
- **CCL calculado:** el CCL se estima con GGAL. Puede diferir levemente del que publican los
  medios.
- **Horario:** solo se considera la rueda regular (sin pre-market ni after-hours).
- **Variación diaria:** se mide en la moneda nativa del activo y no incluye el movimiento
  del tipo de cambio.
- **Aviso perdido si falla Telegram:** si Telegram no responde en 3 intentos, la alerta ya
  quedó marcada como cumplida y el aviso solo queda en `logs/monitor.log`.
- **PC apagada o suspendida:** no hay revisiones y tampoco hay aviso de que el bot estuvo caído.

### Símbolos con problemas en tu watchlist (validado el 25/09/2026)

| Símbolo | Problema | Acción |
|---|---|---|
| `X` (US Steel) | Sin datos en Yahoo: la compró Nippon Steel | Comentado en `config.yaml` |
| `BMWYY` | Yahoo no devuelve datos | Comentado. Alternativa: `BMW.DE` |
| `EA` | Sin operaciones desde el 04/08/2026 | Comentado |
| `ADDDF` | Cotiza, pero con volumen casi nulo (OTC) | Conviene usar `ADDYY` |

Volvé a validar cuando quieras con `monitor validar-watchlist --completa`.

---

## 6. Estructura

```
creando software/
├── config.yaml              configuración (watchlist, intervalos, monedas)
├── .env                     claves (no se sube a git)
├── iniciar_monitor.bat      arranque con doble clic
├── src/monitor_mercado/
│   ├── configuracion.py     carga y valida config.yaml y .env
│   ├── registro.py          logs
│   ├── aviso_legal.py       aviso "no es recomendación"
│   ├── mercados.py          horarios de cada bolsa
│   ├── datos/               precios (yfinance) y conversión de monedas
│   ├── alertas/             modelo, base SQLite, evaluador, parser, servicio
│   ├── tecnico/             historial, indicadores, patrones, señal, reporte, gráfico
│   ├── noticias/            fuentes RSS/API, sentimiento con Claude, agregado, reporte
│   ├── resultados/          calendario, métricas, sorpresas, comunicado, valuación, veredicto
│   ├── backtest/            simulación con costos, walk-forward, bootstrap, reportes
│   ├── cartera/             tu cartera, valuación y resumen de cierre
│   ├── stops/               stop-loss y trailing stop sobre la cartera
│   ├── riesgo/              tamaño de posición y prueba de estrés
│   ├── senal_final.py       combina técnico + noticias
│   ├── explicacion.py       resumen "para aprender" y glosario
│   ├── aplicacion.py        arma todas las piezas (lo usan la terminal y el bot)
│   ├── notificaciones/      bot de Telegram y formato de mensajes
│   └── cli.py               comandos de terminal
├── tests/                   tests automáticos (pytest)
├── data/                    base SQLite (se crea sola)
└── logs/                    monitor.log
```
