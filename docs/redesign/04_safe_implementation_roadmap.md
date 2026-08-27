# Hoja de ruta de implementación segura

Este plan evita una sustitución total de la UI. Los readers, writers, offsets,
reglas y contratos realtime quedan fuera de las primeras fases. Cada fase debe
ser un commit/checkpoint revisable y conservar un camino de rollback.

## Reglas transversales

1. La UI clásica permanece disponible mediante un flag local hasta lograr
   paridad de todas las filas afectadas.
2. El flag selecciona presentación, no backend ni datos. Ambas interfaces usan
   la misma run y los mismos servicios.
3. No se ejecutan dos ventanas completas a la vez contra un emulador real.
4. Los componentes nuevos se prueban con fixtures/fakes; ningún test escribe en
   RAM o saves personales.
5. Un cambio realtime no se cierra sin validación física en el backend objetivo.
6. Toda operación visible expone confirmado/proyectado/pendiente/fallido.
7. Si la nueva vista necesita “arreglar” un writer para funcionar, la migración se
   detiene y ese bug se investiga por separado.
8. La interfaz clásica no se elimina por calendario: solo por evidencia de
   paridad y ausencia de regresiones.

## Fase 0 — Baseline y arnés visual

### Objetivo

Congelar evidencia de la UI actual y crear mecanismos de comparación sin cambiar
la interfaz entregada.

### Áreas potenciales

- nueva carpeta `app/ui_next/` aún no conectada;
- fixtures de presentación en `tests/ui_next/`;
- capturas de referencia generadas con datos fake;
- flag de configuración solo si puede permanecer desactivado por defecto.

### Incluye

- inventario de resoluciones 1100×720, 1360×860, 1920×1080 y DPI 100/125/150%;
- estados fake: sin run, conectado, error, party 0/1/5/6, PC lleno/vacío, pending;
- helper para construir componentes sin servicios reales;
- prueba de que la versión clásica se abre exactamente igual con el flag off.

### Excluye

Navegación nueva, writers, adaptación de datos, cambios visuales de producción.

### Riesgo y dependencias

Riesgo bajo; depende de poder aislar `RoleRunManager` de hotkeys/procesos en el
arnés. Si no se puede, usar componentes hijos con root de test, no instanciar la
app completa.

### Tests

- suite completa actual;
- smoke clásico con flag off;
- render de fixtures sin emulador;
- `git diff` sin assets personales.

### Prueba manual

Abrir una vez interfaz clásica y comprobar selector/run; no probar operaciones.

### Aceptación / rollback

Aceptada si no hay diferencia funcional ni visual con flag off. Rollback: retirar
solo arnés/flag; no hay migración de datos.

## Fase 1 — Tokens y componentes atómicos

### Objetivo

Crear el lenguaje visual reutilizable sin reemplazar páginas.

### Áreas

- `app/ui_next/tokens.py`;
- botones, chips, status badge, banner, input, tooltip, empty/error state;
- catálogo de componentes solo en modo desarrollo/test.

### Incluye

Estados normal, hover, focus, selected, disabled, pending, success, warning,
danger y stale; escalado y contraste.

### Excluye

Lectura de run, navegación, drag/drop y operaciones reales.

### Riesgos

- contraste insuficiente del dorado;
- fuentes o símbolos distintos según Windows;
- componentes que dependen de tamaños fijos.

### Tests

- construcción/destrucción;
- navegación de foco y activación por teclado;
- snapshots visuales en resoluciones objetivo;
- verificación automatizada de tokens y estados disponibles.

### Prueba manual

Revisar una única lámina de componentes a 100% y 150% de escala.

### Aceptación / rollback

Todos los estados son distinguibles sin depender solo del color. Rollback:
componentes aislados no referenciados por producción.

## Fase 2 — Modelo de presentación y Centro de operaciones

### Objetivo

Expresar procedencia, capacidades y ciclo de operación antes de mover controles.

### Áreas

- view models inmutables;
- adaptador de lectura desde `RoleRunManager`, `RunProject`, `RunSession` y
  snapshot actual;
- `OperationPresentation` y panel sin comandos nuevos.

### Incluye

- estados confirmado/proyectado/pendiente/fallido/stale;
- capabilities por sesión derivadas exclusivamente de rutas ya demostradas;
- traducción de cambios pendientes y lotes live existentes;
- prioridad de atención y errores persistentes.

