# Business Algorithms Engine

### Una solicitud. Un precio explicable. El profesional adecuado.

**Por [Nando · Creador de algoritmos de negocio](https://github.com/nandoagentss)**

[![Algorithm checks](https://github.com/nandoagentss/business-algorithms-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/nandoagentss/business-algorithms-engine/actions/workflows/ci.yml)

Las operaciones de servicios concentran decisiones difíciles: cuánto cobrar,
qué perfil necesita cada plaza, quién está disponible y cómo evitar que dos
personas acepten el mismo lugar o que un profesional se reserve dos veces.

Este proyecto convierte esas decisiones en **reglas de dominio ejecutables**, con
catálogo versionado, base de datos SQLite, selección explicable y reservas
transaccionales. Es una implementación pública de referencia con datos sintéticos,
inspirada en problemas de operación de marketplaces de servicios.

## Verlo funcionar

Python 3.11 o posterior. Sin paquetes externos en Linux/macOS con base de zonas horarias.

~~~bash
git clone https://github.com/nandoagentss/business-algorithms-engine.git
cd business-algorithms-engine
python3 engine.py
python3 -m unittest -v
~~~

La demo usa SQLite en memoria y un reloj fijo. No requiere cuenta, credenciales,
servicios de IA ni conexiones a una plataforma real. En Windows, si no hay base
IANA de zonas horarias, instalar el paquete oficial de Python: `pip install tzdata`.

**Resultado del escenario incluido:** dos plazas de staff, cotización sintética
de **246.90 MXN**, dos profesionales distintos reservados y tres eventos
persistidos durante la ejecución (creación más dos reservas). No son tarifas comerciales.

## Del negocio al software

~~~text
Solicitud → Jornada → Catálogo → Cotización
                                     ↓
Eventos ← Reserva atómica ← Aceptación demo ← Pros elegibles
~~~

| Decisión | Variables | Garantía demostrada |
| --- | --- | --- |
| Jornada | Fecha, horario local, duración, anticipación, ubicación y preferencia | Razones explícitas y política identificada |
| Precio | Perfil, horas, jornada, cantidad y catálogo | Centavos exactos, moneda única y versión de tarifa |
| Elegibilidad | Verificación, perfil, ubicación, agenda y reseñas para jornada Pro | Candidatos incompatibles excluidos |
| Orden | Nivel Súper Pro, distancia e identificador | Política determinista visible en código |
| Reserva | Plaza, Pro, versión, agenda y vigencia de cotización | Transacción y revalidación antes de reservar |
| Recuperación | Dueño, clave idempotente, comando y eventos | Reintentos sin duplicar solicitud ni reserva |

El precio se **consulta en una tarifa existente**. No se pide a un modelo de IA
que invente un importe. Súper Pro y la jornada Pro son conceptos distintos:
el primero participa en el orden; la segunda determina una variación de catálogo
y exige reseñas de cinco estrellas sin redondear en esta demo.

## Pruebas que puedes revisar

La suite cubre precisión monetaria, monedas mixtas, catálogo ausente o cambiado,
reintentos, conflictos de idempotencia, horarios, ubicación, elegibilidad,
reseñas, vencimiento y versiones obsoletas.

También ejecuta **carreras reales con dos conexiones a la misma DB SQLite**:

- Dos Pros intentan reservar una plaza: una sola reserva tiene éxito.
- Un Pro intenta reservar plazas solapadas de solicitudes distintas: una sola tiene éxito.
- La DB se reabre para comprobar persistencia y recuperación del resultado original.

[Consultar ejecuciones y resultados públicos](https://github.com/nandoagentss/business-algorithms-engine/actions).

## Leer el código

- [engine.py](engine.py): reglas, esquema SQLite, creación idempotente, matching y reserva.
- [test_engine.py](test_engine.py): escenarios reproducibles y conflictos concurrentes.
- [ci.yml](.github/workflows/ci.yml): pruebas y recorrido completo en GitHub Actions.

Se conserva el snapshot de la cotización. Si el catálogo cambia, la reserva exige
una nueva cotización; no modifica silenciosamente el precio histórico.
El bloqueo `BEGIN IMMEDIATE` serializa las escrituras de la demo y permite verificar
la agenda entre solicitudes antes de reservar.

## Alcance real

**Implementado:** núcleo de negocio, DB SQLite, fixtures, ranking configurable en
código, idempotencia, reservas con control de concurrencia y eventos en la misma
transacción. `Engine(path)` permite usar una DB persistente; las pruebas lo comprueban.

**Simulado:** catálogo, Pros, clasificación, reloj, aceptación y condiciones comerciales.
Las coordenadas se sitúan alrededor de un origen artificial. Los radios, horarios
y tarifas son demostrativos; no son una publicación de la política productiva de Soy Pro.
La distancia es geográfica, no tiempo de traslado. Los intervalos adyacentes son
compatibles en esta demo y no incluyen buffer de viaje.

**Pendiente para una operación pública:** autenticación y autorización por actor,
API, pagos verificados y conciliación, adaptador al catálogo vivo, agenda con
políticas de traslado, cancelaciones, notificaciones, entrega de eventos con
reintentos, observabilidad y pruebas de carga. El registro de eventos es durable;
no existe todavía un despachador a servicios externos. No se afirma escalabilidad
productiva por haber ejecutado esta muestra.

La función `accept_demo` recibe un comando de confianza para probar el motor.
No verifica identidad, consentimiento humano ni pago. Elegir al primer candidato
en el ejemplo no equivale a aceptar un servicio en nombre de una persona real.

## La visión

Desarrollar operaciones autónomas a partir de algoritmos propios del negocio:
reglas precisas, datos confiables y decisiones que se puedan explicar, probar
y recuperar ante fallos. La IA puede ampliar la interfaz y la productividad;
las decisiones críticas requieren contratos y controles explícitos.

Este repositorio permite a colaboradores, clientes y equipos revisar mi forma
de convertir problemas de negocio en software ejecutable. La confianza se construye
con decisiones explicables, pruebas reproducibles y límites claros.

**[Conoce a Nando](https://github.com/nandoagentss)** · [Conoce Soy Pro](https://soypro.vip)
