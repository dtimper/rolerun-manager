# BDSP / Ryujinx — matriz maestra de paridad realtime

Fecha de corte: 2026-08-22.

## Objetivo y criterio de terminado

Este documento es el checklist maestro de Pokémon Diamante Brillante / Perla
Reluciente sobre Ryujinx. La meta es reproducir la experiencia funcional madura
de RoleRun en 3DS, no trasladar sus direcciones ni copiar sus estructuras. BDSP
es Gen 8, usa PB8 y objetos Unity/IL2CPP; Ryujinx expone memoria invitada mediante
un transporte y un ciclo de proceso distintos de Azahar/Citra.

Una capacidad dependiente de RAM o emulador solo se cierra cuando concurren las
cuatro condiciones siguientes:

1. implementación en el flujo de producción;
2. regresión causal automatizada;
3. suite completa verde;
4. validación física del usuario en la combinación exacta de juego, revisión y
   emulador.

Los estados de la matriz son evidencias acumulables, no una escala que permita
saltar comprobaciones:

- **NO INICIADO**: no existe investigación o implementación realtime de BDSP;
- **INVESTIGANDO**: existe una candidata o captura, pero aún falta demostrar el
  contrato completo;
- **READER VALIDADO**: lectura de producción estructuralmente validada y cerrada
  ante ambigüedad;
- **WRITER VALIDADO**: writer con precondiciones, readback y rollback demostrados;
- **IMPLEMENTADO**: integrado en Adapter/Core/UI, sin implicar por sí solo cierre;
- **TEST AUTOMÁTICO**: existe una regresión determinista específica;
- **VALIDADO FÍSICAMENTE**: el usuario confirmó el comportamiento dentro de la
  partida real.

Cuando una celda contiene varios estados, todos ellos están demostrados para el
alcance descrito. Una capacidad sobre save puede estar **IMPLEMENTADA** mientras
su variante realtime permanece **NO INICIADA**.

## Evidencia BDSP disponible y límites

- Entorno demostrado: Perla Reluciente `1.3.0`, Title ID
  `010018E011D92000`, Ryujinx `1.3.3+e2143d4`, Windows x64 y
  `HostMappedUnsafe`.
- `app/ryujinx_gdb.py` queda como diagnóstico GDB. `app/ryujinx_host_memory.py`
  y `RyujinxBridge` mantienen la captura HostMapped con un handle exclusivamente
  de consulta/lectura. Alpha.75 añade `app/ryujinx_host_write.py`: abre RW solo
  durante una transacción precondicionada y lo cierra al terminar.
- `BDSPBoxReader` aplica la cadena demostrada de cajas SP 1.3.0, doble lectura,
  dimensiones 40×30, longitud 344 y checksum. La prueba física sin GDB produjo
  11 ocupados y 1.189 vacíos válidos. Está conectado a la UI como lane PC de
  lectura. El writer cubre el swap 1↔1 y el cambio de cola 5↔6 de alpha.82,
  ambos validados físicamente; alpha.83 añade la compactación intermedia
  demostrada y pendiente de su prueba iniciada desde RoleRun.
- La primera colección de seis PB8 hallada en `SaveData.playerParty` no cambió
  tras daño físico y queda rechazada como fuente live. El source exacto de
  OpenDPR demostró la separación con el campo no serializado
  `PlayerWork._playerParty`; `BDSPPartyReader` implementa esta segunda fuente y
  la validación física confirmó sus seis identidades y HP fuera de combate.
- `BDSPBattleReader` implementa la fuente independiente
  `BattleProc → MainModule → BattleEnv → POKECON → BTL_PARTY`. En un combate
  salvaje simple publicó el daño `67→58` mientras la party normal seguía
  atrasada; al salir, la party normal convergió 608 ms antes de desaparecer la
  fuente de batalla. Una segunda captura demostró `7/21→0/21`, la reordenación
  de filas al elegir sustituto y la convergencia tardía de PlayerWork. Los
  combates especiales siguen pendientes.
- `BDSPEngine`/`RoleRun.SaveEngine` cubren operaciones de save, pero no se usan
  como prueba de RAM. El layout runtime del writer alpha.75 procede de OpenDPR
  `5b0cb0c8...` y de los readers SP 1.3.0 validados físicamente.
- `BDSPRealTimeAdapter` está registrado y publica party y battle health en
  Core/UI. Mantiene una conexión HostMapped, valida cada fila por
  PokeID/especie/nivel/HP máximo y aísla un fallo de batalla de la party válida.
  `BDSPLiveWriter` está registrado para roles/movimientos de party y consumo
  atómico de MT. PC cubre swap 1↔1 y cola 5↔6 con los límites documentados;
  alpha.85 añade las tres utilidades con writer transaccional y alpha.86 corrige
  la identidad/inserción de Repelente Máximo; progreso solo
  publica las medallas leídas.

Fuentes canónicas: `docs/BDSP_REALTIME_BASELINE.md`, `docs/CURRENT_STATE.md`,
`docs/REALTIME_CORE.md`, `docs/GAME_ENGINES.md` y
`diagnostics/manual/bdsp_sp130_gdb_control_20260822_142756.json`.

## 1. Conexión y sesión

