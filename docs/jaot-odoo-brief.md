# JAOT × Odoo — Documento de arranque

**Autor:** sesión de Claude Code (PC trabajo, sin acceso al repo local de JAOT ni credenciales de GitHub de `avallavall`)
**Fecha:** 2026-07-29
**Destinatario:** Claude Code de casa, que ya tiene contexto y memoria del proyecto JAOT
**Estado:** propuesta de arranque, NO plan cerrado. Todo lo de aquí es discutible y varias cosas necesitan verificación (ver §11).

---

## 0. Cómo usar este documento

Esto **no** es un plan de implementación ni una spec. Es el documento de contexto para arrancar una fase de investigación sobre "cómo llevar JAOT a Odoo".

Lo que hay dentro:
- **§1–2**: contexto y restricciones del terreno Odoo (probablemente lo que menos sabes).
- **§3**: seis decisiones arquitectónicas propuestas, cada una con su razonamiento y las alternativas descartadas. Son el núcleo. Discútelas, no las asumas.
- **§4–7**: consecuencias prácticas (estructura, trampas, licencias, MVP).
- **§8**: plan de investigación concreto con comandos.
- **§9**: preguntas que solo puede responder Adrià.
- **§11**: nivel de confianza de cada afirmación. **Léelo antes de tratar nada de aquí como hecho.**

Adrià ya anotó ayer la idea en la planificación del proyecto para no olvidarla. Este documento sustituye/amplía esa nota.

---

## 1. Contexto de partida

### 1.1 Qué es JAOT (según el README público, para anclar suposiciones)

Plataforma self-hosted de optimización que baja la barrera de entrada a solvers industriales:

- **Frontend** Next.js 16 (5 idiomas) · **Backend** FastAPI / Python 3.12
- **Infra**: PostgreSQL 18, RabbitMQ + Celery, Redis, Qdrant (RAG), API de Anthropic Claude, Docker Compose
- **Arquitectura**: monolito modular; el solver es el primer bounded context extraído, tras un protocolo `SolverAdapter` intercambiable
- **Solvers**: SCIP (PySCIPOpt), HiGHS (highspy), adaptador opcional Hexaly (BYO-license)
- **Definición de problemas**: lenguaje natural (asistente LLM con RAG), JSON, canvas visual, DSL `JModel`, y **102 templates** (knapsack, VRP, scheduling, production planning, portfolio)
- **Análisis**: restricciones activas, holguras, utilización, sensibilidad LP (precios sombra, costes reducidos), what-if por perturbación real del modelo, tornado charts
- **Superficies de integración ya existentes**: API HTTP del backend + **servidor MCP con 30 herramientas**
- **Licencia**: Apache-2.0, marketplace de modelos colaborativo, sin billing

> ⚠️ Esto está sacado del README público. Si el estado real del repo difiere (p. ej. la API HTTP no está estabilizada, o el MCP es la única superficie madura), **corrige este documento antes de seguir** — varias decisiones de §3 dependen de que exista una API HTTP utilizable desde fuera.

### 1.2 Qué quiere hacer Adrià

Un módulo Odoo, de código libre, que **no** sea un JAOT genérico embebido, sino algo ya pensado para engancharse a los módulos de Odoo que tienen cosas optimizables: planificación de producción, transporte/rutas, cobertura de plantilla vs. vacaciones, cashflow, compras, y más.

Su intuición inicial (textual): que el módulo **auto-detecte los módulos instalados** en ese Odoo y se auto-genere conectores para cada uno, o al menos proponga qué se puede optimizar y cómo integrarlo en los workflows existentes.

Motivación del enfoque: hacer una integración a medida por cada módulo de Odoo es inviable — cada cliente tiene un subconjunto distinto de módulos, muchos usan módulos de la OCA, y otros llevan desarrollos a medida.

### 1.3 Input externo recogido

Consulta a un experto de Odoo de confianza (partner/integrador con años de experiencia), resumen de lo que dijo:
- Enterprise es un pack completo, se adquiere entero y se paga como SaaS mensual.
- Puedes hacer que tu módulo dependa **solo de Community**, y tener una versión aparte para Enterprise.
- Los módulos de terceros se bajan del Odoo App Store y tienen precio por descarga.
- Cree que, de lo listado, **vacaciones es lo único Enterprise**.

