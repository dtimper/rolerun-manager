# Propuesta maestra de rediseño

Estado: propuesta para revisión; no implementada  
Base: auditoría de `0.2.2-alpha.86`

## 1. Principios

1. **La partida manda.** La interfaz nunca presenta como confirmado un cambio que
   no haya superado la verificación del backend activo.
2. **Una operación, un contexto.** Equipo, PC, roles y datos del Pokémon deben
   poder consultarse sin encadenar ventanas.
3. **Capacidades, no juegos supuestos.** Cada control se deriva de capacidades
   declaradas por la sesión; no de una equivalencia visual entre juegos.
4. **Resumen no significa duplicación.** Inicio muestra estado y atención, no una
   versión reducida de cada herramienta.
5. **Acción frecuente visible; diagnóstico bajo demanda.** Los detalles técnicos
   existen, pero no compiten con jugar una run.
6. **Ratón y teclado equivalentes.** Drag and drop es un acelerador, nunca el único
   modo de completar una operación.
7. **Identidad RoleRun contenida.** Oscuro, dorado, sprites y roles permanecen;
   superficies y adornos dejan espacio a los datos.
8. **Migración sin reescritura.** Las primeras fases envuelven servicios actuales
   y conservan la interfaz clásica como rollback.

## 2. Arquitectura de información propuesta

```text
RoleRun Manager
├─ Inicio                         Centro de control y atención
├─ Pokémon
│  ├─ Equipo y PC                 Espacio unificado maestro–detalle
│  └─ Movimientos                 Explorador por Pokémon/rol/método
├─ MT                             Inventario y enseñanza, MT-primero
├─ Drafteos                       Wizard existente refinado
├─ Progreso
│  ├─ Run                         Vidas, curaciones, drafteos, hitos
│  └─ Recursos                    Dinero y objetos relevantes
├─ Registro
│  ├─ Actividad                   Línea temporal filtrable
│  └─ Cementerio                  Bajas, pendientes y ubicación
├─ Emisión                        OBS, visibilidad y barra flotante
├─ Ajustes                        Run, fuentes, idioma, atajos
└─ Diagnóstico avanzado           Conexión, lanes, grabación y replay
```

En anchura normal, el primer nivel aparece en una barra lateral contraíble. Los
subniveles pueden ser tabs dentro de la página; no necesitan otro sidebar. En
modo compacto quedan icono + tooltip y un selector de sección accesible por
teclado.

### Elementos persistentes

- selector/identidad de run en la parte superior del sidebar;
- estado de conexión como control compacto y explícito;
- centro de operaciones con número de pendientes/fallos;
- botón de barra flotante dentro de Emisión y como acceso rápido opcional;
- comando global de búsqueda/acciones, planteado para una fase posterior.

La barra superior deja de alojar Guardar/Descartar en todas las páginas. Las
operaciones clásicas se agrupan en un **Centro de cambios** persistente solo
cuando existan cambios. Realtime muestra pendientes hasta readback, confirmados
recientes y fallos recuperables.

## 3. Estado común de sesión y capacidades

La nueva UI debe recibir un `SessionPresentation` inmutable o equivalente,
derivado de autoridades existentes:

```text
SessionPresentation
├─ run_identity
├─ connection {state, backend, game, last_confirmed_at, summary}
├─ capabilities
│  ├─ party.read / party.write / party.resize
│  ├─ pc.read / pc.write / pc.reorder
│  ├─ moves.read / moves.write
│  ├─ tm.inventory / tm.teach
│  ├─ progress.badges / deaths / utilities
│  └─ mode: realtime | save | unavailable
├─ confirmed_state
├─ projected_state
├─ operations[]
└─ attention_items[]
```

No sustituye a `RealTimeSnapshot`, `RunProject` ni `RunSession`. Es una vista de
lectura compuesta. En las primeras fases puede construirse desde métodos actuales
de `RoleRunManager`; posteriormente la composición puede salir del monolito.

## 4. Pantalla Inicio

### Objetivo

Responder en pocos segundos: qué run está abierta, si está conectada, cómo está
el equipo, qué recursos quedan y qué requiere atención.

