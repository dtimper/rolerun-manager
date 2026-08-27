# Baseline técnica BDSP / Ryujinx

Fecha de corte: 2026-08-22.

## Alcance demostrado en el equipo del usuario

- Juego: Pokémon Perla Reluciente.
- Title ID base: `010018E011D92000`.
- Revisión efectiva: `1.3.0`. La selección de update de Ryujinx y sus cachés PTC
  coinciden en esa revisión.
- Mod activo: `Output`, exclusivamente bajo `romfs`; no existe reemplazo ni
  parche `exefs` en esa capa.
- Configuración de memoria: `HostMappedUnsafe`.
- Emulador ejecutado en la validación: Ryujinx `1.3.3+e2143d4` sobre Windows
  x64. El GDB Stub se activó temporalmente en el puerto `55555`, con
  `debugger_suspend_on_start=false`, para la captura física de solo lectura.
- Run existente: `SP-Timper`, asociada a
  `bis\user\save\0000000000000007\0\SaveData.bin`.

Las dos copias `0\SaveData.bin` y `1\SaveData.bin` fueron leídas sin
modificarlas. PKHeX las identifica como `SP` / `SAV8BS`, ambas con el mismo
equipo de seis en la captura actual. RoleRun no debe cambiar automáticamente la
ruta de la Run: la copia `0` continúa siendo la autoridad hasta que el flujo de
Ryujinx demuestre lo contrario.

## Capacidades que ya existen sobre save

La lectura real del save asociado demostró:

- equipo de seis y marcas de rol;
- 40 cajas de 30 slots;
- mochila legible;
- catálogo de 512 movimientos válidos para el save;
- proveedor Unity de las MT randomizadas desde `personal_masterdatas`.

Estas capacidades pertenecen al motor `BDSPEngine` y a
`RoleRun.SaveEngine`. No son realtime: el único mecanismo anterior era vigilar
cuándo Ryujinx reemplazaba `SaveData.bin` después de guardar dentro del juego.

## Primera frontera realtime incorporada

`app/ryujinx_gdb.py` implementa un cliente GDB RSP estrictamente de solo
lectura y limitado a diagnóstico. Descubre la configuración real de Ryujinx,
identifica Title ID y módulos invitados mediante `qRcmd,get info`, lee memoria
con `m` y resuelve cadenas de punteros sin cachearlas. Ryujinx 1.3.3 no incluye
la línea `Process/PID` que devuelven revisiones nuevas y nombra el NSO principal
`SwitchPlayer.nss`; el parser acepta ambos formatos y rechaza cualquier lista
de módulos ambigua. El `RyujinxBridge` permanente usa HostMapped y
`BDSPRealTimeAdapter` ya publica snapshots de party y batalla y expone la matriz
PC al reconciliador Core/UI. El adapter sigue siendo exclusivamente de lectura.
Desde alpha.73 expone además inventario/MT live mediante un reader separado; no
expone writers ni progreso realtime.

La conexión no envía `continue`, no pausa el juego y no expone `write_memory`.
Un Title ID distinto se rechaza antes de leer memoria específica del juego.

## Evidencia técnica externa contrastada

- Ryubing commit `4c21a617573d19cb72a754e01925778116b85073`: el GDB Stub
  escucha por TCP, lee directamente `CpuMemory`, expone `get info` con Title ID
  y bases de módulos, y no detiene el juego por el mero hecho de conectarse.
- PKHeX-Plugins commit `c8e23a43dc48147a8099ee30ad8481c5af839ebb`:
  `SP_v130` declara cadenas separadas para cajas, entrenador e inventario.
- SysBot.NET commit `7f104205f66023011ebbad942efdb8b2cdb25a65`:
  `PokeDataOffsetsBS_SP` fija explícitamente Title ID de Perla Reluciente,
  revisión `1.3.0`, escena y punteros de cajas.

La cadena de cajas SP 1.3.0
`[[[[main+4E7BE98]+B8]+10]+A0]+20` ya no es solo una coincidencia estructural:
en la ejecución real resolvió 40 punteros de caja y 30 objetos PB8 por caja. Los
11 slots ocupados del save se compararon uno por uno y coincidieron exactamente
en caja, slot, especie, PID, TID, SID, validez y checksum PB8. La evidencia
anonimizada se conserva en
`diagnostics/manual/bdsp_sp130_gdb_control_20260822_142756.json`.