| ID / capacidad | Comportamiento de referencia exacto y código actual | Estado BDSP | Evidencia que falta | Prueba física necesaria | Dependencias |
|---|---|---|---|---|---|
| C1 · Juego, revisión y emulador | El backend exige GDB apagado, `HostMappedUnsafe`, un proceso, Title ID y revisión exactos desde el título activo generado por Ryujinx; después valida la huella de `main`. `app/ryujinx_host_memory.py`, `app/bdsp_live.py`. | SP 1.3.0 HostMapped: **READER VALIDADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | Falta DI 1.3.0 y cualquier otra revisión; no se extrapola la huella. | Ninguna adicional para SP 1.3.0; repetir perfil completo al incorporar otra edición/revisión. | Perfil por juego/revisión; host mapping único. |
| C2 · Módulo `main` | GDB obtiene módulos en diagnóstico; HostMapped busca la huella completa de la revisión solo en pares Base/Mirror y exige exactamente un candidato. | **READER VALIDADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | Añadir una huella independiente por revisión futura. | Completada: reinicio con nueva dirección host y redescubrimiento único. | C1. |
| C3 · Conexión/desconexión | La UI inicia y detiene el transporte sin bloquear Tk; el Core deja de publicar datos si la sesión desaparece. `RealTimeCore`, hooks de `app/ui.py`; referencia Citra en `app/citra_gdb.py`. | **IMPLEMENTADO · TEST AUTOMÁTICO** | Falta validación física de desconexión/reconexión. | Cerrar y reabrir el juego con RoleRun abierto. | C1, adapter BDSP. |
| C4 · Reinicio de emulador | PID, base, punteros, cachés y baseline anterior se invalidan; la nueva sesión no produce eventos retrospectivos. `reset_runtime_state()` de adapters y `LiveBlockResolver`. | **NO INICIADO** | Clave de sesión Ryujinx y regresión de invalidación. | Reiniciar Ryujinx, volver al mismo save y comprobar que no aparecen cambios o muertes falsos. | C2, S3, M3. |
| C5 · Rechazo de título incorrecto | Un Title ID distinto se rechaza antes de usar cadenas BDSP. `RyujinxGDBClient.require_title_id()`. | **IMPLEMENTADO · TEST AUTOMÁTICO** | Integración UI/Core y prueba física no destructiva con otro título solo si resulta necesaria. | Ninguna para cerrar el algoritmo; basta la regresión y la suite al integrarlo. | C1. |
| C6 · Memoria desaparecida | Una lectura fallida/incompleta no se convierte en party vacía ni borra UI/OBS; el lane queda inválido/stale de forma visible. `RealTimeSnapshot.diagnostics`, adapters 3DS. | **IMPLEMENTADO · TEST AUTOMÁTICO** para lane de batalla; sesión completa pendiente | El Core conserva el último snapshot si falla la captura principal; falta validación física de cierre/suspensión. | Suspender/cerrar el juego durante una sesión conectada. | C3, S4, S5. |
| C7 · State-load/cambio de save | Cualquier salto de estado invalida punteros, snapshots, roles proyectados y baseline de HP. Referencia: reset de adapters y reglas de `AGENTS.md`. | **NO INICIADO** | Señal detectable o invalidación conservadora demostrada en Ryujinx. | Cargar otro save/estado de forma controlada y comprobar resincronización sin eventos falsos. | C4, P2, M3. |
| C8 · Selección automática de backend | El Core ve un único adapter del juego; bridge/emulador no filtran offsets a UI. `RealTimeGameAdapter`, `XYMultiRealTimeAdapter`. | Transporte: **IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE**; selección UI: **IMPLEMENTADO · TEST AUTOMÁTICO** | Falta validar físicamente la conexión automática de la versión integrada. | Abrir una Run BDSP con GDB apagado y verificar conexión automática. | C1–C3, S2–S4. |

## 2. Party en tiempo real

| ID / capacidad | Comportamiento de referencia exacto y código actual | Estado BDSP | Evidencia que falta | Prueba física necesaria | Dependencias |
|---|---|---|---|---|---|
| P1 · Colección de seis slots | Publicar entre 1 y 6 miembros válidos, sin inventar huecos. Readers específicos y `SaveGameData.party`. | Party, cola 5↔6 y compactación intermedia: **READER VALIDADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | Ciclo base de tamaño cerrado. | Ninguna adicional para 1–6. | C1–C2. |
| P2 · Identidad estable | Especie+PID+TID+SID identifica al miembro a través de orden/cambios. `pokemon_identity()` en Core y watcher. | Reordenación, Equipo↔PC alpha.81 y dos bajas alpha.84: **READER/WRITER VALIDADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | Reinicio/reconexión pertenece a C4/M10. | Ninguna adicional para sustitución en la misma sesión. | P1. |
| P3 · Especie, forma y nombre | Decodificación PB8 correcta, incluidas formas, apodo y huevo. `BDSPEngine` es referencia de formato de save, no de dirección runtime. | **INVESTIGANDO** | Fixture anonimizado con formas/huevo y parser runtime demostrado. | Equipo con al menos una forma o apodo; confirmar presentación exacta. | P1–P2. |
| P4 · HP actual y máximo | Snapshot estable publica HP de party; combate puede ser un lane distinto. Readers SM/USUM y `BattleState`. | Readers party/batalla: **READER VALIDADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** para daño, KO, cambio y salida; snapshot: **IMPLEMENTADO · TEST AUTOMÁTICO** | Falta validar físicamente la publicación integrada y otros tipos de combate. | Debilitar el primer miembro con RoleRun integrado y comprobar el contador inmediato. | P1–P2, M1–M2. |
| P5 · Nivel | Cambios en juego generan `LEVEL_CHANGED` sin sustituir identidad. `app/realtime/events.py`. | Campo/reader: **READER VALIDADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** en valores estáticos | Falta adapter y una transición de nivel real. | Ganar un nivel y comprobar actualización inmediata después de integrar el adapter. | P1–P3, C8. |
| P6 · Movimientos | Los cuatro IDs se leen del juego y un cambio externo genera `MOVES_CHANGED`. Readers 3DS, Core events. | **READER/ADAPTER IMPLEMENTADO · TEST AUTOMÁTICO** | Falta validar una transición externa real. | Aprender, olvidar o reordenar un movimiento dentro del juego. | P1–P2, V1. |
| P7 · PP | PP/PP Ups se mantienen coherentes con los movimientos y no se reconstruyen por intuición. Writers/readers 3DS y PKHeX. | Reader/writer alpha.75 y PP inicial tras MT alpha.76: **VALIDADO FÍSICAMENTE** | Falta validar el decremento posterior al usar el movimiento; no afecta al writer ya confirmado. | Usar una vez el movimiento enseñado y observar el PP. | P6, B1. |
| P8 · Objeto equipado | El objeto vivo cambia sin sustituir al Pokémon. `SavePokemon.held_item`; readers de party. | **NO INICIADO** | Campo y estabilidad en PB8 runtime. | Equipar/retirar un objeto desde el juego. | P1–P2. |
| P9 · Orden y composición juego→RoleRun | Core distingue `ORDER_CHANGED` de `PARTY_CHANGED`; UI, OBS y metadata se reconcilian. `events.py`, `app/ui.py`, `app/live_pc_mirror.py`. | Reordenación, composición equipo↔PC y PC↔PC alpha.72: **VALIDADO FÍSICAMENTE** | Escrituras iniciadas por RoleRun se validan por separado. | Ninguna para lectura juego→RoleRun. | P1–P3, PC2. |
| P10 · Captura estable por lanes | Party válida sobrevive a fallo opcional de PC, inventario, batalla o progreso. Adapters 3DS y `RealTimeSnapshot.diagnostics`. | Party/batalla/PC: **READER VALIDADO · TEST AUTOMÁTICO**; party/batalla validadas físicamente | PC se ejecuta como lectura opcional serializada y conserva la vista anterior al fallar; falta validarlo durante una transición real. | La prueba PC2. | C6, S3–S5. |

## 3. Roles

