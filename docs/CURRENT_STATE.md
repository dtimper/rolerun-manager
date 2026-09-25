# RoleRun Manager — estado funcional canónico

- Fecha de corte: 2026-09-25
- Versión de aplicación: `0.5.0` (`app/config.py`; Release publicada en GitHub
  el 25-09-2026 con instalador, tras `v0.4.x` del mismo día y `v0.3.1` del 07-09-2026)

Este documento es la fuente canónica del estado funcional actual. `CHANGELOG.md`
conserva la evolución histórica; `ROADMAP.md` conserva tanto
prioridades actuales como hitos antiguos. Si una afirmación histórica contradice
este documento, hay que comprobar código, tests, logs y validación física y
actualizar aquí el resultado demostrado.

## Resumen vigente (25-09-2026)

Las entradas fechadas de más abajo son el registro de cada avance; esta
sección es la foto de hoy. Lo posterior al 14-09 está solo en `CHANGELOG.md`.

- **Juegos seleccionables**: Negro/Blanco y Negro 2/Blanco 2 (melonDS), X/Y,
  ROZA, Sol/Luna y UltraSol/UltraLuna (Azahar), Diamante Brillante/Perla
  Reluciente (Ryujinx).
- **Ocultos del selector** (`GAMES_OCULTOS`, `app/ui.py`): Diamante/Perla y
  Platino (sin direcciones de RAM medidas) y HeartGold/SoulSilver (aparcado:
  combate sin estabilizar; la escritura sigue encendida desde el 06-09-2026,
  `MELONDS_GEN4_ESCRIBE` en `app/ui.py`).
- **Combate de seis Pokémon** (vida + drafteo automáticos): validado
  físicamente en los siete juegos seleccionables.
- **Bugs abiertos confirmados**: estado alterado mal mostrado en la barra
  flotante (ORAS muestra otro estado; BDSP no muestra ninguno porque el offset
  `0x94` de `PlayerWork._playerParty` no lleva el estado vivo).
- **Huecos teóricos sin observar**: en USUM la sonda de combate no distingue
  salvaje de entrenador para el combate de seis.

## Foco activo: Design Evolution

La numeración funcional queda fijada así: `v0.2.1` corresponde a BDSP,
`v0.2.2` a USUM, `v0.2.3` a Sol/Luna, `v0.2.4` a X/Y, `v0.2.5` a ORAS y
`v0.2.6` a B2/W2. El changelog conserva los nombres históricos anteriores para no
borrar trazabilidad.

### 14-09-2026 (3) — FIX real de USUM: combate ganado sin bajas nunca terminaba

Extendiendo la regla de "combate de seis" a UltraSol/UltraLuna se descubrió
un bug preexistente y ajeno a esa regla: `USUMLiveReader` nunca declaraba
`state="none"` tras un combate ganado SIN perder ningún Pokémon propio,
porque su mecanismo de fin de combate (alpha.62) exige al menos una baja
propia observada para converger contra PartyData -sin bajas no hay nada que
converger-. Nunca se había validado físicamente contra un UltraSol real
(alpha.62 terminaba "pendiente de validación física"). Corregido con una vía
de escape por tiempo real (20 s de par idle sostenido sin bajas ⇒ se asume
overworld), sin tocar el camino ya probado de "sí hubo baja". Ver
`CHANGELOG.md` para el detalle completo y la razón del primer intento de
arreglo descartado.

### 14-09-2026 (2) — Regla de "combate de seis" CONFIRMADA en vivo en ORAS y X/Y

Tras el fix de abajo, el usuario probó ambos juegos con combates de seis
reales (en X/Y tuvo que añadir Pokémon extra al líder, ya que los gimnasios
tempranos sin modificar no llegan a seis). Se encontró un tercer bug, solo en
X/Y: la sesión se cerraba en falso a mitad de combate porque el objeto de
combate del rival tarda varios segundos reales en reconstruirse tras cada
sustitución, y ese hueco bastaba para superar la confirmación de "fin de
combate" (entonces medida en número de muestras, no en tiempo real). Un
combate real se fragmentó en más de veinte resoluciones prematuras de 1-2
rivales cada una. Corregido midiendo tiempo de reloj real (10 s de "none"
sostenido) en vez de contar muestras -cadencia de sondeo variable, número de
muestras no es robusto-. Confirmado en directo justo después: +1 vida y +1
drafteo correctos en un combate de seis real de X/Y. **La regla queda
funcionando en vivo en ambos juegos, ya sin pendientes de validación física.**
Retirado el registro de diagnóstico temporal que sirvió para encontrar los
tres bugs de esta serie de entradas. Detalle completo en `CHANGELOG.md`.

### 14-09-2026 — FIX: la regla de "combate de seis" no se disparaba en directo

El usuario ganó su primer gimnasio de seis en ORAS tras la entrada de abajo y
no sumó ni vida ni drafteo. Causa: `ui.py` nunca ve el `ORASBattleProbe` de
`oras_live.py` directamente -ve `RealTimeSnapshot.battle`, un `BattleState`
genérico que `ORASRealTimeAdapter._capture_optional_lanes` reconstruye campo
por campo-, y `opponent_identity` no viajaba por esa conversión porque
`BattleState` ni lo declaraba. El dato se perdía en silencio en cada sondeo.
Corregido en `app/realtime/models.py` (campo nuevo en `BattleState`) y
`app/realtime/oras_adapter.py` (se copia explícitamente). Nuevo test de
regresión en `tests/test_oras_adapter_battle_state.py` que ejercita la
conversión completa, no solo el probe aislado. **El usuario necesita
reiniciar RoleRun** para que el proceso en marcha deje de correr el código
viejo. Sigue pendiente de validación física contra un combate de seis real
tras el reinicio.

### 09-09-2026 — Regla de "combate de seis Pokémon" automatizada en ORAS

El usuario dictó por voz el mismo día la regla completa de vidas/drafteos
(ver memoria `rolerun-format-rules`): superar un combate de seis Pokémon da
siempre +1 drafteo, y además +1 vida si nadie del equipo murió en ESE
combate. Hasta ahora los cuatro contadores se ajustaban a mano desde la
cabecera; esta regla concreta ya se automatiza para ORAS.

RoleRun no lee el roster completo del rival (solo existe una dirección fija
del rival ACTIVO, `ORAS_BATTLE_TRAINER_OPPONENT_ADDRESS`, ya usada para
distinguir salvaje/entrenador). En vez de eso, `oras_live.read_battle_probe`
decodifica species_id+PID de ese PK6 rival en cada sondeo y
`RunProjectService.note_six_mon_battle_opponent` acumula cuántos rivales
DISTINTOS salieron durante el combate en curso; al confirmarse el fin del
combate (dos lecturas seguidas de "none", igual que el resto del pipeline),
`resolve_six_mon_battle_end` paga la regla solo si fueron exactamente seis.
Las bajas propias durante ese combate ya las cuenta `register_detected_faint`
sin cambios de comportamiento -esta regla solo lee ese conteo, nunca
descuenta una segunda vez-.

Solo ORAS expone hoy la identidad del rival activo; X/Y comparte el mismo
`ORASBattleProbe` pero su sonda solo trae PS del rival, no PK6 completo, así
que en X/Y `opponent_identity` llega `None` y la regla nunca se dispara (sin
falsos positivos). Cubierto por tests (`tests/test_run_service.py`,
`tests/test_oras_live.py`); **pendiente de validación física** con un
combate de seis real en ORAS -no confirmado en emulador, ver `CHANGELOG.md`-.

### 06-09-2026 (5) — Retomados Diamante/Perla, Platino y HeartGold; primer carril de combate de HGSS

A petición explícita del usuario, se retoma el trabajo en los tres juegos
ocultos desde alpha.97 (cuatro incidentes reales de «Huevo malo» al escribir
cuarta generación). `GAMES_OCULTOS` queda vacío: los diez juegos vuelven a ser
seleccionables. Estado real por juego:

- **HeartGold**: lee todo en vivo de forma fiable. Escribir sigue apagado
  (`MELONDS_GEN4_ESCRIBE = False`) — el último incidente (alpha.96) tiene una
  causa sin explicar (un campo `sanity`), y no se reactiva sin investigarla.
  **Primer carril de combate implementado y VALIDADO FÍSICAMENTE**: a
  diferencia de Gen5, cuarta no mantiene una tabla de seis filas, solo
  demuestra al que está en el campo (`HgssMelonDSReader.read_battle_probe`,
  direcciones `0x022CC4EC`/`0x022CC484`, ver `CHANGELOG.md`).
- **Diamante/Perla y Platino**: parten de cero — ninguna dirección de RAM
  medida todavía. Las ROM del usuario existen pero sin save en curso; hace
  falta arrancar una partida antes de poder buscar anclas.

Pendiente inmediato: aprendizajes por rol y escritura en vivo para HGSS
(ninguno existe hoy); descubrimiento completo de direcciones para DP/Pt desde
cero, con el mismo método que ya funcionó en Blanco/Negro 2 y ahora en HGSS.

### 06-09-2026 (4) — Negro 2/Blanco 2: medido el paso de combate

Pendiente de alpha.32. Medido sobre la partida real: **0x224, igual que
Blanco**. Hallazgo de camino: `battle_presentation`/`battle_logical` no son
dos tablas independientes en este juego (a diferencia de Blanco) — son la
MISMA tabla de seis filas, una por puesto del equipo, sin intercambio de
activo a la fila 0. Cada fila sigue el PS real de su miembro tanto activo
como banqueado, confirmado con dos cambios de combatiente seguidos.

Encontrado de camino un bug real: la validación exigía que el campo "nivel"
también coincidiera, y ese campo sale con valores imposibles en cualquier
fila que no sea la del recién activo — descartaba las cinco filas enteras.
Especie + PS máximo + habilidad ya identifican sin ambigüedad; se quitó el
nivel de la comparación.

Ver `CHANGELOG.md` v0.3.1-alpha.34. **VALIDADO FÍSICAMENTE** (06-09-2026) con
el equipo real del usuario a mitad de combate. Suite completa: 2746 passed,
2 skipped.

### 06-09-2026 (3) — X/Y: la tabla de combate no es fiable; el bug real estaba en el respaldo

Pendiente de alpha.32: comprobar si X/Y tiene la tabla de combate de seis
filas de ORAS. La tiene (mismo paso de 580 bytes, mismo intercambio del
activo a la fila 0), pero **no es fiable**: tras el segundo cambio de
combatiente un miembro desapareció de la tabla y apareció una fila que no
correspondía a nadie, de forma estable. Descartada; X/Y sigue demostrando
solo la fila del activo.

Persiguiendo esa tabla, el usuario capturó en vivo tres bugs reales de fondo,
los tres **VALIDADOS FÍSICAMENTE** tras cada arreglo:

1. El respaldo de un Pokémon benqueado usaba el bloque de equipo, que NO
   sigue el daño de un miembro ya benqueado (se queda congelado en su valor
   de antes de esa pelea) — un solo cambio de combatiente ya lo mostraba
   "curado". Arreglado cacheando el último PS confirmado por partida doble
   mientras cada uno estuvo en el campo (`XYLiveReader._battle_confirmed_hp`):
   un banquillo no puede perder ni ganar PS por nada ajeno al combate activo,
   así que ese valor sigue siendo exacto mientras siga fuera.
2. Con (1) resuelto, los cinco que nunca habían salido se quedaban en gris
   hasta que les tocaba turno uno a uno. Arreglado sembrando esa misma caché
   con el bloque de equipo COMPLETO en el primer instante resuelto de cada
   combate: fuera de combate el bloque de equipo sí es la verdad, así que no
   hace falta esperar a que cada uno pise el campo.
3. El puntero del rival, con la misma indirección que el del jugador, podía
   leerse inválido durante el instante de transición de un K.O. Un solo tick
   así declaraba el combate terminado y publicaba el bloque de equipo crudo
   -sin el daño de esa pelea- como la verdad, "curando" a todo el mundo.
   Arreglado exigiendo que la ausencia se repita dos tics seguidos
   (`_battle_opponent_absent_streak`).

Ver `CHANGELOG.md` v0.3.1-alpha.33. Suite completa: 2746 passed, 1 skipped.

### 06-09-2026 (2) — aprendizajes por rol en quinta, con UNA sola capa

B2/W2 y Blanco/Negro eran los últimos juegos con escritura viva sin
aprendizajes por rol. Ya lo tienen, y con menos capas que ningún otro.

**Lo demostrado antes de escribir ningún writer**: la tabla vive en `a/0/1/8`
(709 archivos = las 709 especies de la tabla personal; valida contra
aprendizajes conocidos y 709/709 con niveles crecientes); melonDS mantiene la
imagen entera de la ROM en su memoria, en región `READWRITE`, con la cabecera
en la base y la tabla idéntica byte a byte a la del .nds; y no hay ninguna
copia cacheada en los 16 MB de RAM del DS. **Prueba física**: cambiado el
aprendizaje de nivel 5 de Lillipup (`Rastreo` → `Hidrobomba`, nivel intacto),
el juego **anunció y aprendió Hidrobomba** con su tipo y sus PP.

**Consecuencia**: quinta relee la tabla en cada aprendizaje, así que basta el
Enfoque A. No hace falta ni la red de seguridad reactiva ni el parcheo del
cartel que sí necesitan X/Y, Sol/Luna y UltraSol/UltraLuna — el juego anuncia
el nombre correcto por sí solo, como en ORAS.

Módulos nuevos: `app/gen5_levelup_moves.py` (decodificar y calcular) y
`app/gen5_levelup_memory.py` (localizar y escribir). `app/nds_rom.py` gana las
posiciones absolutas de cada archivo de un NARC. La ROM del usuario **se abre
siempre en solo lectura**: se parchea la copia en memoria. Incluye historial
para RECUERDA MOVIMIENTOS, que quinta también gana. Localizar la imagen pasó
de 48 s a 0,07 s agrupando por asignación y buscando la cabecera al principio,
sin relajar ninguna verificación. Ver `CHANGELOG.md` v0.3.1-alpha.29.

Suite completa: 2720 passed, 1 skipped. **VALIDADO FÍSICAMENTE** (06-09-2026).

La validación destapó un bug transversal, corregido en alpha.30: el historial
de RECUERDA-MOVIMIENTOS calculaba el sustituto sobre el subconjunto de
entradas recién cruzadas, mientras que el parche lo calcula sobre la tabla
COMPLETA de la especie. Como `compute_species_patch` excluye los movimientos
que la especie ya tiene, los dos conjuntos de exclusión diferían y elegían
sustitutos distintos: 13 de las 14 entradas de Patrat discrepaban. Afectaba a
ORAS, X/Y, Sol/Luna, USUM y quinta -no a BDSP, que registra el movimiento ya
confirmado en RAM-. Los cinco calculan ya sobre la tabla completa.

### 06-09-2026 — BDSP: el vacío del JUEGO no es el vacío que escribe RoleRun

Validación física de alpha.27: SM, USUM, B2/W2 y Blanco/Negro **funcionan**.
BDSP falló, pero no por el intercambio nuevo -sus tres escrituras salieron
bien- sino por `move-box-slot`, que ya estaba en producción: no se podía
mover un Pokémon a otra caja.

Medido leyendo los 1.200 huecos de la partida real: de los 1.189 vacíos,
**1.185 no coinciden byte a byte con el vacío canónico**. La diferencia está
entera en los 16 bytes de cola (espejo de stats de party, que no describe al
Pokémon): el juego deja un residuo constante y RoleRun escribe ceros. Los 328
bytes del Pokémon están a cero en los 1.189. La representación «canónica»
resultó ser la minoritaria: los 4 huecos que RoleRun misma había vaciado.

`_box_slot_is_clean_empty` pasa a comprobar los 328 bytes del bloque
guardado, no los 344. Sigue siendo más estricto que `party-to-box` y
`replace-fainted`, que solo exigen `species == 0`. Corregido además que los
bytes originales del destino guardados para el rollback eran el canónico y no
los reales. Ver `CHANGELOG.md` v0.3.1-alpha.28. Suite: 2689 passed.

**VALIDADO FÍSICAMENTE** el mismo día: el usuario confirma que ya puede mover
un Pokémon entre cajas en Perla Reluciente. Con esto, el estado del
intercambio PC↔PC queda: SM, USUM, B2/W2 y Blanco/Negro **validados**; BDSP
validado en la misma caja (sus tres escrituras salieron bien desde el primer
intento) y **pendiente entre cajas distintas**, que hasta ahora no se podía
ni montar; ORAS y X/Y ya lo estaban; HGSS implementado y sin poder probarse.

### 05-09-2026 (2) — intercambiar dos casillas del PC, en los ocho juegos

Pedido del usuario tras revisar la matriz de funcionalidades: el intercambio
entre dos casillas **ocupadas** del PC existía solo en ORAS y X/Y. Ahora lo
tienen los ocho backends con escritura viva (SM, USUM, BDSP, B2/W2,
Blanco/Negro y HGSS se suman).

No es una escritura nueva en ningún juego: es la misma transacción que su
`move-box-slot` ya tenía demostrada, sobre la misma matriz PC, sin ningún
vacío de por medio —las dos casillas están ocupadas— y con las **dos**
identidades como ancla, que es una garantía más fuerte que la del traslado.
Writers: `SMLiveWriter._apply_pc_swap`, `USUMLiveWriter._apply_pc_swap`,
`BDSPLiveWriter._apply_box_swap`, `B2W2MelonDSReader.swap_pc_slots` y
`HgssWriter.swap_pc_slots`. `PC_SWAP_GAME_KEYS` pasa a igualar a
`PC_A_PC_GAME_KEYS`. Ver `CHANGELOG.md` v0.3.1-alpha.27.

Corregido de paso un fallo real encontrado revisando el port: en SM y USUM el
apunte para el rollback se hacía DESPUÉS de escribir, y
`WindowsProcessMemory.write` lanza también con `ERROR_PARTIAL_COPY`, cuando
parte de los bytes ya han caído. Una escritura parcial dejaba una casilla
corrupta fuera del rollback —informando además de que se había restaurado
todo—. Corregido también en los dos `_apply_pc_move` hermanos, donde estaba
latente. Cubierto con un doble de memoria que escribe la mitad y luego falla.

Suite completa: 2686 passed, 1 skipped. **Pendiente de validación física**,
juego por juego. HGSS queda escrito pero sigue sin poder probarse: sus
escrituras están apagadas en bloque (`MELONDS_GEN4_ESCRIBE = False`).

Deuda conocida heredada (no introducida por este cambio, no bloquea): el
intercambio de HGSS reescribe el bloque de equipo y el contador desde una
captura previa, porque reutiliza el marco transaccional de `move_pc_slot`;
B2/W2 y HGSS no comprueban «no durante un combate» como sí hace BDSP; y la
verificación de BDSP no repite tras un asentamiento ni compara byte a byte,
solo identidad. Los tres vienen de sus hermanos ya validados.

### 05-09-2026 — X/Y: aprendizajes por rol completos, con las tres capas

X/Y alcanza la paridad de USUM/SM en aprendizajes por nivel según el rol:
archivo del mod (Enfoque A, `a/2/1/4`), red de seguridad reactiva (Enfoque B,
`_sync_xy_levelup_moves_backup`) y parcheo en RAM del cartel del juego
(Enfoque C, `_sync_xy_levelup_announcement_cache`). **Validado físicamente**
por el usuario.

Cuatro causas raíz reales encontradas leyendo `escrituras_vivas.jsonl`, todas
con su prueba de regresión:

1. El parcheo de RAM recibía las evoluciones adelantadas del archivo del mod
   —especies sin ningún búfer real asignado—, y buscar uno ahí tumbó el
   emulador. Ahora solo recibe la party real.
2. El búfer del cartel de X/Y vive a ~13 MiB de la party, muy fuera de la
   ventana de 8 MiB heredada de Gen 7: no se encontraba nada, en silencio.
   `XY_ANNOUNCEMENT_CACHE_SCAN_SPAN` la amplía a 40 MiB.
3. El parcheo solo se disparaba al reescribir el archivo (un cambio de rol).
   Un cruce de nivel sin cambio de rol no lo activaba nunca.
4. Un barrido preventivo de 5-6 especies por cambio de rol tardaba 10+
   segundos y el aviso urgente del cruce de nivel se descartaba en silencio al
   encontrar el candado ocupado. El candado ya no descarta —encola—, y el
   barrido preventivo se retiró: solo dispara el cruce de nivel.

### 04-09-2026 (4) — Sol/Luna: destino exacto Equipo→PC, y un clic sin diagnosticar del todo

Dos hallazgos del usuario tras validar los anteriores:

- **Corregido**: `SMLiveWriter._apply_team_swap` ignoraba
  `change.box`/`change.box_slot` para `"party-to-box"` y siempre buscaba el
  primer hueco libre, aunque la UI ya calculara un destino exacto desde la
  matriz live (no desde un save desfasado, la razón original de ese
  comportamiento). Réplica del contrato ya validado de USUM. Ver
  `CHANGELOG.md` v0.3.1-alpha.24. Pendiente de validación física.
- **Mitigado, sin causa raíz demostrada**: tras un intercambio PC↔Equipo, la
  tarjeta del Pokémon entrante podía dejar de responder al clic -sin abrir
  su ficha ni avisar-. Se sospecha una carrera entre el repintado proyectado
  del intercambio y el confirmado por la RAM, pero no se ha podido
  reproducir para demostrarlo. `_click_team_card` ya no revienta en silencio
  en ese caso y deja diagnóstico (`perf.mark`); la causa real sigue abierta.

### 04-09-2026 (3) — Gen 7: el testigo "recién salido al PC" era imposible de cumplir

Causa raíz real de que CAJAS PC de Sol/Luna nunca se abriera (ni con
REINTENTAR, ni tras guardar la partida): `_open_pc_selector_from_live_matrix`
mete el equipo vivo entero como anchors con `box=None/box_slot=None`, igual
que un testigo real de "recién salido al PC". Los resolutores exigen a la
vez que ningún anchor así aparezca en el PC (`boxpokemon-overlaps-live-party`)
Y que al menos uno aparezca (`missing-recent-party-to-pc-witness`) —una
contradicción que ninguna dirección, ni la correcta, podía superar nunca.
Corregido restando la party viva del conjunto de testigos exigidos, en
`sm_live.py` (tres funciones) y `usum_live.py` (dos funciones equivalentes).
Ver `CHANGELOG.md` v0.3.1-alpha.23. **Pendiente de validación física**:
confirmar que CAJAS PC de Sol/Luna se abre en la partida del usuario.

### 04-09-2026 (2) — Sol/Luna se quedaba estancado en "Preparando Equipo y PC…"

Causa raíz demostrada con el log real del usuario: la party se leía bien,
pero la matriz PC en vivo no se demostraba esa sesión (sin testigo party→PC
reciente). `_retire_initial_shell_when_ready` tenía una condición exclusiva
de `"sm"` que no publicaba la primera página hasta demostrar esa matriz, y la
barrera no publica por timeout a propósito -así que no abría nunca-. USUM y
Perla Reluciente usan el mismo mecanismo y no bloquean el arranque por esto:
la degradación (aviso "NO SE PUDIERON ABRIR LAS CAJAS · REINTENTAR" sin
tapar el resto de la app) ya existía y ya funcionaba para ellos. Se retira la
excepción de `"sm"`. Ver detalle en `CHANGELOG.md` v0.3.1-alpha.22.
**Pendiente de validación física**: confirmar que la Run afectada del
usuario ya abre.

### 04-09-2026 — Sol/Luna: mover dentro del PC (a hueco vacío)

Pedido del usuario: mover un Pokémon del PC a otro hueco del PC no existía
para Sol/Luna -solo Equipo→PC-, aunque ORAS, BDSP y USUM ya lo tenían.

`SMLiveWriter._apply_pc_move` (réplica del contrato ya probado de
`USUMLiveWriter._apply_pc_move`) sobre la matriz PC de SM que
`_ensure_pc_live_cache_for_team_write`/`_read_proven_pc_matrix` ya demuestran
para `party-to-box`/`box-to-party` -no una dirección nueva ni prestada de
otro juego-. `apply()` despacha `"move-box-slot"` a este writer; `"sm"` se
añade a `PC_A_PC_GAME_KEYS` en `app/ui.py`. Solo mueve a un hueco **vacío**:
el intercambio con un Pokémon ya presente en el destino queda fuera de
alcance, igual que en UltraSol/UltraLuna (`PC_SWAP_GAME_KEYS` solo tiene
`"oras"`).

Tests sintéticos en `tests/test_sm_alpha30_pc_swap_write.py`
(`test_sm_pc_to_pc_moves_exact_pk7_to_requested_box_and_slot`,
`test_sm_pc_to_pc_rejects_occupied_destination_without_writing`). **Pendiente
de validación física** en Sol/Luna con Azahar: mover un Pokémon del PC a un
hueco vacío de otra caja, confirmar en el juego que llega intacto y que el
origen queda vacío.

### Corrección posterior 30-08-2026 (3) — el depósito no sabía calibrar su propia caja

Diagnosticado con `Logs/escrituras_vivas.jsonl`: tras las dos correcciones de
abajo, arrastrar del equipo a una casilla concreta del PC seguía terminando en
"No se pudo confirmar el hueco vacío del PC de ORAS con los testigos de esa
caja" (y la barra volvía a verde en cuanto el monitor confirmaba que la party
seguía intacta, así que el fallo se leía como un cambio realizado).

Causa: `ORASLiveWriter._locate_empty_pc_destination` solo probaba la caché del
**escritor** y las dos direcciones conocidas (`ORAS_PC_KNOWN_ADDRESSES`). Si la
matriz de cajas de la partida no está en ninguna de ellas —el caso normal— el
depósito solo funcionaba cuando alguna operación previa de PC (`_locate_pc_base`,
que sí escanea) había dejado la base en esa caché. El **lector** encontraba la
dirección buena escaneando en cada lectura del PC, pero la guardaba en su propia
caché, que este camino no consultaba.

Corregido sin relajar ninguna garantía: el destino vacío sigue sin identificar
nada por sí solo. Ahora se prueban, en orden, caché del escritor → caché del
lector → direcciones conocidas, y si ninguna casa se calibra con
`_scan_empty_pc_destination`, que ancla siempre en un **testigo ocupado** de la
misma caja (el vecino real que la UI capta al arrastrar), exige dos testigos
—mismo listón que `_scan_pc_base`— y solo acepta la base si
`_empty_pc_destination_matches` confirma todos los testigos y que el hueco
elegido sigue libre.

El Pokémon cae en la casilla exacta donde se suelta (no en el primer hueco
libre): ya lo hacían el gesto (`_team_pc_drop` → `send_pokemon_to_pc`
`destination`), el escritor (`change.box_slot` → `_box_slot_address`) y la
proyección visual; lo único que faltaba era poder localizar la matriz.

Suite completa: 2188 passed, 1 skipped.

### Corrección posterior 30-08-2026 (5) — Caja → Caja en ORAS

PC→PC no fallaba: estaba **deshabilitado**. ORAS no figuraba en
`PC_A_PC_GAME_KEYS`, así que al arrastrar dentro del PC todas las casillas se
pintaban en rojo y al soltar salía «DESTINO NO HABILITADO», en cualquier caja.

Añadido `ORASLiveWriter._apply_pc_move`, con el mismo contrato que el de X/Y:

- El origen ocupado es el ancla (`_locate_pc_base`); el destino vacío nunca
  identifica nada y se exige libre con `parse_pk6_boxed_lenient`.
- Se escribe el **destino antes** de vaciar el origen, así que ningún fallo
  intermedio puede hacer desaparecer al Pokémon.
- Readback inmediato + segundo readback tras el asentamiento (mismo hallazgo
  que en Equipo↔PC: Azahar confirma bytes que el juego todavía no ha adoptado)
  y rollback verificado de las dos casillas.
- El hueco que queda en el origen son los 0xE8 bytes a cero, exactamente lo que
  `_apply_party_resize` ya escribe en la casilla de origen al incorporar del PC
  al equipo (validado físicamente el 30-08-2026). ORAS no necesita la plantilla
  de vacío cifrado que sí exige X/Y (`XYLiveWriter._validated_empty_pc_slot`).

Origen y destino pueden estar en cajas distintas: la matriz es contigua y solo
cambia el índice. En la UI se añadió `oras` a `PC_A_PC_GAME_KEYS`, a la
compuerta de aplicación inmediata y a las operaciones soportadas por el
adaptador; los testigos de PC→PC en ORAS pasan a salir de `_pc_box_witnesses`
(proyección viva) en vez de `_pc_role_witnesses` (solo el `main`), que en una
caja recién estrenada no aportaba ningún acompañante.

Suite completa: 2199 passed, 1 skipped.

### Corrección 31-08-2026 (3) — la lectura viva del PC reintenta sola

«NO SE PUDO LEER EL PC DE ORAS · No se pudo localizar de forma segura la matriz
viva del PC de ORAS para leerla», con un botón REINTENTAR que **funcionaba a la
primera**. Es decir: el fallo era transitorio —la matriz no se deja localizar
mientras el juego reconstruye sus cajas, típicamente justo después de una
escritura— y el aviso rojo estaba pidiendo al usuario que hiciera a mano lo que
RoleRun puede hacer sola.

`_schedule_oras_external_pc_reconcile` reintenta ahora la lectura antes de
publicar el error, con los retardos de `LIVE_PC_READ_RETRY_DELAYS_MS`
(260 ms y 700 ms). Cada reintento queda registrado como `pc-reconcile-reread`.
El aviso solo aparece si ninguno lo consigue, y una lectura buena reinicia el
contador. No se relaja ninguna garantía: sigue sin publicarse jamás una caja
vacía como si fuera el estado real, y una lectura no forzada mantiene su
`fallback_inference` de siempre.

Suite completa: 2250 passed, 1 skipped.

### Corrección 31-08-2026 (2) — Equipo ↔ PC moría tras mover algo en el PC

Diagnosticado con `Logs/escrituras_vivas.jsonl`: varias operaciones de PC en
vivo seguidas y, justo después, un intercambio Equipo ↔ PC fallando con «No se
pudo localizar y validar la caja viva de ORAS con los Pokémon de esa caja».

Causa: `_pc_role_witnesses` —la que alimenta `swap-party-box` y
`box-to-party`— construía los vecinos leyendo solo `data.boxes`, es decir el
último `main`. En cuanto una operación de PC en vivo movía un Pokémon, esos
testigos apuntaban a huecos que ya no lo contenían; ninguna base candidata
casaba en `_pc_base_matches` (ni en el escaneo, que usa los mismos testigos) y
`_locate_pc_base` abortaba sin escribir un byte.

Es exactamente la corrección que `_pc_box_witnesses` ya llevaba —su comentario
la documenta— y que esta función no recibió. Ahora los vecinos salen de
`_project_pc_box_pokemon`, la misma proyección viva que pinta la cuadrícula.
Cuando no hay ninguna operación viva pendiente, la proyección coincide con el
guardado y el resultado es idéntico al de antes: solo cambia el caso que estaba
roto.

Suite completa: 2248 passed, 1 skipped.

### Novedad 31-08-2026 — intercambiar dos casillas ocupadas del PC (ORAS)

Soltar sobre una casilla **ocupada** del PC dejó de estar prohibido. Antes,
`resolve_team_pc_drop` devolvía `None` para ese gesto («El intercambio entre dos
casillas PC ocupadas no está habilitado») en todos los backends.

Ahora el resolutor distingue dos operaciones PC→PC y deja la decisión de quién
sabe escribir cada una a la interfaz:

- `move-box-slot` — llevar a un hueco libre (`PC_A_PC_GAME_KEYS`).
- `swap-box-slots` — intercambiar dos ocupadas (`PC_SWAP_GAME_KEYS`; ORAS y,
  desde el 05-09-2026, X/Y con `XYLiveWriter._apply_pc_swap`, misma
  transacción). En los demás backends la casilla se sigue pintando en rojo.

`ORASLiveWriter._apply_pc_swap` es una transacción independiente: captura
estable de los dos bloques de 0xE8 bytes, verificación de que cada casilla
contiene exactamente el Pokémon que la interfaz declaró, precondición inmediata
antes de escribir, escritura cruzada con readback por bloque, verificación
semántica de ambas casillas, segundo readback tras el asentamiento y rollback
verificado de las dos. Ninguna casilla se vacía en ningún momento del plan.

Aquí no hay ningún hueco vacío del que desconfiar y, a cambio, **las dos
identidades son ancla**: `_pc_swap_witnesses` las aporta como testigos, así que
el escaneo de calibración ya tiene sus dos identidades sin depender de vecinos.
Efecto colateral útil: si una de las dos ha dejado de estar donde decía la
interfaz, ninguna base candidata confirma y se aborta antes de leer la pareja.

Refactor asociado: `_pc_witnesses_match`, `_scan_pc_base_with_witnesses` y
`_locate_pc_base_with_witnesses` unifican la localización de la matriz para las
tres rutas de PC (depósito en hueco vacío, traslado e intercambio), con
`empty_slot` como única diferencia. El depósito conserva su comportamiento.

Origen y destino pueden estar en cajas distintas. Corregido de paso el rótulo
de REVISAR CAMBIOS, que describía las operaciones PC→PC como «· EQUIPO».

Suite completa: 2247 passed, 1 skipped.

### Ajuste 30-08-2026 (6) — cadencia del cambio de caja durante el arrastre

Corrección de una afirmación equivocada del punto (5): el cambio de caja sin
soltar el Pokémon YA existía —`UnifiedTeamPCView._update_drag_box_hover`, con
sus propios tests desde `v0.2.6-alpha.14`—, así que arrastrar entre cajas nunca
dependió de un gesto nuevo.

Lo que sí era impracticable era su cadencia: cada entrada en la flecha ‹ o ›
provocaba un único salto (`_drag_box_hover_consumed`) y había que salir y
volver a entrar una vez por caja. Con 31 cajas, llegar a la 15 eran catorce
idas y venidas con el Pokémon cogido.

Ahora el primer salto sigue esperando `DRAG_BOX_HOVER_DELAY_MS` (420 ms, para
no dispararse al pasar por encima) y, mientras el puntero siga en la flecha, se
repite cada `DRAG_BOX_HOVER_REPEAT_MS` (520 ms). Cada repetición vuelve a
comprobar que el arrastre sigue vivo y que el puntero no se ha ido, y mover el
ratón dentro de la flecha no reinicia el temporizador. La intención original
del guardia —no encadenar cajas sin control— se mantiene: la cadencia es fija y
visible, no un encadenado a velocidad de eventos.

Suite completa: 2200 passed, 1 skipped.

### Corrección posterior 30-08-2026 (4) — soltar en una caja vacía del PC

La corrección anterior seguía exigiendo testigos de la MISMA caja
(`box_witnesses`), así que una caja de destino vacía no aportaba ni una
identidad y el depósito se rechazaba sin escribir nada.

Las 31 cajas son una sola tabla contigua en RAM: un Pokémon real de la caja 1
demuestra la dirección base exactamente igual que un vecino de la caja 5. Se
añade `PendingTeamChange.pc_anchor_witnesses` —`(caja, hueco, identidad)`, de
cualquier caja— que la interfaz rellena con `_pc_anchor_witnesses` (recorre las
cajas empezando por la de destino y abriéndose a las más cercanas, así que en la
práctica proyecta una o dos, y nunca aporta la casilla que va a recibir al
Pokémon). Solo lo consume el escritor de ORAS.

En el escritor, `_empty_destination_witnesses` reúne primero los vecinos de la
caja de destino y después los de cualquier otra; `_empty_pc_destination_matches`
y `_scan_empty_pc_destination` verifican cada testigo en SU posición exacta
(caja + hueco). Las garantías no se relajan: el hueco vacío nunca es ancla, el
escaneo sigue exigiendo dos testigos y la base solo se acepta si todos casan y
el destino sigue libre.

Limitación restante: un PC entero sin un solo Pokémon no puede demostrar nada
—ni el lector ni el escritor— y ese primer depósito se sigue rechazando sin
escribir. Es el único caso que queda.

Suite completa: 2192 passed, 1 skipped.

### Corrección posterior 30-08-2026 (2) — el mismo problema, del lado del PC

