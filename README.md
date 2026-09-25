# Monitor de mercado

Sistema personal en Python para seguir activos financieros. Se construye por etapas:

| Etapa | Contenido | Estado |
|---|---|---|
| 1 | Alertas de precio por Telegram | ✅ Lista para probar |
| 2 | Datos históricos y análisis técnico | Pendiente |
| 3 | Noticias con puntaje de sentimiento | Pendiente |
| 4 | Análisis de resultados de empresas | Pendiente |
| 5 | Backtesting | Pendiente |

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
SIMBOLO compra|venta sube|baja|var+|var- VALOR [ars] [repetir]
```

| Ejemplo | Significado |
|---|---|
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
│   ├── notificaciones/      bot de Telegram y formato de mensajes
│   └── cli.py               comandos de terminal
├── tests/                   tests automáticos (pytest)
├── data/                    base SQLite (se crea sola)
└── logs/                    monitor.log
```