### Wireframe

```text
┌ Inicio ────────────────────────────────────────────────────────────┐
│ SP · Timper              Ryujinx ● Conectado   Confirmado 12:41:08 │
├────────────────────────────────────────────────────────────────────┤
│ Requiere atención (solo si existe)                                 │
│ [1 baja pendiente de sustituto] [1 operación fallida · Ver detalle]│
├─────────────────────────────┬──────────────────────────────────────┤
│ Equipo actual               │ Run                                  │
│ [1 sprite rol HP] ... [6]   │ Vidas 8 · Curaciones 3 · Drafteos 1 │
│ clic abre Equipo y PC       │ 2/8 medallas · lectura automática    │
├─────────────────────────────┴──────────────────────────────────────┤
│ Actividad reciente: 3 eventos significativos             [Ver todo]│
└────────────────────────────────────────────────────────────────────┘
```

### Reglas

- sin tarjetas vacías si no hay incidencias;
- máximo tres eventos recientes, no el historial completo;
- equipo compacto, sin habilidad/objeto/movimientos;
- valores automáticos etiquetados y sin botones +/-;
- error de lane opcional no borra equipo válido: aparece como atención acotada;
- `Enter` sobre un miembro abre Equipo y PC con ese Pokémon seleccionado.

En resolución pequeña, Equipo y Run se apilan; nunca se oculta la conexión ni la
atención.

## 5. Pantalla Equipo y PC

### Objetivo

Permitir comparar, seleccionar y mover Pokémon manteniendo a la vista party, caja
y detalle. Es el núcleo del rediseño.

### Wireframe ancho

```text
┌ Equipo y PC ───────────────────────────────────────────────────────────────┐
│ [Equipo 6/6] [Caja 1 ▾] [Buscar…] [Filtros]        ● Estado confirmado   │
├───────────────┬──────────────────────────────────────┬─────────────────────┤
│ EQUIPO        │ CAJA 1 · 10/30                      │ DETALLE             │
│ 1 [sprite] L  │ [mon][mon][mon][mon][mon]           │ Sprite · Nombre     │
│ 2 [sprite] A  │ [mon][mon][mon][mon][mon]           │ especie · nivel     │
│ 3 [sprite] M  │ ...                                  │ rol / habilidad     │
│ 4 [sprite] T  │                                      │ objeto / HP         │
│ 5 [sprite] P  │ ← Caja anterior   Caja siguiente →  │ 4 movimientos       │
│ 6 [sprite] S  │                                      │ [acciones válidas]  │
├───────────────┴──────────────────────────────────────┴─────────────────────┤
│ Operación: Slowpoke → Caja 1/8  [pendiente de verificación] [Cancelar]   │
└────────────────────────────────────────────────────────────────────────────┘
```

### Wireframe estrecho

```text
[Equipo | PC] tabs
[lista/rejilla seleccionable]
[panel de detalle deslizable]
[barra de operación persistente]
```

En estrecho no se intenta comprimir tres paneles. La selección se conserva al
cambiar tab y el resumen de destino aparece en la barra de operación.

### Selección y detalle

- una sola selección primaria compartida por lista/rejilla/detalle;
- flechas navegan miembros/celdas; `Enter` abre detalle; `Esc` cancela operación;
- búsqueda por especie, apodo, habilidad y movimiento conserva la capacidad
  actual;
- filtros propuestos: rol, con/sin rol, caja, equipo, movimiento incompatible y
  baja/cementerio;
- el detalle explica procedencia: vivo, save, proyectado o stale.

### Drag and drop: contratos separados

El gesto nunca decide por sí solo la semántica. El tipo de origen y destino crea
un comando explícito.