| ID / capacidad | Comportamiento de referencia exacto y código actual | Estado BDSP | Evidencia que falta | Prueba física necesaria | Dependencias |
|---|---|---|---|---|---|
| R1 · Seis marcadores | Mapeo uno a uno de Líbero, Asesino, Mago, Tanque, Prisma y Support, sin duplicados silenciosos. `app/role_rules.py`, `app/ui.py`, SaveEngine. | Reader validado; writer alpha.75: **IMPLEMENTADO · TEST AUTOMÁTICO** | Falta validar físicamente una escritura con layout 2. | Cambiar un rol desde RoleRun y comprobar la marca dentro del juego. | P1–P3. |
| R2 · Juego→RoleRun | Un marcador cambiado en el juego actualiza rol, UI, barra y OBS. Adapters 3DS y `ROLE_CHANGED`. | **NO INICIADO** | Reader de marking y prueba de cambio externo. | Cambiar una marca en el juego y observar actualización. | R1, P9. |
| R3 · RoleRun→juego | Asignar rol escribe la unidad PB8 demostrada, preserva identidad y verifica readback. Writers 3DS. | Escritura de marcador dentro de `replace-fainted` alpha.84: **IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | El botón manual de cambio de rol conserva su prueba propia; no se infiere de la sustitución. | Cambiar un rol manualmente si se quiere cerrar también ese punto de entrada. | P1–P3, S6–S8. |
| R4 · Swap atómico de roles | Si el rol está ocupado, ambos marcadores se intercambian en una transacción; no queda un estado intermedio. `app/role_swap.py`, tests SM/ORAS. | Writer batch disponible: **IMPLEMENTADO · TEST AUTOMÁTICO** | Falta validación física del intercambio. | Intercambiar dos roles ocupados. | R3. |
| R5 · Autoasignación | Un miembro nuevo recibe el primer rol libre según las reglas, nunca uno supuesto por slot. UI/RunService y writers PC 3DS. | Alpha.82 BDSP, incorporación al sexto hueco: **IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | Otras transiciones de tamaño requieren su propia evidencia. | Ninguna adicional para el caso de cola. | P9, PC4, R2. |
| R6 · Herencia en sustitución | Todo swap 1↔1 preparado por RoleRun hereda el rol de la plaza saliente; la sustitución de un fallecido usa el mismo contrato. `PendingTeamChange`, SaveEngine y writers PC 3DS. | Swap alpha.81 y baja alpha.84: **IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | El marcador del sustituto coincidió dentro del juego con RoleRun. | Ninguna adicional para estos dos flujos. | M1–M9, PC3–PC8, R3. |
| R7 · Último rol en PC | RoleRun recuerda el rol del Pokémon guardado y lo recupera al volver, sin confundir identidad/slot. `app/boxed_metadata.py`, PC mirror. | Save: **IMPLEMENTADO · TEST AUTOMÁTICO**; realtime: **NO INICIADO** | Reconciliación con PC live BDSP y cambios externos. | Enviar al PC, cambiar la sesión y recuperar el mismo Pokémon. | PC1–PC5, P2. |

## 4. Movimientos y drafteo

| ID / capacidad | Comportamiento de referencia exacto y código actual | Estado BDSP | Evidencia que falta | Prueba física necesaria | Dependencias |
|---|---|---|---|---|---|
| V1 · Detección juego→RoleRun | IDs, orden y huecos de movimientos se reflejan en la UI y generan evento. Readers/adapters 3DS, `events.py`. | **IMPLEMENTADO · TEST AUTOMÁTICO** | Falta una transición física iniciada dentro del juego. | Aprender o reordenar un movimiento dentro del juego. | P6. |
| V2 · Sustitución RoleRun→juego | Reemplaza exactamente un slot y establece PP coherente sin alterar vecinos. Writers 3DS; SaveEngine `replace-move`. | RAM alpha.76: **VALIDADO FÍSICAMENTE** | La prueba cubre sustitución por MT; eliminación independiente conserva su validación automatizada. | Cubierto el 2026-08-22 dentro del juego. | V1, P7, S6–S8. |
| V3 · Eliminación y compactación | Borrar un movimiento deja una representación válida y compacta cuando el juego lo exige. Tests de reemplazo/acciones. | UI validada; RAM alpha.75: **IMPLEMENTADO · TEST AUTOMÁTICO** | Falta comprobar dentro del juego la compactación runtime. | Eliminar un ataque y revisar orden/PP dentro del juego. | V2. |
| V4 · Reglas por rol | Legalidad del juego, compatibilidad de MT y restricciones RoleRun se muestran como capas distintas. `app/role_rules.py`, UI y tests alpha17. | **IMPLEMENTADO · TEST AUTOMÁTICO** en lógica común | Validar que datos BDSP/randomizer alimentan la misma regla al usar estado live. | Probar un movimiento permitido y otro restringido para el rol. | V1, T1–T2. |
| V5 · Drafteo | Selección/reroll/contador y revisión pendiente conservan el flujo actual. `app/ui.py`, RunProjectService, OBS. | Save/UI: **IMPLEMENTADO**; integración realtime: **NO INICIADO** | Sincronización tras writer y rechazo de snapshot stale. | Completar un drafteo y comprobar juego, contador y OBS. | V2, O2. |
| V6 · Verificación posterior | Readback desde RAM real prueba ID, PP y los otros tres slots; fallo revierte bytes previos. Writers 3DS. | Alpha.75: **IMPLEMENTADO · TEST AUTOMÁTICO** con fallo inyectado y rollback | Falta el éxito físico V2/V3; no se fuerza un fallo real. | Se cubre con V2/V3. | V2–V3, S6–S8. |

## 5. PC y sustituciones de equipo

