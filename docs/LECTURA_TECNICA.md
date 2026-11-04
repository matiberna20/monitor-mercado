# Guía de lectura técnica

Resumen de los criterios de análisis técnico clásico que usa el monitor, escrito con palabras
propias a partir de John J. Murphy, *Análisis técnico de los mercados financieros* (el capítulo
va entre paréntesis). El libro **no** está en el repositorio: esto es una guía de trabajo, no una
copia.

Sirve para dos cosas:
1. Documentar qué reglas están programadas en `src/monitor_mercado/tecnico/` (`lectura.py` y
   `complementos.py`).
2. Darle a Claude un método para explicar un gráfico cuando el usuario pregunta.

> El backtest del propio sistema mostró que la **dirección** que surge de estas reglas no anticipa
> el movimiento de las semanas siguientes mejor que el azar. Lo valioso es el **mapa**: dónde
> están los niveles, qué invalida una idea y cuánto se arriesga. Explicalo siempre así.

---

## 1. Lista de control para leer un gráfico (cap. 19)

Del plazo largo al corto, y de lo principal a lo secundario:

1. **Contexto:** ¿qué hace el mercado en general y el sector? → `panorama_mercado`, `fuerza_relativa`.
2. **Gráfico semanal y de largo plazo:** ¿la tendencia principal sube, baja o va de costado? → "Tendencia principal" y "Gráfico semanal" en `grafico`/`analizar`.
3. **Tres grados de tendencia:** principal (meses), intermedia (3 semanas a 3 meses), corta (días).
4. **Soportes y resistencias** clave, números redondos, cambio de rol de los niveles.
5. **Líneas de tendencia y canales:** ¿están validadas (3 toques)? ¿se rompieron?
6. **Volumen:** ¿confirma? (más volumen a favor de la tendencia, OBV acompañando).
7. **Retrocesos:** ¿dónde caen el 38%, 50% y 62% del último tramo?
8. **Huecos (gaps):** ¿de qué tipo son? ¿siguen abiertos?
9. **Figuras de giro o de continuación** y su objetivo medido.
10. **Medias móviles** (50/200 días, 10/40 semanas) y regla de las 4 semanas.
11. **Osciladores** (RSI, estocástico, MACD): sobrecompra/sobreventa y divergencias, siempre
    subordinados a la tendencia.
12. **Régimen:** ¿hay tendencia o rango? (ADX). Define qué herramientas creer.
13. **Velas y días de giro** como señales de corto plazo.
14. **Plan:** ¿cuál es el objetivo, dónde se anula la idea, cuánto se arriesga, la relación
    ganancia/riesgo llega a 3 a 1? → `plan_de_riesgo`.

Para cerrar, conviene cruzar con lo fundamental (cap. 19): ¿qué tendría que pasar en la empresa
para justificar lo que muestra el gráfico? ¿Cómo reaccionó el precio a la última noticia?

---

## 2. Reglas programadas

### Tendencia (caps. 2, 4 y 8)
- Tendencia alcista = máximos y mínimos cada vez más altos; bajista, al revés; lateral si son parejos.
  Una tendencia sigue vigente hasta que da señales claras de terminar.
- Tres grados: principal (gráfico semanal, precio contra la media de 40 semanas), intermedia
  (estructura del zigzag diario) y corta (media de 20 ruedas y momento de 10). Una corrección
  intermedia dentro de una principal alcista suele ser una pausa, no un giro.
- El análisis se hace del plazo largo al corto: el semanal manda sobre el diario.

### Soportes y resistencias (cap. 4)
- Un soporte es un mínimo previo; una resistencia, un máximo previo. Pesan más cuanto más veces
  se respetaron, cuanto más volumen se negoció ahí y cuanto más recientes son.
- **Cambio de rol:** una resistencia superada con claridad pasa a ser soporte, y al revés.
- **Números redondos** (10, 25, 50, 100, múltiplos de 1.000) frenan subas y bajas. Los stops no se
  ponen justo en el número redondo, sino un poco más allá.

### Rupturas y filtros (caps. 4 y 5)
- Una ruptura vale al **cierre**, no por tocar el nivel durante el día.
- Filtro de precio: cerrar al menos **1%** más allá (3% para niveles de largo plazo), o filtro de
  tiempo: **dos cierres seguidos** del otro lado. Reduce las rupturas falsas.