| Origen → destino | Semántica | Estado inicial |
|---|---|---|
| Equipo → slot PC vacío | retirar; party puede reducirse | habilitar solo con capacidad `party.resize` + `pc.write` |
| PC → slot Equipo vacío | incorporar; party crece | habilitar solo con capacidad demostrada |
| Equipo → Pokémon PC | swap 1↔1 | habilitar con swap verificado |
| PC → Pokémon Equipo | el mismo swap 1↔1 | misma operación, no implementación paralela |
| Equipo → Equipo | reordenar party física | deshabilitado hasta que backend lo declare |
| PC → PC vacío/ocupado | mover/swap de cajas | depende de `pc.reorder`, independiente del swap party |
| Pokémon → chip de rol | asignar/transferir marcador | comando de rol; no mueve físicamente al Pokémon |
| Rol → rol | transferir/intercambiar rol | mantiene orden físico |
| Baja → candidato PC | sustitución + cementerio | flujo transaccional específico, no swap genérico |

### Estados del gesto

1. al iniciar, el origen se mantiene visible y marcado;
2. destinos válidos muestran contorno y verbo: “Mover”, “Intercambiar”,
   “Asignar rol”; destinos inválidos no solo cambian de color, muestran motivo;
3. al pasar sobre destino ocupado aparece preview de ambos lados;
4. soltar crea resumen de operación; confirmación solo cuando haya pérdida,
   desplazamiento, baja o ambigüedad relevante;
5. la vista proyecta el resultado con badge “pendiente”; no elimina la copia
   confirmada del modelo;
6. worker ejecuta la operación existente;
7. readback confirma y retira el badge;
8. fallo restaura la vista confirmada y deja una fila accionable con causa;
9. `Esc` cancela antes de ejecutar; después solo “Revertir”, si existe inversa
   verificada.

Debe existir siempre un menú/botón equivalente: **Mover a PC**, **Añadir al
equipo**, **Intercambiar**, **Cambiar rol**. El drag no puede ser requisito.

### Confirmaciones

- sin confirmación redundante para un swap reversible y claramente
  previsualizado;
- confirmación para sobrescribir, eliminar movimiento, enviar una baja al
  Cementerio, limpiar un origen o ejecutar una operación cuya inversa no está
  disponible;
- si el estado cambió entre preview y ejecución, cancelar y explicar; nunca
  actualizar el preview contra un objetivo distinto silenciosamente.

## 6. Pantalla Movimientos

### Objetivo

Cruzar cuatro preguntas: qué sabe el Pokémon, qué podría aprender, por qué una
opción es válida/no válida y por qué método está disponible.

```text
┌ Movimientos ───────────────────────────────────────────────────────┐
│ Pokémon [Farigiraf ▾]  Rol [Líbero]  [Buscar movimiento…]         │
├───────────────────────────┬────────────────────────────────────────┤
│ MOVIMIENTOS ACTUALES      │ EXPLORAR                              │
│ 1 Cuerpo Pesado   ✓       │ filtros: Compatible / Método / Tipo  │
│ 2 Luz Lunar       ✓       │ lista: movimiento · tipo · datos     │
│ 3 Protección      ✓       │ badge MT / nivel / tutor / catálogo  │
│ 4 Carantoña       ✓       │ motivo exacto si no disponible       │
├───────────────────────────┴────────────────────────────────────────┤
│ Selección: datos, regla de rol, disponibilidad y acción permitida │
└────────────────────────────────────────────────────────────────────┘
```

La UI separa:

- legalidad del juego;
- compatibilidad de especie;
- posesión/disponibilidad del método;
- compatibilidad con reglas RoleRun;
- capacidad de escritura del backend.

“No compatible” siempre incluye motivo. Enseñar por MT puede enviar a la pantalla
MT con Pokémon y slot preseleccionados; no debe duplicar la lógica.

## 7. Pantalla MT

### Evidencia actual que condiciona el diseño

La lógica parte hoy de Pokémon + slot, obtiene el perfil real de MT de la
ROM/capa aplicable, lee inventario y filtra por especie, posesión y rol. Los
nombres localizados son presentación; los IDs son identidad. Hay juegos donde
la fuente o la escritura no está disponible.

### Propuesta