Con la lectura de la party ya reparada (entrada de abajo), "Equipo → casilla
concreta del PC" seguía fallando: un hueco del PC que la revisión de
ORAS/emulador nunca ha tocado puede no ser cero puro (memoria del emulador
sin inicializar), sin ser por eso un Pokémon real — el mismo problema que el
hueco de party, pero del lado de la caja. `_empty_pc_destination_matches` (al
comprobar si el destino elegido está realmente libre) y la reverificación de
`_apply_party_resize` justo antes de escribir llamaban a `parse_pk6_boxed`
sin capturar su `ORASLiveError`, así que el depósito entero abortaba con "El
Pokémon del PC 1:1 no superó checksum/especie" aunque ese hueco estuviera
perfectamente disponible.

Añadido `parse_pk6_boxed_lenient` (mismo patrón que `parse_pk6_party_lenient`)
y usado en esos dos puntos exactos. Los demás usos de `parse_pk6_boxed` en el
resto del escritor (`_pc_base_matches`, `_scan_pc_base`, `_resolve_pc_target`)
ya estaban correctamente protegidos o deliberadamente estrictos (un slot
fuente que debería tener un Pokémon real y no lo tiene es un error genuino,
no un hueco disponible) y se dejan sin tocar.

Suite completa: 2187 passed, 1 skipped.

### Corrección posterior 30-08-2026 — un hueco roto tiraba TODA lectura de ORAS

Encontrado tras la validación física de abajo, con el hueco residual de esas
mismas pruebas todavía en la party: el "hueco roto" que deja el propio juego
al depositar (cabecera a cero, resto de bytes sin limpiar — ver la entrada de
abajo) no solo confundía la precondición de `_apply_party_resize`.
`ORASLiveReader.read()`, `read_monitor()`, `_parse_compact_party_region`
(sondeo de batalla) y `ORASLiveWriter._read_party_members` (compartido por
roles, movimientos, curación, swap...) llamaban a `parse_pk6_party`
directamente, sin capturar el `ORASLiveError` que levanta un slot así. Un
solo hueco de este tipo bastaba para tirar **cualquier** lectura completa de
la party — el monitor normal, F5, cada intento de reconexión — dejando a
ORAS atascado en "REVISIÓN NECESARIA" sin recuperarse nunca solo, y
bloqueando de paso "Equipo → casilla concreta del PC" (nunca llegaba a
intentar la escritura).

Añadido `parse_pk6_party_lenient` (envuelve `parse_pk6_party`, un slot roto
cuenta como vacío) y usado en los cuatro puntos de lectura de arriba.
`ORASLiveWriter._party_slot_occupied`/`_build_game_lenient` (de la entrada
de abajo) se simplificaron para reusarlo, eliminando la duplicación.

Suite completa: 2186 passed, 1 skipped.

### VALIDADO FÍSICAMENTE 30-08-2026 — party-to-box/box-to-party en ORAS

Cierra las dos entradas anteriores. El usuario validó en directo, contra su
partida real (Omega Rubí/Alfa Zafiro en Azahar), el ciclo completo desde
RoleRun: depositar un Pokémon del equipo al PC y traer uno del PC de vuelta
al equipo, en ambas direcciones, sin pérdida ni duplicado.

Entre el escritor (entrada anterior) y esta validación aparecieron **siete**
compuertas más, todas con el mismo patrón exacto que ya había dejado ORAS sin
esta capacidad desde el principio: cada una de las rutas de UI que ya sabían
tratar `party-to-box`/`box-to-party` para X/Y tenía su propia lista de claves
de juego, y "oras" faltaba en seis de ellas mientras la séptima confundía
"ocupado" con "no está a cero puro":

1. `_oras_live_unsupported_changes` (app/ui.py) — compuerta de la UI,
   independiente de `ORASLiveWriter._unsupported_changes`.
2. `_request_oras_live_auto_apply` (app/ui.py) — sin esta, el cambio se
   quedaba "PENDIENTE · todavía no confirmado en Azahar" para siempre: nunca
   se llegaba siquiera a intentar la escritura, así que tampoco aparecía
   ningún error.
3. La rama "destino exacto" de `_team_pc_drop` para party-to-box — sin
   "oras" aquí, arrastrar a una casilla concreta del PC siempre acababa en
   el primer hueco libre.
4. **El bug más sutil**: la precondición de `_apply_party_resize` contaba un
   slot como "ocupado" con `any(raw)` (¿tiene algún byte no-cero?). Depositar
   desde el propio menú del juego —no desde RoleRun— solo pone a cero la
   cabecera del slot (constante de cifrado, centinela, checksum), dejando el
   resto de bytes tal cual. Ese hueco real se contaba como "ocupado", así
   que el equipo vivo parecía tener un miembro más de los que decía el
   contador de ORAS, y la operación se rechazaba con "El equipo vivo tiene 6
   slot(s) ocupado(s), pero el contador de ORAS dice 5" — aunque la RAM
   estuviera perfectamente sana. Arreglado con `_party_slot_occupied`, que
   usa el mismo criterio ya validado que `parse_pk6_party` (un slot solo
   cuenta si parsea de verdad), reutilizado también en `_first_empty_party_slot`
   y en la verificación posterior a escribir.

Confirmado también, en el mismo directo: `move-box-slot` (mover dentro del
PC sin pasar por el equipo) sigue correctamente bloqueado con "DESTINO NO
HABILITADO" — nunca se prometió esa capacidad en esta ronda, y el aviso lo
deja claro sin proyectar ningún cambio falso.

Suite completa: 2185 passed, 1 skipped.

### Escritor 30-08-2026 — party-to-box/box-to-party en ORAS (sin validación física, sin UI)

Sigue de la entrada anterior ("Hallazgo físico 30-08-2026"). Con
`ORAS_PARTY_COUNT_ADDRESS` confirmado, se implementó
`ORASLiveWriter._apply_party_resize`, siguiendo el mismo patrón transaccional
que `XYLiveWriter._apply_party_resize` (captura doble estable, identidad
antes de tocar nada, escribir, readback por unidad, contador al final como
punto de compromiso, segunda lectura diferida de asentamiento, reversión
completa —contador incluido, el último en restaurarse— ante cualquier
divergencia), adaptado al hallazgo de que ORAS NO compacta: cada uno de los
6 slots se trata como independiente, y "hueco" se define exactamente como lo
hace `parse_pk6_party` (el bloque almacenado + el espejo de estadísticas en
`ORAS_PARTY_STATS_OFFSET` a cero) — nunca se toca la franja completa de
`ORAS_PARTY_STRIDE`, solo esas dos regiones que el resto del código ya lee o
escribe.

Cubierto con 9 tests sintéticos nuevos (`ORASPartyResizeTests` en
`tests/test_oras_live_write.py`): depósito y retirada completos, contador
como último byte escrito en ambas direcciones, rechazo sin vaciar el equipo,
rechazo con el equipo lleno, rechazo si el contador no coincide con los
slots realmente ocupados, exigencia de testigos de caja antes de aceptar un
destino vacío, reversión completa si el commit del contador falla, y
detección de que el juego revierte la escritura tras la primera
confirmación (mismo hallazgo que motivó el segundo readback diferido de
X/Y). Suite completa: 2179 passed, 2 skipped.

**Todavía NO hay validación física.** Y, deliberadamente, la función sigue
sin poderse usar desde la aplicación: `send_pokemon_to_pc`
(`app/ui.py:17806-17817`), `_team_pc_execute_change` (`app/ui.py:14899-14910`)
y `_team_pc_can_drop` (`app/ui.py:15103-15111`) siguen bloqueando ORAS
exactamente igual que antes. Falta, en este orden: (1) revisar el escritor
con calma, (2) una validación física controlada de un depósito y una
retirada reales antes de confiar en él, y solo entonces (3) quitar los tres
bloqueos de UI.

### Hallazgo físico 30-08-2026 — contador de tamaño de party localizado en ORAS

No es una versión nueva: es un prerequisito para una capacidad que sigue sin
existir. El usuario pidió depositar un Pokémon en ORAS sin sustituto 1↔1
("Enviar al PC"), bloqueado hoy porque `ORASLiveWriter` no tenía ninguna
dirección de "cuántos miembros tiene la party" — a diferencia de X/Y
(`XY_PARTY_COUNT_ADDRESS`, alpha.8 de v0.2.4), nadie había hecho todavía la
prueba física controlada equivalente para ORAS.

Captura de solo lectura (`tools_oras_party_size_capture.py`, nuevo,
`diagnostics/manual/oras_party_size_transition_AUTO_20260830_15*.json`)
contra una partida real en Azahar: `0x08CF7208` pasó de 6 a 5 al depositar un
Pokémon desde el propio menú del juego, y volvió a 6 al retirarlo — el mismo
desplazamiento relativo (`-0x74`) que usa X/Y respecto al inicio de su party.
Ahora vive como `ORAS_PARTY_COUNT_ADDRESS` en `app/oras_live.py`, documentada
pero sin usar en ningún escritor todavía.

**Diferencia importante con X/Y: ORAS no compacta la party al depositar.**
El Pokémon depositado estaba en el slot 3 de 6; tras el depósito ese slot
quedó con un checksum inválido en su sitio (ni PK6 vacío canónico, ni
desplazamiento de los slots 4-6). Al retirarlo, volvió exactamente al mismo
slot. El contrato de "prefijo compacto" que usa el writer de X/Y
(`_apply_party_resize`) no aplica aquí sin más — un futuro escritor ORAS
necesita su propia lógica para decidir qué slot está realmente activo.

Sigue sin existir ninguna escritura viva que cambie el tamaño del equipo en
ORAS; `send_pokemon_to_pc`/`_team_pc_execute_change`/`_team_pc_can_drop`
siguen bloqueándolo igual que antes. Esto solo cierra el primer prerequisito
de esa capacidad, documentado para retomarlo.

### v0.2.6 Alpha.68 — FIJAR ROLES, en los diez juegos

Botón nuevo en la cabecera de EQUIPO. Asigna de una vez el rol de su casilla a
todos los miembros que no tengan rol, en vez de abrir el editor uno por uno.

**Y el usuario tenía razón**: esto es del programa y no de ningún juego, así que
entra en los diez a la vez. No hay ninguna rama por juego — lo único que hace es
encolar los mismos `PendingRoleChange` que crea el editor de rol, y cada backend
los escribe como ya sabe. Una prueba lo recorre con las diez claves.

**La regla: la casilla manda.** Es la misma que sigue un Pokémon al entrar desde
el PC, así que no se inventa ningún reparto: se confirma el que la vista lleva
enseñando. Un Pokémon que ocupa una casilla ajena pero **ya tiene rol propio** no
se toca, porque eso es una decisión del usuario.

**El Líbero** es el único que necesita decidir algo —qué dos estadísticas sube—,
así que se pregunta antes de tocar nada, reutilizando el selector que ya existía.
Si se cancela **no se fija ninguno**: mejor eso que dejar el equipo a medias.

Detalles: el botón solo aparece si hay algo que fijar, y la vista se reconstruye
una sola vez al final en lugar de una por Pokémon.

- `tests/test_fijar_roles.py`: 21 pruebas. Suite completa: 1424.

### v0.2.6 Alpha.67 — el paso entre filas era 0x224, no 0x228

Primera prueba física del combate de Blanco: el equipo salía con vida teniendo
dos Pokémon debilitados en el juego. El diagnóstico lo explicó en una lectura.

**Alpha.65 restó dos cosas distintas.** La búsqueda por forma devuelve el
**inicio** de la fila; la traza de dos estados devuelve el **campo de PS**, que
va cuatro bytes más allá. Restar uno de otro daba `0x228` en vez de `0x224`.

Con el paso mal, la fila del segundo miembro salía desplazada cuatro bytes: el
nivel caía donde va la habilidad, la validación la rechazaba —correctamente— y
al no quedar ninguna fila buena RoleRun se caía al bloque de equipo, que en
quinta **no se actualiza durante el combate**. De ahí el equipo intacto.

**La validación por miembro hizo su trabajo**: rechazó filas que no describían a
su Pokémon en vez de publicar datos de otro. El fallo se vio como «no se
actualiza», que es el modo seguro, y no como «vida equivocada».

`0x224` sale **dos veces por caminos independientes**, uno por cada tabla, y
coloca la habilidad del Serperior donde le toca.

- Suite completa: 1403.
- **Pendiente de validación física** otra vez: ver bajar la vida en combate.

### v0.2.6 Alpha.66 — el combate de Blanco, conectado y por equipo entero

Con el paso entre filas medido, Blanco no lee una fila: lee **las seis**, una por
miembro del equipo. Publica los PS vivos de todos durante el combate, no solo
los del que está en el campo — que es más de lo que hace Negro 2.

- `read_battle_party()`: una fila por miembro, con doble lectura y **validada
  contra su propio miembro**. Si la del tercero no describe al tercero, se
  descarta esa sola y ese Pokémon conserva lo que diga el bloque de equipo. No
  se pierde el combate entero por una fila mala.
- El adaptador usa esa vía cuando el paso está medido y la de siempre cuando no.
  Negro 2 no cambia de comportamiento.
- Pedirle la lectura por miembro a Negro 2 se niega con su motivo: su paso no
  está medido y suponerlo sería la analogía de siempre.

- `tests/test_bw_memory.py`: 31 pruebas. Suite completa: 1400.
- **Pendiente de validación física**: entrar en combate en Blanco y ver bajar la
  vida en directo.

### v0.2.6 Alpha.65 — el combate de Blanco, resuelto y con estructura

La traza de dos estados lo resolvió a la primera, y de paso reveló cómo está
montado todo.

**Cuál es cuál.** Con el Serperior recibiendo dos golpes:

| | |
| --- | --- |
| `0x0226E794` bajó a los **1115 ms** | lógica |
| `0x0226D898` bajó a los **4544 ms** | presentación, la que sigue la barra |

Los **3429 ms** de diferencia son casi exactamente los **3362 ms** que separan a
las dos copias de Negro 2 en su propia traza. El mismo retardo de animación,
medido en dos juegos distintos y con dos métodos distintos.

**La estructura.** Las direcciones del Serperior no coincidían con las que había
dado la búsqueda anterior para el Purrloin, y ahí estaba la clave: hay **dos
tablas de filas, una por miembro del equipo**, con un paso de `0x228`. Purrloin
es el primero y Serperior el segundo, y la diferencia entre sus filas es
exactamente ese paso, en las dos tablas.

Se guarda la fila del primero, que es donde arranca cada tabla, más el paso.

**Negro 2 no hereda ese paso.** Allí no se ha medido, así que vale `None` y se
sigue leyendo una sola fila. Suponerle el mismo `0x228` sería justo la analogía
que este proyecto no admite.

Con esto **Blanco no tiene nada por inventar**: ancla, MT y las dos filas de
combate, todas medidas contra el juego.

- `tests/test_bw_memory.py`: 26 pruebas. Suite completa: 1400.

### v0.2.6 Alpha.64 — el combate de Blanco, por dos estados

La búsqueda por firma falló **dos veces**, y por el mismo motivo: suponía que
Blanco coloca los campos de la fila igual que Negro 2.

1. Encontró un Pansear a nivel 3342, que había coincidido por azar.
2. Con el Purrloin debilitado y el Serperior luchando, solo encontró las dos
   copias viejas del Purrloin a 0/27. La fila del que estaba peleando **no
   apareció**: la suposición sobre el formato no se cumple.

Se cambia al método que este proyecto sí se cree y que el documento de paridad
exige: **dos estados**. Si un Pokémon pasa de X a Y puntos de salud, en la
memoria hay posiciones que contenían X y ahora contienen Y. No supone nada del
formato de la fila, que es justo donde fallaba lo anterior.

Es el mismo procedimiento con el que se demostraron la mochila y el dinero de
Negro 2.

Encontradas las posiciones, un tercer paso las vigila durante otro golpe: la que
baje antes es la lógica y la que lo haga después, la de presentación.

- Suite completa: 1398.

### v0.2.6 Alpha.63 — la segunda fila de Blanco era del rival

El usuario lo vio antes que la herramienta: la traza temporal lo confirma.

- **`0x0226D670`** describe de verdad a su Pokémon: bajó de **24 a 9 PS** al
  recibir el golpe.
- **`0x0226E348`** tenía un **Pansear a nivel 3342**. Coincidió una vez por azar
  cuando el Purrloin estaba a 19/19, y ya no.

**Por qué eso deja el asunto sin resolver.** La traza de Negro 2 enseña cómo son
las dos copias buenas: describen **al mismo Pokémon**, y la lógica se adelanta a
la de presentación —3,4 segundos en aquella captura—. Con una sola fila no se
puede saber si `0x0226D670` es la que manda en pantalla o la que se adelanta, y
elegir mal cantaría una baja antes de que el jugador la vea. Ambas siguen `None`.

**La herramienta nueva hace las dos cosas de golpe**, sin suponer ninguna
distancia entre las filas: busca **todas** las que describen al Pokémon que está
luchando y las vigila a la vez cada 10 ms durante un turno. La que baje antes es
la lógica; la que lo haga después, la de presentación.

Se descarta el intento anterior, que partía de dos direcciones fijas.

- Suite completa: 1398.

### v0.2.6 Alpha.62 — Blanco no tenía MT porque preguntaba al juego equivocado

Reportado por el usuario justo después de alpha.61: aunque la dirección de MT de
Blanco ya estaba demostrada, la pantalla seguía sin funcionar.

**El motivo:** `_get_b2w2_tm_profile` pedía el perfil siempre a
`b2w2_realtime_adapter`, escrito a mano. Con Blanco abierto leía la dirección de
Negro 2 —o fallaba— en vez de la suya. Lo mismo pasaba en otros dos sitios: el
lector de PC del selector y los PP de la tarjeta de drafteo.

Los tres pasan a resolver el adaptador **del juego activo**. Es la misma clase
de fallo que alpha.58 dejó a medias: quedaban tres referencias por nombre fijo
que la generalización no alcanzó.

- Un test nuevo comprueba las **dos** rutas: con Negro 2 abierto responde el
  adaptador de Negro 2, y con Blanco el de Blanco. El anterior solo comprobaba
  que respondiera alguien.
- Suite completa: 1398.

### v0.2.6 Alpha.61 — la tabla de MT de Blanco, y el combate a medias

**MT demostrada: `0x0209EA88`.** La misma búsqueda por forma que en Negro 2: de
**381** tramos con la forma de una tabla de MT, uno solo coincide **101 de 101**
con la lista derivada de PKHeX. La forma sola no bastaba —381 candidatos lo
dicen—; lo que decide es el contenido.

**El combate está localizado pero no ordenado.** La búsqueda por firma encontró
**exactamente dos** filas, `0x0226D670` y `0x0226E348`, que comparten especie,
PS máximos, habilidad y nivel con el Pokémon en combate. Eso confirma que son
las dos copias.

Lo que no se puede saber con esa captura es **cuál manda en pantalla**: el
Pokémon estaba a vida llena, así que las dos decían 19/19. Fuera de la
animación siempre dicen lo mismo.

Y elegir mal no es cosmético: con la copia lógica como autoridad, RoleRun
adelantaría el KO a la animación y cantaría una baja que el jugador todavía no
ha visto. Es exactamente lo que el diseño de Negro 2 evita. Así que ambas siguen
valiendo `None` y la capacidad, apagada.

`cual_es_cual_combate_blanco.bat` lo resuelve: muestrea las dos cada 10 ms
durante un turno y apunta cuál baja los PS más tarde. Esa es la de presentación.

- Suite completa: 1397.

### v0.2.6 Alpha.60 — Blanco VALIDADO: lectura y escritura

El usuario confirmó (27-08-2026) sobre su partida de Blanco:

- El **equipo** se lee entero y correcto.
- Las **cajas del PC** también, y los **intercambios Equipo↔PC funcionan**.
- El **botón de dinero escribe**: la partida quedó al máximo.

Y en Negro 2, que el PC sigue bien tras el arreglo de alpha.59.

Es más de lo que parece: los intercambios y el dinero son **escrituras**, así
que el contrato transaccional entero —relectura fresca, readback, verificación y
rollback— queda validado en Blanco con sus propias direcciones, todas derivadas
de una única ancla medida.

**Lo que queda de Blanco** son las dos cosas que no salen del cálculo:

- `buscar_mts_blanco.bat`: la herramienta de MT, ahora con descriptor de juego.
  Busca 101 movimientos seguidos y los contrasta con la referencia de PKHeX.
- `buscar_combate_blanco.bat`: nuevo. Aprovecha que ya se conoce la forma de la
  fila para buscar con una **firma de cuatro campos** —especie, PS máximos,
  habilidad y nivel— contra un miembro del equipo que RoleRun ya sabe leer, en
  vez de rastrear transiciones a ciegas como hubo que hacer en Negro 2. Descarta
  las posiciones que caen dentro del bloque de equipo y separa presentación de
  lógica por los PS que el usuario ve en pantalla.

- Suite completa: 1393.

### v0.2.6 Alpha.59 — el PC vuelve a leerse (fallo introducido en alpha.57)

**El equipo de Blanco se lee perfecto** —Snivy, Purrloin, Patrat y Lillipup, con
sus niveles, PS y movimientos—, así que el ancla y todo lo derivado quedan
validados. Pero el PC fallaba, y el fallo era mío.

Al sustituir las direcciones por `self.memory.*` en alpha.57, una de ellas cayó
dentro de un `@staticmethod`, que no tiene `self`. **El PC dejó de leerse en los
dos juegos**, no solo en Blanco.

**Por qué ninguna prueba se enteró:** los dobles de melonDS sustituyen `read_pc`
entero, así que nunca llegan a `_read_pc_rows`. La ruta que pide la dirección no
estaba cubierta.

- El método pasa a ser de instancia.
- `test_ningun_metodo_usa_self_sin_tenerlo` recorre el módulo con el analizador
  de sintaxis y cubre **la clase entera de error**, no el caso concreto.
- `test_el_pc_se_lee_de_la_direccion_de_su_juego` ejercita `_read_pc_rows` de
  verdad para los dos juegos, sustituyendo solo la lectura de memoria: la
  dirección que pide, la doble lectura y el parseo son código de producción.

- Suite completa: 1393.

### v0.2.6 Alpha.58 — Blanco, conectado

Blanco tiene ya su adaptador vivo, registrado junto al de Negro 2 y compartiendo
con él lector, writer y contrato. Lo único propio es el descriptor de
direcciones, medido contra el juego.

- El adaptador recibe el descriptor; `key`, `game_key` y `display_name` pasan a
  ser por instancia para que los dos convivan en el registro.
- La familia de datos personales deja de estar escrita a mano: Blanco consulta
  su tabla de 668 especies y Negro 2 la suya de 709. Consultar la equivocada
  habría dado las estadísticas de otra especie a partir del índice 668.
- La lectura de la ROM pasa a ser por juego (`_get_gen5_rom_profile`).
- `MELONDS_REALTIME_GAME_KEYS` sustituye a los `== "b2w2"` repartidos por la
  interfaz: nueve listas de juegos y quince comprobaciones dejan de enumerar a
  mano. Tres pruebas que localizaban la rama por su texto se actualizan.

**Lo que Blanco declara tener**: equipo, cajas PC, mochila, dinero y medallas,
con roles, curación, movimientos y Equipo↔PC por el mismo writer transaccional.

**Lo que declara no tener**: el carril de combate y la tabla de MT. No viven en
el bloque del guardado, así que no salen del cálculo, y el texto de ayuda del
backend lo dice en vez de prometerlo.

- `tests/test_bw_memory.py`: 20 pruebas. Suite completa: 1385.
- **Pendiente de validación física**: abrir Blanco en RoleRun y ver el equipo.

### v0.2.6 Alpha.57 — el lector de quinta deja de estar clavado a Negro 2

El lector recibe ahora el **descriptor del juego**. Las direcciones dejan de ser
constantes incrustadas y salen de `gen5_memory`, donde solo el ancla se mide.

- 26 usos de direcciones dentro del lector pasan a `self.memory.*`.
- Tres métodos estáticos que necesitaban direcciones pasan a ser de instancia.
- Las constantes del módulo se conservan como alias, pero **derivadas** del
  descriptor: antes eran números sueltos que podían divergir.
- Construirlo sin argumentos sigue dando Negro 2, así que nada de lo que ya
  existía cambia de comportamiento.

**Lo que un juego no tiene demostrado, se niega con su motivo.** La tabla de MT
y el carril de batalla no viven en el bloque del guardado, así que Blanco no las
tiene todavía. Pedirlas devuelve «todavía no está demostrado en Negro/Blanco» en
vez de leer una dirección inventada o fallar más tarde con un error mudo. La
comprobación va **antes** de abrir el proceso.

- `tests/test_bw_memory.py`: 14 pruebas. Suite completa: 1385.

Con esto Blanco tiene ya, a nivel de lector: equipo, PC, mochila, dinero y
medallas. Falta conectarlo al adaptador y a la interfaz, y demostrar sus dos
direcciones que no se derivan.

### v0.2.6 Alpha.56 — el ancla de Blanco, y sus direcciones derivadas

**`0x02234974`**, medido contra la partida del usuario. Dos confirmaciones
independientes en la misma captura:

1. **Por forma**: ahí arrancan cuatro bloques PK5 seguidos, separados
   exactamente 220 bytes, y el usuario declaró un equipo de cuatro.
2. **Por contenido**: en la dirección que predice la resta del guardado, el
   dinero leído era **1624**, el que había apuntado antes de empezar. De los
   diez candidatos del volcado, solo ese acertó.

De ahí salen, sin más capturas: contador `0x02234970`, PC `0x0221BF6C`, mochila
`0x02233F6C`, dinero `0x0223CD6C` y medallas `0x0223CD70`.

- `app/gen5_memory.py`: un descriptor por juego. Solo el ancla se mide; el resto
  son propiedades derivadas. Una prueba comprueba que la regla **reproduce las
  seis direcciones de Negro 2**, cada una demostrada por separado antes de
  conocerse la regla.
- Lo que sigue sin demostrarse en Blanco: la tabla de MT y las copias de
  batalla. No viven en el bloque del guardado, así que valen `None` y el backend
  sabe que esas capacidades no están.

**Corregido un fallo de la herramienta de captura**: leía el contador del equipo
cuatro bytes antes de donde está, así que daba el byte de cabecera y ningún
candidato «cuadraba del todo». El ancla se identificó igual por las otras dos
comprobaciones.

- `tests/test_bw_memory.py`: 9 pruebas. Suite completa: 1380.

### v0.2.6 Alpha.55 — el bloque vivo es un espejo del guardado

**Un hallazgo que cambia el coste de cada juego nuevo.** El bloque que quinta
generación mantiene en RAM es un **espejo contiguo del guardado**: partiendo
*solo* de la dirección del dinero de Negro 2, ya demostrada, y del
desplazamiento que PKHeX declara para ese campo, se calcula dónde empezaría el
bloque; y con esa base el contador del equipo y los seis Pokémon aparecen en el
guardado real del usuario, en las posiciones exactas que predice PKHeX.

Seis bloques PK5 con checksum válido no aparecen por azar.

**Qué significa:** cada juego nuevo necesita **un ancla, no seis**. Encontrado
el equipo en la RAM de Blanco, la mochila, el dinero y las medallas salen
restando y sumando desplazamientos ya conocidos.

**Lo que no autoriza** es heredar direcciones. Sondeado en PKHeX: Blanco guarda
el dinero en `0x21200` y Negro 2 en `0x21100`. Misma regla, distintos números.

- `tools_bw_anchor_capture.py` + `buscar_ancla_blanco.bat`: busca un PK5 de
  party válido en la RAM de melonDS y exige que **las tres cosas** cuadren —el
  contador ocho bytes antes, y el dinero y las medallas donde los predice el
  desplazamiento del guardado—. Una coincidencia suelta no basta.
- `tests/test_gen5_save_mirror.py` fija la regla y su límite.
- Suite completa: 1371.

### v0.2.6 Alpha.54 — Blanco: la base común, y qué comparte de verdad con Negro 2

Primer paso del segundo juego de DS. Todo lo de esta versión se hizo **sin pedir
nada al usuario**: sus cinco ROM están en el disco.

**Qué comparten Blanco y Negro 2, comprobado y no supuesto:**

- La **tabla de movimientos** (`a/0/2/1`) es **idéntica byte a byte**: 560
  registros de 36. Los PP de Blanco coinciden 559/559 con PKHeX.
- La **tabla personal** (`a/0/1/6`) **no**: Blanco usa 668 especies de `0x3C` y
  Negro 2, 709 de `0x4C`. Darlas por iguales habría leído las estadísticas de
  otra especie. Es justo el tipo de analogía que este proyecto no admite.
- En los dos, la tabla coincide con la copia de PKHeX salvo las habilidades 2 y
  oculta, que PKHeX normaliza. Las **estadísticas base coinciden en todas**.

**La arquitectura que pedía el usuario: plantilla, no copia.**

- `app/nds_rom.py`: sistema de archivos de una ROM de DS —cabecera, FNT, FAT y
  contenedores NARC—. No sabe de Pokémon, y sirve para los cinco juegos.
- `app/gen5_rom_service.py`: quinta generación con **un descriptor por juego**.
  Lo que cambia son cuatro datos, no un módulo entero.
- `app/b2w2_rom_service.py` desaparece; su contenido específico es ahora el
  descriptor `GEN5_GAMES["b2w2"]`.
- `boxed_metadata` gana la familia `bw` con su propia tabla, y
  `tools_extract_pkhex_personal.ps1` la extrae.

**Lo que falta para Blanco** son las direcciones de RAM: equipo, PC, batalla,
mochila, dinero y medallas. Ninguna se puede deducir de Negro 2 y todas
necesitan el juego en marcha.

- `tests/test_gen5_rom_service.py`: 37 pruebas, ahora sobre los dos juegos.
- Suite completa: 1367.

### v0.2.6 Alpha.53 — medallas VALIDADAS FÍSICAMENTE

El usuario confirmó (27-08-2026) que el contador de la cabecera marca **1** tras
conseguir la Medalla Base, y que los botones de sumar y restar ya no aparecen.
Con esto quedan cerradas alpha.50, 51 y 52.

**Estado de B2/W2.** Todo lo que la Run necesita está implementado:

| Capacidad | Estado |
| --- | --- |
| Equipo, PC, batalla y PS en vivo | validado |
| Roles y EV | validado |
| Curación | validado |
| Bajas y sustitución | validado |
| Mochila y utilidades de cabecera | validado |
| Enseñar MT (tabla viva, filtro por rol) | validado |
| Datos de juego desde la ROM | validado |
| Medallas | validado |
| Drafteo y borrado de movimientos | **implementado, sin validar** |

Lo único descartado por decisión del usuario: cambiar el rol de un Pokémon que
permanece en el PC. Basta con que entre al equipo con el rol que le toca.

**Siguiente frente: los otros cuatro juegos de DS** (DP, Pt, HGSS, BW), que hoy
tienen soporte de guardado pero cero tiempo real. B2/W2 se usa como plantilla,
no como copia: lo común —resolución de la base del proceso, primitivas de
memoria, contrato del writer transaccional, lectura de la ROM NDS— ya está
escrito de forma reutilizable; lo específico de cada juego (direcciones, formato
PK4 frente a PK5) va en su descriptor.

### v0.2.6 Alpha.52 — la dirección de medallas, confirmada contra el juego

Con la Medalla Base ya conseguida, `0x022266A8` vale **0x01**: exactamente lo que
predijo la deducción de PKHeX antes de mirar la RAM.

Dos caminos independientes apuntan al mismo byte:

1. **Antes de mirar**: en el guardado, cambiar `Misc5B2W2.Badges` mueve el byte
   que está cuatro más allá del dinero.
2. **Mirando**: ese byte tiene un bit encendido y el usuario tiene una medalla.

En el volcado aparece un segundo byte que también vale `0x01` (`dinero−32`), y
es una coincidencia esperable: con una sola medalla, cualquier byte a uno
encaja. Lo que separa a `dinero+4` es que estaba predicho. La segunda medalla lo
zanjará del todo —el bueno pasará a `0x03`— y hay una prueba anclada a la
captura que lo deja escrito.

- `tests/test_b2w2_badges.py`: 29 pruebas. Suite completa: 1357.
- Queda por confirmar que el **contador de la cabecera** sube solo, que es lo
  que arregló alpha.51.

### v0.2.6 Alpha.51 — la medalla ya llega al contador

Alpha.50 leía las medallas de la RAM y **las tiraba**: la rama de B2/W2 del
monitor nunca llamaba a `_process_oras_badge_value`, así que el contador no se
enteraba. Reportado por el usuario al conseguir la Medalla Base.

- La medalla se procesa ahora **antes** de cualquier return por herencia de rol
  o cambio de equipo, igual que en Perla Reluciente: una transición de party no
  puede retrasarla. Hay una prueba que fija ese orden, no solo la llamada.
- B2/W2 entra en `AUTOMATIC_BADGE_GAME_KEYS`, así que **desaparecen los botones
  de sumar y restar medallas**. Con el valor gobernado por el juego, mantener el
  control manual crearía dos fuentes de verdad.

**La dirección sigue sin confirmarse contra el juego.** Se dedujo de PKHeX y del
ancla de dinero, lo cual da por hecho que el bloque vivo respeta el reparto del
guardado más allá del propio dinero. `comprobar_medallas_b2w2.bat` lo resuelve
con una sola lectura: con N medallas conseguidas, el byte tiene que tener N bits
encendidos, y la herramienta lista todas las posiciones de la zona que encajan
para no fiarse de una sola.

- `tests/test_b2w2_badges.py`: 27 pruebas. Suite completa: 1355.

### v0.2.6 Alpha.50 — medallas en tiempo real, y el dinero corregido

**Medallas: `0x022266A8`**, deducidas sin pedir ninguna captura.

El dinero ya estaba demostrado en `0x022266A4`. Faltaba la distancia hasta las
medallas, y eso lo dice PKHeX: cambiar `Misc5B2W2.Badges` en un guardado en
blanco mueve el byte `0x21104`, y cambiar el dinero mueve `0x21100..0x21102`.
Medallas = dinero + 4. Misma vecindad que ORAS.

La equivalencia entre guardado y RAM está confirmada por partida doble: el
guardado real del usuario pone **4524** en `0x21100`, exactamente el valor con el
que empezó su traza de dinero.

- Quinta guarda **un bit por medalla**, no el número como ORAS: se cuentan.
- Si no se pueden leer se publica `None`, no un cero: un cero sería
  indistinguible de no tener ninguna.
- La procedencia se declara en el contrato común (`badge_source_is_live`), que
  rechaza por defecto cualquier fuente no registrada.

**Corregido de paso: el dinero ocupa tres bytes, no cuatro.** PKHeX solo toca
`0x21100..0x21102`. RoleRun escribía cuatro y pisaba el byte siguiente, que no le
pertenece. En el guardado del usuario ese byte vale cero, así que la validación
física de alpha.39 no se vio afectada, pero no había motivo para escribirlo.

- `tests/test_b2w2_badges.py`: 25 pruebas. Suite completa: 1355.
- **Pendiente de validación física**: al conseguir una medalla, el contador de
  la cabecera debe subir solo. Hoy el guardado marca cero.

### v0.2.6 Alpha.49 — el marco cortado, esta vez medido

Alpha.48 intentó arreglarlo a ojo y lo empeoró. Medido con la tarjeta real
reconstruida: **la tarjeta deja 92 píxeles útiles y el contenido pedía 95**, así
que Tk recortaba tres — exactamente el borde inferior de la fila de ataques, que
es la última. No era un problema de dibujo: la celda aislada se dibuja perfecta.

- El sitio sale del bloque de estadísticas, que iba sobrado: de 70 a 64 píxeles.
  Dos filas de etiqueta (10) y valor (11) con su margen ocupan unos 46.
- Se retiran los márgenes que alpha.48 había añadido, que eran justo los tres
  píxeles de más.
- Resultado medido: 86 necesarios sobre 92 útiles, seis de margen. Antes
  faltaban tres.
- Una prueba fija los tres números para que el recorte no vuelva por descuido.

- Suite completa: 1330.

### v0.2.6 Alpha.48 — el Support ya se puede resolver, y el marco cortado

**Las acciones del Support, donde ya estaban las demás.** Alpha.47 pintó de
dorado los ataques que sobran, pero al abrir la ficha no aparecía nada que
hacer. Ahora una celda dorada lleva los mismos **SUSTITUIR** y **ELIMINAR** que
lleva una incompatibilidad roja: es el patrón que la ficha ya usaba en todos los
juegos, no uno nuevo.