Esta prueba autoriza esa cadena exclusivamente como lector de cajas para Perla
Reluciente 1.3.0. `BDSPBoxReader` la activa en producción en modo de solo
lectura. No demuestra por sí sola `PokeParty`, HP, combate ni escritura; cada
uno requiere evidencia independiente.

Una investigación posterior localizó una colección de seis PB8 coherentes
dentro del objeto `SaveData` y la monitorizó cada 0,75 s. El usuario recibió
daño físicamente y terminó el combate, pero el journal conservó únicamente el
baseline inicial: ninguno de los seis HP observados cambió. Por tanto esa
colección queda rechazada como autoridad de HP live. El resultado no demuestra
todavía si puede servir como fuente de identidad u otros campos. Evidencia:
`diagnostics/manual/bdsp_sp130_party_hp_transition_20260822.jsonl`, SHA-256
`18C93E2D866FC4377378B0E18AB8690C317F7F0347B8EE5BBAD4FD00B594D4C7`.

## Party runtime y lane de batalla demostrados

El source exacto de OpenDPR, commit
`5b0cb0c8e11e1a4fdf072e7bb368b8f45a348c6a`, distingue
`SaveData.playerParty` de `PlayerWork._playerParty`: el segundo es un
`PokeParty` no serializado con un array de seis `PokemonParam`. Una búsqueda
HostMapped acotada encontró exactamente seis cores PB8 válidos, un propietario
por core, un único array de seis miembros y un único `PokeParty` coherente. La
cadena de su singleton para esta ejecución y perfil es
`[[[main+4E7BE98]+B8]+10]+808`. `BDSPPartyReader` la resuelve de nuevo en cada
captura, exige conteo 1–6, longitud seis, punteros únicos, cores/cálculos
estables, checksum, especie, nivel y HP coherentes. Evidencia:
`diagnostics/manual/bdsp_sp130_runtime_party_graph_PROOF_20260822.json`.

La primera prueba de daño demostró además que esa party runtime queda atrasada
durante el combate. El source exacto trazó la jerarquía
`BattleProc → MainModule → BattleEnv → POKECON → BTL_PARTY →
BTL_POKEPARAM`, y la observación física localizó una única cadena coherente del
cliente jugador. Los `PokeID` 0–5 mapearon inyectivamente a los seis índices de
party. Dentro del combate, el primer miembro publicó `58/67` en `BTL_PARTY`
mientras `PlayerWork._playerParty` aún publicaba `67/67`; al huir, la party
normal convergió a `58/67` y el objeto de batalla desapareció 608 ms después.

`BDSPBattleReader` lee esa lane solo cuando los flags propios de `BattleProc`
indican inicializado y no terminado, valida conteo, arrays, cinco punteros de
cada fila, especie, nivel, HP y `PokeID`, y trata una desaparición concurrente
como muestra inválida, nunca como HP cero o party vacía. Evidencia:
`diagnostics/manual/bdsp_sp130_battle_to_party_convergence_AUTO_20260822_163121.jsonl`
(SHA-256 `46AE0D518B7FF0D474D96E57F71BCB7D49D52D5C6D984E4F797FFB46B4AF16C7`)
y `diagnostics/manual/bdsp_sp130_battle_lane_PROOF_20260822.json`.

Alpha.76 demuestra otra forma de ausencia dentro de la misma revisión. En una
sesión física SP 1.3.0 que todavía no había cargado `BattleProc`, dos lecturas
consecutivas de `main+0x4E71D00` devolvieron exactamente `nullptr`, mientras el
TypeInfo de `BattleViewUISystem` seguía siendo un puntero estable y la party de
PlayerWork publicaba seis miembros. Solo ese cero estable se acepta como clase
no cargada; un valor no nulo no direccionable sigue siendo un error de
estructura/revisión y bloquea cualquier writer. Evidencia:
`diagnostics/manual/bdsp_alpha75_battleproc_null_outside_battle_PROOF_20260822.json`.