**Matiz importante a ese último punto** (verificar, §11): `hr_holidays` (Ausencias / Time Off) está en el repo Community de Odoo, es LGPL. Lo que sí es Enterprise es `planning` (planificación de turnos) y `hr_payroll` (nóminas). Si el caso de uso es "cobertura de plantilla vs. vacaciones aprobadas", los datos están en Community. Si es "generar el cuadrante de turnos óptimo", ahí sí entras en Enterprise.

---

## 2. Restricciones del terreno: Odoo 101 para este proyecto

### 2.1 Las cuatro capas de módulos

| Capa | Qué es | Licencia | Coste | Relevancia |
|---|---|---|---|---|
| **Community** (`odoo/odoo`) | Núcleo: `base`, `mrp`, `stock`, `sale`, `purchase`, `account`, `hr`, `project`, `delivery`… | LGPL-3 | Gratis | **Aquí vive el 90% de lo que necesitamos** |
| **Enterprise** (`odoo/enterprise`, repo privado) | `planning`, `hr_payroll`, `helpdesk`, `field_service`, `documents`, `sign`, `quality`, `mrp_plm`, `approvals`, `account_accountant`, `sale_subscription`, `timesheet_grid`… | OEEL-1 (propietaria) | Suscripción SaaS mensual | Solo para casos concretos |
| **OCA** (Odoo Community Association) | Cientos de módulos comunitarios de calidad variable pero a menudo alta | **AGPL-3** mayoritariamente | Gratis | Muy usado por partners. **Su licencia nos condiciona** (§6) |
| **App Store / terceros** | Módulos comerciales | OPL-1 u otras | Precio por descarga | Fuente de fragmentación en instalaciones reales |

### 2.2 Cómo testear sin pagar

Para lo que Adrià quiere probar (producción, transporte, cashflow, RRHH básico), **Community + Docker en local es suficiente y gratis**. No hace falta ni odoo.sh ni Enterprise para arrancar.

Para inspeccionar los modelos Enterprise (`planning`, `hr_payroll`) cuando toque:
1. **Trial gratuito de Odoo Online / odoo.sh** (~15 días, todas las apps activadas). Suficiente para leer esquemas de modelos, entender relaciones y probar una integración vía API externa.
2. **Plan gratuito de Odoo Online**: una app gratis para siempre — no sirve para probar integración multi-módulo.
3. El código fuente de Enterprise solo es accesible a suscriptores/partners.

**Recomendación**: no pagar nada hasta tener el MVP funcionando en Community. Diseñar de forma que Enterprise sea siempre un bridge opcional, nunca una dependencia dura.

### 2.3 Herramientas de introspección que Odoo ya te da

Esto es clave para la idea del "escaneo" (§3.3, §3.4). Odoo expone su propio metamodelo como datos consultables:

- `ir.module.module` → módulos disponibles, con `state` (`installed`, `uninstalled`, `to upgrade`…), `author`, `license`, `category_id`. **Esto es literalmente el "escáner" que Adrià imagina, y es una query.**
- `ir.model` → todos los modelos ORM registrados.
- `ir.model.fields` → todos los campos, con tipo, relación, `store`, `compute`, `required`.
- `ir.model.relation`, `ir.model.constraint` → relaciones y constraints a nivel BD.

Un agente LLM que lea estas cuatro tablas tiene un mapa **completo y exacto** de la instalación concreta que tiene delante, incluyendo módulos OCA y desarrollos a medida que nunca ha visto. Esa parte de la intuición de Adrià es sólida.

---

## 3. Decisiones arquitectónicas propuestas

Seis decisiones. Cada una lleva razonamiento y qué se descarta. **Trátalas como propuestas a validar, no como dadas.**

### D1 — JAOT no se porta a Odoo. El módulo es un cliente fino.

**Propuesta**: el addon de Odoo **no** contiene solver. Su trabajo es:
1. Extraer datos de Odoo y construir un `OptimizationProblem` (el schema que JAOT ya tiene).
2. Enviarlo a una instancia de JAOT vía HTTP.
3. Recibir la solución y materializarla en registros Odoo.

**Por qué**:
- **Dependencias Python imposibles**: `pyscipopt` y `highspy` son extensiones nativas. En Odoo Online (SaaS) no puedes instalar nada. En odoo.sh puedes vía `requirements.txt` pero con fricción y riesgo de build. On-premise es viable pero te ata a controlar el despliegue. Sacando el solver fuera, **da igual dónde corra el Odoo**.
- **Timeouts**: los HTTP workers de Odoo matan peticiones largas (`limit_time_real`, por defecto ~120s; `limit_time_cpu` ~60s). Un MIP no cabe ahí. Cualquier diseño que resuelva dentro de la petición está muerto al nacer.
- **Preserva la inversión**: `SolverAdapter`, JModel DSL, análisis de sensibilidad, what-if, los 102 templates, el RAG — todo eso sigue viviendo en JAOT y sirve para todos los canales, no solo Odoo.
- **Modelo de producto**: JAOT sigue siendo el producto. Odoo pasa a ser un canal de entrada más, al lado del MCP server. Estratégicamente es lo correcto.