```text
┌ MT ─────────────────────────────────────────────────────────────────┐
│ [Buscar…] [Tipo ▾] [Poseídas ✓] [Compatibles con equipo ✓]         │
├──────────────────────────────────┬───────────────────────────────────┤
│ MT 29 · Psíquico                 │ COMPATIBILIDAD DEL EQUIPO         │
│ Psíquico · 90 pot · 100% · 10 PP │ Farigiraf  ✓ [Enseñar]           │
│ Disponibles: 2                   │ Slowpoke    Ya lo conoce          │
│ [lista/rejilla de MT]            │ Barboach    Especie incompatible  │
│                                  │ ...                               │
├──────────────────────────────────┴───────────────────────────────────┤
│ Explicación: fuente, regla de rol, slot y resultado esperado        │
└──────────────────────────────────────────────────────────────────────┘
```

Campos cuando existan en los datos demostrados: número/ID, nombre, tipo,
potencia, precisión, PP, cantidad y método. Si el repositorio no aporta un campo
fiable para un juego, se omite o aparece “No disponible”; nunca se rellena por
analogía.

Flujo de enseñanza:

1. seleccionar MT;
2. seleccionar Pokémon compatible;
3. elegir hueco vacío o movimiento a sustituir;
4. previsualizar movimiento/PP y consumo;
5. ejecutar el mismo comando ya usado por el selector actual;
6. verificar Pokémon, slot, movimiento e inventario;
7. confirmar o revertir visualmente.

## 8. Drafteos

Se conserva el wizard porque representa dependencias reales. Cambios propuestos:

- encabezado compacto con drafteos disponibles y reglas;
- stepper horizontal o vertical reducido;
- selección de Pokémon reutilizando el selector común;
- candidatos como lista comparable, no tarjetas enormes;
- resumen fijo antes de confirmar;
- enlace al motivo de compatibilidad de Movimientos;
- resultado en Centro de cambios, igual que cualquier enseñanza.

No se fusiona con MT: un drafteo consume una regla/recurso RoleRun distinto.

## 9. Progreso

### Estructura

```text
┌ Progreso ──────────────────────────────────────────────────────────┐
│ Vidas        8       Manual      [−] [+]                          │
│ Curaciones   3       Manual      [−] [+]                          │
│ Drafteos     1       Manual      [−] [+]                          │
│ Medallas     2/8     Automático  ● confirmado 12:41              │
│ Hitos USUM   Kahunas/medallas según contrato del juego            │
├ Recursos relevantes ──────────────────────────────────────────────┤
│ Dinero 999 999 ₽  confirmado │ Caramelos 999 │ Máx. Repel 999    │
└────────────────────────────────────────────────────────────────────┘
```

Cada fila declara origen:

- **Automático:** leído de juego, sin edición manual normal;
- **Manual:** autoridad RoleRun, editable;
- **Pendiente:** comando en curso;
- **Informativo:** lectura sin capacidad de escritura;
- **No disponible:** capacidad ausente con explicación.

Los nombres específicos (Kahunas, medallas, líderes) proceden de metadata por
juego. El contador persistente no debe presentarse como lectura RAM si no lo es.

## 10. Registro: Actividad y Cementerio

### Actividad

- timeline agrupada por sesión/día;
- filtros por muertes, equipo/PC, roles, movimientos/MT, progreso, recursos,
  sincronización y sistema;
- búsqueda por Pokémon;
- cada evento muestra estado: confirmado, revertido, fallido o manual;
- acciones de recuperación solo si existe una inversa demostrada;
- “Limpiar historial” se mueve a menú secundario de mantenimiento, con alcance y
  consecuencia explícitos.

### Cementerio

- lista de bajas persistidas con Pokémon, rol, fecha, causa/fuente y ubicación;
- sección separada de sustituciones pendientes;
- acceso a la caja física cuando el backend permite leerla;
- nunca ofrecer “resucitar” o mover desde cementerio sin una regla/capacidad real;
- vínculo bidireccional con el evento de muerte en Actividad.

## 11. Emisión

Reúne:

- previsualización de seis roles y contadores que OBS recibe;
- mostrar/ocultar por rol;
- estado/carpeta de salida OBS;
- conflicto que impide publicar un rol;
- abrir/configurar barra flotante;
- prueba visual local no destructiva de assets.