### Excluye

Cambiar la manera de ejecutar writers o reconciliar PC.

### Riesgos

Duplicar autoridad o etiquetar como confirmado un override. Debe ser una
proyección sin mutaciones.

### Tests

- matrices save/realtime/desconectado;
- lane opcional fallida con party válida;
- operación clásica preparada frente a live pendiente de readback;
- ningún método del view model toca backend.

### Prueba manual

Con una run abierta, comparar el estado nuevo en modo diagnóstico con cabecera,
Equipo y Revisar cambios; no ejecutar acciones.

### Aceptación / rollback

Todos los valores coinciden y muestran procedencia correcta. Rollback: desactivar
consumidor; fuentes actuales no cambian.

## Fase 3 — Nueva shell e Inicio, solo lectura

### Objetivo

Pilotar navegación, densidad y estado de conexión con una pantalla sin escrituras.

### Áreas

- shell alternativa;
- sidebar contraíble;
- Inicio;
- selector de UI clásica/nueva en configuración de desarrollo.

### Incluye

Resumen de equipo, contadores, conexión, atención y actividad reciente; links a
páginas clásicas para funciones aún no migradas.

### Excluye

Editar contadores, roles, Equipo/PC, MT y diagnóstico.

### Riesgos

Dos sistemas de navegación, focus de barra flotante y cambio de run.

### Tests

- navegación ratón/teclado;
- sidebar ancho/contraído;
- Inicio por estado fixture;
- cambio de run con pendientes;
- barra flotante restaura la página correcta;
- suite de foco Windows relevante.

### Prueba manual

Abrir una run sin operar, minimizar/restaurar y alternar UI clásica/nueva.

### Aceptación / rollback

Inicio refleja exactamente el mismo estado y la barra no cambia de conducta.
Rollback inmediato mediante flag.

## Fase 4 — Registro, Cementerio y Progreso de solo lectura

### Objetivo

Migrar vistas de bajo riesgo y hacer visibles datos hoy dispersos.

### Incluye

- timeline con filtros;
- Cementerio y bajas pendientes, sin nuevas acciones;
- Progreso con origen automático/manual;
- recursos solo informativos;
- eventos desconocidos con fallback neutral.

### Excluye

Editar contadores, sustituir bajas, limpiar historial o invocar utilidades.

### Riesgos

Interpretar eventos históricos heterogéneos o prometer datos no almacenados.

### Tests

- fixture por tipo de evento;
- historial vacío/grande/corrupto controlado;
- baja pendiente vs enterrada;
- labels por juego;
- automático no presenta +/-.

### Prueba manual

Comparar contadores/historial/cementerio con la UI clásica en una run existente.

### Aceptación / rollback

No desaparece ningún evento y no se ofrecen acciones falsas. Flag permite volver.

## Fase 5 — Equipo y PC de solo lectura

### Objetivo

Validar la pantalla de tres paneles, selección, búsqueda y rendimiento antes de
autorizar movimientos.

### Incluye

- party, caja, búsqueda, filtros, inspector y navegación de cajas;
- lectura de proyección existente, incluido live/stale/overrides;
- selección por teclado y ratón;
- actualización externa conservando selección cuando la identidad sigue viva;
- fallback a tabs en ancho pequeño.

### Excluye

Drag/drop y toda escritura.

### Riesgos

1 200 celdas potenciales, caché de sprites, polls de BDSP y coherencia party-PC.

### Tests

- 0/1/30/1 200 slots;
- búsqueda actual completa;
- misma identidad nunca simultánea en party/PC;
- lectura fallida conserva vista válida con stale;
- poll se cancela al salir/minimizar;
- navegación de caja y foco.

### Prueba manual

En un solo juego piloto, mover un Pokémon dentro del juego y comprobar que la
nueva vista refleja el cambio. No mover desde RoleRun.

### Aceptación / rollback

Paridad de lectura con Toplevel actual, sin bloqueos perceptibles ni selección
fantasma. La página clásica sigue accesible.

## Puerta tecnológica después de Fase 5

Medir tiempo de primera carga, cambio de caja, búsqueda, memoria, estabilidad de
foco y esfuerzo real de accesibilidad/virtualización. Solo si CustomTkinter no
alcanza criterios definidos se autoriza un prototipo PySide6 aislado. El prototipo
no se conecta a RAM y no cambia el plan de producción sin decisión separada.