**Descartado**: (a) embeber `highspy` en el addon — rompe SaaS y solo cubre LP/MIP pequeños; (b) reimplementar una versión "simple" de JAOT en Python dentro de Odoo — duplica el core y diverge en 3 meses.

**Matiz a investigar**: quizá tenga sentido un modo degradado opcional (`jaot_local_solver`, no auto-instalable) con HiGHS embebido para on-premise sin conectividad. Como extra, nunca como base.

### D2 — "Auto-integrarse" = bridge modules con `auto_install`, no magia de runtime.

**Propuesta**: estructura de módulos puente, uno por módulo Odoo soportado, todos con `auto_install`:

```
jaot_base      depends: ['base']                      # config, cliente API, motor de bindings, modelo de escenarios
jaot_stock     depends: ['jaot_base', 'stock']        auto_install: True
jaot_mrp       depends: ['jaot_base', 'mrp']          auto_install: True
jaot_hr        depends: ['jaot_base', 'hr_holidays']  auto_install: True
jaot_account   depends: ['jaot_base', 'account']      auto_install: True
jaot_purchase  depends: ['jaot_base', 'purchase']     auto_install: True
```

Con `auto_install: True` en el `__manifest__.py`, Odoo instala el puente automáticamente en cuanto **todas** sus dependencias están presentes. El usuario instala `jaot_base` y se encienden solos los conectores de lo que ese cliente tenga instalado. **Ese es exactamente el comportamiento que Adrià describe.**

**Por qué**:
- Es el patrón nativo de Odoo. El propio core lo usa: `sale_stock`, `purchase_mrp`, `account_edi`… Cualquier partner de Odoo lo reconoce al instante; cualquier otra cosa le parecerá rara.
- Sin magia de runtime: el estado es declarativo y auditable, no depende de que un escáner acierte.
- Desinstalar `mrp` desinstala `jaot_mrp` limpiamente. Sin código huérfano.
- Aísla el riesgo: un bug en `jaot_mrp` no tumba `jaot_stock`.

**A verificar**: Odoo moderno (creo que desde la 15, confirmar para la versión objetivo) acepta `auto_install` como **lista de dependencias** en vez de booleano, lo que permite "instálate cuando esté `mrp`, aunque `X` sea dependencia dura no disparadora". Da control más fino. Comprobar en el código de `odoo/modules/`.

**Descartado**: un módulo monolítico `jaot` con `try: import` y comprobaciones `if 'mrp' in env` por todas partes. Funciona, pero es imposible de mantener, imposible de testear por módulo, y contamina las vistas.

### D3 — Binding por roles abstractos, no por campos hardcodeados.

**Este es el punto crítico**, y la respuesta real al problema "hay gente con OCA y desarrollos a medida".

**Propuesta**: una *receta* de optimización (que mapea a un template de JAOT) **no** referencia `mrp.workorder.duration_expected`. Declara **roles semánticos** y trae *bindings por defecto* para los módulos que conoce:

```
Receta: "Job-shop scheduling"
Roles requeridos:
  tarea         → modelo   (default en mrp: mrp.workorder)
  duración      → campo    (default: duration_expected)
  recurso       → m2o      (default: workcenter_id)
  capacidad     → campo    (default: mrp.workcenter.capacity)
  precedencia   → relación (default: operation_id.sequence)
  fecha_límite  → campo    (default: production_id.date_deadline)
Roles opcionales:
  coste_setup, prioridad, calendario (resource.calendar)
```

Si el cliente usa un módulo OCA o un desarrollo a medida, el admin **remapea el rol** en una vista de configuración: eso es un mapeo, no un conector nuevo. Coste marginal de soportar una instalación exótica: minutos en vez de un sprint.

**Por qué**: separa lo estable (la estructura matemática del problema, que ya tienes en los 102 templates) de lo volátil (qué campo concreto tiene los datos en *esta* instalación). Es la única forma de escalar a la fragmentación real del ecosistema Odoo sin escribir N conectores.