- Una ruptura al alza necesita volumen. A la baja, el volumen ayuda pero no es imprescindible.

### Líneas de tendencia y canales (cap. 4)
- Con dos mínimos ascendentes se traza una línea tentativa; un **tercer toque la valida**.
- Cuanto más tiempo y más toques, más importante es, y más significativa su ruptura.
- Una línea demasiado empinada no se sostiene: su ruptura suele ser solo un ajuste a una
  tendencia más lenta.
- Una línea rota cambia de rol (el soporte pasa a resistencia).
- La línea paralela forma un canal. No llegar al borde del canal es una señal de debilidad.

### Retrocesos (caps. 4 y 13)
- Las correcciones suelen devolver entre un tercio y dos tercios del tramo anterior; el 50% es
  el más común. Los de Fibonacci son 38,2% y 61,8%.
- Si la corrección pasa del 66%, aumentan las chances de que sea un cambio de tendencia.

### Huecos (cap. 4)
- **De separación:** al salir de un rango o una figura, con volumen alto. No suele cerrarse.
- **De escape o de medida:** en plena tendencia, cerca de la mitad del movimiento.
- **De agotamiento:** después de un movimiento largo, y el precio lo cierra a los pocos días.
- **Isla de giro:** un hueco en un sentido y otro en el contrario dejan unas ruedas aisladas.
- Un cierre que rellena un hueco alcista es señal de debilidad.

### Días de giro (caps. 4 y 8)
- Día de giro bajista: marca un máximo nuevo y cierra debajo del cierre anterior (el alcista es al
  revés). Pesa más si es día externo y con volumen alto. El giro semanal pesa más que el diario.

### Figuras de giro (cap. 5)
- Necesitan una **tendencia previa** que dar vuelta.
- Se confirman recién con el cierre más allá de la línea cuello (con filtro). Antes de eso, un
  rebote en un máximo anterior es normal y **no** es un doble techo.
- Entre los dos techos o pisos de una figura doble debería haber al menos ~1 mes.
- En los **pisos**, el aumento de volumen en la ruptura es imprescindible; en los techos, el
  volumen tiende a bajar en cada máximo sucesivo.
- El objetivo medido (altura de la figura proyectada desde la ruptura) es un **mínimo**. El
  máximo es deshacer toda la tendencia previa. Si cae cerca de un soporte claro, se ajusta a él.
- Es común un retorno a la línea cuello después de la ruptura. Si el precio vuelve a cruzarla con
  claridad, la figura fracasó.
- Figuras: hombro-cabeza-hombro (y su versión invertida), triple techo o piso, doble techo o piso.

### Figuras de continuación (cap. 6)
- Triángulo simétrico: pausa; suele seguir la tendencia previa. La salida suele llegar entre 2/3
  y 3/4 del camino al vértice; si no sale, pierde fuerza.
- Triángulo ascendente: alcista. Descendente: bajista.
- Cuña: líneas que convergen inclinadas. **La ascendente es bajista y la descendente, alcista.**
- Formación expansiva: máximos más altos y mínimos más bajos; mercado nervioso, típica de techos.
- Bandera y banderín: pausa corta (1 a 3 semanas) después de un movimiento casi vertical, con
  **volumen en baja**. Suelen aparecer a mitad del movimiento.
- Rectángulo: rango horizontal; el lado del volumen más fuerte da una pista de la salida.

### Volumen (cap. 7)
- El volumen debería crecer a favor de la tendencia. Precio en máximos con volumen en baja es
  una divergencia. El volumen suele adelantarse al precio.
- **OBV** (volumen acumulado): suma el volumen de los días de suba y resta el de los de baja. Si
  el precio hace un máximo nuevo y el OBV no, es una alerta.
- Clímax de compra o venta: movimiento brusco con volumen enorme al final de una tendencia.

### Medias móviles (cap. 9)
- Siguen la tendencia, no la anticipan. Cortas = señales antes pero más falsas; largas = al revés.
- En acciones: 50 y 200 días, o 10 y 40 semanas. Bollinger: 20 días ± 2 desvíos.
- **Regla de las 4 semanas:** comprar al superar el máximo de 4 semanas y vender al perder el
  mínimo. Simple y de las que mejor resultado dieron en estudios de sistemas.