| ID / capacidad | Comportamiento de referencia exacto y código actual | Estado BDSP | Evidencia que falta | Prueba física necesaria | Dependencias |
|---|---|---|---|---|---|
| PC1 · 40 cajas × 30 | Lee ocupación, identidad, caja y slot completos; no confunde vacíos. `read_pc()` de adapters 3DS y SaveEngine `read-boxes`. | Alpha.70: **READER VALIDADO · IMPLEMENTADO · TEST AUTOMÁTICO · SONDA FÍSICA 11/1200** | Falta validar la publicación visual tras una mutación real. | Depositar un Pokémon desde el juego. | C1–C4, P2. |
| PC2 · Cambios hechos en el juego | Un movimiento externo actualiza PC/party y metadata sin exigir guardar. Live PC mirror/reconciler y tests SM/XY. | Equipo↔PC alpha.71 y PC↔PC alpha.72: **VALIDADO FÍSICAMENTE** | Cambios con búsqueda activa quedan como caso de robustez, no bloquean el carril base. | Ninguna para el ciclo base. | PC1, P9. |
| PC3 · Equipo→PC | Selecciona destino vacío válido, actualiza tamaño de party y verifica origen/destino/conteo. Writers SM/USUM/ORAS; SaveEngine `party-to-box`. | Último miembro alpha.82 y miembro intermedio alpha.83: **WRITER VALIDADO · IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | El ciclo de depósito queda cerrado para cola y posición intermedia. | Ninguna adicional para el depósito base. | P1, PC1, S6–S8. |
| PC4 · PC→Equipo | Usa hueco libre demostrado, limpia el origen con vacío válido y asigna rol. Writers 3DS; SaveEngine `box-to-party`. | Alpha.82, siguiente slot fijo: **WRITER VALIDADO · IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | El ciclo base de cola está cerrado. | Ninguna adicional para incorporación al siguiente slot. | PC1, P1, R5, S6–S8. |
| PC5 · Swap 1↔1 | Intercambia PB8 completos y runtime auxiliar requerido sin perder identidad, stats u objetos. Writers 3DS; SaveEngine `swap-party-box`. | Alpha.81: **VALIDADO FÍSICAMENTE** en SP 1.3.0 / Ryujinx | Recorrido base cerrado: selector live, intercambio dentro del juego y readback. Quedan fuera los cambios de tamaño. | Ninguna para el caso base 1↔1. | PC1, P1–P4, S6–S8. |
| PC5b · Intercambio PC↔PC | Cruza dos huecos de caja **ocupados los dos**, sin tocar la party y sin ningún vacío canónico de por medio. `BDSPLiveWriter._apply_box_swap`; SaveEngine `swap-box-slots`. | Alpha.27 (05-09-2026): **IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE en la misma caja** (06-09-2026: tres escrituras correctas al primer intento) | Son las mismas dos escrituras de 344 bytes de `move-box-slot`, cruzadas; las dos identidades son ancla, así que ninguna casilla vacía interviene en la calibración. | **PENDIENTE**: intercambiar dos ocupadas de cajas DISTINTAS. Hasta alpha.28 ni siquiera se podía montar ese caso: mover a otra caja fallaba (ver PC11). | PC1, PC11, PC12. |
| PC6 · Tamaño de party | Conteo 1–6, compactación y huecos obedecen la representación BDSP real; nunca se infieren de Gen 7. Tests alpha36/44. | Cola alpha.82 y compactación intermedia alpha.83: **DEMOSTRADO · WRITER VALIDADO · IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | El contrato base 1–6 queda cerrado. | Ninguna adicional para el tamaño base. | PC3–PC4. |
| PC7 · Selector y búsqueda | UI carga PC fuera del hilo Tk, permite buscar/filtrar y no duplica ventanas. `app/ui.py::open_pc_selector`, preload del faint picker. | Repintado automático BDSP alpha.71: **VALIDADO FÍSICAMENTE** | Búsqueda con una mutación concurrente queda fuera de esta prueba. | Se cubrirá al ampliar los casos PC, si resulta necesario. | PC1, U1–U4. |
| PC8 · Sustitución de fallecido | La operación `replace-fainted` usa la identidad pendiente y el rol heredado, no solo el slot visual. Faint picker y writers 3DS. | Uno y dos KO + marcador heredado alpha.84: **WRITER VALIDADO · IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | Flujo base cerrado; reconexión y combates especiales son capacidades distintas. | Ninguna adicional para el caso base. | M1–M9, PC5, R6. |
| PC9 · Último rol y metadata | Cambios externos y operaciones RoleRun conservan metadata por identidad. `app/boxed_metadata.py`, `app/live_pc_mirror.py`. | Alpha.70 conserva campos PB8 live y nivel por ancla fuerte: **IMPLEMENTADO · TEST AUTOMÁTICO** | Validar físicamente rol/icono en depósito y recuperación; reinicio queda aparte. | La prueba PC2 y después un reinicio. | PC2, R7. |
| PC10 · Cementerio | El fallecido queda registrado exactamente una vez y no vuelve al equipo mediante el selector normal. RunProjectService/RunService y UI. | Colocación de uno y dos debilitados en Caja 4 alpha.84: **IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | Historial y filtros del selector no se comprobaron expresamente. | Revisar historial después de una baja futura. | M1–M8, PC8. |
| PC11 · Vacíos/corrupción | Un vacío es la representación cifrada válida de BDSP; jamás ceros por analogía. Writers 3DS y pruebas de empty cifrado. | Vacío PB8 canónico de party/caja alpha.82 + **alpha.28 (06-09-2026): las DOS representaciones de caja medidas y caracterizadas** sobre el PC real | Las dos representaciones difieren SOLO en los 16 bytes de cola (espejo de stats de party, ajeno al Pokémon): el juego deja un residuo constante en 1.185 de 1.189 huecos y RoleRun escribe ceros en los suyos. Los 328 bytes del bloque guardado están a cero en los 1.189. `move-box-slot` exigía los 344 idénticos y rechazaba así casi todo el PC; ahora comprueba los 328, que es lo que «vacío» significa. | **VALIDADO FÍSICAMENTE** 06-09-2026: mover entre cajas funciona. | PC1, PC3, S6–S8. |
| PC12 · Rollback/readback | Fallo en cualquier región restaura party, PC, conteo y metadata y verifica restauración. Writers 3DS. | Swap, cola y compactación: **ÉXITO VALIDADO FÍSICAMENTE**; alpha.84 añade **READBACK/ROLLBACK TEST AUTOMÁTICO** de party+origen+Cementerio | No se provoca deliberadamente un fallo real; las regresiones inyectan el fallo final. | Ninguna prueba destructiva de rollback en partida real. | PC3–PC8, S6–S8. |

## 6. Muertes