**Implicación de diseño**: los bindings deben poder ser algo más que "un campo": a veces será un path (`production_id.date_deadline`), a veces un dominio de filtrado, a veces una pequeña expresión. Investigar `safe_eval` de Odoo y **restringir la edición de bindings a `base.group_system`** — un binding con expresión es superficie de ataque.

### D4 — El escaneo/LLM es descubrimiento y borrador, no autopilot.

**Dónde la idea original NO funciona**: como generador automático de conectores. Saber que existe `mrp.production` no te dice la función objetivo, ni qué restricciones importan a ese cliente, ni dónde están las capacidades reales, ni los costes, ni qué tiene prohibido tocar el planificador por política interna. La introspección te da el **esquema**; no te da el **modelo**. Auto-generar formulaciones produciría modelos plausibles y sistemáticamente inútiles — peor que no tener nada, porque destruye la confianza del usuario en la primera demo.

**Dónde SÍ funciona** (dos features distintas, ambas valiosas):

**(a) Opportunity scan.** Lees `ir.module.module` + `ir.model.fields`, y el sistema reporta: *"tienes `mrp`, `stock`, `hr_holidays` y `purchase` instalados y con datos → estas 6 recetas de optimización aplican; estas 3 aplicarían si mapeas 2 campos que faltan"*. Salida a un modelo `jaot.opportunity` con estado y un botón "configurar". Esto es **vendible**, es honesto, y es el 80% del valor percibido de la idea original.

**(b) Auto-binding asistido por LLM.** Cuando el usuario elige una receta, el LLM recibe los roles requeridos + el esquema real de esa instalación (`ir.model.fields` filtrado) y **propone un borrador de binding**. El humano lo revisa, ajusta y guarda como receta versionada. Human-in-the-loop, con diff visible antes de guardar.

Aquí encaja de forma natural lo que JAOT ya tiene: RAG sobre la librería de templates, asistente de formulación, y el MCP server. **Investigar**: ¿se puede reutilizar el asistente de formulación existente pasándole el esquema Odoo como contexto adicional, en vez de construir un pipeline nuevo?

**Regla de diseño no negociable**: nada que el LLM proponga se aplica sin confirmación humana explícita. Ni bindings, ni escrituras.

### D5 — Async con `ir.cron` nativo, no con `queue_job` de la OCA.

**Propuesta**: el ciclo de vida de un solve es asíncrono y se gestiona con un modelo propio + `ir.cron`:

```
draft → queued → solving → solved → applied
                        ↘ failed / cancelled
```

`jaot_base` encola, un cron hace polling contra la API de JAOT y actualiza el estado. Nada de esperar dentro de una petición HTTP.

**Por qué no `queue_job`**: es el estándar de facto para trabajos asíncronos en Odoo y técnicamente es mejor que un cron… pero es **OCA y AGPL-3**. Depender de él **obliga a que tus módulos sean AGPL-3** (ver §6). Si eso limita opciones de distribución o monetización futuras, es un precio alto por comodidad de ingeniería en algo que un cron resuelve.

**Decisión a tomar por Adrià, no por el agente** (§9): si la respuesta es "AGPL me va bien y no pienso vender nunca", entonces usa `queue_job` y ahorras trabajo. Si hay cualquier duda, evítalo en `jaot_base` — cambiarlo después es doloroso.

**Alternativa intermedia a investigar**: `jaot_base` sin `queue_job` + un `jaot_queue_job` opcional (AGPL, auto_install si `queue_job` está presente) que sustituya el mecanismo. Lo mejor de ambos, a coste de una capa de abstracción.

### D6 — La solución se escribe en un modelo propio, y "aplicar" es un acto explícito.

**Escribir de vuelta es más difícil que leer.** Reprogramar 400 `mrp.production` de golpe dispara recomputes en cascada, reservas de stock, movimientos, actividades y correos. Puedes tumbar un ERP en producción con un solo `write()` bienintencionado.

**Propuesta**:
1. La solución aterriza en `jaot.scenario` + `jaot.scenario.line` — modelos propios, sin efectos secundarios.
2. El usuario ve un **diff**: qué cambiaría, en qué registros, con qué impacto en el KPI.
3. Botón explícito **"Aplicar"**, que escribe en lotes, con `savepoint`, con log de auditoría, y con posibilidad de revertir.
4. Guardar el payload de request y response en el escenario → auditable, reproducible, y depurable sin acceso a producción.

### D6-bis — Comparación de escenarios ⭐ PRIORIDAD DE ESTUDIO (marcado a mano por Adrià)