La barra flotante conserva su propósito y tamaño. Su gestión de foco se mantiene
intacta hasta una fase dedicada; el rediseño solo cambia la forma de abrirla y
sus componentes visuales cuando haya regresiones específicas.

## 12. Ajustes y Diagnóstico avanzado

### Ajustes

- Run y fuentes: save, ROM/capa, nombre y cambio de run;
- Apariencia e idioma;
- Atajos;
- OBS solo para elegir ruta básica; el uso diario queda en Emisión;
- Seguridad y copias.

### Diagnóstico avanzado

- resumen humano primero: conectado/no conectado y función afectada;
- backend, proceso, revisión y lanes debajo;
- grabar/detener, replay y carpeta;
- errores persistentes copiables;
- controles que generan paquetes marcados como exportación explícita;
- sin offsets editables ni operaciones de RAM arbitraria.

## 13. Sistema de diseño conceptual

### Tokens

```text
Fondos
  canvas       #101113
  surface-1    #17191C
  surface-2    #202328
  surface-3    #292D33

Identidad
  gold-500     dorado RoleRun principal
  gold-300     hover/resalte suave
  gold-muted   superficies seleccionadas, no texto largo

Semántica
  success      confirmación verificada
  warning      pendiente/atención
  danger       fallo o acción destructiva
  info         lectura/estado informativo
  stale        dato conservado no actual

Texto
  primary / secondary / muted / disabled
```

Los valores exactos se validarán por contraste antes de implementar. Los colores
de rol se usan en chip/símbolo y nunca sustituyen al nombre.

### Tipografía y espaciado

- una familia de sistema compatible con Windows; fallback explícito;
- escala: 12 auxiliar, 14 cuerpo, 16 cuerpo destacado, 20 sección, 28 página;
- altura de línea mínima coherente;
- grid base de 4 px; espacios principales 8/12/16/24/32;
- radio 8 para controles, 12 para superficies, modal solo cuando sea necesario;
- sombras mínimas; jerarquía principalmente por superficie y espaciado.

### Componentes

- botón primario dorado, secundario neutral, peligro rojo y texto/ghost;
- chips de rol, origen, capacidad y sincronización;
- fila/celda seleccionable con foco visible;
- banner de atención persistente;
- toast solo para confirmaciones no críticas;
- panel de operaciones para pendiente/fallo/rollback;
- diálogo con título, consecuencia, objeto afectado y acción inequívoca;
- tooltip para iconos, motivo disabled y atajo;
- skeleton solo si no puede conservarse un valor confirmado previo.

### Movimiento

- 120–180 ms para cambios de panel/selección;
- respetar preferencia de movimiento reducido;
- no animar HP, estado confirmado o errores de forma que retrase su lectura;
- nunca usar animación para ocultar el tiempo real de una escritura.

## 14. Patrones de referencia y adaptación

No se propone copiar ninguna aplicación.

### Figma: navegación + selección + inspector contextual

Figma documenta una estructura con panel de navegación izquierdo y panel de
propiedades derecho que cambia con la selección. El patrón resuelve en RoleRun la
separación entre rejilla de PC y detalle, sin abrir otro modal. Se adapta a tres
paneles solo en anchura suficiente; en pequeño, el inspector se vuelve panel
deslizable. Riesgo: saturar la pantalla si todo se hace editable a la vez.