| ID / capacidad | Comportamiento de referencia exacto y código actual | Estado BDSP | Evidencia que falta | Prueba física necesaria | Dependencias |
|---|---|---|---|---|---|
| M1 · Estado de combate | Distingue overworld, combate activo, sustitución forzada y salida sin extrapolar flags de otro juego. Readers 3DS y `BattleState`. | Combate salvaje simple, KO, sustitución y salida: **READER VALIDADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | Faltan victoria y combates no simples. | La prueba integrada M4; después cubrir dobles/especiales por separado. | C1–C4, B1. |
| M2 · Lane HP de combate | Reconcilia HP mostrado/real y party por identidad; una lane inválida no invalida party. SM/USUM live readers. | `BTL_PARTY` + PokeID, presentación visible y gating Adapter alpha.69: **READER VALIDADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** en combate salvaje simple | Faltan dobles y encuentros especiales. | Cubrir cada modalidad por separado cuando entre en alcance. | P2, P4, M1. |
| M3 · Baseline y transición | Solo `>0→0` tras baseline válido produce muerte; conectar con HP=0 no la inventa. `LivePartyWatch`, Core events y tests Gen7. | **IMPLEMENTADO · TEST AUTOMÁTICO** en BDSP | Falta validación física de baseline al conectar dentro de combate/reconectar. | Primero conectar antes del combate; después se hará una prueba separada de reconexión. | P4, M2, C4. |
| M4 · Vidas -1 sincronizada | La muerte demostrada se compromete durante el combate, después de la presentación visible del KO, y actualiza persistencia/OBS una vez. UI health flow, RunService. | Alpha.69: **IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** en combate salvaje simple | Faltan dobles, encuentros especiales y comprobación OBS separada. | Cubrir cada modalidad y OBS cuando entren en alcance. | M1–M3, O1. |
| M5 · Ocultación inmediata | El Pokémon pendiente desaparece de vistas normales, barra y slot OBS al comprometerse. UI/OBS y `test_floating_live_stability.py`. | UI alpha.69: **IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE**; OBS pendiente | Falta comprobar el slot OBS por separado. | Revisar OBS durante un KO futuro. | M4, O5, U5. |
| M6 · Exactamente una vez | Repetición de HP=0, reordenación, party atrasada o reconexión no decrementan otra vida. `LivePartyWatch`, `pending_faints`, historial. | Dos KO y exactamente dos vidas alpha.84: **IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | Falta reconexión BDSP. | Reconectar después de un KO ya comprometido. | M2–M4. |
| M7 · Reconciliación postcombate | Party atrasada converge sin duplicar; fin de batalla habilita sustitución. Flujo USUM alpha59–63. | Uno y dos KO alpha.84: **IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | Faltan modalidades de combate especiales. | Cubrir cada modalidad cuando entre en alcance. | M1–M6. |
| M8 · Cementerio e historial | Compromiso persistente conserva identidad, rol, instante y causa. RunService/RunProjectService. | **IMPLEMENTADO · TEST AUTOMÁTICO · PENDIENTE DE VALIDACIÓN FÍSICA** | Confirmar persistencia BDSP tras M4. | Revisar historial/Cementerio después de M4. | M4, PC10. |
| M9 · Selector y herencia | Tras batalla abre un solo selector por pendiente; varios KO se procesan consecutivamente. Faint picker y regresiones alpha63. | Dos KO, dos selectores sin minimizar y marcador heredado alpha.84: **IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | Flujo base cerrado. | Ninguna adicional para la misma sesión. | M7–M8, PC7–PC8, R6. |
| M10 · Cambios/combates consecutivos | Un cambio de inicial, dos combates y reinicio no reutilizan filas, HP ni pendientes anteriores. Tests USUM y reset runtime. | **NO INICIADO** | Episode key y replays BDSP. | Dos combates seguidos cambiando el Pokémon inicial. | C4, M1–M9. |

## 7. Progresión y medallas

| ID / capacidad | Comportamiento de referencia exacto y código actual | Estado BDSP | Evidencia que falta | Prueba física necesaria | Dependencias |
|---|---|---|---|---|---|
| G1 · Representación real | Determinar flags/WorkValues/objetos reales de los 8 gimnasios sin analogía con 3DS. Writers/readers de progreso 3DS sirven solo de patrón de validación. | Alpha.77: **DEMOSTRADO EN SOURCE + RAM FÍSICA** | OpenDPR y PKHeX coinciden en `systemFlags[124..131]`; bool[1000] físico y save dieron 2. Falta observar una transición. | Obtener la siguiente medalla con alpha.77 abierta. | C1–C3, diagnóstico acotado. |
| G2 · Reader de contador | Convierte la representación demostrada a 0–8, monótona por sesión normal y con procedencia live explícita. `badge_source_is_live`, adapters/Core. | Alpha.77: **VALIDADO FÍSICAMENTE PARA SINCRONIZACIÓN INICIAL 0→2** | Validar además el cambio durante una entrega real. | Obtener la siguiente medalla con RoleRun abierto. | G1, C8. |
| G3 · Autoridad/fallback | No mezcla un valor live nuevo con save stale ni presenta fallback manual como RAM. `app/realtime/models.py`, UI badge flow. | Alpha.77: **IMPLEMENTADO · TEST AUTOMÁTICO** | Confirmar que el valor RAM actualiza antes de guardar y no retrocede por save stale. | No guardar manualmente hasta ver el incremento en RoleRun. | G2, S5. |
| G4 · UI/Run/OBS | Cada incremento se persiste una vez y actualiza contador y OBS; reconexión no duplica. UI, RunService, ObsSync. | Alpha.77: **UI/RUN VALIDADOS FÍSICAMENTE PARA ARRANQUE 0→2** | Falta la transición real y comprobar OBS; la validación inicial no demuestra 2→3. | Obtener una medalla y comprobar un único incremento. | G2–G3, O3. |

## 8. MT, inventario y utilidades