El diseño de D6 da casi gratis el que probablemente sea el **killer feature de negocio**: comparar escenarios (baseline vs. optimizado, escenario A vs. B), que es donde la sensibilidad LP y los what-if de JAOT lucen de verdad. Adrià lo ha señalado explícitamente como punto a estudiar en profundidad: **tratarlo como línea de investigación propia con su nota dedicada, no como corolario de D6.** Qué estudiar, en concreto:

1. **El baseline como escenario cero.** Para comparar hace falta capturar el estado actual (la planificación manual vigente) como un `jaot.scenario` más, con sus KPIs calculados por JAOT con la **misma función objetivo, sin optimizar**. Sin esto no existe la cifra de "cuánto mejoras" — y esa cifra ES la venta y ES la demo. Pregunta clave para el repo: ¿la API de JAOT soporta modo *evaluate-only* (evaluar una solución dada / warm start con solución fijada) o solo sabe resolver? Si no lo soporta, es probablemente **la primera feature a añadir al core**, porque beneficia a todos los canales, no solo a Odoo.
2. **Qué expone JAOT hoy por API para esto.** Sensibilidad (precios sombra, costes reducidos), what-if por perturbación real, tornado charts: ¿accesibles vía API/MCP, o solo desde el frontend Next.js? Conecta directamente con la Fase C (§8) — añadida allí como pregunta.
3. **UX de comparación dentro de Odoo.** Vista de N escenarios lado a lado: diff de KPIs arriba, diff de líneas debajo (qué órdenes cambian de fecha/recurso/secuencia entre A y B, qué paradas cambian de ruta). Investigar si basta con vistas estándar (lista agrupada + pivot sobre `jaot.scenario.line`) antes de plantear un componente OWL a medida. Empezar simple; el diff de KPIs solo ya vende.
4. **What-if guiado desde Odoo.** "¿Y si tuviera un camión más? ¿Un turno extra? ¿+10% de capacidad en el cuello de botella que me has señalado?" — eso es exactamente la perturbación real de modelos que JAOT ya hace. Expuesto como acción sobre un escenario resuelto, convierte el módulo de "optimizador" en **herramienta de decisión**, que es un pitch muy superior y el diferencial real frente a cualquier planificador embebido de ERP.
5. **Ciclo de vida y staleness.** Los payloads guardados pesan (retención/archivado a definir). Y más sutil: un escenario `solved` se queda obsoleto cuando los datos fuente cambian — guardar hash/timestamp del snapshot de datos extraído y avisar en la UI si el estado actual de Odoo ya no coincide con el que se optimizó. Comparar contra un baseline caducado produce cifras falsas, y una cifra falsa en demo mata la credibilidad del producto entero.

---

## 4. Anatomía propuesta del repo de módulos

Repo separado del core de JAOT (versionado distinto: los addons Odoo van atados a versión de Odoo, JAOT no).

```
jaot-odoo/
├── jaot_base/                  # LGPL-3 (o AGPL, ver §6)
│   ├── models/
│   │   ├── jaot_config.py      # endpoint, api key, timeouts
│   │   ├── jaot_recipe.py      # receta ↔ template JAOT, roles requeridos
│   │   ├── jaot_binding.py     # rol → campo/path/expresión, por receta e instalación
│   │   ├── jaot_scenario.py    # ciclo de vida del solve, payloads, resultados
│   │   ├── jaot_opportunity.py # salida del opportunity scan
│   │   └── jaot_client.py      # cliente HTTP contra JAOT
│   ├── data/ir_cron.xml
│   ├── security/               # grupos: jaot_user / jaot_manager; bindings solo group_system
│   └── views/
├── jaot_stock/                 # bridge, auto_install
├── jaot_mrp/                   # bridge, auto_install
├── jaot_hr/                    # bridge, auto_install
├── jaot_account/               # bridge, auto_install
└── jaot_local_solver/          # opcional, NO auto_install — modo degradado on-premise
```

Cada bridge aporta: recetas + bindings por defecto para su dominio + la lógica de extracción y de aplicación de resultados + vistas integradas en los menús de ese módulo (no un menú "JAOT" aparte: **la integración en el workflow existente es parte del valor**, y Adrià ya lo apuntó).

---

## 5. Trampas técnicas concretas