Fuente: [Figma Help — Properties Panel](https://help.figma.com/hc/en-us/articles/360039832014-Design-Prototype-and-view-Code-in-the-Properties-Panel).

### Linear: selección contextual, búsqueda y acciones por teclado

Linear permite actuar sobre una selección mediante toolbar, menú contextual o
command menu, y ofrece búsqueda dentro de la vista. Para RoleRun esto justifica
que seleccionar un Pokémon revele acciones válidas sin repetir botones en cada
tarjeta. No se copia su densidad extrema ni se ocultan las acciones críticas tras
atajos.

Fuentes: [Linear — Select issues](https://linear.app/docs/select-issues),
[Linear — Search](https://linear.app/docs/search) y
[Linear — Display options](https://linear.app/docs/display-options).

### Rejillas y teclado

La guía W3C para grids explica navegación con flechas y foco gestionado; su guía
de interfaz de teclado exige que las funciones interactivas sean operables sin
ratón y que el foco sea predecible. Aunque RoleRun es una app nativa Tk, el patrón
es aplicable a la rejilla del PC y evita decenas de elementos en el orden de Tab.

Fuentes: [W3C APG — Grid Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/grid/)
y [W3C APG — Developing a Keyboard Interface](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/).

### Model/view como opción tecnológica futura

Qt documenta que model/view separa datos de representación y permite que varias
vistas compartan modelo/selección; también incorpora listas, tablas, filtros y
drag and drop. Es relevante si, tras modularizar, CustomTkinter no puede ofrecer
virtualización/accesibilidad suficientes. No demuestra que migrar sea hoy la
decisión correcta.

Fuente: [Qt — Model/View Programming](https://doc.qt.io/qt-6/model-view-programming.html).

## 15. Evaluación del toolkit

### A. Conservar CustomTkinter sin cambios arquitectónicos

**Beneficio:** coste inicial mínimo.  
**Riesgo:** perpetúa monolito, reconstrucciones, Toplevels y componentes
duplicados. No alcanza el objetivo integral.

### B. Modernizar dentro de CustomTkinter — recomendación inicial

**Beneficios:** conserva empaquetado, ciclo Tk, hotkeys, integración Windows y
backends; permite tokens, componentes, paneles y view models incrementales.
CustomTkinter soporta temas, widgets componibles y escalado HighDPI en Windows.
**Costes:** rejillas grandes, drag/drop robusto, virtualización y accesibilidad
requieren trabajo propio; hay que evitar manipular widgets desde workers.

Fuentes: [CustomTkinter — documentación](https://customtkinter.tomschimansky.com/documentation/),
[CustomTkinter — scaling](https://customtkinter.tomschimansky.com/documentation/scaling/)
y [Python — modelo de hilos de Tkinter](https://docs.python.org/3/library/tkinter.html#threading-model).

### C. Migración progresiva a PySide6/Qt

**Beneficios potenciales:** model/view, selección compartida, tablas, drag/drop,
accesibilidad y tooling de escritorio maduros.  
**Costes/riesgos:** nuevo event loop, empaquetado mayor, reimplementación de foco,
ventanas, hotkeys y componentes; coexistir Tk/Qt en un proceso sería de alto
riesgo; amplia superficie de regresión visual y funcional.

Solo debe evaluarse tras extraer contratos de presentación y ejecutar un prototipo
aislado con datos fake. Si se elige, la migración sería una shell alternativa
completa que consuma los mismos servicios, no widgets Qt embebidos en Tk.

### Decisión propuesta

Fases 0–6: modernización modular en CustomTkinter. Al final de la fase de
Equipo/PC, medir con evidencia:

- rendimiento con 1 200 slots;
- navegación por teclado;
- esfuerzo de drag/drop y virtualización;
- consumo, tamaño de distribución y estabilidad;
- coste real de mantener componentes.

Solo esos resultados pueden abrir una decisión Qt. No hay fundamento para migrar
antes.

## 16. Interfaz optimista sin afirmar falsedades

```text
Usuario
  │ comando semántico
  ▼
Preflight local ──fallo──> explicación, sin proyección
  │ válido
  ▼
Projected state + operation=pending
  │ worker existente
  ▼
Writer con precondiciones
  │
  ├─ readback correcto ──> confirmed state + historial
  │
  └─ error/readback distinto
       ├─ rollback técnico existente
       └─ UI vuelve a confirmed state + operación fallida persistente
```

El Pokémon puede moverse visualmente de inmediato, pero conserva patrón/badge de
pendiente y una referencia al origen confirmado. El mensaje debe decir “Aplicando
cambio” y nunca “Cambiado” antes del readback. Si la operación no tiene ruta
realtime, el estado dice “Cambio preparado en el save” y conserva Guardar.

Los obstáculos actuales son el estado repartido en `RoleRunManager`, handlers que
crean cambios y escriben directamente, y reconstrucciones completas. La hoja de
ruta introduce el modelo común antes de cambiar esas operaciones.