| ID / capacidad | Comportamiento de referencia exacto y código actual | Estado BDSP | Evidencia que falta | Prueba física necesaria | Dependencias |
|---|---|---|---|---|---|
| T1 · Tabla MT efectiva | La partida randomizada usa su `personal_masterdatas`; no una tabla vanilla supuesta. `app/bdsp_tm_service.py`, `_get_bdsp_tm_profile()`. | **IMPLEMENTADO · INTEGRADO CON RAM LIVE · TEST AUTOMÁTICO** | Falta contraste visual de movimientos randomizados en el selector. | Abrir selector y contrastar dos MT con el juego. | Fuente Unity disponible. |
| T2 · Inventario de MT | Solo ofrece MT realmente poseídas, con cantidad/estado actual. `BDSPInventoryReader`, `read_tm_inventory()` y SaveEngine como testigo. | Alpha.74: **READER VALIDADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | El usuario consumió una MT y RoleRun mostró una unidad menos al reabrir el selector; no se anotaron ID/cifras concretas. | Ninguna adicional para el ciclo base; repetir con cifras si se necesita una evidencia cuantitativa archivada. | C1–C4, T1. |
| T3 · Selector de MT | Filtra por posesión y rol sin bloquear UI; BDSP conserva su contrato RoleRun de compatibilidad. `app/ui.py::_open_tm_selector`. | Alpha.74: **IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** para apertura y refresco de cantidad | Queda pendiente contrastar por separado dos resultados randomizados si se quiere cerrar también la tabla efectiva T1. | Ninguna adicional para apertura/refresco; T1 conserva su prueba propia. | T1–T2, V4. |
| T4 · Enseñar desde RoleRun | Actualiza movimiento/PP y, si la regla lo exige, inventario en una transacción verificada. SaveEngine `teach-tm`; writers 3DS. | RAM alpha.76: **VALIDADO FÍSICAMENTE** | Ninguno para la transacción probada; otras revisiones/ediciones necesitan evidencia propia. | Cubierto el 2026-08-22: movimiento, PP y cantidad. | V2, T2, S6–S8. |
| T5 · Consumo RoleRun | El consumo debe obedecer la regla explícita de RoleRun y distinguirla de la mecánica vanilla/randomizer. UI/change review. | Alpha.75 consume exactamente una: **IMPLEMENTADO · TEST AUTOMÁTICO** | Falta readback físico de la cantidad. | Enseñar una MT poseída y revisar contador/estado posterior. | T4. |
| T6 · Caramelo Raro | Ajuste de cantidad solo si el bolsillo, item ID, witness y write/readback/rollback BDSP están demostrados. Writers de utilidades 3DS; SaveEngine `set-item`. | Alpha.85, ID BDSP 50: **VALIDADO FÍSICAMENTE** | El usuario comprobó ×999 en la mochila. | Ninguna adicional. | T2, S6–S8. |
| T7 · Repelente Máximo | Mismas garantías que T6, sin compartir identidad por traducción o proximidad. | Alpha.86, ID BDSP 77: **VALIDADO FÍSICAMENTE** | El usuario confirmó que el alta ausente creó «Repelente Máximo ×999»; alpha.85 queda conservada como reproducción del error de identidad 79. | Ninguna adicional. | T2, S6–S8. |
| T8 · Dinero máximo | Leer testigo, escribir campo demostrado, readback y rollback; no inferir estructura del inventario. Writers 3DS; SaveEngine `set-money`. | Alpha.85, `PlayerWork+0xEC`, máximo 999.999: **VALIDADO FÍSICAMENTE** | El usuario comprobó 999.999 ₽. | Ninguna adicional. | C1–C4, S6–S8. |
| T9 · Fallo de lane | Un fallo de inventario/MT/utilidades no borra party ni activa fallback silencioso a save. Snapshots/adapters. | **NO INICIADO** | Adapter con diagnostics separados y regresión. | Cambiar de escena durante lectura de inventario. | P10, S4–S5. |

## 9. OBS

| ID / capacidad | Comportamiento de referencia exacto y código actual | Estado BDSP | Evidencia que falta | Prueba física necesaria | Dependencias |
|---|---|---|---|---|---|
| O1 · Vidas | `vidas.txt`/`state.json` cambian al compromiso de muerte, no al guardar. `ObsSyncService`, RunProjectService/UI. | **IMPLEMENTADO · TEST AUTOMÁTICO · PENDIENTE DE VALIDACIÓN FÍSICA** | Confirmar salida OBS BDSP durante M4. | Mismo KO de M4. | M4. |
| O2 · Curaciones y drafteos | Los contadores persistidos se publican en archivos globales de la Run activa. `ObsSyncService`. | **IMPLEMENTADO** | Confirmar que la Run BDSP activa actualiza las rutas globales. | Cambiar ambos contadores una vez desde RoleRun. | Run activa. |
| O3 · Medallas | `medallas.txt`/`state.json` siguen el progreso live autorizado. | Alpha.77: **IMPLEMENTADO · TEST AUTOMÁTICO · PENDIENTE DE VALIDACIÓN FÍSICA** | Confirmar el archivo tras una transición real. | Obtener una medalla. | G4. |
| O4 · Sprites por rol | Seis slots de rol muestran especie/sprite correcto y resuelven conflictos sin sobrescribir silenciosamente. `app/obs_sync.py`. | Party/roles BDSP: **IMPLEMENTADO · TEST AUTOMÁTICO** | Falta validación física de OBS con snapshot live. | Reordenar y cambiar dos roles. | P9, R2–R4. |
| O5 · Ocultación por muerte | El rol del fallecido queda vacío inmediatamente y reaparece con el sustituto. ObsSync/UI visibility. | **IMPLEMENTADO · TEST AUTOMÁTICO · PENDIENTE DE VALIDACIÓN FÍSICA** | Confirmar la reaparición tras PC8 alpha.84. | KO, comprobar ocultación y elegir sustituto. | M5, R6. |
| O6 · Actualización consistente | UI, Run, historial y OBS se alimentan del mismo snapshot/commit; no mezclan save stale. Core/UI/ObsSync. | **NO INICIADO** | Integración BDSP y regresión de lane stale. | Cambio externo de party seguido de KO. | P9–P10, M4, S5. |

## 10. Barra flotante y UI

| ID / capacidad | Comportamiento de referencia exacto y código actual | Estado BDSP | Evidencia que falta | Prueba física necesaria | Dependencias |
|---|---|---|---|---|---|
| U1 · Sincronización automática | La barra recibe snapshots live sin refresco manual ni bloqueo de Tk. `app/ui.py`, timers/captura en worker. | **IMPLEMENTADO · TEST AUTOMÁTICO · PENDIENTE DE VALIDACIÓN FÍSICA** | Medir conexión/polling real y estabilidad visual. | Abrir la Run con Ryujinx activo y mantener la barra visible durante un combate. | C3, C8, P9. |
| U2 · Abrir RoleRun | Desde la barra se restaura/mapea la ventana correcta y conserva estado. UI common. | **IMPLEMENTADO · TEST AUTOMÁTICO** | Validación con Ryujinx en foreground. | Abrir/restaurar RoleRun desde la barra con el juego activo. | Ninguna RAM. |
| U3 · Foreground/focus | Detecta si la ventana activa pertenece a este proceso y evita barras/modales solapados. `_foreground_belongs_to_this_process()`, tests Windows. | **IMPLEMENTADO · TEST AUTOMÁTICO** | Validación física con Ryujinx y alt-tab. | Alternar juego↔RoleRun tres veces. | U2. |
| U4 · Party/roles/moves | Solo rerenderiza lo necesario; cambios live no esconden ventana ni pierden scroll. UI publishing y floating stability tests. | **IMPLEMENTADO · TEST AUTOMÁTICO** en BDSP | Falta validación física del render live. | Reordenar dos miembros y comprobar la barra. | P9, R2, V1. |
| U5 · Muerte | Oculta miembro pendiente y muestra feedback sin comprometer dos veces. Floating/projected party. | Combate salvaje simple alpha.69: **IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | Faltan varios KO y otras modalidades. | Cubrirlas por separado cuando entren en alcance. | M4–M6. |
| U6 · Selector de sustituto | Se abre al terminar batalla, no durante sustitución forzada; una ventana por pendiente. Faint picker alpha62/63. | Un KO alpha.84: **IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | El caso múltiple pertenece a U7/M9. | Ninguna adicional para un KO. | M7–M9, PC7. |
| U7 · Sin duplicados/estados atascados | Cerrar/completar un modal programa el siguiente y nunca exige minimizar RoleRun. Tests `test_faint_picker_floating.py`. | Dos selectores alpha.84: **IMPLEMENTADO · TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** en BDSP y USUM | Caso base cerrado para ambos; reconexión queda en M10. | Ninguna adicional para dos KO en la misma sesión. | U6. |
| U8 · Errores comprensibles | Desconexión, lane inválido o writer rechazado se explica sin pedir detalles técnicos ni ocultar datos válidos. Diagnostics/report UI. | **NO INICIADO** | Mensajes BDSP, stale visible y pruebas UI. | Cerrar juego o provocar cambio de escena durante captura. | C6, S4–S5. |