1. **Timeouts de worker** (§D1). Nunca resolver dentro de una petición. Nunca.
2. **Volumen de datos**. No mandes registros crudos a JAOT. El bridge construye una *instancia de problema* compacta (índices, no ORM). Un `search_read` sobre 50k `stock.move` con campos computados no almacenados te come la RAM del worker.
3. **Campos `compute` no almacenados**: leerlos en masa dispara N recomputes. Preferir campos `store=True` en los bindings, y avisar en la UI si un binding apunta a uno no almacenado.
4. **`resource.calendar`**: horarios, turnos y festivos viven aquí y son básicos para cualquier scheduling realista. Es Community. Estudiarlo bien — probablemente es el modelo más infravalorado de Odoo para este proyecto.
5. **Multi-compañía y multi-almacén**: cualquier extracción debe respetar `company_id` y las record rules. Un solve que cruza compañías es un incidente de seguridad, no un bug.
6. **`api key` en `ir.config_parameter`**: legible por admin. Aceptable, pero documentarlo. No meterla en datos de demo ni en el repo.
7. **Migraciones entre versiones de Odoo**: cada versión mayor (anual) rompe cosas. Fijar una versión objetivo y decirlo en el README. Con la fecha actual, **Odoo 19** es lo razonable (verificar cuál es la LTS/estable vigente).
8. **Tests**: `TransactionCase` + datos demo propios por bridge. Los datos demo de Odoo son escasos para probar optimización de verdad; probablemente haya que generar un dataset sintético (p. ej. 200 órdenes de producción con capacidades ajustadas) — trabajo real, presupuestarlo.
9. **Nunca dependas de Enterprise en un módulo `auto_install`**. Si algún día hay `jaot_planning`, va en repo/rama aparte y bien señalizado.

---

## 6. Licencias y distribución — decidir ANTES de escribir código

Situación:
- **JAOT core**: Apache-2.0.
- **Odoo Community**: LGPL-3. Un addon que solo dependa de Community puede llevar prácticamente cualquier licencia (LGPL-3, AGPL-3, OPL-1, MIT…).
- **Módulos OCA**: AGPL-3 mayoritariamente. **Depender de uno obliga a AGPL-3** en tu módulo.

Consecuencia práctica: si `jaot_base` depende de `queue_job` (OCA, AGPL-3), **todo el stack Odoo de JAOT queda AGPL-3**. Eso cierra la puerta a publicar en el App Store bajo OPL-1, y complica cualquier licenciamiento dual futuro.

Opciones, en orden de flexibilidad:
- **A) `jaot_base` LGPL-3, cero dependencias OCA.** Máxima flexibilidad, algo más de trabajo (cron propio). Los bridges pueden ser AGPL si necesitan tocar OCA.
- **B) Todo AGPL-3.** Alineado con la cultura OCA, opción de contribuir los módulos a la OCA (buena distribución y credibilidad, a cambio de estándares estrictos de code review). Cierra el App Store de pago.
- **C) Dual / OPL-1 para lo publicado en App Store.** Solo tiene sentido si hay intención comercial clara. Incompatible con dependencias AGPL.

**Recomendación**: **A**, salvo que Adrià descarte explícitamente cualquier vía comercial. Es la única que no cierra puertas, y el sobrecoste es un cron.

Canales de distribución a evaluar: GitHub propio (control total, cero descubrimiento) · Odoo App Store gratuito (descubrimiento alto, requiere cumplir sus normas) · OCA (credibilidad y mantenimiento compartido, a cambio de ceder gobernanza y aceptar AGPL).

---

## 7. MVP recomendado

**Un dominio, end-to-end, con un KPI visible.** No cinco a medias.

### Candidato principal: optimización de rutas de reparto
`stock.picking` + `delivery` + `res.partner` (geo).

- **A favor**: datos ya estructurados y presentes en cualquier instalación con logística. Todo Community. La baseline (orden manual o por fecha) es manifiestamente mala, así que la mejora se ve. **La demo se ve en un mapa** — impagable para vender. Odoo Community no trae optimización de rutas nativa y la OCA cubre poco → hueco real. Mapea directo a los templates VRP que ya tienes.
- **En contra**: necesitas geocoding y matriz de distancias — dependencia externa (OSRM self-hosted, o API de pago). Decidir pronto. **Y ojo**: la vista `map` nativa de Odoo es **Enterprise**; en Community habría que tirar de un widget OCA (`web_map` o similar) o de un widget Leaflet propio (verificar, §11). Para geocodificar partners, `base_geolocalize` existe en Community. Nada de esto invalida el candidato, pero el "se ve en un mapa" no sale gratis.