- `delete_move` solo miraba las incompatibilidades. Un ataque que sobra en un
  Support **no** es incompatible —el límite de dos es de conjunto, ninguno lo
  incumple por sí solo—, así que la acción no encontraba nada y no hacía nada.
  Ahora, si no hay incompatibilidad, se busca entre los candidatos del Support.
- Una incompatibilidad real sigue teniendo prioridad sobre el dorado.
- El botón que alpha.47 puso en la tarjeta se retira: no llegaba a pintarse y su
  sitio es la ficha.

**El marco cortado (todos los juegos).** Las celdas de movimiento tenían altura
fija y el borde inferior quedaba fuera:

- En la tarjeta, una celda marcada pasa de 16 a 18 píxeles y gana un píxel de
  margen abajo.
- En la ficha, una celda con botones deja de tener altura fija y se ajusta a su
  contenido. Los 54 píxeles se quedaban cortos en cuanto el texto ocupaba dos
  líneas.

- `tests/test_b2w2_move_presentation.py`: 17 pruebas. Suite completa: 1329.

### v0.2.6 Alpha.47 — dos fallos de la interfaz reportados con captura

**1 · Las tarjetas de drafteo salían vacías.** «Pot. — · Prec. — · PP —» y sin
descripción: `_draft_move_metadata` no tenía rama para B2/W2. Ahora la potencia,
la precisión y los PP salen de la ROM cargada —valores de quinta, y de *esta*
partida si está randomizada— y la descripción del catálogo español que RoleRun
ya trae. Sin ROM se muestra un guion en vez del número de otra generación; los
PP se conservan porque su tabla de quinta ya está demostrada.

**2 · Un Support con cuatro ataques no marcaba nada.** La tarjeta antigua ponía
en dorado los ataques candidatos y ofrecía elegir cuáles quitar; la vista
compacta de «Equipo y PC» solo conocía las incompatibilidades rojas, así que el
Support quedaba mudo. Ahora la vista recibe la misma regla y la misma acción.
El dorado no significa «ilegal» sino «elige cuál sobra», y una incompatibilidad
real manda sobre él.

**Decisión de alcance del usuario:** los Pokémon del PC **no** necesitan cambio
de rol, siempre que al entrar al equipo entren con el rol que les toca. Esa
capacidad queda descartada, no pendiente. Lo que sí queda por hacer en B2/W2 son
las **medallas en tiempo real**.

- `tests/test_b2w2_move_presentation.py`: 13 pruebas. Suite completa: 1325.

### v0.2.6 Alpha.46 — el drafteo, y VALIDACIÓN FÍSICA de alpha.42-45

**Validado físicamente el 27-08-2026** por el usuario: enseñar una MT funciona,
la MT no se gasta, y nada de lo que ya iba (roles, EVs, curación, estadísticas)
cambió al pasar a leer los datos de la ROM.

Con esto, alpha.42, 43, 44 y 45 quedan cerradas.

**Nuevo: el drafteo.** Cambiar un movimiento a mano ya escribe en Negro 2.

- Comparte writer con la enseñanza de MT: en el PK5 la escritura es idéntica y
  lo único que cambia es de dónde sale el movimiento. Dos writers para la misma
  escritura habrían sido la clase de duplicado que ya se pagó caro entre
  Sol/Luna y UltraSol.
- **Borrar** un movimiento (`new_move_id = 0`) compacta los huecos: un Pokémon
  no puede tener un hueco vacío delante de uno lleno. Misma operación que
  `_remove_move_slots` en ORAS. Lo necesita un Support al perder los ataques de
  daño que le sobran.
- Dar uno y quitar otro al mismo Pokémon va en **una sola transacción**: primero
  el nuevo —el hueco significa lo que el usuario vio— y después el borrado, que
  lo desplaza como haría el juego.
- No se deja a un Pokémon sin ningún movimiento, ni se borra un hueco vacío.
- La verificación se adapta: sin borrados exige el hueco exacto; con borrados
  exige que el movimiento esté, que el borrado no esté, y que no quede ningún
  hueco vacío por delante.
- Sin identidad del Pokémon no se escribe: el índice de party puede estar
  obsoleto.
- `tests/test_b2w2_draft_writer.py`: 23 pruebas. Suite completa: 1312.
- **Pendiente de validación física.**

Lo que sigue sin writer en B2/W2: los roles de Pokémon que permanecen en el PC.

### v0.2.6 Alpha.45 — la ROM se lee sin congelar la interfaz

Alpha.44 leia la ROM entera para consultar unos kilobytes. Con 512 MiB y un
disco frio, eso es una pausa perceptible en el hilo de Tk la primera vez, justo
lo contrario del objetivo de instantaneidad.

- Ahora solo se leen cabecera, FNT, FAT y los dos contenedores: **2 ms** frente
  a los 512 MiB del archivo.
- Hay una prueba que lo fija: carga una ROM sintética con relleno y comprueba
  que se lee menos de una cuarta parte.
- Suite completa: 1289.

### v0.2.6 Alpha.44 — B2/W2 lee los datos de juego de su ROM

Cierra el hueco que quedaba frente a randomizers, y lo hace como los juegos
terminados: ORAS y X/Y leen su ROM, Perla Reluciente su masterdata, y ahora
B2/W2 lee el `.nds` que melonDS tiene cargado.

**El riesgo que elimina.** Con tablas estáticas, aplicar un rol en una partida
randomizada recalculaba las estadísticas del Pokémon con las bases del juego
original y **las escribía en la partida**. Eso corrompe el equipo del jugador.

- `app/b2w2_rom_service.py`: sistema de archivos NDS (FNT/FAT), contenedores
  NARC, tabla personal (`a/0/1/6`) y tabla de movimientos (`a/0/2/1`).
- **Sin preguntar nada.** melonDS guarda la partida junto a la ROM y con el
  mismo nombre, así que se descubre desde `current_save.path`.
- `boxed_metadata.set_personal_override()`: la tabla del juego sustituye a la
  copia de PKHeX en un solo sitio, y todo lo que dependa del Personal
  —estadísticas base, curva de EXP, nivel derivado— pasa a usarla. Es la misma
  idea que `personal_for` en ORAS. Se olvida al cambiar de Run.
- Los PP de curar y enseñar, y la categoría que filtra las MT por rol, salen de
  la ROM cuando está.

**Formato demostrado contra oráculos independientes** (27-08-2026, ROM real):
- Personal: 709 registros de 76 bytes; idénticos a `pkhex_personal_b2w2.bin`
  salvo habilidades 2 y oculta, que PKHeX normaliza. Estadísticas base
  **iguales en los 709**.
- Movimientos: tipo y PP **559/559** contra `MoveInfo` de PKHeX; categoría
  separa limpiamente las tres; potencia y precisión coinciden con la tabla de
  sexta **salvo donde quinta difiere de verdad** (Lanzallamas 95→90,
  Hidrobomba 120→110, Píncers 14/85→25/95). La ROM corrige datos que la tabla
  estática tenía mal para quinta.
- `tests/test_b2w2_rom_service.py`: 28 pruebas. Suite completa: 1288.
- Pendiente de validación física.

### v0.2.6 Alpha.43 — la pantalla de MT, por rol y por partida

Verificado de extremo a extremo con el motor de reglas real, no con dobles.

- **El filtro por rol ya funcionaba y es el mismo de los demás juegos**:
  `_tm_move_compatible_with_role`. Al Mago no se le ofrecen ataques físicos, al
  Asesino no se le ofrecen especiales, y a un Support que ya conserva dos
  ataques solo se le ofrecen MT de estado. No hay una regla propia de B2/W2.
- **La compatibilidad por especie se sigue ignorando**, a propósito: quien
  decide es el rol. Magikarp, que en quinta no aprende ninguna MT, recibe las
  que su rol permita.
- **Randomizada, se ofrece y se escribe el movimiento de esta partida.** El
  caso que más fácil se rompería queda cubierto: la MT26 vanilla es Terremoto
  y a un Mago no se le ofrece; si la partida la randomiza a un ataque especial,
  sí. Y al revés. El `PendingTMTeach` que llega al writer lleva el movimiento
  vivo, y el número y el objeto de la MT no cambian.
- `B2W2TMSource` expone `.name`, que es lo que la pantalla muestra en todos los
  backends. Antes la procedencia se degradaba a «fuente validada».
- `tests/test_b2w2_tm_roles.py`: 20 pruebas nuevas. Suite completa: 1260.
- Nota abierta: la categoría física/especial de cada movimiento sale todavía del
  catálogo estático. Un randomizer que altere los datos de movimientos (no es
  su ajuste por defecto) desalinearía el filtro. Mismo caso que los PP.

### v0.2.6 Alpha.42 — enseñar MT en B2/W2

La pantalla MT y el selector individual ya funcionan en Negro 2/Blanco 2, con
el writer de enseñanza completo.

- **No se gasta la MT.** En quinta generación son reutilizables, así que el
  writer no toca la mochila. Misma regla que ORAS y X/Y; solo Perla Reluciente
  consume la máquina.
- `pk5_party_with_move()` escribe el movimiento y deja sus PP al máximo. Los
  Más PP del hueco vuelven a cero: se aplicaron al movimiento anterior y no se
  heredan, que es lo que hace el juego.
- Un movimiento que el Pokémon **ya conoce** se rechaza, incluso en su propio
  hueco: el juego tampoco lo permite y reescribirlo encima borraría los Más PP
  del jugador a cambio de nada.
- Enseñar no toca PS, estado ni estadísticas: la extensión de party se conserva
  byte a byte.
- `write_party_moves()` usa el contrato transaccional B2/W2 completo, y el
  adaptador localiza al Pokémon por **identidad fuerte**, no por el índice de
  party que traía el cambio.
- La interfaz no pide ninguna ROM: `_get_b2w2_tm_profile()` lee la tabla viva.
  Sin melonDS enlazado avisa y no lee nada.
- Lo que sigue sin writer en B2/W2: cambiar un movimiento a mano
  (`PendingChange`) y los roles de Pokémon que permanecen en el PC.
- **Pendiente de validación física.**

### v0.2.6 Alpha.41 — la tabla de MT, demostrada y leída en vivo

**Dirección demostrada: `0x02090C54`** (captura del usuario, 27-08-2026).

- En los 4 MiB de RAM hay **un solo** tramo con la forma de una tabla de MT: 101
  movimientos de 16 bits seguidos, todos válidos y todos distintos.
- Ese tramo coincide **101 de 101** con la lista derivada de PKHeX. Dos caminos
  independientes —forma y contenido— señalan el mismo sitio.
- La captura corrigió un supuesto: el juego guarda la lista en **orden de
  objeto** (MT01–92 = 328–419, MO01–06 = 420–425, MT93–95 = 618–620), no en
  orden de número de MT. La primera comparación dio 92/101 justo por eso; eran
  los mismos movimientos colocados de otra manera.
- `B2W2MelonDSReader.read_tm_table()` la lee en vivo con doble lectura y valida
  forma completa. `B2W2RealTimeAdapter.read_tm_profile()` publica el perfil.
- Se publican las **95 MT**. Las 6 MO se leen —van en medio de la tabla— pero no
  entran: la interfaz rotula cada entrada como `MT<número>` y una MO saldría con
  un número ajeno; además, en quinta un movimiento de MO no se olvida en juego.
- `data/b2w2_tm_table.json` queda como **referencia** para localizar y validar.
- Pendiente: conectar el perfil a la pantalla de MT y el writer de enseñanza.
  Nota abierta: los PP salen todavía de una tabla de PKHeX, que un randomizer
  también puede cambiar. Mismo caso que la curación; hay que resolverlo aparte.

### v0.2.6 Alpha.40 — la tabla de MT, replanteada para randomizers

**Corrección de un supuesto equivocado de alpha.39.** Alpha.39 extrajo la tabla
MT → movimiento de PKHeX dando por hecho que en quinta generación es fija. No lo
es para este proyecto: RoleRun está pensado para jugarse en **randomizers**, y un
randomizer cambia qué movimiento enseña cada MT. Esa tabla describe la quinta
generación original y solo acierta en una partida sin randomizar.

- La tabla que manda es la que el juego tiene cargada en memoria. Se lee en vivo,
  como el equipo y la mochila, así que vale sea cual sea la partida.
- `data/b2w2_tm_table.json` se conserva **como referencia**, no como fuente: es
  con lo que se localiza y se valida el tramo de RAM correcto. En una partida sin
  randomizar tiene que coincidir movimiento a movimiento, y esa coincidencia
  demuestra la dirección por un camino independiente de su forma.
- Lo que sí es fijo, randomizada la partida o no, es qué objeto es cada MT: MT01
  es el objeto 328 y MT21 el 348 en cualquier B2/W2.
- `tools_b2w2_tm_table_capture.py` + `buscar_mts_b2w2.bat`: busca 101 movimientos
  seguidos, todos entre 1 y 559 y todos distintos. Peor caso medido: 6,4 s sobre
  los 4 MiB. Sobre ruido totalmente válido aparecen falsos candidatos, y por eso
  la herramienta no se queda con «hay uno»: exige además la coincidencia.
- Lo que **no** cambia: la compatibilidad por especie se sigue ignorando a
  propósito. En RoleRun quién puede aprender una MT lo decide el **rol**, no la
  tabla del juego.
- Pendiente de la captura del usuario para fijar la dirección.

### v0.2.6 Alpha.39 — VALIDADO FÍSICAMENTE

El usuario confirmó (27-08-2026) que los tres botones de la cabecera funcionan
en Negro 2: Caramelos Raros ×999, Repelentes Máximos ×999 y dinero al máximo.

### v0.2.6 Alpha.39 — las utilidades de la cabecera escriben en B2/W2

Los tres botones junto a la vida (Caramelos Raros ×999, Repelentes Máximos ×999
y dinero al máximo) ya escriben en Negro 2/Blanco 2.