## 11. Seguridad y aislamiento

| ID / capacidad | Comportamiento de referencia exacto y código actual | Estado BDSP | Evidencia que falta | Prueba física necesaria | Dependencias |
|---|---|---|---|---|---|
| S1 · Cero direcciones supuestas | Cada cadena queda ligada a juego/revisión/backend y evidencia reproducible; una dirección externa es candidata hasta validarla. `AGENTS.md`, baseline. | **IMPLEMENTADO** como regla; cajas/party/batalla SP 1.3.0: **READER VALIDADO** | Trazabilidad independiente para cada bloque futuro. | Incluida en cada capability RAM. | C1. |
| S2 · Lectura estable | Doble lectura/checksum/longitud/identidad antes de publicar. Readers 3DS, PB8 parser. | Transporte/cajas/party/batalla: **READER VALIDADO · TEST AUTOMÁTICO** | Repetir el patrón por cada lane futuro; el adapter aún debe aislar fallos entre lanes. | Ya se observó y rechazó una mutación intermedia de calc data; repetir en integración. | P1, PC1, T2, G2. |
| S3 · Testigos y unicidad | Punteros, array length, PB8 checksum, identidad y límites deben concordar; candidatos múltiples se rechazan. `LiveBlockResolver` y writers 3DS. | Cajas/party/batalla: **READER VALIDADO · TEST AUTOMÁTICO** | Faltan testigos específicos para inventario/progreso y writers. | Se cubre con controles físicos de cada bloque. | S1–S2. |
| S4 · Fail-safe por ambigüedad | No publica empty/0 ni escribe cuando la evidencia no es única; emite lane inválido. Snapshot diagnostics. | Party/batalla/PC: **IMPLEMENTADO · TEST AUTOMÁTICO** | Falta validación física de una transición PC concurrente. | La prueba PC2. | C6, P10. |
| S5 · Aislamiento de lanes/stale | PC/inventario/progreso/batalla no invalidan party; último valor válido se marca stale. Core/adapters. | Party/batalla/PC BDSP: **IMPLEMENTADO · TEST AUTOMÁTICO** | Inventario/progreso aún no existen; PC pendiente de validación física. | La prueba PC2. | C6, P10. |
| S6 · Precondiciones de writer | Verifica título, revisión, sesión, snapshot fresco, identidad, slot y bytes actuales inmediatamente antes. Writers 3DS. | Party/movimientos/MT alpha.75: **IMPLEMENTADO · TEST AUTOMÁTICO** | Repetir por cada futuro writer PC/progreso/utilidad. | Incluida en T4/R3. | Reader correspondiente validado. |
| S7 · Readback semántico | Relee fuente real y verifica objetivo, vecinos, conteo, HP, rol, objeto y checksums. Writers 3DS. | Party/movimientos/MT alpha.75: **IMPLEMENTADO · TEST AUTOMÁTICO** | Falta validación física del éxito. | Incluida en T4/R3. | S6. |
| S8 · Rollback verificado | Conserva bytes previos, restaura toda la transacción y verifica restauración ante cualquier fallo. Writers 3DS/save service. | Party+MT alpha.75: **IMPLEMENTADO · TEST AUTOMÁTICO** con fallo en el segundo write | No se fuerza fallo físico; cada writer futuro requiere su propia regresión. | Validar solo el éxito real. | S6–S7. |
| S9 · Sin fallback silencioso | Nunca cambia RAM↔save sin indicarlo ni usa save stale como dato live. Adapter/UI diagnostics. | **IMPLEMENTADO · TEST AUTOMÁTICO** para party/HP/PC BDSP | Falta validación visual de error; GDB no es requisito. | Cerrar/suspender Ryujinx durante lectura. | C6, S5. |
| S10 · Aislamiento 3DS | Ningún offset, parser PB8 ni decisión Ryujinx modifica ORAS/XY/SM/USUM salvo fallo demostrado en código común. Arquitectura Adapter/Bridge. | **IMPLEMENTADO** en foundation | Mantener regresiones de consumidores comunes al integrar. | No requiere prueba física 3DS por cambios BDSP aislados; suite sí. | C8, Q7. |
| S11 · Diagnóstico y privacidad | Recorder guarda evidencia acotada y anonimizable; no saves completos, ROMs o datos personales. Core recorder/diagnostics. | **NO INICIADO** para BDSP | Definir bloques mínimos y sanitización antes de activar recorder. | Reproducir una sesión corta y revisar paquete generado. | Adapter BDSP. |

## 12. Testing y validación