### Alternativa: scheduling de producción (`mrp`)
- **A favor**: más valor por cliente, más defendible, y es *el* dolor clásico del ERP.
- **En contra**: la calidad de datos en instalaciones reales es mala (capacidades mal configuradas, rutas incompletas, tiempos ficticios). Riesgo alto de pasar seis meses peleando con datos sucios en vez de con el solver. Como MVP, castiga.

### Descartados como primer paso
- **Cashflow**: modelado atractivo pero el resultado es un informe, no una acción. Poco espectacular en demo.
- **Vacaciones/plantilla**: la parte interesante (cuadrantes) roza Enterprise (`planning`).

**Criterio general para elegir**: (1) el módulo fuente es Community, (2) los datos ya están estructurados sin trabajo de configuración previo, (3) la baseline es visiblemente mala, (4) el resultado es una **acción** aplicable, no un informe.

---

## 8. Plan de investigación sugerido

Tareas concretas, ordenadas. Cada una debería producir una nota breve, no código.

### Fase A — Verificar el terreno Odoo (medio día)

```bash
# Levantar Odoo 19 Community + Postgres en local
# (docker compose con odoo:19 y postgres:16)

# Verificar semántica de auto_install en la versión objetivo
grep -rn "auto_install" odoo/modules/          # ¿acepta bool y lista?
grep -rn "auto_install" addons/sale_stock/__manifest__.py

# Confirmar qué es Community y qué Enterprise
ls addons/ | grep -E "hr_holidays|planning|mrp|stock|delivery|account"
# (planning y hr_payroll NO deberían aparecer en el repo community)

# Explorar el metamodelo desde odoo shell
# env['ir.module.module'].search_read([('state','=','installed')], ['name','author','license'])
# env['ir.model.fields'].search_count([('model','=','mrp.workorder')])
```

**Entregable**: nota confirmando/corrigiendo §2.1, §2.2 y D2.

### Fase B — Validar la hipótesis de los roles (1 día)

Coger **una** receta (VRP o job-shop) y, a mano, mapear sus roles contra:
1. Odoo Community estándar.
2. Un módulo OCA equivalente del mismo dominio (buscar en github.com/OCA).

**Pregunta a responder**: ¿el conjunto de roles aguanta ambos casos con solo cambiar bindings, o hay diferencias estructurales que rompen la abstracción? **Si la abstracción de roles se rompe aquí, D3 cae y hay que replantear todo el enfoque.** Es la validación más importante del proyecto.

### Fase C — Verificar la superficie de integración de JAOT (medio día)

Contra el repo local:
- ¿Hay API HTTP estable para crear problema → resolver → recuperar solución? ¿Está documentada? ¿Autenticación?
- ¿El schema `OptimizationProblem` es serializable/construible desde fuera sin pasar por el frontend?
- ¿Qué hace exactamente el MCP server y sus 30 tools? ¿Solapa con lo que necesitaría el bridge?
- ¿Cómo se consulta el estado de un job Celery desde fuera? ¿Hay webhooks o solo polling?
- **Para D6-bis**: ¿existe modo *evaluate-only* (evaluar una solución dada sin optimizar, para el baseline)? ¿Sensibilidad, what-if y tornado charts son accesibles por API/MCP o solo desde el frontend? Si falta algo de esto, anotarlo como feature candidata del core, no como workaround en el addon.

**Entregable**: contrato de integración Odoo↔JAOT. **Bloquea todo lo demás** — si la API no está lista, el primer trabajo es esa API, no el addon.

### Fase D — Spike técnico (1–2 días)

Sin escribir el módulo: script Python que se conecte a Odoo por XML-RPC/JSON-RPC, extraiga los datos de la receta elegida en Fase B, construya el payload de JAOT, lo resuelva, y devuelva la solución por consola.

**Objetivo**: validar el flujo completo con datos reales **antes** de invertir en estructura de addons. Si el spike funciona, el addon es empaquetado. Si no, has ahorrado semanas.

### Fase E — Decisiones y roadmap

Con A–D hechas: cerrar §9, fijar licencia (§6), fijar MVP (§7), y ahí sí planificar la implementación.

---

## 9. Preguntas abiertas — solo las puede responder Adrià