Una segunda captura física cubrió el KO y el cambio forzado. Skitty pasó en
`BTL_PARTY` de `7/21` a `0/21` mientras PlayerWork seguía en `21/21`. Al elegir
a Shuppet, la fila 1 pasó a `party_index=1` y Skitty quedó en fila 2 con
`party_index=0`; por tanto, la fila no es un slot estable. PlayerWork convergió
a cero 23.096 ms después del KO y BattleProc quedó inactivo 701 ms después.
La traza fuente tiene SHA-256
`565B0335AEED1B1174E5FF6011040BB69FE2F1774A1A554A7483474A1435C617` y
su resumen canónico está en
`diagnostics/manual/bdsp_sp130_ko_switch_PROOF_20260822.json`.

Este alcance físico cubre overworld, entrada, daño no letal, KO, sustitución
forzada y salida de un combate salvaje simple. No cubre todavía dobles,
compañeros, multijugador, encuentros especiales ni escritura. El reader y su
mapeo están validados físicamente; la integración UI y el compromiso automático
de la muerte aún necesitan su prueba física sobre esta nueva versión.

El layout completo usado por el reader se contrastó con el tag `26.07.07`,
commit `fcfb5026...`, del mismo paquete `PKHeX.Core 26.7.7` enlazado por
`RoleRun.SaveEngine`. Los seis PB8 vivos coincidieron con la lectura del save
por identidad, forma, apodo, objeto, habilidad, movimientos, huevo y marcas.
PP y PP Ups pasaron sus invariantes estructurales, pero su transición física
sigue pendiente. Evidencia:
`diagnostics/manual/bdsp_sp130_runtime_pb8_fields_PROOF_20260822.json`.

## Investigación de rendimiento del GDB Stub

El usuario observó cargas aproximadamente tres veces más largas y lag de
overworld al reiniciar con GDB activado. Los hechos disponibles son:

- la sesión usa Intel x64, no ARM64;
- en el source exacto de Ryujinx `1.3.3` (`e2143d43...`), GDB solo fuerza el
  JIT clásico en anfitriones ARM64; en este equipo el JIT clásico ya se usa con
  GDB activado o desactivado;
- una conexión TCP no pausa el juego; solo `?`, interrupción o una orden de
  control llaman a `DebugStop`. RoleRun envió exclusivamente consultas y
  lecturas `q`/`m`;
- el log de esta primera sesión con GDB muestra que Ryujinx reconstruyó 64.863
  traducciones PTC durante 13,047 s y después amplió el JIT hasta 1,25 GiB. Ese
  trabajo coincide con una sesión de calentamiento muy costosa, pero todavía
  no demuestra por sí solo que GDB sea su causa;
- PTC, shader cache, Vulkan, GPU, escala y `HostMappedUnsafe` permanecieron
  iguales a la configuración anterior. `TickScalar=200` también es anterior y
  no fue introducido al activar GDB.

Durante PERF-3, el cliente de solo lectura permaneció conectado aproximadamente
27 minutos y medio a una cadencia de 0,75 s. El usuario siguió observando
lentitud; el log muestra que el JIT creció de 1,25 a 2 GiB y el perfil pasó a
155.293 funciones. Después, PERF-0 con GDB apagado mejoró claramente el juego;
PERF-1 volvió a activar solo el stub, sin cliente RoleRun, y la lentitud regresó,
aunque menos que durante el primer calentamiento.

El source exacto `e2143d43...` demuestra el mecanismo: `Debugger.cs` activa
globalmente `ARMeilleure.Optimizations.EnableDebugging`; `Translator.cs` cambia
del dispatch loop no administrado a ejecución bloque a bloque, añade seguimiento
preciso de PC y evita tail calls; `Ptc.cs` rechaza cachés cuyo `DebuggerMode` no
coincida. GDB queda por tanto rechazado como transporte permanente, no solo
limitado por frecuencia de lectura. Evidencia A/B:
`diagnostics/manual/bdsp_sp130_gdb_performance_ab_20260822.json`.

La alternativa HostMapped tiene una prueba positiva cruzada: se enumeraron
solo pares de regiones `MEM_MAPPED` separados por el espacio invitado de 39 bits,
se obtuvo una única coincidencia del testigo `main` y el mismo delta de sesión
leyó un PB8 independiente de 344 bytes. Ambas lecturas fueron idénticas byte a
byte a GDB. No se escribió memoria. Después se reinició Ryujinx con GDB apagado:
la dirección anfitriona anterior quedó invalidada, el reader redescubrió una
única huella en 1.344 pares HostMapped y resolvió 40×30 objetos. Los 11 PB8
ocupados y los 1.189 vacíos pasaron tamaño y checksum. El componente aislado de
producción verificó además `010018E011D92000` y `1.3.0` desde el título activo
que genera `TitleHelper.ActiveApplicationTitle`, y repitió el resultado en
1,543 s con un handle que solo solicita consulta y lectura. Evidencia:
`diagnostics/manual/bdsp_sp130_hostmapped_bridge_proof_20260822.json` y
`diagnostics/manual/bdsp_sp130_hostmapped_no_gdb_PROOF_20260822.json`.