## Fase 6 — Comandos sin drag: roles y contadores

### Objetivo

Migrar primeras mutaciones usando botones/menús y servicios actuales.

### Incluye

- +/- manual en Progreso;
- cambiar/transferir rol desde inspector;
- visibilidad OBS;
- Centro de operaciones y readback actual;
- alternativas de teclado.

### Excluye

Equipo↔PC, MT, bajas y drag/drop.

### Riesgos

Rol ocupado, marcadores por juego, contador automático y sincronización OBS.

### Tests

- todas las regresiones de roles/markers;
- automático bloquea edición;
- mismo comando clásico/nuevo;
- pending/success/failure/rollback visual;
- OBS y barra reflejan una sola proyección.

### Prueba manual

Cambiar un rol y un contador manual en el juego/backend piloto; confirmar juego,
RoleRun, barra y OBS.

### Aceptación / rollback

Resultado y timing equivalentes a UI clásica. Si difieren, desactivar comandos
nuevos sin cambiar backend.

## Fase 7 — Equipo↔PC mediante comandos explícitos

### Objetivo

Migrar movimientos sin introducir todavía drag/drop.

### Subfases independientes

1. swap 1↔1;
2. retirar 6→5;
3. incorporar 5→6;
4. PC→PC solo donde esté demostrado;
5. reordenar party solo donde esté demostrado.

Cada subfase tiene capability propia y no puede heredar aceptación de otra.

### Incluye

Preview origen/destino, preflight, pending, worker existente, readback, error y
rollback visual. El rol heredado aparece en preview.

### Excluye

Sustitución por muerte y nuevos writers.

### Riesgos

Críticos: identidad stale, tamaño de party, PC lleno, rol séptimo, duplicación
party-PC, mirrors, save vs live.

### Tests

- suites completas de PC/writers por backend;
- regresión de cada subfase;
- cambio concurrente entre preview y write;
- vecinos intactos y operación no soportada invisible/bloqueada;
- error readback restaura selección y estado confirmado.

### Prueba manual

Una operación mínima por subfase y backend habilitado. No repetir comprobaciones
equivalentes si el mismo contrato ya quedó validado y no cambió.

### Aceptación / rollback

Readback y estado visual coinciden; no queda séptima tarjeta ni duplicado. Se
deshabilita solo la capability nueva ante fallo.

## Fase 8 — Drag and drop accesible

### Objetivo

Añadir un acelerador visual sobre comandos ya validados.

### Incluye

- destinos y verbos explícitos;
- preview;
- cancelación Esc;
- menú/botón equivalente;
- teclado para seleccionar origen y destino;
- drag de rol visualmente distinto del movimiento físico.

### Excluye

Nuevas operaciones o cambio en backend.

### Riesgos

Gesto ambiguo, scroll durante drag, DPI, pérdida de foco y soltar sobre destino
equivocado.

### Tests

- tabla completa origen/destino válido/inválido;
- escalas 100/125/150%;
- cancelación, ventana pierde foco, cambio de caja durante drag;
- equivalencia de comando con botón;
- no se ejecuta operación al solo seleccionar.

### Prueba manual

Un swap con drag y el mismo swap con botón en fixture o save de prueba; en realtime
solo tras pasar pruebas automáticas.

### Aceptación / rollback

El drag emite exactamente el comando ya validado. Rollback: desactivar gesto;
botones mantienen paridad.

## Fase 9 — Movimientos y MT

### Objetivo

Dar una superficie MT-primero y unificar explicación de compatibilidad.

### Subfases

1. Movimientos/MT solo lectura;
2. enseñar en slot vacío;
3. sustituir;
4. eliminar movimiento;
5. integración con drafteos.

### Riesgos

Fuente ROM/capa, IDs localizados, posesión, PP, consumo, reglas vs legalidad y
backend no disponible.

### Tests

- todos los perfiles y UI TM por juego;
- motivo exacto de incompatibilidad;
- cantidad antes/después;
- slot/movimiento/PP readback;
- fuente cambia o desaparece;
- projected/failure/rollback.

### Prueba manual

Enseñar una MT poseída a un Pokémon compatible sustituyendo un movimiento; comprobar
movimiento y cantidad. Solo una vez por contrato modificado.

### Aceptación / rollback

Mismo writer, mismas precondiciones, misma verificación que la UI clásica. La
pantalla nueva nunca habilita una MT que el selector clásico bloquearía.