- No funcionan en mercados laterales (un tercio o más del tiempo).

### Osciladores (cap. 10)
- Son **secundarios**: se leen a favor de la tendencia principal, nunca como excusa para ir en
  contra. Comprar sobreventa en tendencia alcista; vender sobrecompra en bajista.
- RSI: 70/30 (80/20 en tendencias fuertes). La señal más valiosa es la **oscilación fallida**: en
  sobrecompra, un segundo pico más bajo que el primero y la perforación del valle intermedio.
- Estocástico lento (14,3,3): señal cuando %K cruza a %D desde arriba de 80 o desde abajo de 20.
- MACD: el histograma cambia de dirección antes que el cruce de líneas.
- Al **comienzo** de una tendencia nueva los osciladores quedan "sobrecomprados" mucho tiempo: hay
  que ignorarlos. Ganan importancia cuando la tendencia madura.

### Régimen: tendencia o rango (caps. 14 y 15)
- **ADX** (14): subiendo y arriba de 20 = hay tendencia (sirven medias y rupturas). Bajando =
  rango o pausa (sirven osciladores). El ADX dice *si* hay tendencia, no hacia dónde va: eso lo
  dicen +DI y −DI.

### Velas japonesas (cap. 12)
- Siempre con tendencia previa: no hay patrón alcista de giro dentro de una suba.
- Programadas: nube oscura, línea penetrante, estrella vespertina y matutina (de las más
  confiables), doji (lápida, libélula) y tres métodos ascendentes y descendentes.
- Filtro recomendado: un patrón bajista de giro vale más con el estocástico arriba de 80, y uno
  alcista con el estocástico debajo de 20.

### Gestión del riesgo (cap. 16)
- Primero se ubica el stop según el gráfico (detrás de un soporte válido) y **después** se calcula
  la cantidad, para no perder más del 1-2% del capital (el libro tolera hasta 5%).
- No más de 10-15% del capital en un solo activo.
- La ganancia potencial debe ser al menos **3 veces** la pérdida posible: los buenos operadores
  aciertan alrededor del 40% de las veces.
- Comprar caídas en tendencia alcista, sumar solo a lo que gana, cerrar primero lo que pierde.
  Una pérdida del 50% exige ganar 100% para recuperarse.

### Entre mercados y amplitud (caps. 17 y 18)
- Cadena clásica: dólar → materias primas → bonos → acciones. Dólar y oro van al revés; materias
  primas y bonos, al revés; bonos y acciones, juntos (los bonos se adelantan). En deflación, bonos
  y acciones se desacoplan.
- **Fuerza relativa** = precio de A / precio de B. Se elige de arriba hacia abajo: mercado →
  sectores que le ganan al índice → acciones que le ganan a su sector.
- Amplitud: una suba es más sana si la acompañan muchas acciones (igual peso, empresas chicas,
  porcentaje sobre la media de 200, máximos contra mínimos de 52 semanas).

---

## 3. Lo que no se programó (y por qué)

- **Ondas de Elliott:** muy subjetivas; el propio autor dice que funcionan mal en acciones
  individuales. Solo se usan los retrocesos de Fibonacci.
- **Ciclos y fechas de giro:** los largos cambian con el tiempo y las metas "se encuentran después
  del hecho". Como mucho, se usa la idea de que los osciladores miden la mitad del ciclo de 20 ruedas.
- **Puntos y figuras:** útil, pero con datos diarios aporta poco frente a las rupturas con filtro.
- **Interés abierto, compromisos de operadores y Market Profile:** son de futuros o necesitan
  datos intradiarios.
- **Encuestas de sentimiento:** no hay una fuente gratuita confiable.

---

## 4. Vocabulario (español de España → uso en Argentina)

apoyo = soporte · límite de protección = stop · contratación = trading · valores = acciones ·
obligaciones = bonos · mercancías = commodities · IFR = RSI · CDMM = MACD · VTA = OBV ·
hueco = gap · día de cambio = día de giro · banda de fluctuación = rango.