## Inventario runtime demostrado

La cadena SP 1.3.0 publicada por PKHeX-Plugins `c8e23a43...`,
`[[[[main+4E7BE98]+B8]+10]+48]+20`, se contrastó con el source OpenDPR
`5b0cb0c8...` y PKHeX `26.07.07`. Las fuentes demuestran
`PlayerWork.SaveData.saveItem`, 3.000 entradas `SaveItem` de 12 bytes, el layout
de cantidad/flags/orden y que el ID del objeto es el índice del registro.

En el Ryujinx real, la raíz fue estable, la longitud IL2CPP fue exactamente
3.000 y dos lecturas completas de 36.000 bytes coincidieron. Los 51 IDs
positivos fueron los mismos que en el save. El objeto #22 valía 10 en el último
guardado y 9 en RAM, mientras las siete MT poseídas coincidían exactamente;
esta diferencia demuestra que la lane activa no es una mera copia del archivo.
`BDSPInventoryReader` queda autorizado solo para lectura en SP 1.3.0 y rechaza
raíz/longitud inestable, cantidades fuera de 0–999, flags, padding u orden
incoherentes. No autoriza ninguna escritura. Evidencia:
`diagnostics/manual/bdsp_sp130_inventory_live_save_PROOF_20260822.json`.

## Progreso runtime demostrado

El source exacto de OpenDPR, commit `5b0cb0c8...`, define
`FlagWork.BadgeCount()` como la suma de ocho flags de sistema concretos:
`PlayerWork.SaveData.systemFlags[124..131]`. El enum asigna esos índices a
`BADGE_ID_C02..C09` y fija `SYSFLAG_SAVE_SIZE=1000`. PKHeX 26.07.07 confirma de
forma independiente el mismo array y los mismos ocho índices en `FlagWork8b`.

En la sesión física SP 1.3.0, `PlayerWork+0x30` resolvió un único array IL2CPP
`bool[1000]`; raíz y contenido coincidieron en doble lectura y los mil valores
fueron booleanos. Los índices de medalla devolvieron
`[1,1,0,0,0,0,0,0]`, total 2. El save activo contenía los mismos ocho flags y
su espejo `MYSTATUS.badge` también valía 2. `BDSPBadgeReader` queda autorizado
solo para lectura en esta revisión y rechaza cualquier raíz, longitud, valor o
muestra inestable. Evidencia:
`diagnostics/manual/bdsp_alpha77_badge_system_flags_PROOF_20260822.json`.

Esto demuestra representación, dirección y lectura del estado actual. La
transición física de una nueva medalla y su propagación única a Run/OBS sigue
siendo obligatoria antes de cerrar la capability.

Alpha.77 supera **107 pruebas dirigidas** de reader/Adapter/UI/Core y la suite
completa queda en **552 passed** en 21,06 s.

## Orden de implementación

1. demostrar transporte, Title ID, `main`, cajas, party runtime y lane de
   batalla por separado (completado para SP 1.3.0 y el alcance físico descrito);
2. ampliar la identidad PB8 necesaria y publicar party/batalla en un snapshot
   común (completado en modo de solo lectura);
3. demostrar una transición de KO `>0→0`, cambio activo, reconciliación y
   presentación visible (completado y validado físicamente con alpha.69 para un
   combate salvaje simple);
4. demostrar PC e inventario en lectura y después cada writer por separado
   (PC integrado y validado en alpha.70–72; inventario/MT integrado en alpha.73
   y pendiente de validación física);
5. demostrar contador de medallas y estados de batalla (reader completado en
   alpha.77; transición física pendiente);
6. validar físicamente cada carril y solo entonces retirar su bloqueo.

No se trasladarán estructuras PK6/PK7 ni se usarán escaneos generales del
proceso de Windows.