| ID / capacidad | Comportamiento de referencia exacto y código actual | Estado BDSP | Evidencia que falta | Prueba física necesaria | Dependencias |
|---|---|---|---|---|---|
| Q1 · Transporte/parser | Config, ambos formatos `get info`, RSP, Title ID, `main`, punteros y prohibición de write. `tests/test_bdsp_ryujinx_gdb_foundation.py`. | **TEST AUTOMÁTICO** | Suite completa después de la última ampliación del parser. | Ya existe control físico de conexión/lectura. | C1–C2. |
| Q2 · Reader party/PB8 | Fixtures reales anonimizados: seis/vacíos/checksum/lectura inestable/reordenación. | Party actual: **TEST AUTOMÁTICO · REORDENACIÓN VALIDADA FÍSICAMENTE** | Cubiertos checksum, mutación, HP incoherente y cambio de raíz; falta cambio de conteo físico. | P1–P9. | P1–P4. |
| Q3 · Reader de lanes | Tests separados para battle/HP, PC, inventario y progreso; fallo opcional no tumba party. | Battle/HP, PC, inventario y progreso: **TEST AUTOMÁTICO**; progreso leído físicamente 2/8 | Falta transición física de progreso y casos adicionales de otras lanes. | Obtener la siguiente medalla. | P10, M2, PC1, T2, G2. |
| Q4 · Writers | Cada operación tiene regresión causal, readback, vecino intacto y rollback inyectado. | Roles/movimientos/MT, PC/sustitución y utilidades alpha.86: **TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | Progreso es solo lectura; no queda ninguna utilidad pendiente. | Ninguna para las utilidades cerradas. | S6–S8. |
| Q5 · Adapter/Core | Snapshot, events, reconnect, stale, orden, roles, moves, badge y battle. `tests/test_realtime_core.py` como referencia. | Party/battle/progreso: **IMPLEMENTADO · TEST AUTOMÁTICO**; adapter físico publicó 2/8 | Falta transición integrada de progreso y otras matrices pendientes. | Obtener la siguiente medalla. | C8, P9, G2, M1. |
| Q6 · UI/OBS/persistencia | Regresiones de muerte, cola, PC, barra, focus, Run e igualdad OBS. Tests common existentes. | Baseline/HP, PC y selector doble alpha.84: **TEST AUTOMÁTICO · VALIDADO FÍSICAMENTE** | OBS e historial visual permanecen aparte. | Flujos O1/O5 y M8. | Q5. |
| Q7 · Suite completa | `python -m pytest -q` debe quedar verde tras cada bloque; cifras históricas no cuentan para un cambio nuevo. | Alpha.86: dirigida **130 passed**; suite completa **581 passed** en 22,05 s. | Ninguna para este bloque. | Ninguna; es automatizada. | Q1–Q6 según bloque. |
| Q8 · Replay/diagnóstico | Una captura permite reproducir transiciones sin depender del emulador. `RealTimeSessionRecorder`, replay UI. | **NO INICIADO** | Adapter, sanitización y fixture compacto. | Grabar party+HP y reproducir offline. | S11, Q2–Q5. |
| Q9 · Matriz física | Cada fila RAM conserva fecha, juego, revisión, Ryujinx y resultado; validaciones parciales no cierran la capability. | **INVESTIGANDO** | Ejecutar las pruebas mínimas indicadas al madurar cada bloque. | Las de cada fila; nunca una macroprueba indistinguible. | Toda la matriz. |

## Carril independiente: rendimiento de Ryujinx

La causa del lag de GDB está demostrada. El usuario ejecutó PERF-0 con GDB
apagado y el juego mejoró claramente; al repetir PERF-1 con GDB activado y sin
cliente RoleRun, la lentitud regresó. El source exacto de Ryujinx 1.3.3 explica
la primera divergencia: el constructor del debugger fija globalmente
`ARMeilleure.Optimizations.EnableDebugging=true`. `Translator` abandona entonces
el dispatch loop no administrado, ejecuta un bucle de depuración bloque a bloque,
actualiza PC preciso y fuerza retornos donde el modo normal usa tail calls. PTC
separa además las cachés por `DebuggerMode`, de modo que cambiar el flag provoca
recompilación. No es una pausa causada por paquetes `q`/`m` ni una carga de
RoleRun.

La comparación controlada utilizará la misma zona, la misma entrada a edificio,
la misma partida y, una vez calentada cada sesión, tres repeticiones por estado:

| Estado | GDB Stub | Cliente | Lecturas | Pregunta que responde |
|---|---:|---:|---|---|
| PERF-0 | No | No | Ninguna | Baseline normal tras reinicio. |
| PERF-1 | Sí | No | Ninguna | Coste de habilitar GDB por sí solo. |
| PERF-2 | Sí | Conectado/idle | Solo identificación | Coste de conexión sin polling. |
| PERF-3 | Sí | Activo | Party a cadencia baja, como la captura actual | Coste de frecuencia/volumen bajo. |
| PERF-4 | Sí | Activo | Cadencia/volumen candidato de producción | Presupuesto real antes de adoptar arquitectura. |

Se conservarán por estado el tiempo de carga observado, log de Ryujinx, FPS o
frame-time disponible, CPU, memoria y eventos PTC/JIT. Primero se compararán
medianas y stutter visible; cualquier degradación material y repetible bloquea
la adopción de ese patrón de acceso. No se elegirán offsets alternativos, host
scans ni otro transporte hasta demostrar en qué estado aparece la primera
divergencia de rendimiento.

Estado: **VALIDADO FÍSICAMENTE** para la degradación y para el transporte
sustituto HostMapped. GDB queda limitado a diagnósticos puntuales y rechazado
como requisito de uso normal. Una comparación simultánea GDB guest↔Windows host
encontró una única vista HostMapped: 64 bytes de `main` y un PB8 independiente
de 344 bytes coincidieron byte a byte mediante un mismo delta de sesión. La
prueba posterior reinició con GDB apagado, redescubrió otra dirección anfitriona
y leyó cajas, party y batalla sin escritura. Evidencia:
`diagnostics/manual/bdsp_sp130_gdb_performance_ab_20260822.json` y
`diagnostics/manual/bdsp_sp130_hostmapped_bridge_proof_20260822.json`.

## Orden propuesto de investigación

Este orden evita construir writers o automatismos sobre una sesión inestable:

1. **Transporte y fuentes base completados para SP 1.3.0**: GDB queda solo como
   diagnóstico; HostMapped, cajas, `PlayerWork._playerParty` y `BTL_PARTY`
   disponen de readers cerrados ante ambigüedad y evidencia física acotada.
2. **Completar modelo de party de solo lectura**: forma, nombre/apodo, huevo,
   movimientos/PP y objeto desde PB8 demostrado; luego Adapter+snapshot sin
   activar todavía muertes ni writers.
3. **Battle/HP y muertes en solo lectura**: capturar KO `>0→0`, cambio activo y
   reconciliación; añadir replay, baseline y exact-once. Solo al final habilitar
   compromiso y selector.
5. **Progreso de gimnasios**: reader 0–8 y fuente live implementados en alpha.77;
   falta validar la transición automática de una nueva medalla y OBS.
6. **PC e inventario en lectura**: convertir la evidencia 40×30 a reader,
   cambios externos, TM poseídas y aislamiento de lanes.
7. **Writers pequeños en orden de riesgo**: rol, movimiento y MT, cada uno con
   precondiciones/readback/rollback y validación física independiente.
8. **Writers de PC y sustitución**: alpha.78 implementa swap 1↔1; alpha.80 conecta
   a RAM el punto de entrada exacto de CAMBIAR CON PC y su selector ya fue
   validado físicamente. Alpha.81 corrige la compuerta que descartaba la operación
   antes del writer. Queda validar la escritura física; después 6→5, 5→6, empty
   válido, herencia, Cementerio y KO completo.
9. **Utilidades**: Caramelo, Repelente y dinero solo tras readers/testigos
   independientes.
10. **Cierre transversal**: reinicio/state-load, desconexión, replay,
    rendimiento de producción, suite completa, UI/OBS/barra y matriz física.

Después de cada prueba se actualizarán en este archivo el estado, la evidencia
conservada, la limitación restante y el siguiente bloque lógico. Ninguna fila se
marcará cerrada por similitud con 3DS ni por pasar únicamente tests sintéticos.