- Mochila: `set_bag_quantity` respeta el compactado del bolsillo. Caramelo Raro
  (#50) va a Medicinas y Repelente Máximo (#77) a Objetos, según el reparto
  extraído de `SAV5B2W2.Inventory`.
- Dinero: `0x022266A4`, demostrado en la traza de dos estados del 27-08-2026
  (único superviviente de 2 candidatos: 4524 → 4224). Tope 999 999, que es el
  único valor demostrado que la utilidad escribe.
- Ambos writers usan el contrato transaccional B2/W2 completo, y el adaptador
  contrasta el rótulo con la tabla de PKHeX antes de escribir.
- Sin melonDS sincronizado la utilidad avisa y no deja nada pendiente.
- **Pendiente de validación física.** Falta también el perfil de MT de B2/W2
  (qué movimiento enseña cada MT y qué Pokémon puede aprenderla), que se puede
  extraer de PKHeX y de `data/pkhex_personal_b2w2.bin` sin necesitar la ROM.

### v0.2.6 Alpha.38 — la mochila publicada por el contrato común

El usuario validó físicamente el lector: lo que RoleRun lee coincide con la
mochila del juego, bolsillo por bolsillo.

El adaptador implementa ya `read_tm_inventory`, el contrato por el que el resto
de RoleRun pide el inventario a cualquier backend, de modo que B2/W2 deja de ser
una excepción. El testigo del guardado sigue siendo solo diagnóstico: manda
siempre la muestra de RAM.

Falta mostrarlo en la interfaz y el writer de mochila/MT.

### v0.2.6 Alpha.37 — lector de la mochila B2/W2

`read_bag()` lee los 2456 bytes de la mochila con doble lectura estable y bajo el
cerrojo que serializa el lector. `parse_bag()` exige que cada bolsillo esté
compactado, que cada identificador sea legal en ese bolsillo según la lista de
PKHeX, que las cantidades estén entre 1 y 999 y que no haya objetos repetidos;
ante cualquier divergencia rechaza la mochila entera.

El número de huecos por bolsillo se deriva de la distancia hasta el siguiente
—310, 83, 109, 48 y 64—, todos por encima de su lista de objetos legales. La
mochila real del usuario pasa el validador completa y termina antes del contador
de party, que ya estaba demostrado.

`comprobar_mochila_b2w2.bat` contrasta contra el juego usando el lector de
producción. No se muestra en la interfaz ni se abre ninguna escritura todavía.

### v0.2.6 Alpha.36 — estructura completa de la mochila B2/W2

El mapa de bolsillos leído en la RAM del usuario coincide **byte a byte** con la
estructura que `SAV5B2W2.Inventory.Pouches` de PKHeX declara para el guardado, en
tres fronteras independientes: 1240, 1572 y 2008 desde el inicio del primer
bolsillo. No es una analogía entre juegos, sino un ajuste verificado tres veces
contra datos reales.

Mochila en `0x0221D9A4`. Bolsillos: Items +0, Objetos clave +1240, MT/MO +1572,
Medicinas +2008, Bayas +2200. Cada hueco son dos enteros de 16 bits,
identificador y cantidad, alineados a 4 bytes. El contenido confirma cada
bolsillo por su tipo, y ninguno de esos objetos formaba parte de la búsqueda.

`data/b2w2_bag_layout.json` recoge los desplazamientos y la lista de objetos
legales por bolsillo, que es lo que permitirá validar cada hueco al leer.

Dinero en `0x022266A4`, confirmado con dos estados.

Falta el reader y su validación; ninguna capacidad se abre todavía.

### v0.2.6 Alpha.35 — anclas de mochila y dinero demostradas

El método de dos estados dejó una sola dirección en cada caso.

El **bolsillo de medicinas está en `0x0221E17C`**: de cinco posiciones que
contenían «Poción ×2», solo esa pasó a «Poción ×3» al usar una. La casilla
contigua contiene Antiparalizador ×2, un objeto que la búsqueda no pedía, lo que
corrobora de forma independiente que es un bolsillo real; el resto de la zona está
a cero, como corresponde a un bolsillo compactado. La estructura son pares de dos
enteros de 16 bits —identificador y cantidad— alineados a 4 bytes. El ancla cae
0x230 antes del contador de party ya demostrado, de modo que la mochila vive en el
mismo bloque espejo del guardado.

El **dinero está en `0x022266A4`** como entero de 32 bits: de dos posiciones con
4524, solo esa pasó a 4224 tras una compra.

Falta mapear dónde empieza y acaba cada bolsillo, y confirmar ambas direcciones
tras reiniciar el juego. Hasta entonces no son direcciones de producción.

### v0.2.6 Alpha.33 — el siguiente paso de B2/W2 es evidencia, no código

El usuario validó físicamente el ciclo completo de combate y bajas: daño en
tiempo real, KO en el momento, descuento de vida, selector, sustitución y
recuperación al curar.

Lo que le queda a B2/W2 —mochila, MT, utilidades y medallas— depende en todos los
casos de direcciones de RAM no demostradas, así que la siguiente entrega es una
herramienta de diagnóstico y no una implementación.

`tools_b2w2_bag_capture.py` busca el par (identificador, cantidad) de 16 bits que
usa la mochila de quinta generación, con las cantidades reales que el usuario ve
en su partida, y conserva solo las zonas donde coinciden varios objetos distintos
y que sobreviven a dos lecturas separadas. El dinero se busca aparte como entero
de 32 bits alineado.

### v0.2.6 Alpha.32 — PS y bajas en tiempo real durante el combate

La traza `b2w2_battle_faint_latest.json` del 27-08-2026 zanjó el diagnóstico con
tres hechos medidos.

El bloque de party de quinta generación **no refleja el daño durante el
combate**: la copia de presentación mostró 3/16 y luego 0/16 mientras la party
seguía en 16/16, y esta solo se actualizó al terminar. La segunda fila de batalla
estuvo **obsoleta todo el combate** —otro miembro, inmóvil, nivel 516 imposible—,
y como `parse_battle_copies` exigía identidad común entre ambas filas, descartaba
la única fuente válida. El byte de estado se mantuvo en 0 incluso con el Pokémon
debilitado, lo que **descarta** la sospecha de la auditoría sobre estados no
demostrados.

La copia de presentación pasa a ser la autoridad y la segunda fila solo
corrobora. Se conservan intactas la identificación única contra el equipo, el
rechazo de PS imposibles y el de estados no demostrados; y con ambas filas de
acuerdo se mantiene el comportamiento validado en alpha.5 de no adelantar el KO a
la animación.

Limitación demostrada: durante el combate solo se conoce el PS del Pokémon
activo; el resto procede del bloque de party, que el juego no actualiza hasta el
final.

Baseline completa: **1112 passed**. Validación física pendiente.

### v0.2.6 Alpha.31 — el ciclo de bajas, cerrado salvo el tiempo real

El usuario validó físicamente la sustitución completa: el debilitado llega al
Cementerio, el sustituto entra heredando el rol y la casilla de origen queda
vacía. Con alpha.29 quedaron validados además la casilla correcta liberada, el
selector y la recuperación al curar.

Queda **un fallo abierto**: ni los PS ni la baja se actualizan durante el
combate; todo aparece al terminarlo. Hay dos explicaciones plausibles —que el
bloque de party de Gen 5 no se actualice hasta el final del combate, o que la
lane de presentación rechace la lectura al morir por un byte de estado no
demostrado— y **ninguna está probada**. Se añade
`tools_b2w2_battle_faint_capture.py`, de solo lectura, que muestrea party y filas
de batalla en paralelo y ejecuta el parser de producción sobre cada muestra
anotando su veredicto.

### v0.2.6 Alpha.30 — aislamiento de ctypes y lector serializado

La prueba física de alpha.29 confirmó que la casilla correcta queda libre, que el
selector se abre y que curar al debilitado lo devuelve. Aplicar la sustitución
fallaba con un `TypeError` de ctypes ajeno a la sustitución.

`PROCESSENTRY32W` se declaraba dentro de la función que enumera procesos, de modo
que cada llamada creaba una clase distinta y refijaba `argtypes` sobre
`ctypes.windll.kernel32`, que es un singleton compartido por los cuatro módulos
de RoleRun que declaran esa misma estructura. Dos hilos solapados se invalidaban
los tipos mutuamente.

B2/W2 pasa a tener una estructura única de módulo y una instancia privada de
kernel32 con los tipos fijados al importar. El lector queda además serializado
con un cerrojo reentrante, que es la mitigación concreta del riesgo ALTO de
concurrencia que la auditoría había anticipado sin poder demostrar.

Queda **abierto** que la vida se descuente en el momento del KO y no al terminar
el combate.

Baseline completa: **1100 passed**.

### v0.2.6 Alpha.29 — la baja de B2/W2 vuelve a tener salida

La prueba física de alpha.28 demostró que detectar la baja no basta: había que
poder salir de ella. La rama B2/W2 del monitor no llamaba a
`_process_oras_battle_state` ni a `_reconcile_pending_faints_against_party`, que
los otros cinco backends sí llaman.

Sin la primera nunca se marca `battle_ended`, y de ahí salían tres síntomas a la
vez: el selector de sustituto no se abría porque lo exige, curar al debilitado no
lo devolvía porque `clear_stale_detected_faint_for_alive_party` exige
`battle_ended` o `prompt_shown`, y reiniciar no ayudaba porque la baja se
persiste en la Run. Sin la segunda, resolver la baja desde el PC del juego pasaba
desapercibido.

Se añade además una regla de presentación común a todos los juegos: una baja
pendiente **reserva la casilla de su rol**. Esa casilla pertenece al rol y es la
que heredará el sustituto; permitir que un miembro SIN ROL se deslizara hasta
ella movía el hueco visible a un rol distinto del que había quedado libre.

Baseline completa: **1092 passed**. Validación física de la sustitución todavía
pendiente.

### v0.2.6 Alpha.28 — bajas y sustitución en B2/W2

Con la lane de combate, el writer de roles y la escritura del PC ya validados
físicamente, B2/W2 puede cerrar el ciclo que da sentido a una RoleRun.

La rama B2/W2 del monitor pasa a llamar al camino común de salud completo, que
detecta las transiciones a cero PS, descuenta la vida, registra el evento y abre
el selector de sustituto. En combate confirmado la fuente es `battle-visible`: la
copia de presentación ya converge con la animación, de modo que el KO se registra
cuando la barra visible llega a cero.

`replace_fainted_party_pc()` mueve tres posiciones: sustituto desde su casilla a
la party, debilitado al Cementerio y casilla de origen vacía con el PK5 semilla-0
que deja el juego. El orden de escritura —Cementerio, party, vaciar origen—
garantiza que ningún Pokémon se quede sin copia en ningún punto intermedio.
Verifica ambas identidades fuertes, exige el Cementerio libre y hace rollback de
las tres posiciones ante cualquier divergencia.

Baseline completa: **1082 passed**. Validación física pendiente.

### v0.2.6 Alpha.27 — el monitor deja de esperar a lo inaplicable

El usuario validó físicamente la curación. Antes de abrir la siguiente capacidad
se cierra la clase de fallo que ha costado tres rondas de diagnóstico.

`_oras_live_reconciliation_can_read` exigía la cola de cambios completamente
vacía. Un cambio que el adaptador activo no sabe aplicar nunca sale de esa cola,
así que el monitor dejaba de leer para siempre. Pasó con la curación en alpha.16
y con los roles en alpha.23, esta última manifestándose como tres fallos
aparentemente distintos que eran uno.

Ahora solo bloquean la lectura los cambios con writer. Los demás siguen en cola
para el flujo de archivo, sin secuestrar el seguimiento en vivo.

Estado de B2/W2 tras las validaciones físicas del 27-08-2026: party, ficha,
combate, PC (lectura, cambios externos y escritura completa), roles con EV y
curación. Quedan mochila/MT, bajas con sustitución, utilidades y medallas.

Baseline completa: **1071 passed**.

### v0.2.6 Alpha.26 — writer de curación en B2/W2

El usuario validó físicamente el rol y los EV de alpha.24/25, y la siguiente
capacidad del documento de paridad es la curación.

Curar deja PS al máximo, estado alterado a cero y los PP de los cuatro
movimientos al tope contando los Más PP. El PP base procede de una tabla propia
de quinta generación, `data/b2w2_move_pp.json`, extraída de la misma PKHeX.Core
que usa el motor de guardados mediante `MoveInfo.GetPPTable(EntityContext.Gen5)`;
la herramienta que la genera vive en `tools_extract_gen5_move_pp/`. No se
reutiliza la tabla de sexta generación porque varios movimientos cambiaron de PP
entre generaciones. Un PP no demostrable detiene la curación en lugar de
inventarse un valor.

`write_party_heal()` mantiene el contrato transaccional del resto de writers
B2/W2 y verifica semánticamente PS, estado y PP antes de dar la operación por
buena. Curar a quien ya está curado no escribe nada.

Baseline completa: **1061 passed**. Validación física pendiente.

### v0.2.6 Alpha.25 — metadatos vivos y reparto de EV en B2/W2

La validación física de alpha.24 confirmó que la marca del rol se escribe en el
juego, y destapó dos cosas más.

La ficha mostraba «—» en estadísticas, IV, EV y naturaleza hasta que se asignaba
un rol. `diff_live_party` ignora esos campos por diseño, y la rama B2/W2 solo
publicaba la captura viva cuando ese diff detectaba algo; cualquier recarga desde
el guardado dejaba la vista sin ellos de forma permanente. Se publica ahora
también cuando la captura viva trae datos que la vista no tiene, comprobado por
identidad fuerte y en un solo sentido.

Los EV de un rol no se repartían porque la lista de backends con reparto estaba
escrita como literal en siete sitios y B2/W2 no figuraba en ninguno. Ahora es la
constante `ROLE_EV_WRITER_GAME_KEYS`. Los tres usos restantes de ese literal
pertenecen a MT/ROM y se conservan.

Baseline completa: **1040 passed**.

### v0.2.6 Alpha.24 — writer de roles y EV en B2/W2

B2/W2 no tenía writer de roles, así que asignar uno no producía ningún efecto: el
`PendingRoleChange` se quedaba en la cola para siempre. Y como el monitor exige la
cola vacía para leer, ese cambio atascado congelaba también la actualización de
la salud. Un mismo defecto explicaba «los roles no funcionan», «los EV siguen a
cero» y «la vida no se actualiza».

El rol vive en las seis marcas del PK5 y, cuando el rol define un reparto de
esfuerzo, también en los EV. `pk5_party_with_role()` reescribe ambos y recalcula
las estadísticas finales con la tabla personal de la edición; conserva el daño
recibido y nunca revive a un debilitado. `write_party_roles()` lo envuelve en el
contrato transaccional habitual: relectura fresca, identidad fuerte por slot,
readback con el parser de producción, verificación semántica y rollback.

La curación de B2/W2 sigue cerrada por no tener writer propio.

Baseline completa: **1027 passed**. Validación física pendiente.

### v0.2.6 Alpha.23 — salud viva durante el combate en B2/W2

La captura física del 27-08-2026 demostró que alpha.22 no bastaba: con Mareep
debilitado y Azurill a 4/20, RoleRun seguía pintando a los seis al máximo durante
el combate y solo se corregía al salir.

`BattleState` vale `"unknown"` por defecto y la lane de presentación de B2/W2 lo
deja así ante cualquier excepción —dos copias describiendo miembros distintos en
un cambio, animación a medias, estado runtime no demostrado—. Con ese valor no se
publicaba salud alguna, así que un fallo que solo concierne al Pokémon activo
congelaba al equipo entero.

La lane gobierna únicamente los PS del activo; los otros cinco ya proceden del
bloque de party incluso en combate confirmado. Con la lane sin validar se publica
ahora ese bloque. La regla de alpha.5 se mantiene intacta para el combate
confirmado, y no se afirma que haya combate cuando no se sabe.

Baseline completa: **999 passed**.

### v0.2.6 Alpha.22 — la rama B2/W2 del monitor, corregida

El usuario reportó dos fallos el 27-08-2026 y resultaron ser el mismo defecto.
La rama B2/W2 de `_finish_oras_live_reconciliation` reconstruía la barra flotante
entera en cada ciclo cuando **no** había cambiado nada, y no publicaba la salud
cuando sí había cambiado.

Lo primero producía el parpadeo de una vez por segundo que arrastraba desde
v0.2.6-alpha.1: `_sync_live_layout(refresh_floating=True)` destruye todos los
widgets de la barra y relee dos PNG del disco. Lo segundo dejaba los PS
congelados en la ventana principal, porque `diff_live_party` ignora la vida por
diseño y B2/W2 era el único backend que no llamaba después a la publicación de
salud.

Se extrae `_publish_live_health()` —la parte de `_process_oras_health_snapshot`
que no decide bajas— y B2/W2 la usa. El KO de B2/W2 permanece cerrado. Solo se
publica salud demostrada: la copia de presentación en combate y el bloque de
party fuera de él; con la lane de batalla en estado no confirmado no se publica
nada, para no adelantar el daño antes de que el juego lo muestre.

La barra flotante gana además actualización en su sitio de sus barras de PS, con
las mismas condiciones de cesión que las tarjetas del equipo.

Baseline completa: **996 passed**.

### v0.2.6 Alpha.21 — actualización incremental de los PS en vivo

Primera pieza de la Fase 3. También la primera medición del proyecto hecha sobre
la vista construida de verdad bajo Tk en Windows, que era la hipótesis abierta
más cara de la auditoría.

Reconstruir Equipo y PC cuesta **845 ms** de hilo Tk y crea **642 widgets**. Una
confirmación de cambio dispara 3-4 reconstrucciones: 2,5-3,4 s de congelación. En
combate, cada cambio de PS pagaba una reconstrucción completa.

`UnifiedTeamPCView` expone ahora `update_team_health()` y
`rendered_team_identities()`. Refrescar las seis barras cuesta **8,2 ms**: ×103.
La presentación (fracción, color y texto) vive en `_health_presentation`, único
punto que usan tanto el render completo como la actualización incremental.

La ruta es de aceleración, no de decisión: cede al render completo si cambia la
composición del equipo, si la vista no es la publicada, si una tarjeta ya está
destruida o ante cualquier error. La evidencia que consulta la barrera inicial se
actualiza junto a los widgets.

Quedan por hacer incrementales los otros disparadores de render completo:
llegada de sprite, snapshot publicado, reconciliación del PC y escritura
confirmada.

Baseline completa: **981 passed**.

### v0.2.6 Alpha.20 — base de melonDS cacheada y revalidada

Primera pieza de la Fase 5. Cada lectura de B2/W2 recorría entero el espacio de
direcciones de melonDS para volver a encontrar la misma base; alpha.19, al
devolver la vida al sondeo del PC, hizo que ese coste se pagara además cada
pocos segundos.

La base se resuelve una vez y se revalida en cada uso con la doble lectura
estable de `count`+party ya existente: no se relaja ninguna comprobación, solo se
deja de buscar. El recorrido completo —único lugar donde se detectan lecturas
ambiguas— se rehace al cambiar el conjunto de procesos melonDS y cada 60 s. Si la
revalidación falla o melonDS desaparece, la base se olvida y se vuelve a
descubrir.

La doble lectura interna de `resize_party_pc` se conserva intacta: es la captura
fresca previa a escribir y pertenece al contrato del writer.

Baseline completa: **961 passed**.

### v0.2.6 Alpha.19 — el seguimiento del PC vivo vuelve a existir

El fallo físico del 27-08-2026 demostró que RoleRun no detectaba ningún cambio
del PC hecho dentro del juego. La causa no estaba en el backend ni en el writer:
`_bdsp_pc_poll_is_active` exigía `active_page == "pc"` y, desde que Equipo y PC
se unificaron en una sola pantalla, ninguna ruta de navegación produce ese valor.
La barra principal solo ofrece `"team"` y los controles secundarios están
ocultos precisamente para `{"team", "pc"}`. El sondeo permanente del PC vivo, el
refresco al entrar en la vista y la cancelación al salir eran código inalcanzable
para B2/W2 y BDSP.

Los tres puntos usan ahora `TEAM_PC_PAGES`, declarado una sola vez. El resto del
archivo ya comprobaba `in {"team", "pc"}` en diez sitios.

El usuario confirmó físicamente el 27-08-2026, en Pokémon Negro 2 España con
melonDS 1.1, que el seguimiento de los cambios del PC hechos dentro del juego
funciona correctamente desde RoleRun. Con eso la fila «PC cambios externos» del
documento de paridad pasa a **VALIDADA FÍSICAMENTE**.

Queda **sin demostrar** el mecanismo exacto de la duplicación observada al
retirar desde la vista desfasada; su precondición está cerrada y no reapareció. El writer valida
identidad y coordenadas contra la RAM antes de escribir, por lo que la partida no
estuvo en riesgo en ningún momento. La capacidad «PC cambios externos» de
`B2W2_REALTIME_PARITY.md` sigue **pendiente de validación física**.

Baseline completa: **953 passed**.

### v0.2.6 Alpha.18 — el bucle de mando deja de robar CPU al hilo Tk

Primera optimización de la fase de rendimiento apoyada en medición, no en
sospecha. `_poll_gamepad` corre a 60 Hz en el hilo de la interfaz y, mientras no
hubiera mando resuelto, buscaba Ryujinx en cada tick enumerando la tabla completa
de procesos de Windows. Medido en esta máquina: 2,36 ms por intento, **142 ms de
CPU por segundo (14 % de un núcleo)** gastados exclusivamente en no encontrar
nada, en todos los juegos salvo BDSP y desde el propio splash.

La búsqueda se limita a un intento cada 2 s. No se restringe a BDSP porque no
está demostrado que el mando no se use en otros juegos con Ryujinx instalado, y
el intervalo ya elimina prácticamente todo el coste.

Baseline completa: **940 passed**.

### v0.2.6 Alpha.17 — monitor huérfano, error≠dato y sprites no bloqueantes

Tres riesgos de la auditoría, los tres con regresión determinista y sin
depender de emulador.

El monitor vivo podía quedarse huérfano en cada guardado del juego: el watcher
reiniciaba la reconciliación con una lectura en vuelo, no lograba armar nada por
el cerrojo, y el worker viejo terminaba sin reprogramar. La sesión quedaba con
`_oras_live_active=True` y sin lecturas. El rearme se hace ahora en el cierre del
worker obsoleto, no soltando el cerrojo antes, para no permitir capturas
solapadas sobre readers con estado mutable y sin lock.

La comparación de la RAM con `main` confundía un fallo del motor con un «no
coincide» demostrado, y con eso RoleRun adoptaba como expectativa una huella que
no había podido verificar. Ahora distingue los tres casos y reintenta.

La ausencia de un sprite ya no puede dejar RoleRun en la pantalla de carga: se
dibuja una silueta local, se avisa sin bloquear y la partida se abre. La descarga
tiene límite de tiempo y las peticiones se deduplican.

Baseline completa: **935 passed**.

### v0.2.6 Alpha.16 — retirada B2/W2 posible y CURAR coherente

Dos defectos demostrados de B2/W2, ambos con regresión determinista.

La retirada PC→Equipo nunca pudo funcionar. `resize_party_pc` escribía 136 ceros
en el slot PC liberado y su propio readback los rechazaba, de modo que la
operación siempre terminaba en rollback. El vacío real del juego es un PK5
almacenado cifrado con semilla 0: lo demuestra la captura física
`b2w2_party_resize_latest.json`, donde tras retirar desde el propio juego el
parser de producción leyó `pc_empty: 717` sin lanzar, y coincide byte por byte
con el prefijo de la cola de party validada en alpha.13.

El botón CURAR se ofrecía en B2/W2 sin writer de curación. Los seis
`PendingPartyHeal` que encolaba no los aplicaba ni los retiraba nadie, y el
monitor —que exige la cola vacía— dejaba de leer la partida viva. El botón queda
retirado hasta que exista el writer. La regresión es un invariante para los seis
backends: botón y compuerta deben coincidir siempre.

Estado real: la retirada 5→6 quedó **implementada, con prueba y VALIDADA
FÍSICAMENTE**: el usuario confirmó el 27-08-2026, en Negro 2 España con
melonDS 1.1, que retirar del PC al equipo funciona correctamente desde RoleRun.
La curación B2/W2 sigue **cerrada** hasta que exista su writer.
Baseline en su momento: **918 passed**.

### v0.2.6 Alpha.15 — instrumentación de rendimiento

La auditoría del 27-08-2026 dejó como hipótesis sin medir el coste real en
Windows del motor .NET, del render completo y del walk de memoria de melonDS.
Alpha.15 no corrige ni optimiza nada: añade la medición que faltaba para poder
decidir con evidencia. El modo se activa con `ROLERUN_PERF=1` y está apagado por
defecto con coste cero.

Primeras cifras demostradas en esta máquina: cada invocación del motor .NET paga
un suelo de **~72 ms** antes de cargar PKHeX.Core y abrir la partida, así que la
carga de una run acumula ≥290 ms solo en arranques de proceso; `append_history`
cuesta 2,5–8,1 ms por evento en NTFS. Detalle y método en
`docs/PERF_INSTRUMENTATION.md`. Baseline completa: **906 passed**.

### v0.2.6 Alpha.14 — destino vivo de depósito y ventana maximizada

El fallo físico del 27-08-2026 demostró que Equipo/PC mostraba correctamente
los slots vivos de melonDS, pero `send_pokemon_to_pc` dejaba B2/W2 en la rama
clásica y volvía a leer el PC del save. Así podía escoger Caja 1/slot 1 desde el
archivo aunque esa posición estuviera ocupada en RAM, y el writer la rechazaba
correctamente. La acción conserva ahora la coordenada exacta de la matriz viva;
la relectura de RAM previa a escribir, el readback y el rollback no se relajan.

La carga inicial continúa centrada y no invasiva. Cuando la partida ya está
validada y compuesta, la raíz se maximiza con el estado normal `zoomed` de
Windows, no con fullscreen/F11. Ambas correcciones tienen regresión automática;
el depósito y la presentación final quedan pendientes de validación física.

### v0.2.6 Alpha.5 — presentación de daño y parálisis B2/W2

La validación física de alpha.4 encontró dos divergencias. La copia lógica de
PS se actualiza antes de que el juego presente la animación y adelantaba el
resultado en la barra; la copia retrasada converge después y pasa a gobernar la
presentación. La fuente rápida permanece como testigo lógico y ambas deben
conservar identidad. No se añade un retraso fijo.

La misma prueba demostró que el runtime nominal B2/W2 expuso `1` para una
parálisis visible. Ese valor no es el bitmask persistente PKHeX que la UI común
interpretaba como sueño. Solo el caso observado se traduce a `64` (PAR); otros
valores runtime no demostrados se ocultan en vez de etiquetarse por suposición.
El usuario confirmó físicamente el 26-08-2026 que la barra ya acompasa el daño
sin adelantarlo y muestra correctamente `PAR`. Ambos arreglos quedan cerrados
para combate simple de Negro 2 España/melonDS 1.1.

### v0.2.6 Alpha.4 — PS inmediatos de combate B2/W2

La traza temporal de 1.308 muestras resolvió las dos copias: ambas comenzaron
con Tepig a 8/24; `0x0225B5FC` publicó 0 PS a los 9.037 ms y
`0x0225B1B4` convergió a 0 a los 12.399 ms. El reader usa la segunda como fuente
inmediata y la primera como testigo retrasado, exige especie, nivel, habilidad,
PS máximos e identidad única contra la party y hace doble lectura. Fuera de
combate ambas filas se demostraron vacías y la party normal volvió a 24/24.

El adapter publica `BattleState.health_game` y la UI actualiza la salud de la
barra cada 250 ms durante el combate. El KO automático permanece deshabilitado:
B2/W2 todavía no dispone de PC/reemplazo seguro y no debe descontar una vida que
no pueda completar de extremo a extremo. Regresiones dirigidas: **26 passed**.

### v0.2.6 Alpha.3 — Pokémon sin rol visibles y primera evidencia de combate

La barra flotante solo consultaba ocupantes con un rol canónico y descartaba
la lista de miembros SIN ROL que la vista principal sí coloca en huecos libres.
Además, el adapter B2/W2 reemplazaba el rol persistido por SIN ROL cuando el PK5
no tenía todavía una marca física, aunque B2/W2 sigue sin writer de marcas.
Ahora barra y equipo usan la misma colocación de seis celdas; un miembro SIN ROL
es visible con esa etiqueta, y el adapter conserva el rol persistido salvo que
exista exactamente una marca viva que constituya evidencia nueva.

La captura guiada `b2w2_battle_capture_latest.json` observó a Tepig/especie 498,
nivel 6, habilidad 66 y PS máximos 24 en dos estructuras idénticas. Ambas
publicaron `24→21` durante el daño y desaparecieron al salir del combate. Los PS
están en `0x0225B1B4` y `0x0225B5FC`, separados por `0x448`. Al existir dos
copias todavía no se ha elegido autoridad ni activado combate/KO en producción.

Regresiones dirigidas de B2/W2 y barra: **23 passed**.
El usuario confirmó físicamente el 26-08-2026 que Tepig vuelve a aparecer
correctamente en la barra flotante de Negro 2/melonDS. El bug de visibilidad de
miembros SIN ROL queda cerrado para este entorno.

### v0.2.6 Alpha.2 — metadatos PK5 y matriz completa de paridad

El PK5 de party ya demostrado publica ahora estado, naturaleza, estadísticas
reales, IV, EV, PP, PP Up, huevo y las seis marcas. Los offsets y el orden
proceden de `PKHeX.Core/PKM/PK5.cs` y se contrastaron contra el Tepig vivo de
Negro 2/melonDS: nivel 6, 19/24 PS, naturaleza 21, stats
`(24,13,9,10,12,11)`, IV `(10,16,23,6,13,11)` y PP `(31,30,0,0)`.
La lectura sigue siendo doble, con checksum e identidad; todas las escrituras
B2/W2 permanecen cerradas. `docs/B2W2_REALTIME_PARITY.md` enumera los carriles
de 3DS/BDSP pendientes para no omitir ninguna mecánica.

Regresiones dirigidas: **10 passed**. La lectura directa de melonDS quedó
comprobada. El usuario validó físicamente en la UI de RoleRun los IV, EV,
habilidad, objeto y movimientos el 26-08-2026. Los PP no tienen representación
visual en la interfaz actual: su lectura interna no se considera por tanto una
validación visual ni se añade una vista nueva fuera del alcance del diseño.
Naturaleza/estado/huevo quedan pendientes de una muestra física específica.

### v0.2.6 Alpha.1 — B2/W2 en melonDS, party de solo lectura

Pokémon Negro 2 (España) en melonDS 1.1 dispone de una primera ruta en el
Real-Time Core. La lectura real del 26-08-2026 publicó Tepig, nivel 5 y 22/22 PS
con la misma identidad PID/TID/SID que el guardado activo.

La primera divergencia del intento anterior estaba antes de la UI: además de la
party nominal `0x0221E3AC`, exigía una supuesta copia fija en `0x02247A2C` que
la sesión actual refutó. Alpha.1 relee dos veces `count + party`, exige un único
mapeo anfitrión y valida checksum y estructura de cada PK5. El adapter rechaza
cualquier RAM sin identidad fuerte común con el guardado seleccionado.

La sincronización inicial y el monitor salen antes de las rutas heredadas. Toda
mutación B2/W2 está cerrada en la compuerta de UI. PC, roles, curación, MT,
inventario, batalla, bajas y progreso no están demostrados. El usuario confirmó
físicamente el 26-08-2026 que la conexión, el equipo, los PS y su actualización
en vivo funcionan correctamente en Pokémon Negro 2/melonDS 1.1.
Baseline completa de `v0.2.6-alpha.1`: **876 passed** en 36,65 s.

### v0.2.5 Alpha.9 — drafteo de Líbero ordenado y validaciones ORAS

El usuario confirmó físicamente en ORAS/Azahar que el dinero infinito se
refleja correctamente, que las cinco opciones de Support aparecen completas y
que el drafteo propio de Líbero respeta su composición. Para facilitar su
lectura, las tres categorías auxiliares aleatorias se publican primero y
ocupan la fila superior; daño físico y daño especial permanecen como resultados
fijos y ocupan la fila inferior centrada. Esta modificación solo cambia el
orden de presentación, no los pools ni el sorteo.

No queda otra funcionalidad ORAS nueva identificada como pendiente en el
alcance actual. La única comprobación necesaria antes de cerrar el juego es la
validación física de la enseñanza de una MT ya implementada: debe cambiar el
movimiento y la MT debe seguir disponible por ser reutilizable en ORAS.

### v0.2.5 Alpha.8 — dinero ORAS resuelto y drafteos de cinco categorías

La dirección nominal del bloque Misc de ORAS contenía una muestra cero que el
resolver aceptaba porque dinero y PB estaban dentro de sus rangos. La
comparación del bloque completo con el testigo del guardado demostró que no era
la copia viva. El resolver rechaza ahora esa coincidencia parcial, localizó el
bloque real y la escritura terminó con readback de `9.999.999 ₽` en
`0x08C6DDD0`. El usuario confirmó después en la interfaz del juego que el dinero
infinito funciona; esa validación física queda registrada en Alpha.9.

Los conjuntos de cinco resultados ya no crean tres filas: usan una composición
3+2 con la segunda fila centrada. La vista de diagnóstico a 1920×1080 mostró
las cinco tarjetas y sus acciones completas sin scroll. Líbero posee además un
drafteo propio de cinco categorías: daño físico, daño especial y tres
categorías auxiliares distintas tomadas de los pools compatibles con la
generación activa. Los IDs permitidos del juego siguen siendo el límite del
catálogo, por lo que no entran movimientos futuros.

### v0.2.5 Alpha.7 — dinero independiente de la mochila y MT ORAS completas

La investigación del dinero infinito localizó la primera divergencia antes de
la escritura: el dinero está en el bloque Misc, pero se trataba como si formara
parte de una bolsa y recibía el desplazamiento dinámico del inventario. El
writer resuelve ahora el bloque Misc con su propio testigo, valida una captura
estable, escribe solo el campo de dinero y conserva readback y rollback. La
acción terminó localmente con el readback confirmado; queda pendiente mirar el
valor 999.999 ₽ en la interfaz del juego.

La tabla de movimientos queda fijada a la revisión ORAS y la UI consume sus
datos. La comprobación visual local mostró solo las dos MT realmente presentes
en la mochila viva: MT39 Truco Fuerza y MT54 Pistola Agua. Sus PP y, cuando
aplican, potencia y precisión se mostraron correctamente. La enseñanza física
de una MT continúa pendiente.

### v0.2.5 Alpha.6 — MT ORAS preparadas con inventario vivo obligatorio

La revisión del flujo completo demostró que el reader y el writer ORAS ya
trabajaban con la mochila RAM validada y trataban las MT como reutilizables,
pero la UI sustituía una lectura viva fallida por el inventario del último
guardado. Esa era la primera divergencia: una fuente obsoleta podía habilitar
el selector pese a que la sesión actual no estuviera demostrada. Se ha
eliminado únicamente ese fallback de ORAS; el guardado sigue sirviendo como
testigo de resolución, pero nunca como inventario operativo. La regresión
demuestra tanto el rechazo seguro como la publicación correcta desde RAM viva,
y el conjunto focalizado termina con `14 passed`. Falta enseñar físicamente
una MT en ORAS/Azahar y confirmar que el movimiento cambia y la MT permanece.

### v0.2.5 Alpha.5 — metadatos completos de equipo y PC ORAS

La ROM y el perfil Personal ORAS eran correctos, pero la sincronización inicial
vaciaba la referencia al perfil después de capturar y antes de publicar los
Pokémon. Esa primera divergencia impedía enriquecer el equipo con stats base y
dejaba las fichas del PC sin naturaleza, stats finales, IV ni EV. El perfil se
prepara ahora antes de cada captura inicial, refresco externo y resincronización
manual, se conserva durante la publicación y las cajas ORAS se refrescan al
terminar la carga inicial. Las regresiones están en verde y la comprobación
local visible confirmó en Dwebble de PC naturaleza Ingenua, stats finales,
stats base, IV y EV. El usuario confirmó después físicamente esos metadatos en
equipo y PC de ORAS/Azahar. La herencia de rol y EV no se modificó.

### v0.2.5 Alpha.4 — intercambio Equipo↔PC ORAS con rol y EV completos

La UI ya incorporaba al `PendingTeamChange` la distribución de EV calculada
para el rol que hereda el Pokémon entrante. La revisión del flujo demostró que
`ORASLiveWriter` consumía el rol pero ignoraba ese mapa de EV antes de construir
la extensión de party; por ello una transferencia podía parecer correcta en
roles y conservar estadísticas incompatibles con ese rol. El writer escribe
ahora los seis EV en orden nativo PK6, valida la distribución y reconstruye las
estadísticas antes del readback. La regresión byte a byte está en verde. Queda
pendiente una única validación física del intercambio Equipo↔PC en ORAS/Azahar.

### v0.2.5 Alpha.3 — perfil Personal ORAS fijado para roles

La ROM ORAS configurada se leyó directamente y contiene 825 entradas Personal;
Quagsire (especie 195, forma 0) devuelve las estadísticas base esperadas. El
mensaje que afirmaba lo contrario procedía de la UI: un cambio de rol con EV
no activaba la precarga que sí se hacía para intercambios Equipo↔PC. Ahora todo
`PendingRoleChange` con EV exige el perfil exacto antes de escribir y el writer
conserva una referencia estable a ese perfil durante la transacción. Las
regresiones automatizadas están en verde y el usuario confirmó físicamente el
intercambio Houndoom↔Quagsire en ORAS/Azahar: rol, EV y estadísticas se
actualizaron correctamente.

### v0.2.5 Alpha.2 — roles, EV y estadísticas vivas ORAS preparados

La revisión extremo a extremo demostró dos partes de la misma divergencia: la
UI no incluía ORAS entre los backends que construyen y propagan EV al cambiar
de rol, y `ORASLiveWriter` solo modificaba el marcador. El backend ya disponía
de los datos Personal y de la extensión viva PK6 necesaria; no se ha añadido
ninguna dirección RAM ni se ha trasladado ningún offset desde otro juego.

Los cambios de rol ORAS incluyen ahora los EV automáticos, el selector de dos
estadísticas para Líbero y el recálculo inmediato de PS máximos y estadísticas.
La transacción exige captura estable, identidad, rol y EV anteriores, nivel y
estadísticas runtime coherentes; escribe por separado PK6 almacenado y extensión
viva, relee ambos y restaura sus bytes originales si el readback diverge. Las
regresiones de éxito, precondición obsoleta y rollback están en verde. Falta la
validación física en ORAS/Azahar antes de cerrar esta capacidad.

### v0.2.5 Alpha.1 — curación completa ORAS validada

El backend ORAS acepta ahora `PendingPartyHeal` sobre la estructura PK6 ya
demostrada. La operación restaura estado, PS y PP, conserva la identidad de los
seis slots, realiza readback desde Azahar y revierte todos los bytes afectados
si cualquier comprobación falla. Las regresiones automatizadas de éxito y
rollback están en verde. El usuario confirmó físicamente en ORAS/Azahar que la
curación completa restaura correctamente el equipo dentro del juego.

### v0.2.4 Alpha.14 — representación vacía segura del PC X/Y

La revisión física completa localizó el Huevo corrupto en Caja 1:11: sus
`0xE8` bytes eran cero. Los vacíos válidos de la misma matriz eran no nulos y
coincidían exactamente entre sí. La primera divergencia estaba en dos ramas de
`XYLiveWriter` que heredaban el supuesto de que cero representaba un BoxPokemon
vacío.

Las rutas PC→Equipo y PC→PC derivan ahora el vacío desde dos lecturas estables
de la matriz viva y solo escriben una plantilla no nula, parseada como vacía,
repetida al menos dos veces y sin empate. El origen, destino y plantilla se
excluyen de inferencias circulares; readback y rollback siguen siendo exactos.
La validación física del usuario en Pokémon X/Azahar 263745c confirmó que un
nuevo movimiento PC→PC conserva el Pokémon exacto en el destino y deja el
origen vacío sin materializar ningún Huevo. El slot afectado anteriormente se
recuperó recargando el estado limpio, por lo que no fue necesaria una reparación
RAM tardía.

La party real posterior al depósito tenía `count=4`, slots 1–4 ocupados y 5–6
vacíos. La distribución de tarjetas que muestra huecos en el menú es propia de
Pokémon X y no demuestra un agujero en memoria.

En la misma sesión física de Pokémon X/Azahar 263745c, el usuario validó las
tres utilidades X/Y de forma independiente: Caramelo Raro ×999, Repelente
Máximo ×999 y dinero máximo. Las tres se reflejaron correctamente dentro del
juego; queda cerrada su validación empírica para este perfil.

También quedó validado el carril de salud: durante un combate salvaje, RoleRun
actualizó correctamente los PS tras recibir daño y conservó el valor real al
salir del combate. El botón de curación restauró correctamente el equipo dentro
del juego. Una prueba controlada posterior cubrió el ciclo completo de una baja:
la transición de PS positivos a cero descontó exactamente una vida, al terminar
el combate apareció el aviso de elegir sustituto y la elección incorporó
correctamente el sustituto. Estas observaciones validan lectura de PS en
combate, convergencia postcombate, writer de curación y el flujo simple de
KO→compromiso→sustitución para Pokémon X/Azahar 263745c. No constituyen todavía
una prueba de reconexión durante la batalla ni de combates especiales. Una
segunda prueba física cubrió dos KO dentro del mismo combate: RoleRun descontó
las dos vidas exactas y presentó y resolvió consecutivamente los dos selectores
de sustitución. Con ello queda validada también la cola múltiple en un combate
salvaje para este perfil.

### v0.2.4 Alpha.13 — testigos PC vivos en X/Y

La captura física posterior a alpha.12 y una lectura RPC independiente
demostraron `count=5`, los cinco PK6 ocupando exactamente los slots 1–5 y el
slot 6 vacío. El hueco inferior izquierdo mostrado por el menú de Pokémon X es
su disposición visual con cinco miembros, no un hueco interno en la party.

El depósito de Budew se rechazaba antes de escribir porque la pantalla componía
la Caja 1 con los overrides de la matriz viva, mientras `_pc_box_witnesses`
seguía leyendo exclusivamente los ocupantes del último `main`. Ahora ambos
consumen la misma proyección viva. El writer conserva intactas sus
precondiciones, readback y rollback. Falta repetir físicamente el depósito.

### v0.2.4 Alpha.12 — compuerta completa Equipo↔PC X/Y

La revisión de extremo a extremo demostró una contradicción entre las
operaciones que la interacción automática preparaba y las que la frontera
final de UI permitía alcanzar al Core. `move-box-slot`, swaps y sustituciones
cruzaban esa frontera, pero `party-to-box` y `box-to-party` se rechazaban antes
del writer aunque este ya implementaba sus precondiciones, readback y rollback.
El flujo manual de cambios pendientes conservaba además una lista anterior.

Ambas compuertas declaran ahora la misma matriz X/Y de cinco operaciones. No se
han relajado los validadores RAM ni se ha añadido ninguna dirección. La
regresión comprueba la frontera real de UI; la capacidad sigue pendiente de
validación física completa en Pokémon X/Azahar.

### v0.2.4 Alpha.11 — autoridad física de Equipo↔PC X/Y

La validación física de alpha.10 demostró que el RPC de Azahar podía aceptar
la escritura y devolverla en su readback mientras el juego conservaba a Budew
en la party. La primera divergencia restante era la fuente usada para escribir
y confirmar: el estado invitado leído por RPC no era prueba suficiente del
estado anfitrión que Pokémon X terminaba consumiendo.

En la sesión real se identificó una única región anfitriona cuyos seis slots
de party, contador y matriz PC completa coinciden a la vez con las estructuras
invitadas ya validadas. El writer no fija esa dirección: vuelve a resolver la
party completa por estructura e identidad, exige un único candidato y comprueba
que contador y PC comparten exactamente el mismo desplazamiento. La operación
se compromete sobre esa autoridad y solo se confirma si party, contador y
destino PC coinciden también tras una segunda lectura estable y por RPC. Ante
cualquier discrepancia se restauran los tres bloques.

Las regresiones automatizadas de X/Y pasan. La capacidad no se considera aún
cerrada: falta comprobar físicamente una sola retirada Equipo→PC iniciada desde
RoleRun con alpha.11.

### v0.2.4 Alpha.10 — despacho real de Equipo↔PC X/Y (incompleto)

La causa del traslado visible solo en RoleRun estaba entre la operación de UI
y el writer: la compuerta X/Y no despachaba `party-to-box` ni `box-to-party`.
El primer cambio quedaba meramente proyectado; por eso el siguiente PC→PC no
podía encontrar en RAM el origen mostrado por la interfaz y el writer lo
rechazaba de forma segura. La compuerta incluye ahora ambos tipos ya soportados
por el writer, sin modificar sus precondiciones, readback ni rollback. La run
persistida del usuario no contiene la operación fallida anterior. Las 50
regresiones X/Y relacionadas pasaron en esa versión, pero la prueba física
posterior demostró que el readback RPC no equivalía al commit físico. Alpha.11
conserva este arreglo de despacho y corrige la siguiente divergencia sin borrar
la evidencia histórica.

El usuario validó físicamente en Pokémon X/Azahar que Prisma acepta y ofrece
correctamente movimientos que provocan problemas de estado. Esta parte queda
cerrada para X/Y; su comprobación en los demás juegos se hará cuando corresponda
a cada backend.

### v0.2.4 Alpha.9 — destinos PC exactos y nuevo Prisma

La investigación de los fallos de arrastre X/Y localizó la primera divergencia
en la composición de la operación, no en las direcciones ni en el writer RAM.
La UI eliminaba el destino concreto para Equipo→PC, solicitaba testigos de rol
para PC→PC en vez de testigos ocupados de la caja y rechazaba toda retirada a
una casilla libre mediante un guard antiguo de Gen 6. El backend X/Y ya tenía
demostradas las transacciones exactas y sus verificaciones. La UI entrega ahora
esas coordenadas y testigos correctos y solo conserva el bloqueo para ORAS.

La regla común de Prisma cambia de Protección a Problemas de Estado: acepta el
pool explícito de movimientos que causan directamente veneno, intoxicación,
parálisis, sueño o quemadura. La disponibilidad final se intersecta con los IDs
del juego activo, de modo que un movimiento posterior no puede aparecer en un
título anterior. Tanque conserva su categoría de Protección. La cobertura
automatizada está completa; quedan pendientes una prueba física X/Y de los tres
movimientos PC y una comprobación de drafteo/compatibilidad Prisma antes de
declarar ambas capacidades cerradas. Baseline completa: **834 tests superados**
con `python -m pytest -q`.

### v0.2.4 Alpha.8 — Equipo↔PC con cambio de tamaño en X/Y

La prueba física controlada en Pokémon X/Azahar demostró que
`0x08CE1C74` es el contador de cuatro bytes little-endian de la party: con seis
miembros contenía 6 y, al depositar uno desde el juego, pasó a 5. La lectura
simultánea de la party situada en `0x08CE1CE8` demostró además que los miembros
posteriores se compactan literalmente hacia la izquierda y que el antiguo
último slot activo recibe el PK6 vacío cifrado canónico. Las palabras situadas
antes del contador no se han identificado semánticamente y permanecen fuera de
toda escritura.

El writer X/Y implementa ahora depósito y retirada con casilla PC exacta. Antes
de escribir exige dos capturas iguales de party y contador, rango 1–6, prefijo
compacto, identidad estable, origen/destino coherente y testigos ocupados de la
misma caja. Conserva cada bloque original, hace readback tras cada unidad,
escribe el contador solo al final y verifica el resultado semántico completo.
Si algo diverge, restaura y verifica todos los bytes, también con el contador
como último paso. ORAS no hereda esta capacidad.

Las regresiones automatizadas demuestran la transacción y su recuperación. La
dirección, el tamaño, la compactación y el vacío final sí están validados
físicamente; el ciclo completo iniciado desde RoleRun todavía requiere una
única validación manual de ida y vuelta antes de declararlo cerrado. Baseline
completa: **831 tests superados** con `python -m pytest -q`.

### v0.2.4 Alpha.7 — MT globales X/Y

La pestaña MT de X/Y mostraba nombre y PP, pero potencia, precisión y
descripción quedaban ausentes. El trazado demostró que el backend X/Y alcanzaba
en la UI el mismo fallback limitado que ORAS, mientras que solo BDSP y Gen 7
tenían una fuente completa. La tabla Gen 7 no era intercambiable: Placaje
(`move_id=33`) vale 50 de potencia en X/Y y 40 en Gen 7.

X/Y dispone ahora de una tabla independiente de 621 movimientos fijada a
generación 6 y `x-y`. La comprobación visual conectada a Pokémon X/Azahar
mostró MT83 Acoso con potencia 20, precisión 100 y 20 PP, además de las seis
tarjetas de compatibilidad. Las regresiones del writer demuestran que enseñar
una MT reutilizable escribe únicamente el PK6 de la party, no consulta ni
modifica la mochila, verifica movimientos y PP y revierte los bytes originales
si el readback falla. El usuario confirmó físicamente el 25-08-2026 que enseñar
una MT poseída y compatible cambia el movimiento dentro de Pokémon X y que la
misma MT continúa disponible después. Queda así cerrada la validación física
del writer de MT reutilizable para Pokémon X/Azahar. Baseline completa:
**826 tests superados**.

### v0.2.4 Alpha.6 — publicación inicial del PC vivo de X/Y

La matriz X/Y corregida en alpha.5 devolvía por lectura directa exactamente
Budew, Ledyba y Skitty en Caja 1, posiciones 1–3, pero RoleRun seguía mostrando
la caja vacía. El trazado hasta la UI demostró la siguiente primera divergencia:
la sincronización inicial solo programaba la reconciliación del PC X/Y cuando
`diff_live_party` detectaba además un cambio de party. Si la party ya coincidía,
el resultado válido del reader no llegaba al modelo visual y permanecía el PC
vacío del guardado.

La apertura validada de X/Y programa ahora una única reconciliación del PC vivo
después de publicar la party, aunque esta no haya cambiado. Una regresión aísla
esa condición y exige el refresco. La comprobación visual en la sesión real de
Pokémon X/Azahar mostró los tres ocupantes correctos en sus posiciones 1–3.
El usuario confirmó después, en la misma combinación de juego y backend, que
el movimiento PC→PC conserva exactamente la casilla vacía de destino solicitada,
incluido el cambio entre cajas. Con ello queda físicamente validado el writer
PC→PC introducido en alpha.4. También confirmó físicamente que una entrada
PC→Líbero abre el selector de distribución, permite elegir las dos estadísticas
y aplica la configuración EV correspondiente.
No se modificó ningún writer ni otro backend. Baseline completa: **821 tests
superados**.

### v0.2.4 Alpha.5 — lectura viva del PC X/Y sin anchors

La sesión real de Pokémon X en Azahar (`kujira-1`, proceso 11) demostró que la
matriz poblada del PC comenzaba en `0x08C861B8`, no en la candidata nominal
`0x08C861C8`. En esa matriz se descifraron exactamente tres PK6 válidos: Budew,
Ledyba y Skitty en Caja 1, posiciones 1–3. La lectura anterior no tenía anchors
posicionados del `main`, aceptaba la base nominal sin comprobarla y fallaba al
descifrar el primer slot; la UI ocultaba después ese fallo con el `main`
guardado, que no contenía Pokémon en el PC. Esta era la primera divergencia.

El lector conserva el rango local documentado y prueba sus alineaciones de
cuatro bytes, pero solo publica una recalibración si existe una única matriz
con al menos dos PK6 completos que superen descifrado, checksum, especie e
identidad estable. Una única aparición o varias candidatas se consideran
ambiguas y no se aceptan. La ruta es de solo lectura y no cambia ningún writer.

El readback directo posterior resolvió `0x08C861B8` y devolvió los tres Pokémon
reales. Las regresiones automatizadas cubren la apertura sin anchors, una caché
nominal obsoleta y el rechazo de dos matrices ambiguas. Baseline completa:
**820 tests superados**. La visualización dentro de RoleRun se confirmó en
alpha.6; el movimiento PC→PC sigue pendiente de confirmación física.

### v0.2.4 Alpha.4 — movimiento exacto dentro del PC de X/Y

X/Y permite ahora mover un Pokémon ya almacenado en el PC a una casilla vacía
concreta, incluso de otra caja. La operación reutiliza la matriz viva ya
demostrada de 31 cajas × 30 posiciones, con stride PK6 de `0xE8` bytes y bloque
vacío a cero. No se ha añadido ni inferido ninguna dirección RAM.

El writer resuelve de nuevo la matriz mediante sus testigos, exige identidad
estable en el origen y destino vacío, relee ambos justo antes de escribir y
aplica una transacción destino→origen. Cada paso tiene readback exacto y la
verificación final vuelve a descifrar ambos PK6; si cualquier comprobación
falla, restaura y verifica los dos bloques originales. La UI conserva caja y
slot exactos al preparar el cambio. Las operaciones que alteran el tamaño de la
party continúan deshabilitadas porque la sesión actual no demuestra el contador
de miembros ni su escritura segura.

Las regresiones cubren movimiento exacto, destino ocupado, identidad stale,
divergencia al vaciar el origen, rollback y preparación de coordenadas desde la
UI. El usuario validó físicamente el movimiento PC→PC exacto, también entre
cajas, en Pokémon X/Azahar el 25-08-2026. Baseline automatizada: **817 tests
superados**.

### v0.2.4 Alpha.3 — roles, EV y estadísticas vivas en X/Y

El flujo común guardaba el rol X/Y, pero lo excluía de la preparación de EV y
el writer heredado de ORAS solo escribía el PK6 almacenado. Las estadísticas
finales de X/Y residen en una región runtime separada, ya demostrada por el
reader y por la curación física. La nueva transacción valida identidad, EV
anteriores, nivel y estadísticas testigo; recalcula desde la tabla Personal de
X/Y; conserva el estado y los PS perdidos; escribe por separado el PK6 y
`PartyData`; verifica ambos readbacks y restaura ambos si falla alguno.

Las entradas PC→equipo hechas dentro del juego heredan igualmente los EV del
rol. Los cinco roles fijos se normalizan sin interacción y Líbero no escribe
nada hasta que el usuario selecciona dos estadísticas. Las regresiones cubren
recalculo efectivo, muestra EV stale, rollback de ambas regiones, rol fijo
automático y selector Líbero. El usuario confirmó físicamente el cambio de rol
fijo y la entrada PC→Líbero con elección de sus dos estadísticas en Pokémon
X/Azahar el 25-08-2026. Baseline automatizada: **811 tests superados**.

### v0.2.4 Alpha.2 — curación visible y baja sin sustituto en X/Y

La curación X/Y ya disponía de writer transaccional, pero dos compuertas de
composición de la UI seguían enumerando únicamente BDSP, Sol/Luna y USUM. Una
capacidad común incluye ahora X/Y y gobierna tanto `CURAR EQUIPO` como las
acciones `CURAR`/`MENÚ` de la barra flotante. El usuario validó físicamente el
25-08-2026 que la curación completa restaura correctamente el equipo en
Pokémon X/Azahar.

Una baja pendiente puede resolverse ahora con `NO SUSTITUIR`. La operación no
escribe RAM, no devuelve la vida descontada y no borra la muerte: archiva de
forma persistente la obligación de reemplazo, conserva la identidad en el
Cementerio y deja libre el rol. Si hay varias bajas, la decisión se toma para
cada una. La sesión real verificó visualmente `NO SUSTITUIR` junto a la baja
pendiente; su persistencia tras accionarlo sigue pendiente de validación física.

La carga inicial comparaba la party física completa con la party proyectada que
la UI muestra después de excluir bajas pendientes. Con dos bajas, esperaba seis
filas mientras solo podían componerse cuatro y la pantalla de carga no terminaba.
La compuerta compara ahora la misma proyección que renderiza la UI. Baseline
automatizada: **806 tests superados**.

### v0.2.4 Alpha.1 — estadísticas completas y curación X/Y

La sesión real de Pokémon X en Azahar demostró que el reader ya leía y
descifraba correctamente el bloque PK6 completo, incluida la extensión
`PartyData`, pero el parser Gen 6 compartido solo publicaba PS actuales y
máximos. Ahora el snapshot conserva naturaleza, IV, EV y los seis stats en el
orden canónico de RoleRun. La comprobación visual del 25-08-2026 confirmó los
valores completos de los seis miembros; por ejemplo, Delphox mostró 286 PS,
164 Ataque, 143 Defensa, 253 At. Esp., 255 Def. Esp. y 222 Velocidad. No se ha
añadido ninguna dirección RAM.

La curación completa de X/Y usa la misma estructura ya validada por su reader,
pero respeta su disposición física partida: `0xE8` bytes del PK6 almacenado y
`0x16` bytes de datos runtime en `slot + 0x158`. Restaura PS, estado y PP con
precondiciones, readback y rollback; las regresiones automatizadas cubren éxito
y restauración tras una escritura corrupta. La sesión real confirmó que la
acción sobre una party ya curada es idempotente, no bloquea la interfaz y no
altera el equipo. La curación efectiva de una party dañada queda pendiente de
validación física en Pokémon X/Azahar antes de declararse cerrada. La baseline
completa de esta entrega es de **803 tests superados**.

### Alpha.148 — selector EV del sustituto Líbero en BDSP

La selección fresca de dos estadísticas tras sustituir a un Líbero debilitado,
validada físicamente en Sol/Luna, se extiende a BDSP. El flujo común omitía la
clave `bdsp` aunque el backend ya consume el mapa EV del snapshot y ejecuta el
recalculo/readback posterior. La regresión demuestra que BDSP no prepara ni
aplica el reemplazo hasta recibir la selección y que conserva exactamente los
dos EV elegidos. ORAS y XY permanecen fuera por no tener demostrada esta
capacidad de escritura realtime.

### Alpha.147 — paridad segura de continuidad en USUM

La apertura física de Sol/Luna Alpha.146 quedó validada por el usuario: la
barrera se retira y `Equipo y PC` aparece completo. La auditoría posterior
demostró que UltraSol/UltraLuna conservaba el mismo rechazo determinista ante
dos sustituciones gestionadas. USUM recibe ahora los mismos testigos persistidos
de la Run y solo acepta dos entrantes cuando ambos están identificados y se
conservan los otros cuatro miembros. BDSP, XY y ORAS no usan este contrato de
continuidad y no se han modificado.

### Alpha.146 — arranque SM tras dos sustituciones gestionadas

El bloqueo indefinido del arranque quedó localizado antes de UI: la party viva
de Sol/Luna conservaba cuatro identidades exactas del último testigo, pero tenía
dos sustitutos distintos ya registrados en `managed_pokemon_roles`. El contrato
de continuidad de `SMLiveReader` solo aceptaba una sustitución gestionada y la
barrera inicial, correctamente, no publicaba una muestra que el reader rechazaba.

La continuidad admite ahora únicamente el caso demostrado: seis miembros en
ambos estados, exactamente dos entrantes persistidos por la Run y los otros
cuatro testigos conservados. La regresión verifica tanto el rechazo sin evidencia
como la aceptación con ambos testigos. La sesión física actual de Azahar produjo
`snapshot=true`, `continuity_proof=multiple-managed-replacements` y retiró la
pantalla inicial, mostrando después el selector EV pendiente del Líbero.

### Alpha.145 — elección EV del sustituto de un Líbero debilitado

La validación física de Alpha.144 confirmó que un sustituto de rol fijo recibe
correctamente sus EV. También aisló una divergencia anterior y específica de
Líbero: `_prepare_faint_replacement()` infería sus dos stats a partir de los EV
del Pokémon muerto y continuaba sin abrir el selector. Por tanto, el writer
funcionaba, pero recibía una decisión que el usuario no había tomado para el
nuevo Pokémon.

En Sol/Luna y UltraSol/UltraLuna la operación queda ahora detenida antes de
crear `PendingTeamChange`. RoleRun abre el selector EV en la superficie visible
y solo al confirmar dos stats reanuda la misma sustitución transaccional. La
regresión demuestra que mientras el diálogo está pendiente no se prepara ni se
aplica ningún cambio y que la selección nueva reemplaza al reparto anterior.
El usuario validó físicamente en Pokémon Sol/Azahar que, al sustituir a un
Líbero debilitado, el selector permanece abierto, exige dos estadísticas y
aplica el reparto elegido antes de completar la sustitución.

### Alpha.144 — EV heredados en sustituciones por baja de Sol/Luna

La comparación exacta con el flujo USUM demostró dos divergencias anteriores
al writer final: `_prepare_faint_replacement()` solo incorporaba los EV del rol
para USUM y `SMLiveWriter._apply_faint_replacement()` reconstruía el PK7
entrante sin consumir un reparto preparado. La sustitución heredaba la marca de
rol, pero podía conservar los EV que el Pokémon tuviera en el PC.

Sol/Luna prepara ahora el reparto del rol del debilitado dentro del snapshot de
la misma transacción. El writer valida que el rol declarado coincide, aplica
los seis EV antes de recalcular checksum y cifrado, y mantiene readback y
rollback conjuntos de equipo y PC. Las regresiones de UI y writer están
automatizadas. El usuario confirmó físicamente el 25-08-2026 que un sustituto
de rol fijo recibe correctamente el reparto correspondiente; esa prueba reveló
por separado la ausencia del selector para Líbero, corregida en Alpha.145.

### Alpha.143 — selector EV protegido frente al refresco flotante

La validación física de Alpha.142 demostró una segunda divergencia posterior:
el selector sí se abría sobre el emulador, pero el siguiente cambio de firma de
la barra flotante ejecutaba `_render_floating_bar()` y destruía sin distinción
todos los hijos del `Toplevel`, incluido el diálogo. Además, el diálogo cambiaba
su propietario a la ventana principal retirada después de crearse.

El render elimina ahora únicamente widgets reconstruibles y conserva las
ventanas modales registradas. El selector flotante mantiene como propietaria la
barra visible. Una regresión reproduce el refresco y demuestra que el contenido
normal se destruye mientras el diálogo permanece. El usuario confirmó
físicamente el 25-08-2026 que el selector permanece abierto hasta confirmar dos
stats y que el reparto se aplica correctamente.

### Alpha.142 — elección EV en entradas automáticas desde el PC del juego

La primera divergencia estaba en la orquestación común posterior a la lectura
live: al detectar que un Pokémon había entrado al equipo desde el PC del propio
juego, RoleRun construía inmediatamente el cambio de rol heredado. Para Líbero
esa transacción no contenía una elección de EV y podía alcanzar el writer sin
los dos stats requeridos.

En los tres backends cuya escritura EV está demostrada —BDSP, Sol/Luna y
UltraSol/UltraLuna— una entrada automática a Líbero queda ahora detenida antes
de escribir RAM. El selector se abre en la superficie visible activa y solo al
confirmar dos stats se reanuda la transacción con precondiciones, readback y
rollback. Los roles fijos incorporan su reparto normalizado en esa misma
transacción. La entrada PC→Líbero y la persistencia del selector quedaron
validadas físicamente por el usuario el 25-08-2026 en Pokémon Sol.

### Alpha.141 — selector Líbero visible y metadatos de MT Gen 7

El cambio de rol por arrastre desde la barra ya llegaba al flujo correcto de
rol y EV, pero el diálogo que debía elegir los dos stats de Líbero se alojaba
en la ventana principal retirada. Por eso el usuario solo lo veía al restaurar
RoleRun y la operación parecía no haberse aplicado. En contexto flotante el
selector se presenta ahora en un `Toplevel` visible sobre el emulador; no se
escribe el reparto hasta confirmar exactamente dos stats.

La UI de Gen 7 únicamente disponía antes de PP, de modo que potencia, precisión
y descripción aparecían como no disponibles aunque la MT funcionara. La tabla
`data/gen7_move_metadata.json` fija el version-group de Sol/Luna, conserva
procedencia y regla de derivación y aporta los datos españoles de los 760
movimientos introducidos hasta Gen 7. El usuario confirmó físicamente el
25-08-2026 que el selector flotante aparece y aplica el reparto y que las
tarjetas muestran correctamente los datos de las MT.

### Alpha.140 — SUSTITUIR y pestaña MT de Sol/Luna

La sesión real de Pokémon Sol/Azahar demostró que la antigua candidata de
Items era falsa: se calculaba restando el offset de BoxPokemon del save a su
dirección live y devolvía un bloque `0xDE0` completamente vacío. PKMN-NTR
documenta para SN/MN una dirección Items independiente, `0x330D5934`. Dos
lecturas guest estables de esa dirección produjeron una mochila no vacía y la
copia host derivada desde la party ya demostrada coincidió byte a byte.

RoleRun usa ahora esa dirección solo como candidata cerrada por esas mismas
pruebas de sesión. SUSTITUIR y la pestaña MT compartida reciben así el
inventario vivo; la enseñanza reutilizable de Gen 7 conserva la MT y verifica
el Pokémon, el movimiento anterior, PP, host, guest y rollback. Las pruebas
automatizadas y la visualización local quedan registradas en alpha.140. El
usuario confirmó físicamente en Pokémon Sol/Azahar que SUSTITUIR enseña el
movimiento, conserva la MT reutilizable y muestra correctamente sus datos; la
capacidad queda cerrada para esta combinación.


### Alpha.139 — PC vivo coherente y eliminación segura del slot PK7

La captura física del 25-08-2026 demostró dos divergencias independientes en
Sol/Luna. La UI publicaba el equipo desde RAM viva pero mantenía el PC derivado
de una lectura anterior del save; por eso mostraba un Pikipek antiguo aunque el
juego contenía Decidueye en caja 1:1. Sol/Luna consume ahora su matriz PC live
completa antes de retirar la barrera inicial.

Además, el traslado PC→Equipo escribía `0xE8` bytes a cero en el slot de origen.
La lectura viva confirmó esa firma exacta en caja 1:3 y el juego la mostraba
como huevo corrupto. El writer usa ahora el vacío PK7 cifrado canónico, verifica
su readback exacto y conserva rollback. El slot afectado de la sesión fue
reparado de forma acotada tras verificar la precondición, el resultado y que los
slots vecinos permanecieron intactos. El usuario confirmó físicamente el
25-08-2026 que Decidueye aparece de nuevo en Caja 1:1 y que el huevo corrupto
ha desaparecido. Quedan así validados tanto el PC vivo publicado como la
reparación y el vacío PK7 canónico de alpha.139.

### Alpha.138 — reanudación estable de Sol/Luna

La carga eterna tras reiniciar no procedía del transporte ni de una dirección
nueva: la party nominal era estructuralmente válida y cinco de sus seis
identidades coincidían, pero el reader había perdido su testigo de sesión. El
sexto miembro era el Pikipek gestionado que acababa de entrar desde el PC y la
party además se había reordenado; la prueba histórica solo admitía reemplazo o
reordenación por separado y rechazaba indefinidamente su combinación.

El reader recibe ahora las identidades fuertes persistidas por la run y solo
admite `single-managed-replacement-and-reorder` cuando el miembro entrante
coincide exactamente con una de ellas. La identidad equivocada permanece
cerrada. La barrera visual también espera los sprites del equipo y el último
refresco pendiente antes de descubrir la página.

Validación local en Pokémon Sol/Azahar: una apertura desde proceso nuevo resolvió
la party nominal mediante esa prueba, publicó los seis miembros con PS y sprites
completos y permitió seleccionar inmediatamente el Pikipek de Caja 1. Evidencia
local: `diagnostics/manual/sm-alpha138-first-published-frame.png` y
`diagnostics/manual/sm-alpha138-pc-selected.png`. Falta validar físicamente una
nueva transferencia inmediata después de otra apertura limpia.

### Alpha.137 — EV de rol en entradas PC→Equipo de Sol/Luna

La UI ya preparaba el reparto EV del rol para los traslados de Sol/Luna, pero
`SMLiveWriter._party_payload_from_box()` solo consumía rol y movimientos. Esa
era la primera divergencia: el Pokémon entraba con el rol correcto y los EV se
posponían a otra operación. El writer valida y aplica ahora los seis EV al PK7
entrante antes de reconstruir PartyData; marcador, EV, checksum, PS y stats se
confirman así dentro de la misma transacción party↔PC y comparten rollback.

Las regresiones cubren sustitución 1↔1, entrada a hueco libre y rechazo de un
snapshot incompleto antes de escribir. La suite completa queda en `782 passed`.
La validación física del 24-08-2026 intercambió el Pikipek de Caja 1 por la
segunda casilla: entró como Asesino con EV Ataque/Velocidad `252/252`, los otros
cuatro a cero y estadísticas finales recalculadas. Evidencia visual:
`diagnostics/manual/sm_alpha137_pc_to_team_evs.png`.

### Alpha.136 — entrenamiento por rol de Sol/Luna validado físicamente

La primera divergencia respecto de la paridad ya demostrada en USUM estaba en
dos fronteras propias de SM: la UI excluía `sm` al construir `old_evs/new_evs`
y `SMLiveWriter` solo escribía el marcador del rol. Sol/Luna ya publicaba los
EV y disponía de todos los campos necesarios para reconstruir PartyData, pero
ninguno de esos datos llegaba al writer como una transacción de entrenamiento.

La UI incluye ahora SM en ese contrato. El writer exige los EV anteriores y el
Personal efectivo de la ROM, valida IV, nivel, naturaleza, hiperentrenamiento y
estadísticas vivas, aplica la distribución del rol, recalcula PS y las cinco
estadísticas y preserva el daño sufrido. El PK7 almacenado y PartyData se
escriben con precondición, readback host/guest, comprobación semántica y
rollback verificado de ambas regiones. No se añaden direcciones ni offsets.

Las regresiones cubren la generación UI de EV para SM, checksum, orden binario
de los seis EV, recálculo de estadísticas y conservación de PS perdidos. La
validación física del 24-08-2026 en Pokémon Sol/Azahar reasignó Asesino a un
Pikipek de nivel 4: el readback cambió Ataque/Velocidad de EV `1/0` a
`252/252`, puso los otros cuatro EV a cero y recalculó sus estadísticas finales
de Ataque `11` a `14` y Velocidad `9` a `10`, manteniendo `17/17` PS. La
evidencia visual se conserva en `diagnostics/manual/sm_alpha136_role_dialog.png`
y `diagnostics/manual/sm_alpha136_role_readback.png`.

### Alpha.135 — curación de Sol/Luna operativa con destino demostrado

La primera divergencia estaba en la resolución del destino del writer. Cuando
Azahar retenía más de una copia anfitriona válida de la party, la curación
exigía directamente una relación party↔PC ya almacenada en caché. Por tanto,
fallaba de forma segura si era la primera escritura de la sesión, aunque el
backend SM ya disponía del procedimiento autocontenido que demuestra la matriz
PC completa y deriva de ella la única party con el mismo backing FCRAM.

La curación reutiliza ahora esa demostración antes de seleccionar el destino;
no añade direcciones, heurísticas ni fallbacks. Conserva la relectura previa,
la identidad estable, el readback host/guest, la validación semántica y el
rollback verificado. La regresión reproduce dos buffers de party candidatos y
demuestra que se establece primero la prueba PC completa y se selecciona
después el único destino revalidado.

Validación física local completada el 24-08-2026 en Pokémon Sol/Azahar: con la
aplicación iniciada desde el código corregido, `CURAR EQUIPO` cambió un Pikipek
de 11/17 a 17/17 en la memoria viva y no mostró el rechazo. Las capturas
`diagnostics/manual/sm_alpha134_heal_retry_ready2.png` y
`diagnostics/manual/sm_alpha134_heal_retry_after.png` conservan el antes y el
después. El usuario confirmó a continuación que la curación completa funciona
correctamente, cerrando también la restauración conjunta de estado y PP.

### Alpha.134 — implementación inicial de la curación completa de Sol/Luna

El primer writer añadido a la paridad SM restaura conjuntamente PS, estado y PP.
No reutiliza direcciones USUM: resuelve la party de Sol/Luna, exige identidad
estable y escribe las dos regiones de su formato sparse ya demostrado (stored
PK7 y PartyData). Antes de escribir relee todos los campos; después verifica
host, guest y una nueva captura semántica. Ante cualquier divergencia restaura
y comprueba ambas vistas de los bytes originales.

Las regresiones automatizadas demostraron la proyección y el paso por la UI. La
primera prueba física con daño real reveló que la resolución del destino todavía
dependía de una prueba PC previamente almacenada; esa causa se corrigió en
alpha.135. La validación física completa posterior cerró también PP y estado.
La comprobación visual local conservada en
`diagnostics/manual/sm_alpha134_heal_ready.png` demuestra que `CURAR EQUIPO`
aparece en la vista SM definitiva; la ejecución idempotente con los seis
miembros ya sanos no alteró su identidad, composición ni PS.

### Alpha.133 — primera base de paridad Sol/Luna validada en la partida real

La primera divergencia del arranque de Sol/Luna estaba en la barrera de
presentación, antes de las herramientas: `_finish_oras_initial_auto_sync`
trataba cualquier error inicial de transporte de SM como una conexión opcional
y retiraba la shell, mientras que solo BDSP esperaba una captura live con PS
resueltos. Por eso quedaba visible durante la conexión la composición
provisional del save con barras rojas y datos todavía incompletos.

SM comparte ahora únicamente el contrato demostrado de preparación visual: la
shell permanece oculta hasta que Azahar publica una party autoritativa y todos
los miembros tienen pares PS/PS máximos coherentes. No se han copiado offsets,
estructuras ni writers de USUM. La party SM expone además naturaleza, IV, EV,
stats finales y estado desde los campos PK7 ya validados; el adaptador obtiene
las stats base del perfil Personal de la ROM efectiva de Sol/Luna.

Verificación visual local completada el 24-08-2026 con Pokémon Sol en Azahar:
`diagnostics/manual/sm_initial_gate_loading.png` conserva el cargador completo
durante la conexión; `sm_initial_gate_ready.png` muestra la vista definitiva
con los seis PS resueltos; y `sm_initial_gate_detail_ready.png` muestra la ficha
de Decidueye con naturaleza, estadísticas finales y base, IV, EV, habilidad,
objeto y cuatro movimientos. Esta validación cierra la barrera visual y la
lectura de esos datos; no declara todavía paridad de writers o herramientas SM.

### Alpha.132 — incompatibilidades visibles también en la tarjeta de Equipo

La vista nueva calculaba correctamente las incompatibilidades de rol para la
ficha lateral, pero las cuatro cápsulas de movimientos de la tarjeta principal
se dibujaban sin consultar ese resultado. Ambas superficies comparten ahora el
mismo mapa por slot: un movimiento incompatible aparece en rojo desde la vista
general y, al seleccionar el Pokémon, la ficha conserva las acciones
`SUSTITUIR` y `ELIMINAR` ya conectadas al writer transaccional del backend.

La regresión verifica que tarjeta y ficha reciben exactamente el mismo mapa y
que un Pokémon almacenado en PC no hereda por error las restricciones del rol
activo del equipo. La comprobación visual local en la run USUM/Azahar confirmó
que `Cuchilla Solar` de Carnivine/Mago aparece en rojo tanto en la tarjeta como
en la ficha y que esta muestra `SUSTITUIR` y `ELIMINAR`. Validación física
completada en USUM/Azahar el 24-08-2026: `ELIMINAR` retiró `Cuchilla Solar` del
Carnivine tanto en RoleRun como en la partida real. La detección y la escritura
correctiva de movimientos incompatibles quedan cerradas para este entorno.

### Alpha.131 — contrato de MT reutilizable corregido

La primera divergencia no estaba en los writers de los juegos 3DS: las pruebas
existentes demuestran que ORAS, X/Y, SM y USUM escriben el movimiento sin tocar
la mochila. Estaba en la proyección común de la UI, que descontaba una unidad de
cualquier MT pendiente. El cambio conserva ahora en `PendingTMTeach` el contrato
de consumo: `False` para Gen 6/7 y `True` únicamente para BDSP. Inventario
pendiente, refresco tras readback, revisión e historial respetan ese mismo dato.

Las regresiones automatizadas cubren ambos comportamientos. Validación física
completada en USUM/Azahar el 24-08-2026: tras enseñar una MT que tenía cantidad
`x1`, la misma MT continuó disponible con `x1` tanto en la mochila del juego como
en RoleRun. La reutilización de MT de USUM queda cerrada.

### Alpha.130 — arrastre transaccional entre cajas USUM validado físicamente

USUM permite mantener un Pokémon del PC sobre una flecha para cambiar una caja
sin perder el arrastre y soltarlo después en una casilla vacía exacta. La
interacción cambia una sola caja por cada entrada en la flecha; permanecer sobre
ella no genera avances repetidos fuera de control.

El writer usa la matriz PC completa ya demostrada para UltraSol/Azahar: valida
origen, destino, identidad y transporte host/guest, copia el PK7 cifrado exacto,
escribe un vacío cifrado válido en el origen y exige dos readbacks semánticos.
Si falla cualquier comprobación, restaura y verifica ambos huecos. Los destinos
ocupados y los demás backends siguen rechazados.

Alpha.129 contenía el writer correcto, pero la captura del ratón retargeteaba
el puntero a la superficie de origen: las casillas vacías y las flechas nunca
recibían el gesto real. Alpha.130 mantiene la escritura y corrige esa primera
divergencia mediante el bindtag estable del `Toplevel`, sin `grab_set`.

Validación física completada en USUM/Azahar 263745c el 2026-08-24: Eevee se
movió caja 1/casilla 1 → caja 1/casilla 2 → caja 2/casilla 1, y el recorrido
inverso con `<` lo restauró en caja 1/casilla 1. Las capturas de cada frontera
se conservan en `diagnostics/manual/alpha130_*.png`.

### Cierre físico de BDSP — 24 de agosto de 2026

El usuario validó físicamente en Pokémon Perla Reluciente 1.3.0 / Ryujinx 1.3.3
la exclusividad final de teclado y mando de alpha.119: con RoleRun en primer
plano, navegar y aceptar dentro de la aplicación no mueve al personaje ni
interactúa en el juego; al devolver el foco a Ryujinx, los controles vuelven a
funcionar. Con esta comprobación se da por cerrado el desarrollo funcional de
BDSP hasta nuevo aviso. El siguiente foco es trasladar las capacidades nuevas a
UltraSol/UltraLuna sobre Azahar, demostrando por separado cada writer y dato RAM
específico de Gen 7.


### Alpha.119 — RoleRun posee en exclusiva los controles frente a Ryujinx

Cuando RoleRun está en primer plano durante una sesión BDSP, Ryujinx queda
retenido antes de leer el mando y se reanuda al devolver el foco. Esto impide
que flechas, aceptar o atrás naveguen RoleRun y actúen a la vez en el juego. La
prueba física local midió `0` avance de CPU durante 600 ms de retención y
confirmó la liberación posterior. La validación final de interacción con teclado
y mando reales queda pendiente de la comprobación breve del usuario.


### Alpha.118 — primer frame BDSP estable en la geometría final

La causa visual restante de alpha.117 no estaba en RAM ni en los PS: la vista
oculta se validaba antes de maximizar la ventana. El mapeo del HWND iniciaba un
segundo relayout que el cargador ya no cubría por completo. Alpha.118 mantiene
una superficie de carga maximizada e independiente, recompone la vista con la
raíz transparente en su tamaño final y solo la publica tras cuatro muestras
consecutivas de geometría, cajas y PS estables.

La validación física local se repitió dos veces desde procesos nuevos, con una
captura de pantalla cada 150 ms. Las dos secuencias muestran exclusivamente el
loader animado y después la interfaz completa; no aparece ningún frame blanco,
vacío, provisional o parcialmente compuesto. Evidencia conservada en
`diagnostics/ui/alpha118-startup-physical-19/` y
`diagnostics/ui/alpha118-startup-physical-20/`.

### Alpha.117 — primera apertura BDSP protegida por salud live

El vídeo físico `2026-08-24 14-50-17.mp4` demostró la primera divergencia: el
primer intento de transporte con Ryujinx fallaba durante el arranque y
`_finish_oras_initial_auto_sync()` declaraba completa la sonda igualmente. La
shell mostraba por ello los PS provisionales del save; unos trece segundos más
tarde un reintento live los sustituía por los correctos.

BDSP mantiene ahora la barrera animada ante ese fallo inicial. Solo la retira
después de publicar una captura live, demostrar pares HP/Max HP coherentes para
toda la party y completar la composición visual final. Un Pokémon realmente
debilitado con `0/Max HP` es válido; el placeholder `0/0` no lo es. Queda
pendiente validar físicamente una primera apertura desde un proceso RoleRun
nuevo. Esa validación pendiente queda resuelta y supersedida por la doble
captura física de alpha.118 descrita arriba.

### Alpha.116 — repetición deliberada y entrenamiento live publicado

La prueba física de alpha.115 refutó el umbral anterior: 200 ms era menor que
una pulsación humana normal y una sola acción podía atravesar varias casillas.
Alpha.116 mantiene el primer movimiento inmediato y exige 450 ms de pulsación
continua antes del autorrepetido; después repite cada 70 ms.

La ausencia de stats en Drafteos tenía una causa distinta. El lector BDSP sí
entregaba naturaleza, stats, stats base, IV y EV, pero la reconciliación solo
publicaba el snapshot cuando cambiaban identidad, rol o movimientos. Ahora una
mejora de esos campos de presentación también publica el snapshot live, sin
crear cambios pendientes ni escribir en el juego. Las regresiones automáticas
cubren ambas primeras divergencias. El usuario validó físicamente en BDSP que
un tap vuelve a mover una sola casilla y que Drafteos muestra naturaleza,
estadísticas, IV y EV. El autorrepetido se conserva algo lento, aceptado
expresamente para no prolongar este ajuste.

### Alpha.115 — foco exclusivo y repetición recuperada

La validación física de alpha.114 confirmó que el salto de extremos quedó
corregido, pero demostró una regresión de velocidad: se había eliminado la
repetición completa del D-pad junto con la ruta equivocada. Alpha.115 conserva
el propietario único y recupera la repetición controlada tras 200 ms, cada
52 ms mientras se mantiene la dirección.

El drawer es ahora un plano estrictamente vertical: Izquierda/Derecha no hacen
nada y no pueden volver a encender el cursor inferior durante su animación.
Drafteos conserva el marco dorado común; la tarjeta de Líbero deja de tener un
borde dorado fijo que parecía una segunda selección. Las capturas verificadas
son `diagnostics/ui/alpha115-draft-shared-focus.png` y
`diagnostics/ui/alpha115-sidebar-exclusive-focus.png`; la suite completa supera
**719 tests**. Queda pendiente la comprobación física del ritmo del D-pad.

### Alpha.114 — un solo recorrido para teclado y mando

La validación física de alpha.113 demostró que quedaba una segunda ruta: el
teclado respetaba el propietario visible, pero el mando elegía la vista por la
pestaña base. Dentro del flujo integrado de MT enviaba por ello las flechas a
Equipo/PC, que permanecía compuesto debajo. Alpha.114 elimina esa bifurcación:
dirección, aceptar y atrás del mando usan la misma autoridad que el teclado.

La repetición sintética del D-pad se separa del flanco inicial; una pulsación
corta en la aplicación solo puede publicar un movimiento. El foco de Drafteos
usa contraste marfil sobre controles dorados y fue inspeccionado a 1920×1080 en
`diagnostics/ui/alpha114-draft-focus-selected.png`. Las **718 pruebas** pasan;
queda pendiente la validación física con el mando real antes de cerrar la
navegación de BDSP.

### Alpha.113 — una sola autoridad de navegación

La primera divergencia de los saltos y selectores ausentes estaba en el
despacho de entrada, no en la geometría espacial: la página conservada como
buffer, la pantalla situada debajo del flujo MT y la vista visible podían
escuchar el mismo evento del `Toplevel`. El controlador concede ahora la
autoridad a una sola vista y la transfiere explícitamente al abrir/cerrar MT.

El drawer lateral forma parte de esa misma jerarquía: su foco oculta el cursor
de contenido, permite navegar sus entradas y restaura la selección original al
cerrarse. La composición se inspeccionó a 1920×1080 y la suite completa supera
715 tests. Queda pendiente la validación física breve de teclado y mando del
usuario antes de cerrar esta ergonomía.

### Alpha.112 — navegación jerárquica y stats base

La navegación de Equipo/PC, MT y Drafteos conserva ahora el cursor al volver
desde un nivel de detalle y permite alcanzar el menú lateral desde el extremo
izquierdo. La ficha pesada se redibuja de forma agrupada tras las ráfagas de
dirección y el mando aplica repetición controlada al mantener el D-pad.

Los seis stats base se obtienen de la misma tabla Personal BDSP validada que
usa la compatibilidad de MT, se incorporan al snapshot realtime y se presentan
entre el stat final y los IV/EV. La aplicación real conectada a Ryujinx mostró
los valores y procesó cinco entradas separadas 10 ms sin pérdidas. La suite
completa supera 713 tests. La ergonomía final con teclado y mando permanece
pendiente de validación física del usuario.

### Alpha.111 — atajos exclusivos del juego

El usuario confirmó físicamente que los stats del PC ya funcionan. La última
divergencia de interacción estaba en el alcance del foco: alpha.110 permitía
todavía que RoleRun fuese una ventana autorizada para parte del flujo. Alpha.111
aplica un único contrato a todas las acciones: sus teclas solo se registran si
el primer plano pertenece a un emulador compatible y la ejecución vuelve a
comprobar esa misma precondición para rechazar mensajes encolados.

La prueba Win32 sobre la aplicación real y la run activa confirmó para `D` y
`NUM 7`: libres con RoleRun delante, reservadas con Ryujinx delante y liberadas
de nuevo al regresar a RoleRun. Queda pendiente únicamente la validación breve
del usuario antes de dar BDSP por cerrado. La suite completa queda en **705
tests superados**.

### Alpha.110 — stats PC validados en la aplicación real

La prueba real de alpha.109 demostró una divergencia adicional: aunque el reader
y la proyección aislada eran correctos, la sesión no generaba ningún evento
`pc-reconcile-*`. La carga unificada terminaba antes de activar realtime y el
refresco posterior solo contemplaba la página histórica `pc`; la vista actual es
`team`. La captura completa se dispara ahora en cuanto la sincronización inicial
BDSP queda validada y la publicación repinta la vista unificada.

Se abrió el programa real contra Ryujinx y se seleccionó Ornita en caja 1/slot 8.
La traza produjo `pc-read` con 11 ocupados y `pc-reconcile-applied changed=true`;
la ficha mostró naturaleza Huraña, stats `44/31/21/19/18/30`, IV
`23/13/29/17/8/8` y EV a cero. La evidencia visual se conserva en
`diagnostics/ui/alpha110-real-app-ornita-verified.png`.

Las letras simples pueden mapearse de nuevo sin quedar secuestradas en Windows:
su `RegisterHotKey` existe solo mientras el emulador tiene el foco. Una
prueba Win32 real comprobó el ciclo de `D`: libre fuera, reservada dentro y libre
de nuevo al cambiar de aplicación.

La baseline automatizada queda en **705 tests superados**. La ficha PC fue
validada visualmente en la ejecución real; el mapeo de una letra concreta queda
pendiente únicamente de la prueba de uso elegida por el usuario.

### Alpha.109 — primera publicación completa de metadatos PC

La prueba física posterior a alpha.108 demostró que Ornita seguía mostrando
guiones. Una comparación directa en la misma ejecución separó las dos
fronteras: el objeto procedente del guardado tenía naturaleza/stats/IV/EV
vacíos; el reader vivo de Ryujinx devolvía para la misma identidad y caja 1,
slot 8 naturaleza Huraña, stats `44/31/21/19/18/30`, IV
`23/13/29/17/8/8` y todos los EV a cero. La primera divergencia estaba después
del reader: la reconciliación consideraba que identidad y posición iguales
implicaban que no había cambio, conservando el objeto incompleto del save.

BDSP publica ahora la matriz PB8 viva completa y usa una firma de presentación
para repintar únicamente cuando cambian campos visibles. La regresión cubre la
misma identidad en el mismo slot y comprueba caché y proyección final. La
composición se inspeccionó a 1920×1080 tanto en la ventana principal como en el
overlay.

La asignación física `D` demostró además que un `RegisterHotKey` global sin
modificadores secuestra la letra antes de que Windows la entregue al programa
con foco. Alpha.109 la rechazó preventivamente; alpha.110 sustituye esa medida
por registro condicionado al foco, permitiendo el mapeo solicitado sin afectar
a otras aplicaciones.

El usuario confirmó físicamente el 24-08-2026 que los contadores de la barra
flotante responden desde la primera interacción. La visualización física de los
stats PC corregidos queda pendiente de una única comprobación en alpha.109.
La baseline automatizada queda en **705 tests superados**.

### Alpha.108 — stats PC independientes del equipo

Alpha.108 corrigió una divergencia real del reader: el PB8 almacenado no
publicaba EXP y el adaptador no podía derivar el nivel sin un ancla del equipo.
La lectura posterior de Ornita demostró que esa capa ya devolvía nivel 15,
naturaleza, IV/EV y seis stats. Sin embargo, la UI continuó mostrando guiones;
alpha.109 localizó una segunda divergencia posterior en la reconciliación y
evita presentar alpha.108 como una corrección completa del síntoma visual.

Los contadores de la barra ya persistían correctamente; faltaba invalidar y
repintar su vista tras el clic. El repintado queda diferido fuera del callback.
La captura breve de teclas simples también se hace directa.

El mando continúa sin habilitarse: Ryujinx 1.3.3 usa `GamepadSDL2`, mantiene
`disable_input_when_out_of_focus=false` y Windows no tiene HidHide, ViGEm ni
HidGuardian. Detectar botones sin bloquear el dispositivo haría que RoleRun y
el juego recibieran la misma acción.

### Alpha.107 — datos PC y controles accionables

El reader BDSP ya conserva naturaleza/IV/EV extraídos del PB8 y el adaptador
calcula stats del PC solo con nivel anclado por identidad y PersonalTable
validada. Z avanza de MT a Pokémon, drafteos expone elegir/regenerar por separado,
Bolsa confirma sus envíos y el menú raíz incorpora acceso a Configuración.

La columna de mando queda explícitamente sin habilitar: el entorno físico usa
Ryujinx SDL2 con `disable_input_when_out_of_focus=false` y no dispone de un
filtro HID. La mera lectura desde RoleRun no impediría que el juego recibiera el
mismo input, incumpliendo el requisito de exclusividad.
La baseline automatizada queda en **699 tests superados**.

### Alpha.106 — navegación jerárquica sin alterar Ryujinx

La prueba física de alpha.105 demostró dos primeras divergencias: la ruta de
pausa ejecutaba `ShowWindow(SW_RESTORE)` y cambiaba el modo de ventana del
emulador; además, las vistas y el overlay registraban manejadores de `X`
simultáneos, por lo que una sola pulsación podía desmontar toda la superficie.
Alpha.106 elimina por completo la pausa y cualquier escritura sobre el estado
de ventana de Ryujinx. El Toplevel conserva foco y grab de teclado para que las
flechas no lleguen al juego. Una única capa dirige flechas/Z a la vista activa y
reserva X para sección → menú raíz → cierre. El cierre raíz restaura la barra de
forma síncrona. La navegación física queda pendiente de la prueba breve indicada
al usuario.
La baseline automatizada queda en **696 tests superados**.

### Alpha.105 — superficies inmersivas independientes

La prueba física de alpha.104 rechazó tres premisas de presentación: ocultar la
shell no independizaba sus canvases, `textvariable` y `text` competían en el
botón ON/OFF y `PostMessage` no equivalía a una tecla física para el input SDL
de Ryujinx. Alpha.105 crea un viewport propio para cada overlay, deja una sola
fuente textual en el selector y dirige SendInput F5 exclusivamente al HWND BDSP
validado. Equipo/PC, MT, Drafteos y Bolsa han sido inspeccionados a 1920×1080;
la pausa y el repintado ON/OFF quedan pendientes de confirmación física breve.
La baseline automatizada queda en **694 tests superados**.

### Alpha.104 — presentación física de PS y menú inmersivo

La validación física de alpha.103 demostró que el carril de HP ya refrescaba la
barra, pero también que los descensos positivos se publicaban antes de que la
barra del juego terminara. La primera divergencia estaba en
`BDSPRealTimeAdapter._presentation_gated_battle_state`: la compuerta demostrada
por alpha.68 solo cubría `HP=0`; cualquier `HP>0` se aceptaba directamente desde
BTL_PARTY. Alpha.104 aplica la misma evidencia de BUIStatusWindow a todo
descenso y añade una regresión 58→31 que conserva 58 hasta completar la
animación física.

El menú de juego usa la ventana BDSP/Title ID exacta y la tecla de pausa que la
instalación declara en su propio `Config.json`; no generaliza el comportamiento
a otros emuladores. Las vistas inmersivas y la temporización del daño quedan
pendientes de la prueba física breve indicada al usuario.

La baseline automatizada de esta versión queda en **691 tests superados** con
`python -m pytest -q`.

### Alpha.103 — salud viva y controles flotantes pendientes de validación

El usuario validó físicamente el 23-08-2026 en Perla Reluciente 1.3.0/Ryujinx
que la curación completa restaura correctamente todos los datos y que los
cambios de Pokémon del equipo se reflejan correctamente en el juego.

Alpha.103 incorpora el HP y el estado PB8 a la fuente viva que dibuja Equipo y
PC y la barra flotante. La lectura usa el campo de estado ya demostrado por el
writer de curación y los valores se contrastaron mediante reflexión contra la
DLL local `PKHeX.Core.dll`; la validación física de daño/estado y de los nuevos
controles flotantes sigue pendiente.

Verificación automatizada de alpha.103: **690 passed** en 23,51 s con
`python -m pytest -q`.

### Alpha.102 — cierre funcional BDSP pendiente de validación física

La party BDSP dispone de curación completa desde `Equipo y PC` y desde la barra
flotante. El writer modifica únicamente el PB8 identificado: PS actuales hasta
los PS máximos ya leídos, `Status_Condition` a cero y los cuatro PP según
WazaTable más PP Ups. Conserva identidad, EV, IV, rol y datos no implicados; usa
doble lectura, precondiciones host/guest, readback semántico y rollback.

Equipo→Equipo se interpreta en la UI como intercambio de roles y permanece
separado de la reordenación física no demostrada. Cada receptor recibe la
distribución EV de su nuevo rol; Líbero exige dos stats. La entrada PC→Equipo
incorpora la misma distribución en el snapshot y, tras el readback del cambio de
party, aplica el writer probado de rol+EV contra la identidad confirmada.

El inspector usa la evaluación común de reglas para pintar movimientos
incompatibles en rojo y exponer sustitución o eliminación. La barra flotante
tiene preferencia persistente ON/OFF y curación BDSP directa. Dos capturas
sintéticas a 1920×1080 confirman que los nuevos controles no desbordan Equipo ni
la ficha. Estas capacidades quedan pendientes de una única validación física
controlada en BDSP/Ryujinx antes de declararse cerradas. Suite completa:
**671 passed** en 22,69 s con `py -3.14 -m pytest -q`.

No se implementa un bypass genérico de MO. BDSP ya ofrece movimientos ocultos
desde el Pokétch sin enseñarlos; los títulos anteriores requieren investigación
por juego porque sus comprobaciones de campo no comparten un contrato demostrado.

### Pestaña global de MT — implementada, interacción final pendiente de validación

La navegación principal incorpora `MT`. La vista lee la mochila mediante el
reader realtime ya demostrado, muestra solo cantidades positivas confirmadas
y calcula cada miembro con `_tm_flow_candidates()`. Por tanto no duplica
compatibilidad, restricciones de rol ni escritores. Elegir una combinación
válida abre directamente el paso de movimiento a olvidar del flujo integrado;
confirmación, consumo, readback y rollback conservan la ruta anterior.

Las capturas `diagnostics/ui/global-tm-owned-hover.png`,
`global-tm-already-known-final.png` y `global-tm-centered-slots.png` demuestran
a 1920×1080 mochila poseída, estado `YA LO CONOCE` y selector centrado. Hover
actualiza propiedades sobre widgets persistentes; el readback actualiza la vista
sin desmontarla. Suite completa: **662 passed** en 23,85 s. El usuario confirmó
físicamente aprendizaje y consumo correctos en BDSP/Ryujinx; falta validar que
esta revisión final elimina flicker, salto de scroll y cargador posterior.

### Cambios posteriores a alpha.100: validación física y defecto abierto

La primera divergencia investigada de la apertura estaba antes de la barrera visual:
`_finish_save_load` publicaba deliberadamente una vista provisional con
`_pc_cache=None` y una caja, y solo después iniciaba la lectura PC. Además, la
primera publicación realtime podía reconstruir la página después de retirar el
cargador. La carga inicial lee ahora las cajas en el mismo worker de apertura,
instala la caché antes de crear la shell y mantiene la barrera hasta que la vista
final notifica su composición y termina el primer intento realtime. No existe un
timeout que pueda exponer una vista incompleta. Sin embargo, la validación
física posterior demuestra que la primera vista todavía aparece parcialmente
compuesta durante unos tres segundos. Por tanto, **la carga inicial sigue
abierta y no está corregida**. Después de varios cambios consecutivos que no
eliminaron el síntoma, se detiene el parcheo incremental y se aplaza este punto
hasta una investigación nueva de la publicación real de la ventana.

La primera divergencia al salir de MT era distinta: el flujo se destruía antes
de capturar el fondo y acto seguido se reconstruía `Equipo y PC`, aunque esa
vista seguía intacta debajo. La salida conserva primero el flujo MT completo,
lo retira después y revela la vista ya compuesta sin volver a renderizarla. Una
prueba Tk real a 1920×1080 conserva 30 botones PC, tres pasadas de layout,
paneles mapeados y ninguna barrera residual. La validación física posterior
confirma que la entrada, navegación y salida de MT ya se muestran correctamente.
El flujo MT queda validado en BDSP/Ryujinx; esta confirmación no se extiende a la
carga inicial.
Verificación automatizada: **655 passed** en 23,53 s con
`python -m pytest -q`.

Alpha.100 continúa la evolución quirúrgica de la interfaz original de RoleRun Manager.
La implementación se realiza exclusivamente en `RoleRun Manager Design
Evolution`; `RoleRun Manager Dev` y el prototipo rechazado permanecen fuera del
alcance. La comparación inicial demostró una copia exacta de 951 archivos,
74.302.609 bytes y SHA-256 agregado
`4025b7627611bf439ef592f776aff2b079288242626e4fc069d0d8f009474f1a`,
desde `main` / `0659aa624a68df7cd4d116d59c62090b911752ef`.

Alpha.100 vincula la retirada del cargador PC a evidencia de la vista publicada:
tres observaciones consecutivas con el conteo real de cajas y geometría válida.
MT reutiliza el estilo de frame estable oscurecido y el inspector permite
recorrer horizontalmente todas sus acciones. Verificación: **649 passed** en
22,37 s con `python -m pytest -q`. Validación física pendiente.

Tras dos intentos que solo desplazaron el defecto visual, alpha.99 abandona la
captura operativa de CTk: apertura, carga PC y MT usan una superficie opaca
autónoma. La navegación normal conserva su frame validado. Equipo y PC dejan de
compartir una cuadrícula geométrica ficticia; las seis filas de roles se recorren
en orden y `Z` transfiere el foco a las acciones de la ficha. `X` limpia la
selección. Verificación: **648 passed** en 22,78 s con
`python -m pytest -q`. Validación física pendiente.

Alpha.98 corrige dos primeras divergencias demostradas en alpha.97: `_clear_root`
destruía el Toplevel que debía proteger la apertura, y cerrar el flujo integrado
de MT abandonaba su referencia sin destruir sus bindings de teclado. La barrera
queda preservada, MT se retira de forma transaccional y el inspector PC participa
en la navegación con flechas. Verificación: **647 passed** en 22,58 s con
`python -m pytest -q`. Validación física pendiente.

La navegación, Equipo/PC, MT, Drafteos, Ayuda, bajas, Configuración y los
selectores normales ya están integrados en la ventana principal. La barra
flotante, el fantasma técnico de drag y la barrera transitoria de navegación
crean superficies independientes; esta última no contiene controles ni estado.

La prueba física de alpha.94 confirmó que el lateral ya se desliza fluido y que
el cambio de pestaña conserva la vista anterior hasta publicar el destino
completo. Permanecían tres defectos observables: variación zonal de luminosidad
durante esa espera, un tirador `<` residual junto al `>` y ausencia de actividad
animada durante el render síncrono. Alpha.95 transfiere el frame limpio anterior
al scrim, desmapea por completo el drawer al cerrarlo y dibuja el spinner desde
un worker GDI independiente del bucle Tk. La validación física de estos tres
ajustes queda pendiente.

Verificación alpha.95: **638 passed** en 22,71 s con
`py -3.14 -m pytest -q`. `alpha95-navigation-control-60fps.mp4` conserva el
origen completo durante la espera; `alpha95-spinner-contact-sheet.png` muestra
el avance de los radios a 20 fps sin variación del contenido circundante. La
captura asentada muestra únicamente el tirador `>`. Falta la comprobación
física breve de estos tres resultados en la aplicación real.

La validación física posterior de alpha.95 confirma navegación fluida,
publicación atómica, spinner móvil y desaparición del tirador `<` residual. Dos
capturas nuevas demostraron que los loaders CTk de apertura/PC pertenecían al
mismo árbol que se reconstruía: su animación se detenía y el de PC podía quedar
recortado con widgets parciales. Alpha.96 sustituye todas las entradas al sistema
común de espera por una superficie con HWND propio, conserva oscuro el origen de
la navegación y mantiene la carga PC hasta finalizar el render de destino.

Verificación alpha.96: **639 passed** en 22,95 s con
`py -3.14 -m pytest -q`. El preview bloqueó deliberadamente el mainloop durante
1,7 s; `alpha96-activity-overlay-control-60fps.mp4` y
`alpha96-activity-spinner-contact.png` demuestran movimiento continuo sin
recortes ni reconstrucción del fondo. La validación física de alpha.96 encontró
cuatro divergencias: la apertura podía congelar un shell parcial, BDSP
proyectaba el swap antes del readback y podía duplicar una identidad, el
arrastre dejaba trazas y los mensajes de carga podían solaparse. Alpha.97
conserva la barrera inicial hasta terminar la primera lectura PC, usa un
fantasma nativo, repinta una superficie fija de mensaje y publica Equipo/PC
BDSP solo después del resultado verificado. Su validación física queda pendiente.
Verificación alpha.97: **643 passed** en 22,86 s con
`python -m pytest -q`.
Las operaciones
funcionales reutilizan los mismos modelos, servicios, writers y comprobaciones
de alpha.86. Alpha.87 no añadió offsets, lectores, parsers, adapters ni rutas de
escritura RAM. Alpha.88 amplía exclusivamente la decodificación de campos ya
documentados dentro del PB8 BDSP existente; no incorpora direcciones ni writers.
PC→PC y la reordenación física Equipo→Equipo siguen rechazadas porque no existe
evidencia de writers que las soporten.

La sustitución de baja conserva `prompt_shown`, la cola de KO, la vida ya
descontada, Cementerio, precondiciones, readback y rollback. Su cierre es solo
visual y deja una acción persistente para reabrirla. La guía de roles comparte
una única fuente entre Ayuda y los popovers. Las Runs antiguas con Modo Libre
se migran a reglas siempre activas sin escribir en la partida.

Verificación automatizada actual: **637 passed** en 22,95 s. Capturas sintéticas
revisadas a 1100×720, 1360×768, 1440×900, 1900×1040 y escala 125 % en
`diagnostics/design/` y `diagnostics/design_evolution/`. La validación manual pendiente es únicamente
de presentación e interacción; las capacidades realtime conservan la
validación física ya registrada por sus versiones de origen.

Alpha.88 añade el resumen permanente de los cuatro contadores en la cabecera
ancha y compacta Equipo/PC y Drafteos para 16:9. En BDSP live, la ficha publica
naturaleza real/efectiva, stats calculados, IV y EV extraídos del mismo PB8 ya
validado. La tabla efectiva del mod publica además potencia, precisión y 826
descripciones no vacías; el bundle instalado es inglés y se rotula `EN`.

Alpha.101 implementa la asignación automática de EV por rol en BDSP y queda
**validada físicamente**. La transacción actualiza conjuntamente
marcador de rol, seis EV, stats calculados y PS; exige que PersonalTable,
IV/EV/nivel/naturaleza reproduzcan el bloque vivo anterior, hace readback del
core y calc en host/guest y revierte ambos si falla cualquier comprobación. Los
roles fijos maximizan su pareja y ponen a cero los otros cuatro stats; Líbero
exige elegir exactamente dos. El daño previo se conserva y un Pokémon a cero
PS no revive.

Validación física del 23 de agosto de 2026: **Líbero y asignación fija
correctos** en BDSP/Ryujinx. El usuario eligió las dos estadísticas de Líbero y
confirmó después que un rol fijo aplicaba automáticamente su pareja 252/252 y
limpiaba las otras cuatro. La capacidad de EV por rol queda cerrada.

La pestaña global de MT quedó validada físicamente en BDSP/Ryujinx el 23 de
agosto de 2026: solo muestra unidades poseídas, mantiene hover y scroll sin
flicker, distingue `YA LO CONOCE`, presenta el selector compacto y conserva la
vista hasta completar escritura y readback. El juego aprende el movimiento y
la mochila reduce exactamente una unidad.

Alpha.89 hace que las seis tarjetas de Equipo ocupen el panel completo y coloca
todo su contenido dentro del borde de selección. Solo la matriz PC tiene scroll.
Drafteos presenta sprites de 112 px y datos jerarquizados; su transición afecta
exclusivamente al contenido y nunca a la ventana completa. La consulta de
movimientos abierta desde el flujo conserva el drafteo y ofrece un retorno
explícito. Las cargas iniciales, del PC y de la mochila MT muestran un indicador
animado centrado. No se tocó lógica funcional ni ningún backend.

Verificación alpha.89: **620 passed** en 22,92 s con
`py -3.14 -m pytest -q -p no:cacheprovider`. Las capturas canónicas
`phase_h_team_pc_1900x1040.png` y `phase_h_draft_1900x1040.png` se revisaron
visualmente. La validación manual pendiente se limita a presentación,
transición y navegación; no se ha introducido una capacidad realtime nueva.

Alpha.90 elimina la interacción desplegable del resumen superior: vidas,
curaciones, medallas y drafteos son cuatro controles independientes visibles en
todas las páginas. Los controles manuales permiten restar y sumar directamente;
un contador automático conserva bloqueados esos botones para no introducir una
segunda fuente de verdad. En Equipo/PC, las seis fichas terminan junto a las
casillas 21–25 y las 30 posiciones del PC forman una matriz fija 5×6 sin scroll.
Drafteos muestra naturaleza, stats, IV, EV, movimientos y seis botones visibles
en una sola pantalla. El alto de ambas vistas se sincroniza con el viewport real.

Verificación alpha.90: **620 passed** en 23,29 s con
`py -3.14 -m pytest -q -p no:cacheprovider`. Se revisaron visualmente a
1900×1040 Equipo/PC y los tres pasos de Drafteos. No se modificó funcionalidad
realtime, persistencia, reglas, readers ni writers.

Alpha.91 convierte Equipo en la superficie principal: seis fichas completas
publican identidad, nivel, rol, PS/barra live, stats con naturaleza, habilidad,
objeto y movimientos. El PC se limita a tres columnas y desplaza localmente sus
treinta posiciones. La ficha de equipo conserva solo Cambio de rol y Enseñar
MT. La cabecera usa símbolos y Medallas no tiene controles manuales.

La navegación lateral es ahora una capa desplegable sobre contenido oscurecido.
Flechas, `Z` y `B` gobiernan selectores espaciales en Equipo/PC, Drafteos y MT
sin capturar teclas dentro de campos de texto. El indicador animado cubre
writers realtime y las lecturas de mochila ORAS/X/Y pasan a background sin
cambiar sus decisiones funcionales ni sus fallbacks. No se incorpora ninguna
dirección, estructura ni escritura nueva.

Verificación alpha.91: **625 passed** en 22,22 s con
`py -3.14 -m pytest -q -p no:cacheprovider`. La revisión visual sintética a
1900×1040 cubre Equipo/PC, menú lateral desplegado, Drafteos y MT. Queda
pendiente la validación manual de presentación y control por teclado; las
capacidades realtime heredadas no se reabren por este cambio de interfaz.

Alpha.92 compacta cada tarjeta de Equipo sin reducir su información: mote y
nivel comparten cabecera, la barra de PS ocupa aproximadamente un tercio, los
seis stats forman una matriz 2×3 y habilidad, objeto y cuatro movimientos quedan
visibles. Las seis siluetas aportadas por el usuario se conservan mediante su
canal alfa y se presentan en dorado como acceso a la guía de rol. La ficha
elimina la numeración de movimientos y separa IV/EV en seis recuadros.

La ventana principal no permanece minimizada: cambia a barra flotante o vuelve
maximizada cuando no puede abrirla. El menú lateral interpola su anchura durante
210 ms y reserva un carril al tirador. Los cambios de pestaña usan dos árboles
de widgets: la vista anterior deja de escuchar entradas pero sigue pintada hasta
que la nueva ha resuelto geometría y scroll. La primera divergencia del glitch
estaba en la destrucción anticipada de `IntegratedDraftFlow`, no en DWM ni en
los datos de la página.

Verificación alpha.92: **631 passed** en 23,10 s con
`py -3.14 -m pytest -q -p no:cacheprovider`. Se revisaron capturas sintéticas
a 1900×1040 de Equipo/PC, ficha seleccionada, Drafteos y menú lateral. Queda
pendiente la comprobación manual de presentación, tooltip, transición y cambio
entre ventana maximizada/barra; no se modificó ninguna capacidad realtime.

Alpha.93 coloca los cuatro movimientos de cada miembro en una sola fila y
reduce la ficha sin perder datos: cada stat publica valor, IV y EV antes de
habilidad y objeto. El tooltip se posiciona respecto del botón de rol, no con
coordenadas mezcladas entre la tarjeta y la ventana. Drafteos no muestra un
control de cierre en su primer paso; la flecha de los pasos siguientes vuelve
directamente a elegir Pokémon.

El vídeo físico `2026-08-23 17-50-55.mp4` permitió aislar dos fronteras de la
navegación. La capa oscura excedía el contenido al combinar un desplazamiento
horizontal con ancho relativo completo; ahora usa un rectángulo absoluto
acotado a la ventana. Además, la barrera de cambio llamaba a `update()` dentro
del propio intercambio: esa reentrada podía ejecutar temporizadores, resize y
otra navegación antes de terminar el árbol nuevo. Se conserva únicamente el
cálculo de geometría idle, el destino se renderiza tras el cierre real de 210 ms
y la captura anterior se retira después del primer repintado estable.

Verificación alpha.93: **635 passed** en 23,37 s con
`py -3.14 -m pytest -q`. La apertura lateral se inspeccionó a 30, 100 y 220 ms
a 1920×1080; sus anchos observados fueron 80, 201 y 285 px, y la capa oscura
coincidió exactamente con los 1.844 px restantes. También se comprobó escala
125 % y el render final Equipo/PC. Queda pendiente la validación manual breve de
la animación y del cambio de pestaña; no se alteró ninguna capacidad realtime.

Alpha.94 parte del vídeo físico `2026-08-23 18-20-30.mp4`. La primera
divergencia demostrada era que seleccionar Equipo y PC cuando ya estaba visible
ejecutaba de nuevo todo su render. La segunda estaba en la frontera de
composición: una etiqueta hija compartía el mismo orden de repintado que los
canvas de CustomTkinter y Windows podía publicar varios frames del destino
incompleto al retirarla.

La selección del destino actual ahora solo cierra el menú. Para una navegación
real, el último frame completo vive temporalmente en un `Toplevel` sin bordes,
con superficie DWM propia; la página nueva se construye debajo y el fundido no
empieza hasta que se han presentado varios frames estables. El drawer lateral
permanece maquetado a ancho fijo fuera del viewport y solo interpola su X. La
traza real a 1920×1080 redujo los intervalos del tramo visible desde unos 31 ms
a una mayoría de 4–5 ms, sin redimensionar descendientes.

Verificación alpha.94: **637 passed** en 22,95 s con
`py -3.14 -m pytest -q`. La grabación de control
`alpha94-automated-navigation-final-60fps.mp4` fue inspeccionada a 30 fps: el
contacto entre pantallas contiene únicamente dos páginas completas y su mezcla
de opacidad, sin paneles parciales. Se repitió el estado final a escala 125 % y
se comprobó que navegar a la pestaña activa no crea ninguna barrera ni render.
Queda pendiente la validación manual breve de la sensación del deslizamiento y
del cambio de pestaña. No cambia ninguna capacidad realtime.

Verificación alpha.88: **614 passed** en 22,66 s con
`py -3.14 -m pytest -q -p no:cacheprovider`. Las capturas sintéticas nuevas
cubren 1900×1010, 1360×768 y 1100×720. La lectura visual de naturaleza/stats/
IV/EV queda pendiente de una comprobación física breve en SP 1.3.0 / Ryujinx.

## Estado realtime heredado: BDSP / Ryujinx

La matriz exhaustiva y el orden de investigación se mantienen en
`docs/BDSP_REALTIME_PARITY.md`. Es el checklist maestro de esta etapa: una
capacidad dependiente de Ryujinx no se considera cerrada sin implementación,
regresión, suite completa y validación física.

El usuario ha aparcado USUM después de validar físicamente el primer Kahuna en
alpha.65. Los incrementos de los otros tres Kahunas conservan su estado
pendiente, pero no forman parte del trabajo activo hasta nuevo aviso.

El objetivo de esta etapa ha sido dotar a Pokémon Diamante Brillante/Perla
Reluciente de paridad realtime sobre Ryujinx. La baseline local demuestra Perla Reluciente
`1.3.0`, Title ID `010018E011D92000`, mod `Output` solo `romfs`, memoria
`HostMappedUnsafe` y una Run `SP-Timper` con save `SAV8BS` válido. El adapter y
bridge Switch están actualmente integrados para ese perfil exacto.

Se conserva GDB RSP como frontera diagnóstica de solo lectura y se ha añadido
el transporte permanente `RyujinxBridge`/HostMapped. Su cliente de captura
continúa abriendo solo consulta/lectura; alpha.75 añade un handle RW separado y
efímero exclusivamente dentro de transacciones BDSP ya precondicionadas.
`BDSPRealTimeAdapter` publica party, PC, inventario/MT y lane de batalla en el
Core. Roles y movimientos de la party, incluida la enseñanza consumible de MT,
tienen writer transaccional. El swap Equipo↔PC 1↔1 está validado físicamente;
alpha.82 cierra físicamente el cambio de tamaño de cola 5↔6 y alpha.83 añade la
compactación intermedia ya validada desde RoleRun. Alpha.84 incorpora la
sustitución por baja sobre esas mismas unidades demostradas, validada
físicamente para uno y dos KO. Alpha.85 añade las tres utilidades generales con
writer transaccional. La prueba física validó Caramelo Raro y dinero, y demostró
que el supuesto ID de Repelente Máximo era incorrecto. Alpha.86 corrige la
identidad y añade el alta exacta de un objeto todavía ausente; solo ese botón
queda pendiente de una prueba breve.
Progreso se limita al reader de medallas ya integrado. La prueba física del 2026-08-22
confirmó Title ID, `SwitchPlayer.nss` como módulo `main` y tres
fuentes independientes para SP 1.3.0: las cajas 40×30, la party runtime de
`PlayerWork._playerParty` y la party del cliente jugador dentro de
`BattleProc`. Los lectores de producción validan tamaño, conteo, punteros,
doble lectura, identidad y checksum donde corresponde; no trasladan ninguna
estructura de 3DS. Baseline y fuentes: `docs/BDSP_REALTIME_BASELINE.md`.

## Estado realtime vigente heredado de alpha.86

La primera divergencia de las utilidades estaba en la UI: BDSP rechazaba
`PendingInventoryChange` aunque el array vivo `SaveData.saveItem` ya estaba
demostrado. Alpha.85 abrió correctamente esa compuerta y la prueba física
confirmó Caramelo Raro ×999 y dinero 999.999. Sin embargo, el tercer botón dejó
`Repelente ×999`: el fallo no estaba en la transacción sino en la identidad
estática que asociaba `max-repel` con el registro `79`.

La causa queda demostrada por tres evidencias concordantes. El catálogo español
indexado de PKHeX contiene `77 = Repelente Máximo` y `79 = Repelente`; OpenDPR
declara `GOORUDOSUPUREE=77` y `MUSIYOKESUPUREE=79`; y la relectura física tras
alpha.85 mostró `SaveItem[79].Count=999` mientras `SaveItem[77]` seguía en
`Count=0, SortNumber=0`. La primera divergencia era
`BDSP_UTILITY_ITEM_IDS`, antes del writer. Evidencia canónica:
`diagnostics/manual/bdsp_alpha85_max_repel_identity_FAIL_alpha86_ROOT_CAUSE_20260823.json`.

Alpha.86 mapea Repelente Máximo exclusivamente a `77`. Como esta partida nunca
lo había poseído, el botón debe además crear su posición en la mochila. OpenDPR
demuestra que el primer alta asigna el siguiente orden del bolsillo y PKHeX
precisa el algoritmo: máximo `SortOrder` entre los IDs legales del mismo
bolsillo más uno. La mochila actual tiene máximo 16 en General, de modo que el
alta esperada de `77` usa 17. El registro `79` y los restantes 2.998 registros
se conservan byte a byte. Los 999 Repelentes normales producidos por alpha.85
permanecen en la partida; RoleRun no intenta una restauración tardía con un
valor que podría haber cambiado desde la prueba.

Para dinero, OpenDPR demuestra `SaveData.playerData.mystatus` y el orden
`name, id, gold`; PKHeX demuestra el máximo 999.999. En el único `PlayerWork`
físico de SP 1.3.0, `MYSTATUS` quedó localizado en `+0xE0` y `gold` en `+0xEC`.
Nombre, ID32, dinero, edición SP y dos medallas coincidieron con
el save; la doble lectura fue estable y el ID32 apareció una sola vez dentro
del objeto. Evidencia canónica:
`diagnostics/manual/bdsp_alpha85_money_and_utility_layout_PROOF_20260822.json`.

El carril exige fuera de combate dos capturas idénticas de party, mochila
y `MYSTATUS`, huella de sesión y coincidencia guest/host. Solo cambia el
`SaveItem` de 12 bytes del ID demostrado y/o los cuatro bytes de dinero. Conserva
todos los metadatos existentes; para un objeto General ausente, crea exactamente
el orden de bolsillo demostrado. El readback compara los 36.000
bytes de mochila, los 56 bytes de `MYSTATUS`, la party intacta y el valor
semántico. Un fallo restaura todos los destinos y verifica el rollback.

La UI aplica los tres botones automáticamente; desconectada no crea una cola de
save. El editor de rol para un Pokémon que permanece dentro del PC se declara
fuera de alcance por decisión del usuario; no bloquea el cierre de BDSP.
Caramelo Raro, Repelente Máximo y dinero: **validados físicamente** en SP 1.3.0
/ Ryujinx. El usuario confirmó que alpha.86 creó Repelente Máximo ×999, cerrando
la única validación pendiente del carril. Verificación alpha.86: **130 passed**
en el bloque BDSP dirigido y **581 passed** en 22,05 s en la suite completa.

Alpha.76 corrige dos divergencias demostradas en la primera prueba física del
writer de MT. La traza preservada contiene 439 snapshots y todos tienen seis
miembros; al cambiar Pidgeotto por Slowpoke la secuencia pasa de
`303,359,391,353,339,17` a `303,359,391,353,339,79`, nunca a siete. La tarjeta
adicional nacía después del adapter: BDSP publicaba al entrante con su marcador
de caja antes de aplicar la herencia del rol saliente, y el maquetador mostraba
el duplicado de `Mago` fuera de las seis casillas fijas. Ahora se escribe y
verifica primero el rol heredado y solo el readback confirmado puede sustituir
la party visible; si el writer está ocupado se conserva la captura anterior.

La misma sesión emitió 439 avisos `BattleProc contiene un TypeInfo inválido`.
Una doble lectura directa, estable y de solo lectura demostró que la ranura
TypeInfo era exactamente cero fuera de combate, no un puntero no nulo corrupto.
El reader acepta únicamente ese `nullptr` como clase no cargada. Cualquier valor
no nulo inválido, static fields incoherentes, flags inestables o batalla activa
continúan bloqueando la escritura. No se añadió dirección ni fallback de salud.
Evidencias:
`diagnostics/manual/bdsp_alpha75_pc_seventh_and_tm_battleproc_FAIL_20260822_210614.jsonl`
(SHA-256 `51BB6576F4421B4B0A37926E702C77CE0CEE9F658A7FE3C23F38F9E4CA831DC9`)
y `diagnostics/manual/bdsp_alpha75_battleproc_null_outside_battle_PROOF_20260822.json`.

La degradación de rendimiento del GDB Stub ha quedado demostrada físicamente.
Con GDB apagado el usuario observó una mejora clara; al reactivarlo sin ningún
cliente RoleRun, la lentitud regresó. El source exacto `e2143d43...` muestra la
causa: el debugger activa el modo global de depuración de ARMeilleure, sustituye
el dispatch rápido por ejecución bloque a bloque con PC preciso y separa la
caché PTC por `DebuggerMode`. El primer arranque sufrió además recompilación y
crecimiento JIT, por eso fue peor que el segundo. GDB queda rechazado como
transporte permanente y se conservará solo para diagnósticos puntuales.

Una comparación read-only simultánea demostró la alternativa HostMapped:
la vista Windows y GDB devolvieron exactamente los mismos 64 bytes de `main` y
los mismos 344 bytes de un PB8 mediante un único delta de sesión. La prueba
decisiva posterior reinició Ryujinx, mantuvo GDB apagado y redescubrió un mapa
de sesión distinto sin reutilizar ninguna dirección anfitriona. La huella fue
única; la cadena produjo 40 cajas, 1.200 slots, 11 PB8 ocupados y 1.189 vacíos,
todos con checksum correcto. El componente de producción repitió la lectura en
1,543 s después de verificar Title ID y revisión en el título activo de Ryujinx,
y solo abrió `PROCESS_QUERY_INFORMATION | PROCESS_VM_READ`.
Evidencia:
`diagnostics/manual/bdsp_sp130_gdb_performance_ab_20260822.json` y
`diagnostics/manual/bdsp_sp130_hostmapped_bridge_proof_20260822.json`, más
`diagnostics/manual/bdsp_sp130_hostmapped_no_gdb_PROOF_20260822.json`.

La captura física de HP sobre la colección de seis PB8 de `SaveData` terminó
con resultado negativo: pese al daño físico, el journal conservó solo el
baseline y ninguno de los seis HP cambió. Esa colección no se acepta como
autoridad HP live ni se incorpora al reader. Evidencia y SHA se registran en
`docs/BDSP_REALTIME_BASELINE.md`.

La primera divergencia quedó resuelta mediante el código IL2CPP exacto de
OpenDPR y dos capturas HostMapped acotadas. `SaveData.playerParty` es una copia
serializada; la party viva fuera de combate es el campo no serializado
`PlayerWork._playerParty`. Durante el combate tampoco es autoridad inmediata:
`BTL_PARTY` publicó `58/67` para el primer miembro mientras la party normal aún
publicaba `67/67`. Al huir, la party normal convergió a `58/67` y 608 ms después
desapareció el objeto de batalla.

La captura física posterior sí demostró KO y cambio forzado. `BTL_PARTY`
publicó Skitty `7/21→0/21` mientras `PlayerWork` permanecía en `21/21`. Tras
elegir a Shuppet, las filas se intercambiaron: Shuppet quedó en fila 1 con
`party_index=1` y Skitty en fila 2 con `party_index=0`. La party normal no
convergió a `0/21` hasta 23.096 ms después del KO y `BattleProc` desapareció
701 ms más tarde. Por tanto, el adapter aplica HP por `PokeID/party_index` y
exige coincidencia de especie, nivel y HP máximo antes de publicar la muestra;
nunca usa el número de fila como slot. La instrumentación candidata de miembro
activo no se promueve a producción porque no es necesaria para esta función.
Evidencia:
`diagnostics/manual/bdsp_sp130_runtime_party_graph_PROOF_20260822.json`,
`diagnostics/manual/bdsp_sp130_battle_to_party_convergence_AUTO_20260822_163121.jsonl`
(SHA-256 `46AE0D518B7FF0D474D96E57F71BCB7D49D52D5C6D984E4F797FFB46B4AF16C7`)
y `diagnostics/manual/bdsp_sp130_battle_lane_PROOF_20260822.json`, más
`diagnostics/manual/bdsp_sp130_ko_switch_PROOF_20260822.json` y su traza fuente
(SHA-256 `565B0335AEED1B1174E5FF6011040BB69FE2F1774A1A554A7483474A1435C617`).

El reader y el mapeo están validados físicamente. La primera prueba de la
integración alpha.66 no registró el KO ni al terminar el combate. La captura
independiente posterior leyó, desde el mismo Ryujinx aún abierto, la party
completa y al primer miembro a `0/58`; por tanto, las direcciones y el parser no
eran la frontera que falló.

La introspección de solo lectura del proceso RoleRun demostró la primera
divergencia: `_oras_live_active` seguía a `true`, pero no existían timer,
snapshot ni baseline de salud. El watcher del `main` había cargado la copia del
save y `_clear_oras_live_reconciliation()` había cancelado el monitor y
reiniciado el Core. `_reload_from_watched_save()` solo lo rearmaba para la clave
exacta `oras`, así que BDSP quedaba conectado solo nominalmente y no volvía a
leer RAM. No llegó ninguna muestra a LivePartyWatch ni al compromiso de muerte.

Alpha.67 rearma el monitor para todos y solo los backends declarados en
`REALTIME_READ_GAME_KEYS` y añade una traza integrada acotada de snapshots y
fronteras UI. No cambia offsets, parsers, mapeos de batalla ni escritores; BDSP
continúa en solo lectura. La evidencia causal se conserva en
`diagnostics/manual/bdsp_alpha66_save_watcher_monitor_stopped_PROOF_20260822.json`.
La corrección queda físicamente validada por el usuario el 2026-08-22: hubo
cuatro recargas del watcher antes del combate, el monitor siguió activo, se
observó una única transición `12→0`, se restó exactamente una vida, se retiró
el icono y el selector apareció correctamente tras el combate. La traza se
conserva en
`diagnostics/manual/bdsp_alpha67_save_watcher_ko_SUCCESS_20260822_174841.jsonl`
con SHA-256
`F90025A11E43FEE750B2DA399F666B56EFCFD55A7FDC4A8F7AC7FED5C8934487`.

La misma validación reveló una frontera visual: RoleRun cobró la muerte al
inicio del turno, antes de que la pantalla mostrara el golpe/KO. La traza prueba
que el compromiso coincidió con el HP lógico
`BTL_POKEPARAM.CORE_PARAM.hp=0`; no contiene todavía el estado de la barra
visible, por lo que no se aplica un retardo supuesto.

Alpha.68 añadió una lane diagnóstica de presentación. El source exacto y los
metadatos IL2CPP vivos demuestran que `BattleViewUISystem._statusWindows`
mantiene por separado HP mostrado, PokeID, `needHpApply` y
`HpBar.IsAnimation`. El TypeInfo nominal `main+0x04E70E40`, sus cuatro
ventanas y cada FieldInfo se validan antes de publicar la muestra.

La prueba letal de alpha.68 demuestra la primera divergencia visual. Para el
mismo Shuppet/PokeID, el HP lógico de batalla pasó `12→0` en la secuencia 586
(`1787415029.213`) y RoleRun comprometió la muerte 12 ms después, mientras la
ventana jugador seguía mostrando `12/58`. El objetivo visible `0` con
`HpBar.IsAnimation=true` no apareció hasta la secuencia 609
(`1787415035.380`), 6,167 s después; la barra terminó a `0/58` en la secuencia
611 (`1787415035.903`). La primera divergencia estaba, por tanto, en el adapter:
publicaba el cero de resolución lógica como `health_game` antes de que la lane
visible del mismo Pokémon hubiera presentado el KO.

Alpha.69 corrige solo esa frontera BDSP. Cuando el HP lógico cae a cero, el
adapter conserva el último HP positivo hasta observar en una ventana jugador
única, con PokeID y HP máximo coincidentes, la secuencia `0 + animación activa`
seguida de `0 + animación terminada`. No usa retardos fijos. Si falta o resulta
ambigua la presentación, no cobra anticipadamente; la convergencia posterior de
`PlayerWork` mantiene una salida segura. Un HP cero inicial continúa siendo
baseline y no genera una muerte retrospectiva. Evidencia fuente:
`diagnostics/manual/bdsp_alpha68_visible_hp_timing_FAIL_20260822.jsonl`
(SHA-256
`C9211DF2C2C341B50C30852F7670FA7381D39E857B97297C80B4BAB7F922A72F`) y
prueba causal:
`diagnostics/manual/bdsp_alpha68_visible_hp_timing_ROOT_20260822.json`.

El usuario validó físicamente alpha.69 el 2026-08-22 en Perla Reluciente 1.3.0
sobre Ryujinx 1.3.3, con GDB desactivado: el timing fue correcto y el selector
postcombate siguió funcionando. La traza confirma de extremo a extremo la
observación. En la secuencia 467 el HP lógico ya era 0, pero la ventana seguía
visible a 6/58 y el adapter publicó 6. En 498–499 la ventana visible mostró 0
con animación activa y el adapter continuó publicando 6. En la secuencia 500,
con 0 visible y animación terminada, publicó el primer cero; inmediatamente
después aparecen una sola `health-transition` y un solo `faint-registered`.
La función queda cerrada para combate salvaje simple dentro de esta combinación;
dobles y encuentros especiales no se infieren de esta prueba. Control:
`diagnostics/manual/bdsp_alpha69_visible_ko_sync_SUCCESS_20260822.jsonl`,
SHA-256
`855B56E05D904B0762D946C139DF871624DCD1A607A4CD9C957A90A7A1D2C151`.

La reordenación juego→RoleRun también queda validada físicamente en la misma
combinación. El usuario intercambió los dos primeros Pokémon y confirmó que
RoleRun mantuvo correctamente identidad, icono y rol. La traza demuestra la
parte estructural: las secuencias 886–893 cambiaron el orden de especies
`353,391,339,17,303,359` a `391,353,339,17,303,359` y después registraron la
vuelta al orden original, sin cambiar composición. La conservación visual del
icono y rol procede de la observación física del usuario, no se infiere del
journal. Control:
`diagnostics/manual/bdsp_alpha69_party_reorder_SUCCESS_20260822.jsonl`,
SHA-256
`D037D876FDBB464D2D1F444A54C202647F4119DBAA12E6A09B7CB006DEAD5672`.
Los cambios de conteo y composición party↔PC siguen pendientes.

Alpha.70 conecta al reconciliador común la cadena de cajas ya demostrada, sin
añadir offsets ni habilitar escrituras. `BDSPRealTimeAdapter.read_pc()` exige
40×30, doble lectura, longitud PB8, checksum y posiciones completas. Publica
forma, apodo, objeto, habilidad, movimientos, huevo y marcas de rol desde el
PB8 almacenado. El nivel solo se conserva si una ancla de save/party coincide
de forma única por especie, PID, TID y SID; no se calcula mediante una curva
supuesta. Party y PC se contrastan antes de publicar: si una identidad aparece
en ambas capturas asíncronas, la UI conserva la vista anterior y relee.

La ruta integrada se ejecutó sobre el Ryujinx físico abierto y leyó los 1.200
slots, 11 ocupados, en 1,459 s con `writes_enabled=false`. La traza alpha.70
registra posiciones/especies y una huella no reversible de identidad, además de
las fronteras de reconciliación, sin guardar PID/TID/SID crudos. Evidencia:
`diagnostics/manual/bdsp_alpha70_pc_read_probe_PROOF_20260822.json`.

La primera prueba física equipo→PC de alpha.70 **no valida la integración**.
RoleRun vio en la party los depósitos `6→5` y `5→4` y el reader PC demostró
11→12→13 ocupados, pero la caja no se actualizó hasta salir y volver a la
pestaña; entonces ambos depositados aparecieron como `Nv. 0`. Las conciliaciones
tardías recibieron `before/after=5/5` y `4/4`, por lo que ya no contenían la
ancla saliente que conserva el nivel. La primera divergencia de código era la
rama BDSP del monitor: a diferencia de los flujos ya funcionales, retornaba tras
publicar `party_changed` sin programar la lectura PC con los estados anterior y
nuevo. Evidencia preservada:
`diagnostics/manual/bdsp_alpha70_pc_refresh_level_FAIL_20260822.jsonl`, SHA-256
`ABA76FE8028E969A6AA6B9E4854AE86265AAF805BE5B58DC88786DB82235E33B`.

Alpha.71 corrige esa frontera sin modificar readers ni writers: publica la
party nueva y programa inmediatamente la conciliación usando el par real
anterior→nuevo. Así el saliente conserva nivel/rol por identidad fuerte y la
vista PC se repinta al finalizar la lectura, sin navegar. La regresión causal
reproduce un depósito `2→1` y exige que el worker reciba ambos snapshots y el
nivel 12 del saliente.

El usuario validó físicamente alpha.71 el 2026-08-22 en Perla Reluciente 1.3.0
sobre Ryujinx 1.3.3, con GDB desactivado. Los depósitos se reflejaron en CAJAS
PC sin cambiar de pestaña y con sus datos correctos; las recuperaciones también
se reflejaron correctamente en el equipo. La traza confirma seis transiciones
directas con snapshots anterior→nuevo (`4→3`, `3→4`, `4→5`, `5→4`, `4→5` y
`5→6`), cada una seguida por lectura y conciliación PC. La función queda cerrada
para cambios de composición realizados dentro del juego en esta combinación.
No valida todavía PC↔PC sin cambio de party ni ninguna escritura iniciada desde
RoleRun. Control:
`diagnostics/manual/bdsp_alpha71_pc_roundtrip_SUCCESS_20260822_190522.jsonl`,
SHA-256
`7662BD363815B8EF273008AB4CC69E48500549175F11AECB76E0FAA60AF4AC71`.

Alpha.72 implementa el caso PC↔PC sin inventar un evento de party. El análisis
estático demuestra que alpha.71 solo solicitaba la matriz al entrar en CAJAS PC
o ante `PARTY_CHANGED`; mover entre cajas no atraviesa ninguna de esas fronteras.
BDSP reutiliza ahora el reader 40×30 demostrado mediante un único sondeo cada
2,5 s, exclusivamente mientras la página está visible. Cada lectura programa la
siguiente al terminar, se pospone si otra conciliación está activa y se cancela
al salir/minimizar/cambiar de Run o ante error. Una proyección idéntica no repinta
la UI. Las escrituras continúan cerradas.

El usuario validó físicamente alpha.72 el 2026-08-22 en Perla Reluciente 1.3.0
sobre Ryujinx 1.3.3, con GDB desactivado. Sin cambiar la party de seis miembros,
Aipom (`species 190`) se movió de caja 1/slot 2 a caja 2/slot 2. El primer poll
posterior produjo exactamente `changed=true`, `override_slots=1` y
`emptied_slots=1`; los siete polls siguientes publicaron `changed=false`. El
usuario confirmó origen/destino correctos y ausencia de parpadeo. El seguimiento
PC↔PC realizado dentro del juego queda cerrado para esta combinación. Control:
`diagnostics/manual/bdsp_alpha72_pc_to_pc_poll_SUCCESS_20260822_191534.jsonl`,
SHA-256
`1A399AA247275C9A33085327628076D0FD8B64BEBE2107E81370223198101FDD`.

Alpha.73 incorpora la mochila/MT viva sin autorizar escrituras. La cadena
`[[[[main+4E7BE98]+B8]+10]+48]+20` no se aceptó solo por estar publicada:
PKHeX-Plugins `c8e23a43...` la liga explícitamente a SP 1.3.0; OpenDPR
`5b0cb0c8...` demuestra `PlayerWork.SaveData.saveItem`, el layout `SaveItem` y
`ItemSaveSize=3000`; PKHeX `26.07.07` demuestra que el ID es el índice y cómo se
interpretan cantidad y orden. En la partida real, el array declaró 3.000
registros y dos lecturas de sus 36.000 bytes fueron idénticas. Los 51 IDs
positivos coincidieron con el save; el único valor diferente fue Antiparalizador (#22),
10 en el último guardado y 9 en RAM, una divergencia positiva que demuestra que
la lane observa consumo posterior al guardado. Las siete MT poseídas coincidieron
exactamente en ID y cantidad.

`BDSPInventoryReader` valida raíz, longitud, estabilidad, cantidad, flags,
padding y orden antes de publicar. El selector realiza esta lectura en segundo
plano y nunca consulta RAM durante el render pasivo. El save se usa únicamente
como testigo diagnóstico: no sustituye una lectura live diferente. Las MT que
ya están en cambios pendientes se descuentan de la proyección. La tabla
MT→movimiento continúa viniendo del `personal_masterdatas` efectivo, cuya copia
actual tiene SHA-256
`BDA0D7F9E7B8F0472E15F5B78AF4524CAFB5D677FFC0AA7A6D499129D784248B`.
La lectura está automatizada y contrastada en el proceso real, pero la función
queda **pendiente de validación física del usuario** hasta observar dentro del
juego una cantidad y su cambio al consumir una MT sin guardar. Enseñar desde
RoleRun sigue siendo una operación sobre save pendiente de `GUARDAR CAMBIOS`;
no existe writer RAM BDSP. Evidencia:
`diagnostics/manual/bdsp_sp130_inventory_live_save_PROOF_20260822.json`.

Dobles, compañeros, multijugador y encuentros especiales conservan alcance
pendiente.

El parser PB8 se contrastó además con el mismo `PKHeX.Core 26.7.7` usado por
el motor de RoleRun y con los seis miembros reales: coincidieron identidad,
forma, apodo, objeto, habilidad, movimientos, huevo y marcas en los seis casos.
La evidencia anonimizada queda en
`diagnostics/manual/bdsp_sp130_runtime_pb8_fields_PROOF_20260822.json`.

Verificación alpha.73: reader/Adapter/UI BDSP **57 passed** en 0,74 s; bloque
afectado más consumidores Gen7 **112 passed** en 2,16 s. Suite completa:
**519 passed** en 21,12 s con `py -3.14 -m pytest -q` dentro del entorno de
tests aislado.

Alpha.74 corrige tres fronteras de preparación BDSP sin abrir escrituras RAM.
`SUSTITUIR` había quedado deshabilitado porque la tarjeta trataba como ausencia
de MT el `None` deliberado de la carga diferida alpha.73; ahora el enlace live
habilita la acción y el clic valida la mochila en background. `ELIMINAR ATAQUE`
sí generaba y compactaba el cambio, pero cada snapshot físico reemplazaba la
previsualización; ahora las ediciones pendientes se reaplican únicamente a la
copia visual fresca.

La lectura física de la party activa demostró además que `SP-Timper` todavía usa
el layout histórico: `Farigiraf=100000`, `Luto=010000`, `Diego=000001`,
`Shupete=000010` y `pezkeño=000100`. Esos bits corresponden semánticamente a
Líbero, Tanque, Prisma, Support y Mago bajo layout 1, pero no al orden canónico
círculo=Líbero, triángulo=Asesino, cuadrado=Mago, corazón=Tanque,
estrella=Prisma y rombo=Support. La migración BDSP se prepara ahora como lote
sobre el guardado y exige readback de todos los bits con layout 2 antes de
cambiar el contrato persistido. El binario empaquetado se comprobó sobre una
salida temporal: Shupete/Support pasó de `000010` a `000001` y el readback nuevo
devolvió Support. La partida activa no se tocó en esa comprobación.

Las sustituciones 1↔1 preparadas desde RoleRun heredan siempre la marca del
Pokémon saliente, incluido BDSP. Un intercambio realizado directamente dentro
del juego se sigue observando en solo lectura y no normaliza su marcador: esa
variante requiere demostrar antes un writer PB8 runtime con precondiciones,
readback y rollback.

La frase anterior describe el límite histórico de alpha.74. Alpha.75 demostró
el writer PB8 de marcadores de party y alpha.76 lo conecta a los intercambios
1↔1 observados dentro del PC: la herencia se escribe y verifica antes de publicar
la nueva composición. Sigue sin existir un writer de cajas ni fallback al save.

Validación física parcial de alpha.74, comunicada por el usuario el 2026-08-22:
`SUSTITUIR` se habilita y abre correctamente el selector, y
`ELIMINAR ATAQUE` conserva la eliminación, compacta los movimientos restantes y
deja disponible el hueco final esperado dentro de RoleRun. Esta observación
cierra la corrección visual y de interacción.

En la prueba física inmediatamente posterior, el usuario consumió una MT dentro
del juego y reabrió `SUSTITUIR`; RoleRun mostró satisfactoriamente la cantidad
reducida. Esto valida para la combinación probada la cadena
`saveItem RAM viva → BDSPInventoryReader → Adapter → carga background → selector`
y demuestra que no se estaba mostrando la cantidad stale del último guardado.
No se conserva una afirmación sobre qué MT concreta ni sus cifras porque la
observación del usuario no las especificó y el journal actual no registra las
cantidades individuales. Permanecen pendientes la escritura por save, el
movimiento/PP resultante, la herencia física del marcador y la migración efectiva
tras reiniciar.

Verificación automatizada: **523 passed** en 20,96 s con
`py -3.14 -m pytest -q`.

Alpha.75 sustituye el flujo diferido de movimientos BDSP por una transacción
runtime y elimina de su cabecera `DESCARTAR`/`GUARDAR CAMBIOS`. La estructura no
se ha supuesto: OpenDPR `5b0cb0c8...` demuestra que `PokemonParam` mantiene un
core almacenado de 328 bytes y 16 bytes calculados, que `CoreParam.SetWaza`
asigna el ID, reinicia PP Ups y usa `WazaTable.basePP`, y que
`PlayerWork.SaveData.saveItem` contiene los registros runtime de 12 bytes cuya
cantidad gobierna `PlayerWork.GetItem/SetItem`. Los lectores SP 1.3.0 ya
validados aportan la ruta exacta y las unidades mutables; no se añade ninguna
dirección nueva.

`BDSPLiveWriter` exige ausencia de batalla, dos capturas completas iguales,
identidad fuerte única, movimiento y cantidad esperados, punteros estables,
huella de sesión y coincidencia de bytes guest/host. Recalcula checksum y cifrado
PB8, escribe primero el core del Pokémon y después solo el `SaveItem` de la MT.
Verifica readback host, readback guest y una nueva lectura semántica de party y
mochila. Si falla cualquier paso, restaura en orden inverso todas las unidades
intentadas y vuelve a comprobarlas.

La UI aplica automáticamente cambios de rol, sustitución/eliminación de
movimientos y enseñanza de MT. Equipo↔PC, roles de caja, progreso y utilidades
de inventario siguen bloqueados y nunca caen al save. La implementación y sus
regresiones están completas, pero movimiento/PP/consumo permanecen
**pendientes de validación física en Ryujinx**; no se declaran cerrados hasta la
prueba manual indicada para alpha.75.

Verificación alpha.75: suite completa **533 passed** en 21,12 s con
`py -3.14 -m pytest -q`. El perfil Unity efectivo contiene 100 MT y los 512
movimientos activos disponen de PP base válidos. No se ejecutó una escritura
contra la partida real durante el desarrollo automatizado.

Verificación alpha.76: reader/writer/UI BDSP **65 passed** en 0,70 s; bloque
BDSP más consumidores del grid de roles **75 passed** en 1,36 s; suite completa
**542 passed** en 21,12 s con `py -3.14 -m pytest -q`. Una sonda posterior de
solo lectura contra el Ryujinx aún abierto devolvió `battle=None` a partir del
`TypeInfo=nullptr`; no se escribió ningún byte durante la investigación. La
enseñanza real de MT y la herencia del intercambio quedaron validadas
físicamente por el usuario el 2026-08-22 al responder que la prueba combinada
indicada funcionaba. El alcance registrado es: sustitución por MT fuera de
combate y cambio 1↔1 dentro del PC del juego sin séptima tarjeta y con el rol
heredado. No se extiende esa confirmación a escritores de cajas, utilidades,
progreso ni gasto posterior de PP, que no formaban parte de esa prueba.

Alpha.77 incorpora el progreso BDSP sin inferirlo del combate. OpenDPR
`5b0cb0c8...` demuestra que el propio juego calcula `BadgeCount` sumando los
ocho `PlayerWork.SaveData.systemFlags` 124–131; PKHeX 26.07.07 usa exactamente
los mismos flags. En el Ryujinx físico SP 1.3.0, el campo `PlayerWork+0x30`
resolvió dos veces el mismo `bool[1000]`, todos sus elementos fueron 0/1 y los
ocho testigos devolvieron `[1,1,0,0,0,0,0,0]`. El total 2 coincide con el save
y con su contador redundante `MYSTATUS.badge=2`.

`BDSPBadgeReader` publica ese valor como lane opcional, con doble lectura y
rechazo de raíz, longitud o contenido inválidos. El save no actúa como fallback.
La rama UI BDSP procesa el progreso antes de cualquier retorno por batalla,
party o herencia de rol y MEDALLAS queda gobernado automáticamente por RAM. Una
sonda integrada del adapter físico devolvió seis miembros, `badges=2`, fuente
`SystemFlags vivos · PlayerWork.SaveData` y diagnóstico OK. Evidencia:
`diagnostics/manual/bdsp_alpha77_badge_system_flags_PROOF_20260822.json`.
El usuario validó físicamente el 2026-08-22 la sincronización inicial: al abrir
alpha.77, RoleRun recuperó correctamente las dos medallas ya existentes. El
alcance exacto demostrado es la lectura integrada y el compromiso inicial 0→2;
la transición de una nueva medalla 2→3, su compromiso único y OBS siguen
pendientes de validación física.
Verificación alpha.77: **107 passed** en el bloque reader/Adapter/UI/Core y
**552 passed** en 21,06 s en la suite completa.

## Estado vigente de alpha.78

Alpha.78 abre únicamente el intercambio 1↔1 Equipo ↔ PC iniciado desde
RoleRun. La unidad se apoya en el contrato fuente de BDSP
`PokemonParam.DATASIZE=344`, `SerializedPokemonFull` y
`PokemonParam.CopyFrom()`, y en el grafo físico ya demostrado: la caja guarda
un PB8 completo de 344 bytes y la party lo divide en core de 328 y calc de 16.

El writer captura dos veces party y las 40×30 cajas, comprueba coordenadas e
identidades especie/PID/TID/SID, bloquea combate y reconexiones y vuelve a
validar la huella de Ryujinx inmediatamente antes de abrir escritura. Intercambia
party core, party calc y PB8 de caja con readback host/guest; después verifica
las dos identidades y el rol heredado. Cualquier fallo restaura y relee las tres
regiones. Añadir o retirar miembros sigue cerrado porque tamaño, compactación y
vacío runtime son contratos distintos aún no demostrados.

Estado: **IMPLEMENTADO Y CUBIERTO POR REGRESIONES; PENDIENTE DE VALIDACIÓN
FÍSICA EN SP 1.3.0 / RYUJINX**. Verificación: **60 passed** en el bloque BDSP
dirigido y **555 passed** en 21,15 s en la suite completa.

## Estado vigente de alpha.79

La primera prueba física de alpha.78 no alcanzó el writer. La RAM viva demostró
Slowpoke en la party y Pidgeotto en Caja 1:1, mientras el save sin actualizar
conservaba Pidgeotto en party y Slowpoke en Caja 1:1. El selector contextual
mostró Slowpoke porque `open_pc_selector()` consumía `_read_pc_data()` antes de
solicitar la matriz viva. Reader y adapter entregaban el valor correcto; la
primera divergencia estaba en la composición UI del modal.

Alpha.79 difiere la apertura del selector hasta terminar `read_pc()` en segundo
plano. La ocupación y coordenadas proceden exclusivamente de RAM; el save solo
puede enriquecer nombre/nivel por identidad fuerte. Un error ya no cae a la
copia antigua: bloquea la ventana con diagnóstico visible. El writer alpha.78
no cambia y continúa pendiente de su primera validación física real. Verificación
alpha.79: **62 passed** en el bloque BDSP dirigido y **557 passed** en 21,55 s
en la suite completa.

## Estado vigente de alpha.80

La validación física de alpha.79 reprodujo exactamente el mismo Slowpoke stale.
La corrección anterior había cubierto un selector vecino, no el botón probado:
las tarjetas de Equipo abren `_open_team_to_pc_swap_picker()`, cuyo título y
cabecera coinciden con la captura del usuario y que aún ejecutaba
`_read_pc_data(force=True)`. La traza no registró carga PC ni writer, confirmando
que el flujo live de alpha.79 nunca se ejecutó.

Alpha.80 conecta ese punto de entrada exacto al cargador de matriz viva antes de
construir cualquier tarjeta. Se añadieron eventos automáticos
`pc-selector-live-start`, `pc-selector-live-ready` y
`pc-selector-live-error`, además de una regresión que falla si el botón real
vuelve a consultar primero el save. El usuario validó físicamente esta frontera:
el modal mostró Pidgeotto, que era el ocupante RAM de Caja 1:1, en vez del
Slowpoke stale del save. Al confirmar, no obstante, Ryujinx mantuvo Slowpoke en
la party y la traza no registró ningún intento de escritura. Verificación
alpha.80: **63 passed** en el bloque BDSP dirigido y **558 passed** en 21,62 s
en la suite completa.

## Estado vigente de alpha.84

El selector de bajas común ya producía una operación completa con las dos
identidades fuertes, el slot vivo, el origen PC y un hueco de Cementerio. La
primera divergencia exclusiva de BDSP estaba inmediatamente después: la
compuerta UI no enviaba `replace-fainted` y el dispatch del writer la rechazaba.
No faltaba información que debiera aportar el usuario ni se necesitaba una
dirección RAM nueva.

Alpha.84 compone los contratos físicamente demostrados en alpha.81–83. Vacía el
origen PC con el PB8 canónico, conserva los 344 bytes exactos del debilitado en
Caja 4 y escribe al sustituto en el mismo objeto fijo core(328)+calc(16). El
conteo y el resto de la party no cambian. El rol heredado procede del debilitado
releído en RAM, no de una premisa de UI.

Antes de escribir exige dos capturas completas idénticas de party y cajas,
identidades/posiciones, HP=0 actual, rol único, Cementerio vacío, huella de
sesión y precondiciones guest/host. Después verifica semántica y bytes en los
seis slots de party y las 1.200 cajas. Un fallo restaura en orden inverso los
cuatro bloques y confirma host y guest. Las regresiones cubren éxito, fallo en
el cuarto write, miembro revivido y compuerta automática de UI.

Verificación: **121 passed** en el bloque BDSP y **572 passed** en 22,17 s en
la suite completa. Validación física posterior del usuario en SP 1.3.0 /
Ryujinx: el selector apareció tras el combate, el sustituto entró correctamente,
el debilitado pasó a la Caja 4 y se descontó exactamente una vida. Estado:
**implementado, probado automáticamente y validado físicamente para un KO
simple**. No se amplía esta validación a OBS, al marcador visto dentro del juego
ni a otros tipos de combate, que conservan comprobaciones propias.

Una segunda prueba física cubrió dos KO dentro del mismo combate. RoleRun
descontó exactamente dos vidas, mostró ambos selectores consecutivamente sin
necesidad de minimizar, incorporó los dos sustitutos y conservó los dos
debilitados en la Caja 4. Esto valida la cola múltiple de sustituciones y el
compromiso exactamente una vez para ese escenario. No demuestra reconexión,
OBS ni historial visual.

La inspección posterior de los marcadores dentro del juego confirmó que el
sustituto conserva exactamente el marcador correspondiente al rol mostrado en
RoleRun. La herencia de rol de `replace-fainted` queda así validada de extremo a
extremo. Esta evidencia no se extrapola a otros botones o flujos manuales de
cambio de rol.

## Estado vigente de alpha.83

La limitación restante de PC era retirar un miembro intermedio. OpenDPR
`5b0cb0c8...` demuestra que `PokeParty` dispone de `RemoveMember()` y una rutina
privada `scootOver()`, pero no conserva sus cuerpos; por tanto no demostraba qué
bytes, arrays u objetos debían mutar.

La captura física de solo lectura del 2026-08-22 retiró el slot 2 de una party
de seis. El objeto `PokeParty`, su array, los seis `PokemonParam` y todas las
direcciones core/calc permanecieron estables. Los PB8 completos coincidieron
byte a byte en la cadena 3→2, 4→3, 5→4 y 6→5; el antiguo slot 2 apareció exacto
en Caja 1:3; el vacío PC canónico apareció exacto en el slot 6; y
`m_memberCount` pasó 6→5. Solo cambió esa posición de caja. Evidencia:
`diagnostics/manual/bdsp_sp130_party_size_transition_AUTO_20260822_224902.json`,
SHA-256 `B65F6B7812314955CD090DB2AA6B68748402DDF17D4ADEA858D2A896254AEFCE`.

Alpha.83 reproduce exactamente ese flujo sobre los objetos fijos. La operación
completa queda cerrada por doble captura, correspondencia miembro/almacenamiento,
testigos guest/host, contador en último lugar, readback de los seis PB8 y de las
1.200 cajas, y rollback inverso verificado. Una regresión reproduce los doce
bloques del caso físico y otra provoca el fallo final para comprobar que party,
PC y contador vuelven íntegros.

Verificación: **117 passed** en el bloque BDSP y **568 passed** en 21,62 s en
la suite completa. Validación física posterior del usuario en SP 1.3.0 /
Ryujinx: la retirada intermedia iniciada desde RoleRun se reflejó correctamente
en el juego y en la aplicación. Estado: **causa y contrato demostrados; writer
probado automáticamente y validado físicamente**.

## Estado vigente de alpha.82

El bloqueo de cambios de tamaño exigía demostrar la representación runtime real.
La captura 6→5 del 2026-08-22 muestra que el `PokeParty`, su array y sus seis
direcciones de almacenamiento permanecen estables: Pidgeotto desaparece solo
del sexto objeto, ese objeto recibe el PB8 vacío canónico, Caja 1:3 recibe los
mismos 344 bytes y `m_memberCount` cambia 6→5. La captura inversa 5→6 reutiliza
exactamente las mismas direcciones y revierte esos tres contenidos y el contador.
Los cinco miembros restantes y los otros 1.199 slots de caja no cambian.

La evidencia queda preservada en
`diagnostics/manual/bdsp_sp130_party_size_transition_AUTO_20260822_222122.json`
(SHA-256 `718373E0D7061BECBB804EB1DC84E3CF765D830DD258BD47DA03BEB4F070F248`)
y `diagnostics/manual/bdsp_sp130_party_size_transition_AUTO_20260822_222322.json`
(SHA-256 `C2AEF1C40D2D4A8C3F8BE94FCABC13A5B79EEC89A82F3B1D6DA5380B58BF0BFE`).

Alpha.82 implementa únicamente ese contrato demostrado: enviar el último miembro
al primer vacío PC vivo y recuperar un miembro como nuevo último slot. El writer
revalida party/cajas completas, identidad, direcciones, vacío canónico y sesión;
escribe las unidades mínimas y el contador al final; hace readback guest/host y
semántico; protege los miembros y 1.199 slots vecinos; y revierte los cuatro
bloques con verificación si algo falla. Retirar un miembro intermedio sigue
bloqueado porque el algoritmo de compactación no está demostrado.

Las regresiones cubren éxito 6→5, éxito 5→6 con primer rol libre, rollback al
fallar el contador y rechazo previo de un miembro no final. Verificación:
**116 passed** en el bloque BDSP dirigido y **567 passed** en 21,00 s en la
suite completa. En ese corte quedó implementado y probado automáticamente; las
dos capturas probaban el comportamiento nativo, pero aún no sustituían la prueba
del writer alpha.82 que se completó después.

El usuario validó después el writer alpha.82 desde RoleRun en SP 1.3.0 /
Ryujinx: enviar el sexto miembro al PC y recuperarlo como sexto miembro produjo
el resultado correcto tanto en RoleRun como dentro del juego. El ciclo de cola
5↔6 queda **VALIDADO FÍSICAMENTE**. No demuestra la compactación al retirar un
miembro intermedio, que permanece bloqueada.

## Estado vigente de alpha.81

La primera divergencia del fallo de confirmación estaba en la compuerta común
de aplicación inmediata, antes del writer. `_prepare_pc_team_change()` creaba el
swap 1↔1, pero la rama BDSP de `_request_oras_live_auto_apply()` solo seleccionaba
roles, movimientos y MT; descartaba el `PendingTeamChange` y por eso no podía
existir ningún evento de escritura. La capa posterior y `BDSPLiveWriter` ya
declaraban y probaban ese mismo `swap-party-box`, lo que demuestra que no faltaba
una dirección ni una operación RAM nueva.

Alpha.81 abre la compuerta exclusivamente para el swap 1↔1 ya demostrado. Los
cambios de tamaño de party permanecen bloqueados. La regresión falló antes del
arreglo con cero IDs programados y pasa después; el bloque BDSP completo queda en
**64 passed** y la suite completa en **559 passed** en 21,44 s. El writer conserva
sus precondiciones, doble captura, readback semántico y rollback.

El usuario validó físicamente alpha.81 en Perla Reluciente 1.3.0 / Ryujinx el
2026-08-22: tras elegir Pidgeotto desde `CAMBIAR CON PC`, el intercambio se
reflejó correctamente dentro del juego. Queda cerrado el recorrido base
RoleRun → selector PC live → writer 1↔1 → readback → party publicada para
esta combinación. Esta validación no se extiende a entradas/salidas que cambian
el tamaño de la party, que continúan bloqueadas.

## Estado vigente de alpha.65

El usuario derrotó físicamente a Kaudan/Hala con alpha.63 abierta. UltraSol
entregó Lizastal Z, pero RoleRun mantuvo `medallas=0`. La lectura RPC posterior
demuestra un bolsillo Z-Crystals estable y válido con Normastal Z `807` y
Lizastal Z `813`; el contador puro devuelve 1. El `main` todavía contiene solo
`807` y devuelve 0.

La primera divergencia está en `USUMLiveWriter.read_kahuna_badges_for_game()`.
La ruta ItemsOffset demostraba la mochila y publicaba su prueba en
`_tm_guest_inventory_anchor`, pero el siguiente bloque consultaba por error
`_utility_block_cache["items"]`, reservada a utilidades de escritura. Al estar
vacía, se descartaba el 1 live y se devolvía el 0 del save antes de Adapter/UI.

Alpha.65 consume la ancla correcta tras demostrarla y la relee de forma estable
en ticks posteriores. Una sonda integrada de solo lectura sobre el proceso
físico actual devolvió 1 dos veces con procedencia
`Z-Crystals vivos · referencia ItemsOffset revalidada`. No se añadió ninguna
dirección ni escritura.

El usuario validó físicamente alpha.65 en UltraSol/Azahar el 2026-08-22: al
abrir la versión corregida con Lizastal Z ya presente en la mochila viva,
RoleRun detectó la medalla y mostró el incremento 0→1. Queda así cerrada la
recuperación del primer Kahuna para esta combinación. Sigue pendiente comprobar
los incrementos sucesivos 1→2, 2→3 y 3→4 al derrotar a los demás Kahunas.

La evidencia canónica está en
`diagnostics/manual/usum_alpha63_hala_badge_missing_FAIL_20260822_133454_*`.

Baseline alpha.65: **67 passed** en las fronteras progreso/adapter/Core y
**448 passed** en 20,37 s para la suite completa con `python -m pytest -q`.
La sonda física fue exclusivamente de lectura; no se escribió RAM ni el save.

## Historial de alpha.64

Alpha.63 quedó físicamente validada por el usuario: dos KO se registraron y los
dos selectores se abrieron consecutivamente sin minimizar RoleRun. La detección
de muertes, la salida por convergencia y la cola de sustituciones quedan cerradas
para esa reproducción de UltraSol/Azahar. No se cambió después su lógica RAM.

La auditoría transversal de alpha.64 está detallada en
`docs/3DS_BACKEND_AUDIT.md`. Ha corregido tres primeras divergencias demostradas:

- el consumidor común podía aceptar que un fallback del `main` redujera un
  contador de progreso live más nuevo;
- los writers de utilidades SM/USUM podían omitir de la transacción el write
  cuyo readback fallaba y afirmar una restauración no verificada;
- el parser de cajas USUM derivaba nivel/formas con `personal_sm` pese a que el
  PKHeX distribuido contiene `personal_uu` distinto.

USUM registra ahora automáticamente cada cambio de Kahunas o de procedencia en
`Documentos\RoleRun Manager\Logs\usum_kahuna_progress_trace_latest.jsonl`.
No contiene datos de Pokémon ni de mochila. La lectura del primer Kahuna quedó
validada físicamente en alpha.65; resta validar la progresión sucesiva de los
tres Kahunas restantes.

Baseline alpha.64: batería focal de las fronteras auditadas **123 passed** y
suite completa **446 passed** en 20,46 s con `python -m pytest -q` sobre Windows
en el entorno Python aislado. No se ejecutaron escrituras contra una partida ni
contra la RAM real durante estas pruebas.

## Historial y validación de alpha.63

### Validación física de alpha.62

El usuario validó físicamente en UltraSol que alpha.62 detecta dos KO durante
el combate y termina el episodio cuando ambos convergen a PartyData. La traza
conservada contiene `battle-idle-evidence` para las dos identidades y
`battle-end` con motivo `observed-ko-converged-to-party`. Las dos muertes se
comprometieron inmediatamente y quedaron listas para sustitución.

La evidencia canónica de esa ejecución se conserva con el prefijo
`diagnostics/manual/usum_alpha62_two_pending_second_picker_delayed_PROOF_20260822_131803`.
La traza tiene SHA-256
`0A6B8E37868F5154F957EBEB3B2ADB65F3AB153EEBCCA286EBFB61A888F249B1`;
también se preservaron `config.json`, `history.json` y ambos estados OBS.

### Nuevo fallo de UI demostrado

En la misma ejecución, Porygon y Registeel quedaron como `pending_faints` con
`battle_ended=true`. El primer prompt se persistió a las 13:14:01. Tras cerrarlo,
el segundo no se persistió hasta las 13:14:52, inmediatamente después de
minimizar y restaurar RoleRun.

El código explica exactamente esa diferencia: `close_picker()` destruía el
primer modal sin volver a programar la cola; `_on_main_map()` sí programaba la
revisión. Por eso restaurar la ventana era el disparador accidental. Reader,
snapshot, LivePartyWatch y compromiso de muerte habían completado correctamente
su trabajo antes de esta primera divergencia.

### Corrección alpha.63

- Cerrar un selector vuelve a programar la cola y permite abrir el siguiente
  pendiente sin remapear la ventana principal.
- Si la sustitución del selector anterior sigue aplicándose, la revisión se
  reintenta en vez de perderse.
- Las compuertas existentes mantienen como máximo un modal y una escritura a
  la vez. No se modifica ningún backend ni la lógica de detección de muertes.
- Dos regresiones fallaron antes de la corrección y pasan después.

### Validación alpha.63

- Regresiones causales: **2 passed**.
- Selector, barra, RunService y ciclo USUM alpha.59–62: **37 passed**.
- Suite completa: **428 passed** en 19,95 s con `python -m pytest -q`
  (Windows, Python 3.13.14, pytest 9.1.1, entorno aislado).
- Validación física completada por el usuario en UltraSol el 2026-08-22: tras
  dos KO, los dos selectores aparecieron consecutivamente sin minimizar ni
  restaurar RoleRun. El flujo reader→muerte→final de combate→cola de selectores
  queda físicamente validado para esta reproducción.
- La detección automática del primer Kahuna quedó validada posteriormente en
  alpha.65; los otros tres incrementos siguen pendientes de validación física.

## Historial de alpha.62

### Validación física heredada de alpha.61

El usuario validó físicamente el objetivo principal de alpha.61 en UltraSol,
Title ID `00040000001B5000`, proceso RPC `momiji` 11 y Azahar 263745c:

- Porygon/party slot 4 llegó a 0 en battle row 1 y RoleRun registró la muerte
  inmediatamente a las 03:53:08;
- Eevee/party slot 2 llegó a 0 en battle row 2 y RoleRun registró la muerte
  inmediatamente a las 03:53:21;
- el historial demuestra `vidas` 6→5→4 y la configuración conserva ambas
  identidades como `pending_faints` con `battle_seen=true`.

Queda por tanto validado físicamente el mapeo PK7 de battle rows y el compromiso
inmediato de ambas muertes. No queda validado el flujo completo de sustitución:
al finalizar el combate RoleRun no abrió el selector del PC.

La traza de control de este nuevo fallo se conserva en
`diagnostics/manual/usum_alpha61_two_kos_picker_missing_FAIL_20260822_035426.jsonl`
(219.579 bytes, SHA-256
`29625A347B403874C120095B3B7E7CDAFF2E0C5ABE8550912F01BF3D0A757818`).
Se preservaron con SHA verificado también `history.json`, `config.json`, los dos
estados OBS y el diagnóstico PC de la ejecución.

### Primera divergencia del selector ausente

La traza contiene 64 `battle-sample`, cuatro cambios de flags, un `battle-start`
y un `battle-suspend`, pero ningún `battle-end`. A las 03:53:28 el reader observa
`0x00040005/6` y lo mantiene como `state="battle"`. Por ello Adapter y UI no
reciben `none`; las dos pendientes terminan con `battle_ended=false` y
`battle_exit_samples=0`. La primera divergencia está de nuevo en
`USUMLiveReader`, antes de la compuerta de RunService y antes del selector.

Sin reiniciar la partida, Azahar ni RoleRun, el usuario confirmó que el combate
había terminado. Una lectura RPC de solo lectura posterior conserva los mismos
flags `0x00040005/6`, pero PartyData validada publica Eevee/slot 2 y
Porygon/slot 4 a 0 HP. La prueba completa se conserva en
`diagnostics/manual/usum_alpha61_postbattle_idle_party_PROOF_20260822_040601.json`.
En la captura alpha.60 del estado transitorio, esas mismas filas de batalla ya
estaban a 0 mientras PartyData aún mantenía Eevee y Porygon a 19. Esto demuestra
que el mismo par de flags corresponde tanto a sustitución forzada como a
overworld; el dato que los separa es la convergencia de los KO a PartyData.

La fuente técnica específica
[USUMCheatMenu `helpers.c`](https://github.com/pablogormi/USUMCheatMenu/blob/09c4c1b98f3cd9b88c4a537c5e22c249c72edb0e/Sources/helpers/helpers.c#L65-L69)
solo considera batalla cuando `0x30000158 == 0x00040001`. No documenta
`0x00040000/1` como paso terminal obligatorio. Alpha.60 había generalizado una
observación física de control que esta ejecución refuta.

### Corrección alpha.62

- El reader registra por proceso únicamente transiciones Displayed HP `>0→0`
  de slots cuya fila e identidad PK7 ya están validadas.
- En `0x00040005/6` sigue publicando batalla suspendida mientras esos KO no
  aparezcan a 0 en PartyData. Cuando todos convergen por la misma identidad,
  publica `none`, limpia el episodio y permite las dos muestras de salida que ya
  exige la UI.
- Un Pokémon que ya estaba a 0 al crear el baseline no cuenta como transición y
  no puede cerrar falsamente una sustitución forzada.
- La traza registra `battle-idle-evidence` y el motivo de `battle-end`.
- No se añaden direcciones RAM ni se modifica UI, RunService, LivePartyWatch,
  PC, writers, Sol/Luna u otros backends.

### Validación alpha.62

- La regresión causal reproduce el fallo de alpha.61 y falla antes del arreglo:
  **1 failed, 1 passed**.
- Regresión alpha.62 y ciclo/identidad alpha.60–61: **8 passed**.
- Flujo reader→RunService→selector/barra: **38 passed**.
- Batería USUM completa: **45 passed**.
- Suite completa: **426 passed** en 19,90 s con `python -m pytest -q`
  (Windows, Python 3.13.14, pytest 9.1.1, entorno aislado).
- En la prueba física posterior el reader sí terminó la batalla y preparó ambos
  selectores; esa validación reveló el fallo de cola de UI corregido en alpha.63.

## Historial de alpha.61 (detección de KO validada; selector postcombate superado por alpha.62)

### Nueva reproducción física y primera divergencia

- Traza preservada:
  `diagnostics/manual/usum_alpha60_restart_changed_active_FAIL_20260822_033047.jsonl`,
  222.053 bytes, SHA-256
  `B0A0CC9EC8D4E82FDA7A1FFAF489579652AA63BB22430E8F22261A4575AFC2EA`.
- Se preservaron además el historial, configuración y estado OBS de la misma
  ejecución. `vidas` permaneció en 6 y no apareció ningún `pending_faint`: la
  muerte no cruzó nunca la frontera reader→snapshot.
- UltraSol, Title ID `00040000001B5000`, proceso RPC `momiji` 11 y Azahar
  263745c. RoleRun se había reiniciado; Azahar y la partida seguían abiertos.

La batalla empieza con party
`[Registeel 18/18, Eevee 19/19, Kangaskhan 149/149, Porygon 19/19,
Tsareena 101/101, Carnivine 17/17]`. La tabla HP empieza en orden
`[19,19,149,18,101,17]`. Alpha.60 puede demostrar los slots 1, 3, 5 y 6,
pero no distinguir las filas 1 y 2: Eevee y Porygon comparten tanto Max como
HP actual. La fila 1 pasa a cero en la secuencia 8 y la fila 2 en la secuencia
73; ambas continúan sin identidad, PartyData permanece retrasado y
`LivePartyWatch` no recibe ninguna transición `>0→0`.

La salida `0x00040005/6` de las 03:29:51 sí queda registrada como
`battle-suspend`, no como `battle-end`. Por tanto el arreglo de ciclo de vida de
alpha.60 funcionó en esta ejecución; el fallo restante estaba exclusivamente en
la identidad de filas dentro de `USUMLiveReader`.

### Causa raíz finalmente demostrada

Max/Displayed/Actual HP describen salud, no identidad. El matching alpha.60 era
seguro al rechazar la ambigüedad, pero incompleto: cuando dos miembros empezaban
con los mismos valores no existía ninguna observación futura capaz de reconstruir
qué cero pertenecía a cuál sin otro campo de identidad.

La fuente técnica
[USUMCheatMenu `pokemon.h`](https://github.com/pablogormi/USUMCheatMenu/blob/master/Sources/pokeutil/pokemon.h#L61-L67)
declara `0x3254EE60 + 0x104*N` como `PARTY ON BATTLE INITIAL DATA`. Una sonda RPC
acotada y de solo lectura sobre el mismo proceso físico descifró y validó por
sanity/checksum los seis PK7 stored:

| Battle row | PK7 (especie/PID) | Party slot | Max HP de la fila |
|---:|---|---:|---:|
| 1 | Porygon / `BC0C2B25` | 4 | 19 |
| 2 | Eevee / `DB76FD4F` | 2 | 19 |
| 3 | Kangaskhan / `8C3FC66A` | 3 | 149 |
| 4 | Registeel / `8D65562F` | 1 | 18 |
| 5 | Tsareena / `080D79E3` | 5 | 101 |
| 6 | Carnivine / `8D826F23` | 6 | 17 |

La prueba derivada se conserva en
`diagnostics/manual/usum_alpha60_battle_row_identity_PROOF_20260822_034449.json`.
La correspondencia `4,2,3,1,5,6` coincide exactamente con las filas HP físicas.
Esta es la primera evidencia que desambigua directamente Porygon/Eevee y demuestra
la causa sin usar el síntoma como premisa.

### Corrección alpha.61

- Cada fila se enlaza ahora por `(species, PID, TID, SID)` obtenido de un PK7
  checksum-válido mediante doble lectura estable. Max y ambos HP siguen siendo
  precondiciones obligatorias de la fila.
- Una identidad ausente o duplicada no se adivina. Los Max únicos pueden seguir
  publicando sus filas demostradas; las ambiguas permanecen cerradas.
- El resolvedor host de una base HP desplazada valida el multiconjunto completo
  de Max HP y ya no exige el orden de party falsado por las capturas físicas.
- El mapeo se invalida en suspensión/reentrada/terminal. Se conserva íntegro el
  ciclo activo→suspendido→terminal de alpha.60.
- No se modifica SM, UI, `LivePartyWatch`, RunService, PC, writers, movimientos
  ni progresión.

### Validación y cierre

- Las dos regresiones nuevas fallaban con alpha.60 y pasan con alpha.61.
- Regresiones de batalla alpha.57–61: **13 passed**.
- Batería USUM completa: **44 passed**.
- Suite completa: **424 passed** en 19,86 s con `python -m pytest -q`
  (Windows, Python 3.13.14, pytest 9.1.1, entorno aislado).
- La reproducción física posterior sí validó el mapeo y compromiso inmediato de
  los dos KO de alpha.61, pero descubrió que el selector postcombate no se abría.
  Ese hallazgo da origen a alpha.62 y no altera esta baseline histórica.

## Historial de alpha.60 (conservado; invalidado parcialmente por la reproducción posterior)

Alpha.60 introdujo el ciclo activo/suspendido/terminal y un matching por
Max/Displayed/Actual. La reproducción posterior confirmó físicamente el ciclo,
pero demostró que el matching no podía resolver dos miembros a 19/19. Su baseline
histórica fue **422 passed**; no debe interpretarse como cierre físico del KO.

## Historial de alpha.59 (conservado; superado por la reproducción alpha.59 posterior)

- Baseline automatizada: **418 passed** en 20,31 s con
  `python -m pytest -q` (Windows, 2026-08-22).
- No hay ningún test fallido ni escritura de tests en los Logs persistentes del
  usuario.

### Hechos demostrados

- Azahar inició el proceso usado por SUCCESS a las 02:05:27. El módulo
  `Battle` del combate preservado cargó a los 66,525 s y descargó a los
  86,267 s. La traza publica los KOs de Registeel y Eevee a las 02:06:38 y
  02:06:50; el historial los compromete en esos mismos segundos.
- Un segundo combate del mismo proceso cargó a los 261,888 s. El historial
  vuelve a comprometer ambos KOs durante el combate, a las 02:09:53 y 02:10:04,
  antes de la descarga de `Battle` a los 279,306 s.
- El juego se reinició a los 323,283 s. En el siguiente combate, `Battle` estuvo
  cargado entre 334,903 s y 400,996 s; ambos KOs se comprometieron juntos a las
  02:12:09, ya fuera del módulo de batalla. Esto demuestra que Adapter, UI,
  `LivePartyWatch` y el compromiso postcombate seguían operativos.
- La copia llamada FAIL fue creada a las 02:12:44, después de otro reinicio a
  los 432,360 s y durante la carga de `TitleMenu` (437,841 s). Sus seis filas
  incompatibles demuestran que `0x30000158 == 0x00040001` también puede coexistir
  con memoria que no es la party de batalla; no contiene los ticks de los dos
  KOs físicos.
- La fuente pública de las direcciones es un cheat con direcciones absolutas; no
  aporta un puntero ni una prueba de estabilidad entre ciclos de proceso.

### Causa raíz demostrada

Alpha.56–58 convertía una base de heap estática y un flag insuficiente en un
localizador permanente. La validación por slot impedía publicar basura, pero no
podía recuperar la tabla real cuando esa candidata dejaba de describir la party;
el resultado era `validated_slots=[]`, `health_game=None` y ausencia total de
muestras para `LivePartyWatch`. Por eso podían fallar el primero y el segundo KO
por la misma divergencia y recuperarse ambos al volver a PartyData postcombate.

### Corrección implementada

Alpha.59 conserva la base publicada solo como candidata rápida. Cuando todas sus
filas fallan, `USUMLiveReader` calibra host↔guest con los seis PK7 exactos del
mismo tick, exige el vector completo de Max HP/stride, HP acompañantes en rango,
una sola candidata y dos readbacks RPC idénticos con flags antes/después. La base
se revalida cada tick y se descarta fuera de combate. Una búsqueda ambigua o sin
prueba continúa sin publicar HP.

La traza alpha.59 ya no se abre con `w` en cada reentrada. Registra episodios,
flag primario, flag de fase, base/fuente, prueba del resolver y conserva además
un archivo inmutable en `Logs\USUM-Battle-Traces`.

### Estado de cierre

La corrección automatizada y la causa técnica están cubiertas por regresiones.
La capacidad realtime de alpha.59 **sigue pendiente de validación física** y no
se declarará cerrada hasta observar un KO dentro del emulador tras reiniciar el
proceso del juego.

## Historial y baseline de alpha.58 (conservado)

## Checkpoint Git y baseline automatizada

- Snapshot funcional alpha.58: `369e53f983a21a56e5b835a109eeeab3db91a7d1`.
- Reglas permanentes: `b52634d67dd01b80187a281f12f4028d5251ff5a`.
- Entre ambos commits solo se añadió `AGENTS.md`; los archivos funcionales son
  idénticos.
- Comando de suite completa: `python -m pytest -q` desde la raíz.
- Baseline ejecutada en Windows, Python 3.13.14 y pytest 9.1.1: **413 passed,
  1 failed, 414 collected** en 20,35 s.
- Fallo preexistente y dependiente de Windows:
  `tests/test_faint_picker_floating.py::test_mapping_main_window_hides_a_still_visible_floating_bar_before_picker`.
  El doble `SimpleNamespace` no define `_foreground_belongs_to_this_process()`,
  método que `_on_main_map()` consulta solo en la rama `os.name == "nt"`.

Este párrafo describía exclusivamente la baseline alpha.58: entonces la suite
no era hermética y podía reemplazar archivos `*_latest` del usuario. La
infraestructura de tests posterior aisló todos los `LOG_DIR` mediante directorios
temporales; no debe interpretarse como una limitación vigente.

## Arquitectura y backends activos

La UI y raíz de composición siguen en `app/ui.py`. El motor común de partidas es
`engine/RoleRun.SaveEngine` mediante `app/save_engine_client.py`. El Core común
está en `app/realtime/`; offsets y validadores permanecen en cada backend.

| Juego | Save/PKHeX | Tiempo real actualmente registrado |
|---|---|---|
| DP, Pt, HGSS, BW, B2W2 | Sí | No |
| BDSP | Sí; proveedor Unity para MT randomizadas y PP base | Ryujinx HostMapped; party/PC/inventario/HP live; writer transaccional de roles y movimientos/MT de party |
| ORAS | Sí | Azahar RPC |
| X/Y | Sí | Azahar RPC |
| Sol/Luna | Sí | Azahar RPC |
| UltraSol/UltraLuna | Sí | Azahar RPC |

Los adaptadores registrados en `app/ui.py` son ORAS, XY, SM, USUM y BDSP. Los
bridges activos son Azahar RPC y Ryujinx HostMapped, este último para Perla
Reluciente 1.3.0. X/Y tuvo en su día un bridge Citra GDB/broker alternativo,
pero nunca llegó a habilitarse en la práctica y se retiró el 07-09-2026. La
frontera Ryujinx GDB se conserva solo para diagnóstico. No existe bridge RAM
para DS.

Estado funcional relevante:

- ORAS: party, roles, movimientos, PC, inventario/MT, progreso y muertes live.
- X/Y: party, roles, movimientos, PC, inventario/MT, batalla y progreso live;
  las operaciones iniciadas por RoleRun que cambian el tamaño de la party siguen
  protegidas hasta validación específica.
- SM: party, roles, movimientos, PC, inventario/MT, Kahunas y muertes live están
  implementados y sujetos a sus validadores Gen 7.
- USUM: paridad implementada para party, roles, movimientos, PC, inventario/MT,
  Kahunas y muertes. El carril de KO y la cola de selectores están validados
  físicamente en alpha.63; solo Kahunas sigue pendiente de validación física.

Las etiquetas visuales `stable`/`experimental` no sustituyen una validación
física de la combinación exacta juego/revisión/backend.

## Apéndice histórico: investigación alpha.58 del primer KO de USUM

> Esta sección conserva el estado anterior a las capturas SUCCESS/FAIL y a la
> reproducción alpha.59 de 03:02–03:05. Sus carencias de evidencia y pasos
> pendientes ya no describen el estado vigente; la conclusión actual está al
> principio de este documento.

### Comportamiento físico comunicado

1. RoleRun está conectado y comienza un combate.
2. El primer Pokémon enviado al campo cae a 0 HP.
3. RoleRun no descuenta vida ni retira su icono en ese momento.
4. Entra un segundo Pokémon y también cae a 0 HP.
5. La segunda muerte se registra inmediatamente durante el combate.
6. La primera solo se registra al finalizar el combate.

Alpha.58 es exclusivamente diagnóstica y no cambia el criterio de muerte de
alpha.57.

### Estado de la evidencia física

La ruta esperada es:

`C:\Users\PC\Documents\RoleRun Manager\Logs\usum_battle_health_trace_latest.jsonl`

El archivo presente el 2026-08-22 a las 01:43:18 no contiene la batalla física.
Su SHA-256 es
`8398A447E8D6C327CCF770F47B530DBD08D446BD81D505BB3E13A6140D4BB78B` y
solo contiene `battle-start` más una muestra separada por 1 ms:

| Fila | Party Max | Battle Max | Displayed | Actual | Candidatos por Max | Válida |
|---:|---:|---:|---:|---:|---|---|
| 1 | 60 | 61 | 0 | 0 | ninguno | no |
| 2 | 80 | 81 | 37 | 35 | ninguno | no |

La party son dos Pikachu sintéticos con HP 50/60 y 40/80. Los valores coinciden
exactamente con
`test_alpha56_battle_lane_still_rejects_when_no_slot_is_proven` en
`tests/test_usum_alpha43_foundation.py`. Esa prueba crea `USUMLiveReader` sin
redirigir `LOG_DIR`; `_battle_trace_start()` abre el archivo real con modo `w`.
La prueba alpha.58 siguiente sí usa `tmp_path`, pero no protege la anterior.
La hora coincide con la ejecución de la suite completa y con otros diagnósticos
sintéticos escritos en `Logs`.

No se encontró otra copia en Documentos, OneDrive, File History, alternate data
streams ni shadow copies disponibles. El historial de la run confirma compromisos
automáticos de muertes, pero no conserva battle rows, Max/Displayed/Actual HP ni
snapshots por tick. Por ello no permite reconstruir el orden causal.

**Conclusión vigente:** la causa raíz del bug físico no está demostrada. No es
válido identificar los dos Pikachu de la traza actual con los dos Pokémon de la
partida ni usar esa muestra sintética para elegir una corrección.

### Flujo demostrado por código

#### 1. RAM → `USUMLiveReader`

`app/usum_live.py::read_battle_probe()`:

- lee el flag `0x30000158` antes y después de los HP y exige `0x00040001`;
- lee Max HP desde `0x30002776`, Displayed HP desde `0x30002778` y Actual HP
  desde `0x30009760`, con stride `0x330`;
- itera las filas en el mismo índice que la party PK7 filtrada;
- una fila es válida solo si Battle Max coincide con Party Max del mismo índice
  y Displayed/Actual están en rango;
- para una fila válida, `health_game.current_hp` recibe **Displayed HP**;
- Actual HP solo viaja en `liveBattleActualHp` y en la traza;
- para una fila rechazada, el clon conserva el HP de party, que puede ir retrasado
  durante el combate;
- si no queda ninguna fila válida, devuelve `health_game=None`.

La traza alpha.58 registra por tick party, filas, candidatos por Max, slots
validados y motivos de rechazo, pero no registra directamente la llamada de UI
ni el resultado de `detect_fainted_transitions()`.

#### 2. Reader → adapter → snapshot

`app/realtime/usum_adapter.py::capture_monitor()` captura primero la party estable
y después llama a `read_battle_probe(raw.game)`. Construye
`RealTimeSnapshot.battle` con estado, `health_game` y pares de HP. Una sonda
rechazada conserva `state="battle"`, pero no entrega `health_game`.

`capture_full()` hace la misma lectura para establecer el baseline inicial de
alpha.57. Arrancar dentro de combate establece baseline sin cobrar muertes
retrospectivas; arrancar fuera deja estado `none` y party overworld como baseline.

#### 3. Snapshot → monitor de salud de UI

En `app/ui.py::_finish_oras_live_reconciliation()` para SM/USUM:

- con `probe_state == "battle"` y `probe_health` válido, compara contra el
  snapshot de salud anterior;
- si el estado anterior era `unknown`, la muestra se usa solo como baseline;
- con `probe_health=None`, no entrega una muestra nueva al detector;
- con `probe_state == "none"`, procesa `snapshot.game` como fallback overworld;
- no sustituye una sonda de combate inválida por HP overworld mientras sabe que
  el combate sigue activo.

#### 4. UI → LivePartyWatch

`app/ui.py::_process_oras_health_snapshot()` actualiza
`_oras_live_health_snapshot` y llama a
`app/live_party_watch.py::detect_fainted_transitions(before, after)`.

El detector empareja por `(species_id, PID, TID, SID)` y solo produce evento si
el mismo Pokémon pasa de `old_hp > 0` a `new_hp == 0`. No produce transición si:

- no existe snapshot anterior;
- el Pokémon no aparece con la misma identidad;
- el snapshot anterior ya tenía HP 0;
- la muestra nueva conserva HP positivo;
- la UI no llamó al detector porque `health_game` era `None`.

Para Gen 7, `source="battle-visible"` se compromete en el mismo tick lógico; el
retraso de un segundo solo se usa para `source="battle"` de ORAS.

#### 5. LivePartyWatch → compromiso

`RunProjectService.register_detected_faint()` exige identidad estable, evita una
pendiente activa duplicada, resta una vida, persiste `pending_faints` y añade
`pokemon_fainted_auto` al historial. La UI actualiza después layout, iconos y OBS.
El selector de sustitución continúa cerrado hasta confirmar salida del combate;
esto no retrasa el descuento de vida ni la retirada visual una vez registrada la
muerte.

### Primera divergencia

Con la evidencia disponible no puede localizarse la primera divergencia entre
la muerte que falla y la que funciona. El dato decisivo debía aparecer en el
primer tick físico donde cada Pokémon alcanzó Actual o Displayed HP 0:

- battle row y Max HP;
- party index/slot y Max HP;
- candidatos y slots validados/rechazados;
- `health_game` reconstruible y baseline anterior.

Sin esos ticks no se puede decidir si la primera diferencia ocurrió en el valor
RAM, el mapeo fila↔party, la validación Max HP, la elección Displayed frente a
Actual, el baseline de UI o una condición posterior. No se propone solución hasta
capturar de nuevo esa evidencia.

## Evidencia que entonces era necesaria (ya obtenida)

Reproducir una única batalla con alpha.58 y, antes de ejecutar tests o comenzar
otro combate, copiar `usum_battle_health_trace_latest.jsonl` a un nombre único
fuera de `Documentos\RoleRun Manager\Logs`. La captura debe comenzar con RoleRun
ya conectado fuera de combate y conservar desde `battle-start` hasta `battle-end`.

La siguiente investigación debe comparar tick por tick ambos Pokémon y registrar
para cada transición:

1. primera secuencia con Actual HP 0;
2. primera secuencia con Displayed HP 0;
3. Max HP y candidatos de la battle row;
4. party index, slot, HP y Max HP testigo;
5. pertenencia a `validated_slots` o motivo de rechazo;
6. `health_game` que se deriva de esa muestra;
7. baseline anterior de UI;
8. resultado esperado de `detect_fainted_transitions()`;
9. primer `pokemon_fainted_auto` correspondiente en el historial.

## USUM alpha.125 — EV automáticos en entradas desde PC

La inspección extremo a extremo demostró que `_prepare_pc_team_change()` ya
incluía en `incoming_snapshot` la distribución EV del rol para USUM, pero
`USUMLiveWriter._apply_team_swap()` no la entregaba a
`_party_payload_from_box()`. El PK7 entrante heredaba el marcador correcto y
conservaba sus EV antiguos: esa era la primera divergencia.

Alpha.125 valida el rol testigo del snapshot, aplica sus seis EV antes de
refrescar el checksum y construye la `PartyData` desde ese mismo PK7. Stored,
estadísticas finales, rol, movimientos, PC y PartyCount continúan dentro de la
transacción ya demostrada, con readback y rollback existentes. Las regresiones
cubren tanto añadir a un hueco libre como sustituir una casilla ocupada. La
validación física en UltraSol/Azahar del 24-08-2026 confirmó que la entrada desde
PC aplicó correctamente los EV y estadísticas finales del rol.

## USUM alpha.127 — selector visible y arrastre a casilla PC exacta

La reproducción visual mostró dos divergencias independientes. En el selector
de sustitución, el botón final pertenecía al cuerpo fijo de la ficha y quedaba
recortado al crecer stats/IV/EV bajo la altura reducida por los avisos. Ahora las
acciones son un pie reservado del inspector. La captura sintética
`diagnostics/manual/alpha127_faint_replacement_footer_preview.png`, generada a
1920×1080 con el modo de baja activo, muestra el botón completo.

En Equipo→PC, cada objetivo de arrastre ya declaraba `box` y `slot`, pero
`_team_pc_drop()` los sustituía por `None`; por ello el writer ejecutaba
correctamente su ruta de «primer hueco libre». Alpha.127 conserva las coordenadas
solo para el gesto explícito de USUM. El writer vuelve a leer la matriz live,
exige que la casilla exacta exista y esté vacía, y después conserva las mismas
precondiciones, readback y rollback del traslado demostrado. `ENVIAR AL PC` sin
arrastre sigue eligiendo el primer hueco libre. La regresión escribe un testigo
en Caja 3/posición 4 y comprueba que Caja 1/posición 1 permanece vacía; otra
prueba demuestra que un destino ocupado no modifica party ni PC. Validación
física completada en alpha.128.

## USUM alpha.128 — salud flotante y destino PC validados físicamente

La traza de batalla de control demostró que el reader no publicó seis ceros: en
ninguna muestra hubo dos HP mostrados simultáneamente a cero y el último snapshot
conservó los seis HP de party coherentes. La primera divergencia estaba después
del reader: la barra flotante consumía los HP provisionales de la party proyectada
en vez del snapshot de salud validado. Ahora resuelve cada miembro por identidad
fuerte única y solo acepta un rango `0 <= HP <= HP máximo` coherente.

El resto rojo de una baja era independiente: `CTkProgressBar` dibujaba el extremo
redondeado aun con progreso cero. Los miembros vacíos o a cero usan ahora un
carril neutro. La barra también se retira al mapear una ventana principal ya
explícitamente visible, cerrando la carrera de foco observada al maximizar.

La validación visual a 1920×1080 confirma que el selector no presenta el aviso rojo
superior redundante, mantiene tarjetas completas y muestra enteramente `ELEGIR
COMO SUSTITUTO`. La barra flotante de control muestra una casilla debilitada/vacía
sin píxel rojo residual.

La validación física en UltraSol/Azahar del 24-08-2026 arrastró Porygon desde el
equipo hasta Caja 1/posición 8. La matriz visible lo mostró exactamente allí y el
historial confirmó `team_to_pc`, `box: 1`, `box_slot: 8`, `output: RAM`. La
operación inversa lo devolvió al rol Support desde la misma casilla y el historial
confirmó `pc_to_team` con caja/slot 1/8. El estado usado para la comprobación quedó
restaurado.

El usuario confirmó además físicamente que una baja deja la posición flotante
neutra —sin resto rojo— y que la barra flotante desaparece al maximizar RoleRun.

## USUM alpha.129 — arrastre de Pokémon entre cajas PC

La primera divergencia estaba en la UI: las flechas de caja eran botones de clic,
no destinos de arrastre. La segunda estaba en el contrato común de drop, que
rechazaba expresamente todo PC→PC aunque el backend USUM ya hubiese demostrado la
matriz BoxPokemon completa. Mantener un Pokémon sobre una flecha cambia ahora una
sola caja tras 420 ms y conserva la captura del ratón aunque se reconstruya la
cuadrícula. Al abandonar la flecha puede avanzarse otra caja; al soltar sobre una
casilla vacía se declara origen y destino exactos.

El writer USUM copia los 0xE8 bytes cifrados exactos del PK7 stored al destino y
escribe en origen el PK7 vacío cifrado válido. Exige matriz 32×30 estable
host==guest, identidad de origen, destino vacío, límites, preflight inmediato,
dos verificaciones completas y rollback verificado de ambos huecos. No toca party,
otros backends ni reconstruye campos Pokémon. La validación física en Azahar queda
pendiente.

## USUM alpha.126 — EV del rol al sustituir una muerte

La inspección del siguiente punto de entrada PC→Equipo localizó una ruta que no
atravesaba alpha.125: `_prepare_faint_replacement()` heredaba el rol del miembro
debilitado, pero dejaba en el snapshot los EV antiguos del Pokémon de caja; a su
vez, `_apply_faint_replacement()` reconstruía `PartyData` sin consumir EV
preparados. Esa era la primera divergencia y ocurría antes de publicar el nuevo
equipo.

Alpha.126 prepara los EV automáticos del rol heredado y los aplica al mismo PK7
con el que se reconstruyen las estadísticas finales. Para Líbero solo conserva
una pareja demostrada por dos EV a 252 en el miembro saliente; si no existe esa
evidencia, no inventa una selección. La regresión de writer verifica rol, seis
EV, estadísticas runtime, origen PC vacío válido y Pokémon debilitado exacto en
el Cementerio. La validación física en UltraSol/Azahar queda pendiente.

## USUM alpha.124 — estadísticas finales reconciliadas y validadas físicamente

La prueba directa sobre la partida abierta localizó una segunda divergencia:
`assign_role()` salía antes de `_apply_role_assignment()` cuando Líbero ya tenía
la misma pareja de EV. Por tanto, la capacidad transaccional de alpha.123 era
correcta, pero la UI no llamaba al writer en el caso exacto necesario para
reparar el estado dejado por alpha.122.

Alpha.124 mantiene ese retorno temprano para el resto de backends, pero USUM
atraviesa la reconciliación siempre que existe una distribución EV explícita.
La regresión de UI demuestra esa llamada. La validación física en UltraSol con
Azahar del 24-08-2026 observó a Kangaskhan nivel 50 con EV PS/Ataque 252/252 y
estadísticas antiguas 172/140; después de aceptar de nuevo esos mismos EV, el
readback y la pantalla de RoleRun mostraron 203 PS y 170 Ataque. Los EV se
mantuvieron 252/252 y los PS actuales quedaron 203/203 al partir de salud
completa. La evidencia visual se conserva en
`diagnostics/ui/alpha123-live-before.png` y
`diagnostics/ui/alpha123-live-after.png`.

## USUM alpha.123 — writer de estadísticas finales; UI aún omitía la llamada

La prueba física de alpha.122 confirmó que seleccionar PS y Ataque para Líbero
escribía 252/252 en los EV, pero demostró que las estadísticas finales no
cambiaban. La primera divergencia estaba dentro de `USUMLiveWriter`: modificaba
el PK7 stored, mientras que la party Gen 7 mantiene sus estadísticas calculadas
en una `PartyData` dispersa separada (`slot + 0x158`).

Alpha.123 recalculaba ese bloque desde Personal efectivo, nivel, naturaleza, IV,
hiperentrenamiento y los EV deseados. Stored y PartyData comparten ahora
precondiciones, readback y rollback. También permite volver a seleccionar la
misma pareja de Líbero para reparar una party que alpha.122 hubiera dejado con
EV nuevos y stats antiguos. La prueba posterior demostró que la UI descartaba
esa petición antes del writer; alpha.124 cierra y valida esa última frontera.

## USUM alpha.122 — EV escritos; estadísticas finales incompletas

La siguiente diferencia demostrada respecto a BDSP estaba en la frontera de
edición de rol: USUM escribía el marcador PK7, pero la UI solo generaba
`old_evs/new_evs` para `bdsp` y el writer USUM ignoraba esos campos. Alpha.122
habilita la distribución EV para cambios de rol y entradas desde el PC. El
writer usa el campo PK7 ya demostrado en `0x1E:0x24`, exige coincidencia exacta
de los EV anteriores, valida 252/510, actualiza checksum y confirma por
readback identidad, rol, EV y movimientos antes de aceptar la operación. La
prueba física confirmó la distribución EV, pero no las estadísticas finales:
esa limitación queda corregida y pendiente de validar en alpha.123.

## USUM alpha.121 — fichas, PC, curación y barra validados físicamente

- En UltraSol ejecutado por Azahar se validó una ficha de Equipo y una ficha de
  PC con naturaleza, estadísticas calculadas, estadísticas base, IV y EV. La
  ficha PC de control mostró, además, habilidad y los cuatro movimientos.
- La primera divergencia de las fichas PC estaba antes de la UI: el primer
  snapshot podía dejar activa la caché del guardado y el worker PC podía
  ejecutarse antes de cargar el Personal de la ROM. La matriz PK7 viva y el
  Personal efectivo se exigen ahora antes de enriquecer la ficha.
- Se validó físicamente la curación completa sobre un Eevee con 11/19 PS. El
  writer terminó el readback y RoleRun publicó 19/19 sin quedar bloqueado en
  «Curando el equipo».
- La barra flotante USUM mostró los seis miembros y sus barras de PS, además de
  los controles CURAR y MENÚ. El menú se abrió y cerró correctamente y el logo
  devolvió a la ventana principal manteniendo vivo y responsivo el proceso.
- La validación corresponde a la partida y proceso Azahar abiertos el
  24-08-2026. No traslada por analogía ninguna dirección o writer a otro backend.

## Regla de actualización

Actualizar este documento cuando cambie una capacidad, se ejecute una baseline
completa, se demuestre una nueva dirección/estructura o termine una validación
física. No marcar una función realtime como cerrada solo porque pasen tests.
## USUM alpha.130 — arrastre PC físicamente accesible

- Causa raíz demostrada: el arrastre se enlazaba a un frame estable y llamaba
  a `grab_set`; Tk retargeteaba los movimientos/liberación a esa superficie en
  lugar de conservar el widget situado bajo el puntero. Por ello el destino se
  resolvía como la casilla ocupada de origen y las flechas no recibían hover.
- La continuación del gesto usa ahora el bindtag del `Toplevel`, que sobrevive
  al redibujado de una caja sin alterar el destino físico del cursor.
- Validado físicamente en USUM con Azahar 263745c el 2026-08-24: movimiento
  exacto dentro de caja, navegación sostenida caja 1→2, escritura en la casilla
  elegida y recorrido inverso hasta restaurar Eevee en caja 1/casilla 1.

## B2/W2 alpha.6 — evidencia de party, PC y estado de combate

- La captura real de Negro 2 España en melonDS 1.1 demostró que Lillipup y
  Patrat desaparecían en la frontera de decodificación: la permutación de
  bloques PK5 estaba invertida para PID no autoinversos. La corrección reconoce
  los seis miembros presentes en RAM; queda pendiente confirmación visual de UI.
- La captura controlada con party 6/6 y Sewaddle recién enviado al PC demostró
  la matriz en `0x022059A4`: 24 cajas, 30 slots de 136 bytes y stride `0x1000`.
  Dos lecturas completas coincidieron y dieron 3 ocupados y 717 vacíos PK5
  válidos. El reader está implementado; el writer sigue cerrado.
- La traza de parálisis demostró `0x0225B1C4` como byte de presentación:
  `0` antes, `1` con PAR visible y `0` fuera del combate. Alpha.6 lo publica
  desde ese carril.
- Validación física completada por el usuario el 26-08-2026 en Negro 2
  España/melonDS 1.1: RoleRun mostró los seis miembros (incluidos Lillipup y
  Patrat), la barra flotante completa, Azurill/Lillipup/Sewaddle en Caja 1 y
  PAR durante el combate en el momento correcto.

## B2/W2 alpha.9 — movimiento PC→PC validado

- El 27-08-2026 la prueba transaccional movió Lillipup de Caja 1/slot 2 a
  Caja 1/slot 4 en Negro 2 España/melonDS 1.1. El usuario confirmó el resultado
  visual y una lectura independiente verificó origen vacío, identidad completa
  en destino y la matriz restante coherente (3 ocupados, 717 vacíos).
- La capacidad se habilita en producción solo para origen ocupado y destino
  vacío, con precondición de identidad, readback integral y rollback. No
  demuestra ni habilita Equipo↔PC ni intercambios entre dos slots ocupados.
- Validación adicional desde la interfaz de alpha.9: el usuario movió el
  Pokémon dentro del PC y confirmó que RoleRun y el juego reflejaron el destino
  correcto. PC→Equipo continuó cerrado, conforme a la compuerta prevista.

## B2/W2 alpha.10 — intercambio Equipo↔PC 1:1 validado

- La captura controlada desde el PC del juego demostró stored PK5 idénticos en
  ambos sentidos y la regeneración del anexo party según el contrato oficial
  de PKHeX. La restauración devolvió todas las identidades originales.
- La prueba de escritura construyó el anexo con estado limpio, nivel, PS y stats
  recalculadas. El usuario confirmó visualmente Lillipup en Equipo/1 y Tepig en
  Caja 1/slot 2; la relectura independiente confirmó nivel 6, 21/21 PS,
  stats 21/12/11/8/12/12 y 3 ocupados + 717 vacíos coherentes.
- Se habilita solo el intercambio 1:1 con entrante sin objeto. Los cambios de
  tamaño de party y objetos/correo requieren pruebas separadas.
- El usuario validó después desde la interfaz de RoleRun los tres recorridos
  cubiertos: Equipo→PC dentro del swap 1:1, PC→PC a vacío y PC→Equipo 1:1.

## UI alpha.11 — carga inicial en ventana normal

- La barrera inicial ya no se maximiza ni se mantiene por encima del resto del
  escritorio. Conserva el tamaño normal de RoleRun y permite cambiar de ventana
  mientras termina la lectura. La frontera de publicación de la shell no cambia.

## UI alpha.12 — carga inicial centrada

- La ventana normal de RoleRun y su barrera inicial 1360×860 se sitúan en el
  centro de la pantalla principal de Windows. No se recuperan maximización,
  `topmost` ni captura de foco.

## B2/W2 alpha.13 — compactación y tamaño 1–6

- La captura real demostró `6→5`: al depositar el tercer miembro, los tres
  posteriores se desplazan una posición, el contador baja a 5 y el depositado
  conserva su stored PK5 en Caja 1/slot 4. La retirada hace `5→6` y lo añade
  al final; las seis identidades se conservan.
- Una segunda captura del span completo demostró que el slot liberado es
  exactamente el PK5 party vacío cifrado con semilla cero, no memoria aleatoria.
- Alpha.13 implementa count-last, compactación, append, readback y rollback.
  La validación física desde la interfaz sigue pendiente.