## Verificación automatizada

La batería focal cubre configuración sin mutación, pares HostMapped, presupuesto,
huella única, ambigüedad, permisos read-only, resolución de punteros, cajas
40×30, descifrado/checksum PB8, party runtime, lifecycle de batalla y rechazo
de lecturas inestables, HP incoherente, raíces cambiantes y mapeos duplicados o
ajenos al jugador. El Adapter/UI añade regresiones de fila reordenada, baseline,
transición `>0→0`, lane opcional, conexión persistente y prohibición de escritura.
GDB conserva además sus regresiones diagnósticas de protocolo e identidad. La
batería dirigida del bloque alpha.70 queda en **45 passed**. La suite completa
queda en **507 passed** en 21,09 s con `py -3.14 -m pytest -q` dentro del
entorno de tests aislado. Alpha.67 añade la regresión del watcher que cancelaba
el monitor realtime de BDSP después de recargar el save; alpha.68 valida la
geometría y demuestra físicamente la secuencia de presentación durante un KO.
Alpha.69 exige el ciclo visible `cero animando→cero estable` del mismo PokeID
antes de publicar el cero lógico anticipado. Las regresiones cubren la secuencia
causal y la ausencia segura de la lane visual. La validación física posterior
confirmó que las secuencias 498–499 mantuvieron 6 HP mientras la barra animaba a
cero y que la secuencia 500 publicó cero tras terminar; se registraron una sola
transición y una sola muerte. Control:
`diagnostics/manual/bdsp_alpha69_visible_ko_sync_SUCCESS_20260822.jsonl`.

Alpha.70 conecta `BDSPBoxReader` al contrato `read_pc()` y al reconciliador UI.
La sonda integrada sobre el Ryujinx físico leyó 1.200 slots, 11 ocupados, en
1,459 s y confirmó `writes_enabled=false`. Su primera prueba física demostró
que reader y party sí veían dos depósitos, pero la rama BDSP no programaba la
conciliación al recibir `PARTY_CHANGED`; solo navegar de nuevo forzaba una
lectura, ya sin el miembro saliente que actuaba como ancla de nivel. Alpha.71
programa la conciliación inmediata con los snapshots anterior y nuevo. La
publicación visible corregida quedó validada físicamente con varios depósitos y
recuperaciones: la caja se actualizó sin navegar y el equipo recuperó los
miembros correctamente. La traza conserva seis transiciones directas, cada una
seguida por lectura y conciliación PC. Control:
`diagnostics/manual/bdsp_alpha71_pc_roundtrip_SUCCESS_20260822_190522.jsonl`,
SHA-256
`7662BD363815B8EF273008AB4CC69E48500549175F11AECB76E0FAA60AF4AC71`.
Las pruebas BDSP completas de alpha.71 dieron **60 passed** en 0,75 s y la
suite completa **508 passed** en 21,04 s con `py -3.14 -m pytest -q`.

Alpha.72 cubre el hueco restante de lectura PC↔PC: como un movimiento entre
cajas no cambia la party, no existe `PARTY_CHANGED` que dispare el reconciliador.
Solo mientras CAJAS PC está visible se relee la matriz demostrada cada 2,5 s,
sin solapes y sin repintar capturas idénticas. Minimizar, salir de la página,
cambiar de Run o encontrar un error detiene el bucle. La batería BDSP queda en
**62 passed** y la suite completa en **510 passed** en 20,94 s.

Alpha.73 añade las regresiones de inventario 3.000×12, raíz/longitud/bloque
inestables, campos imposibles, diferencia save/live, carga fuera de Tk y
descuento de MT pendientes. Reader/Adapter/UI BDSP dan **57 passed**; el bloque
afectado más consumidores Gen7 da **112 passed** y la suite completa
**519 passed** en 21,12 s. La prueba física del selector sigue pendiente.

La validación física posterior cerró ese caso: con party 6→6, Aipom se movió de
caja 1/slot 2 a caja 2/slot 2. Solo el primer poll publicó `changed=true`; los
siete posteriores fueron `changed=false`, sin parpadeo observado. Control:
`diagnostics/manual/bdsp_alpha72_pc_to_pc_poll_SUCCESS_20260822_191534.jsonl`,
SHA-256
`1A399AA247275C9A33085327628076D0FD8B64BEBE2107E81370223198101FDD`.