## Fase 10 — Bajas, sustitución y Cementerio operativos

### Objetivo

Integrar la bandeja de bajas sin tocar detección ni timing.

### Incluye

- notificación/bandeja persistente;
- selector nuevo que consume el mismo evento pendiente;
- sustitución y Cementerio con writer actual;
- varios KO en cola;
- reabrir pendiente al restaurar app.

### Excluye

Cualquier cambio en lectores HP, `LivePartyWatch` o compromiso de muerte.

### Riesgos

Críticos: selector antes de fin de combate, doble muerte, segunda ventana oculta,
cementerio lleno y foco con barra flotante.

### Tests

- primer KO, dos KO, conexión dentro/fuera, fin de combate, reconexión, falso
  positivo y cola de dos pickers;
- regresiones de floating/faint picker;
- cierre/reapertura;
- rollback writer y persistencia exactamente una vez.

### Prueba manual

Un combate con un KO y sustitución; solo añadir dos KO si el código de cola/modal
ha cambiado. La prueba debe ser breve y dictada por la diferencia implementada.

### Aceptación / rollback

El momento de cobro y apertura coincide con la UI clásica físicamente validada.
Rollback: volver al picker clásico sin perder `pending_faints`.

## Fase 11 — Emisión, Ajustes y Diagnóstico

### Objetivo

Terminar la reorganización de funciones de soporte.

### Incluye

- preview OBS y visibilidad;
- apertura/configuración de barra;
- Ajustes agrupados;
- Diagnóstico avanzado y errores persistentes;
- hotkeys y ayuda de atajos.

### Excluye

Cambio de formato OBS, recorder, paquetes, bridges o lógica Win32.

### Riesgos

Rutas, permisos, hotkeys globales, focus/grab y exportación accidental.

### Tests

- archivos OBS iguales antes/después;
- hotkeys, conflictos y foco;
- recorder/replay sin RAM real;
- paquetes solo por acción expresa;
- barra al minimizar/restaurar en cada página nueva.

### Prueba manual

Comprobar una escena OBS y minimizar/restaurar con barra. No repetir operaciones
de juego ya validadas.

### Aceptación / rollback

Salidas OBS byte/semánticamente equivalentes y cero cambios en ciclo de barra.

## Fase 12 — Retirada controlada de la interfaz clásica

### Precondiciones

- matriz completa en `paridad` para todos los juegos soportados;
- suite completa verde;
- pruebas visuales y teclado en resoluciones objetivo;
- validación física de toda función realtime cuyo control/timing cambió;
- al menos una versión estable con UI nueva por defecto y clásica disponible;
- migración de configuración reversible o inexistente;
- documentación/ayuda actualizada;
- no hay bug crítico exclusivo de la UI nueva.

### Retirada

1. ocultar selector clásico para runs nuevas, conservar flag de emergencia;
2. observar una versión;
3. retirar rutas clásicas página por página;
4. conservar adapters/comandos y tests funcionales;
5. eliminar flag solo tras un último checkpoint etiquetable.

### Rollback

Mientras exista el flag, volver a clásica. Después, `git revert` del commit de
retirada, no reset destructivo. Los datos de run nunca deben requerir downgrade.

## Estrategia de pruebas total

### Unitarias

Tokens, view models, capabilities, reducers de operaciones, filtros, selección y
comandos semánticos.

### Integración

Componentes con fakes de GameEngine/adapter; mismos fixtures pasan por handler
clásico y nuevo y comparan el comando resultante.

### Visuales

Capturas deterministas sin datos personales en cuatro resoluciones y tres escalas;
comparación revisada, no actualización automática para esconder cambios.

### Accesibilidad/teclado

Orden de Tab, foco visible, flechas en rejillas, Enter/Esc, alternativas a drag,
disabled con explicación y texto junto a colores.

### Manuales

Solo para foco/Windows, OBS y contratos realtime afectados. Cada entrega debe pedir
la mínima prueba que discrimine el cambio realizado; si no se cambió el contrato,
no se repite por rutina.

## Criterio de parada

Si dos iteraciones de una pantalla desplazan el mismo fallo de selección, estado o
sincronización, detener el ajuste visual. Reconstruir desde autoridad → view model
→ selección → comando → writer → readback → render y localizar la primera
divergencia antes de un tercer parche.