1. **Licencia**: ¿hay intención comercial futura (App Store de pago, dual licensing, soporte)? Determina §6 y D5. **Es la pregunta que más bloquea.**
2. **Modelo de despliegue**: ¿JAOT self-hosted por el cliente al lado de su Odoo, o un jaot.io SaaS al que el módulo se conecta? Cambia auth, latencia, privacidad de datos y propuesta de valor.
3. **Privacidad**: ¿hay clientes que no aceptarán que datos de producción salgan del Odoo? Si sí, `jaot_local_solver` sube de "opcional" a "requisito".
4. **Público objetivo**: ¿partners Odoo que lo instalan a clientes, o usuarios finales? Cambia radicalmente la UI (un partner acepta configurar bindings; un usuario final, no).
5. **Versión objetivo de Odoo**: ¿19? ¿Soporte multi-versión desde el principio (caro) o una sola (recomendado)?
6. **MVP**: ¿rutas o producción? (§7 recomienda rutas.)
7. **Alcance del LLM**: ¿el auto-binding asistido entra en v1 o se deja para v2? (Sugerencia: v2. V1 con bindings por defecto bien hechos + edición manual ya es útil, y reduce el riesgo a la mitad.)

---

## 10. No-objetivos explícitos de la v1

Escribirlos evita scope creep:

- ❌ Soportar módulos Enterprise.
- ❌ Auto-generar formulaciones de optimización sin humano en el bucle.
- ❌ Solver embebido en el proceso de Odoo.
- ❌ Soporte multi-versión de Odoo.
- ❌ Escritura automática en registros de producción sin confirmación explícita.
- ❌ Cubrir más de un dominio de optimización.

---

## 11. Nivel de confianza — LEER ANTES DE USAR

Este documento se escribió **sin acceso al repo local de JAOT** y **sin un Odoo delante**. Clasificación honesta:

**Alta confianza** (conocimiento estable de Odoo, poco probable que haya cambiado):
- Existencia y semántica básica de `auto_install` y el patrón de bridge modules.
- Community = LGPL-3, OCA = AGPL-3 mayoritariamente, y el efecto contagio del AGPL.
- Existencia y utilidad de `ir.module.module`, `ir.model`, `ir.model.fields`.
- Los HTTP workers matan peticiones largas (`limit_time_real` / `limit_time_cpu`).
- `mrp`, `stock`, `sale`, `purchase`, `account`, `hr`, `project`, `delivery` son Community.
- Los riesgos de escritura masiva vía ORM.

**Confianza media — VERIFICAR**:
- Que `hr_holidays` sea Community y `planning`/`hr_payroll` Enterprise en la versión objetivo (contradice lo que dijo el experto consultado; verificar antes de rebatirlo).
- Que `auto_install` acepte lista de dependencias además de booleano, y desde qué versión.
- Los valores por defecto exactos de `limit_time_real` / `limit_time_cpu`.
- La clasificación Community/Enterprise de módulos frontera: `mrp_mps`, `stock_barcode`, `account_accountant`, `sale_subscription`.
- Que Odoo 19 sea la versión estable adecuada como objetivo a día de hoy.
- Condiciones exactas del trial de Odoo Online/odoo.sh (duración, apps incluidas).
- Que la vista `map` sea Enterprise, qué alternativa OCA existe para Community (¿`web_map`?), y que `base_geolocalize` siga en Community en la versión objetivo.

**Suposiciones sobre JAOT que hay que contrastar con el repo real** (§1.1 sale del README público, que puede ir por detrás del código):
- Que exista API HTTP consumible desde fuera. **Si no existe, D1 entero cambia de forma.**
- Que el schema `OptimizationProblem` sea construible externamente.
- Que los templates VRP y de scheduling estén lo bastante maduros para el MVP.
- Que el asistente RAG sea reutilizable con contexto externo (esquema Odoo).

**Opinión, no hecho** (discutir con Adrià):
- Toda la §7 (elección de MVP).
- La recomendación de licencia (§6, opción A).
- Dejar el auto-binding LLM para v2.
- Que `queue_job` no compense por su licencia.

---

## 12. Resumen en seis líneas

1. El addon Odoo es un **cliente fino**; JAOT se queda fuera con su solver.
2. El "auto-integrarse" se consigue con **bridge modules `auto_install`**, patrón nativo de Odoo — no hace falta magia.
3. La fragmentación OCA/custom se resuelve con **bindings por roles abstractos**, no con N conectores.
4. El **escaneo LLM sirve para descubrir y proponer**, nunca para generar modelos sin supervisión.
5. La **comparación de escenarios** (D6-bis, prioridad marcada por Adrià) es el killer feature de negocio: baseline evaluado + diff de KPIs + what-if guiado. Estudiarla como línea propia.
6. Antes de escribir código: **decidir licencia** (§9.1) y **validar la abstracción de roles** (Fase B). Si alguna de las dos falla, el diseño cambia.
