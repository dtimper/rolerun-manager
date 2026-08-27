# RoleRun Real-Time Core — evolución desde 0.2.1

> Este documento explica la arquitectura y conserva hitos de 0.2.1. El mapa de
> capacidades y los bugs abiertos actuales están en `CURRENT_STATE.md`.

## Objetivo

Evitar que cada juego repita la lógica de sincronización que se ha ido
endureciendo en ORAS. El Core define contratos comunes; los adaptadores conocen
el layout concreto del juego y el bridge conoce el transporte del emulador.

```text
Emulador/Transporte
        │
        ▼
 EmulatorBridge
        │
        ▼
 RealTimeGameAdapter  ← offsets, firmas y validadores del juego
        │
        ├── LiveBlockResolver
        │       ├── cache validate
        │       ├── cheap candidates
        │       ├── scan/discovery
        │       ├── score/rank
        │       └── cooldown
        ▼
   RealTimeCore
        │
        ├── RealTimeSnapshot
        ├── Event Engine
        ├── Diagnostics
        ├── Session Recorder
        └── Replay
        │
        ▼
 UI / OBS / automatismos RoleRun
```

## EmulatorBridge

No sabe qué es un Pokémon. Representa el transporte de memoria. Actualmente existen `AzaharBridge` (RPC UDP) y `CitraBridge` (GDB Remote Serial Protocol). X/Y puede usar cualquiera de los dos sin cambiar el contrato del juego.

## RealTimeGameAdapter

Traduce un juego concreto al contrato común. Debe aislar los fallos de carriles
opcionales y puede exponer:

- captura estable;
- PC/inventario/escrituras;
- bloques pequeños útiles para diagnóstico;
- estado serializable de sus resoluciones/cachés.

ORAS/Azahar es la implementación de referencia. Desde `0.2.1-alpha.3`, X/Y fue
el primer segundo adaptador. En `0.2.1-alpha.4` el mismo adaptador lógico X/Y
podía elegir automáticamente Azahar/RPC o Citra/GDB, demostrando que el Core no
estaba acoplado a un único emulador. La frase histórica «PC/MT/batalla
pendientes» dejó de ser cierta en alphas posteriores: el código actual registra
esas capacidades X/Y con sus límites de seguridad, descritos en
`CURRENT_STATE.md`. SM y USUM se añadieron después como adaptadores Azahar
independientes.

BDSP se incorporó en alpha.66 como adaptador de lectura sobre
Ryujinx/HostMappedUnsafe. `PlayerWork._playerParty` aporta la party estable y
`BattleProc.client.BTL_PARTY` el HP inmediato de combate; ambas estructuras y
su mapeo pertenecen exclusivamente al backend BDSP.

Alpha.67 demostró que ese HP es lógico y puede anticipar la presentación del
golpe. Alpha.68 observa por separado `BattleViewUISystem._statusWindows`: HP
mostrado, PokeID, pertenencia al jugador, aplicación pendiente y animación de
la barra. La captura letal demostró que el cero lógico precedió 6,167 s al
inicio de la animación visible y 6,690 s a su final.

Alpha.69 conserva esa lane opcional y usa una máquina de evidencia local al
adapter BDSP: un cero lógico anticipado no se publica hasta que una ventana
jugador única con PokeID y HP máximo coincidentes haya mostrado `0` primero con
`IsAnimation=true` y después con `IsAnimation=false`. No hay temporizador fijo.
Si la lane visible falta o es ambigua, conserva el último HP positivo; al salir
del combate, la party `PlayerWork` convergida sigue siendo la autoridad segura.
El cero de un baseline inicial se publica como tal, pero LivePartyWatch no lo
convierte en una transición retrospectiva.

Alpha.70 expone además `BDSPBoxReader` mediante `read_pc()` sin introducir la
matriz en cada snapshot del monitor. La UI solicita la lectura completa en un
worker al abrir CAJAS PC o al cambiar la composición del equipo. El adapter
serializa esa operación con el monitor, exige la geometría demostrada 40×30 y
devuelve posiciones fuertes al reconciliador común. Antes de publicar, la UI
rechaza una captura temporal en la que la misma identidad figure a la vez en
party y PC y programa una relectura. Este carril sigue siendo de lectura;
alpha.75 no autoriza escrituras PC.

Alpha.73 expone `BDSPInventoryReader` mediante `read_tm_inventory()`. Es un
carril auxiliar solicitado explícitamente por el selector: no forma parte del
snapshot periódico ni bloquea Tk. Resuelve de nuevo la cadena SP 1.3.0, exige
un array de 3.000 `SaveItem`, doble lectura y validación de cada registro. El
save puede acompañar como testigo diagnóstico, pero nunca funciona como
fallback.

Alpha.75 añade `BDSPLiveWriter` para roles y movimientos de la party. Una
enseñanza de MT es una transacción entre el core PB8 de 328 bytes y un registro
`SaveItem` de 12 bytes: doble captura, identidad/valor previo, huella de sesión,
readback host+guest, verificación semántica y rollback de ambas unidades. El
cliente de monitor continúa siendo read-only; el handle RW se abre y cierra
dentro del writer. El Adapter declara escritura disponible para este subconjunto
y la UI deja de ofrecer el guardado diferido. Las operaciones PC se incorporan
por contratos separados en alpha.78–84.

Alpha.85/86 añade utilidades BDSP sin mezclar estructuras. Caramelo Raro y
Repelente Máximo escriben únicamente sus `SaveItem` indexados 50 y 77; dinero
usa un `BDSPMoneyReader` independiente sobre el `MYSTATUS` demostrado en
`PlayerWork+0xE0`, con `gold` en `+0xEC` y máximo 999.999. La transacción exige
party/mochila/MYSTATUS estables, precondición guest+host, readback de los bloques
completos y rollback verificado. Para un objeto todavía ausente, alpha.86 asigna
`max(SortNumber)+1` entre los IDs legales del mismo bolsillo, como demuestran
OpenDPR y PKHeX; no usa un orden global ni otro bolsillo. Progreso sigue siendo
solo lectura.

Alpha.77 añade `BDSPBadgeReader` como lane opcional del snapshot. Lee únicamente
los ocho `PlayerWork.SaveData.systemFlags` que `FlagWork.BadgeCount()` usa en
BDSP, tras validar el array `bool[1000]` con doble lectura. La procedencia
`SystemFlags vivos · PlayerWork.SaveData` forma parte del contrato live común;
un fallo de progreso no invalida party ni batalla y nunca cae al save.

## LiveBlockResolver (alpha.2+)

Es independiente de offsets y del emulador. El adaptador aporta tres piezas:

1. `read_at(address)`;
2. `validate(bytes) -> score | None`;
3. opcionalmente `discover() -> candidatos`.

El resolver aplica siempre el mismo contrato:

1. Si existe caché, leerla y validarla. Si sigue siendo válida se conserva aunque
   su score haya bajado: así un state-load puede retroceder sin saltar a una
   copia stale con mayor progreso.
2. Si la caché falla, probar candidatos baratos/conocidos. Una dirección nominal
   es solo un candidato.
3. Si ninguno vale, ejecutar el descubrimiento caro.
4. Validar y puntuar candidatos, elegir el mejor y cachearlo.
5. Tras un barrido fallido, aplicar cooldown.

La mochila MT/MO de ORAS y el primer resolver `Misc` de X/Y ya utilizan este componente. Los siguientes juegos deben reutilizarlo para cualquier bloque que pueda existir en copias desplazadas.

## USUM — salud de batalla y salida en alpha.62

`USUMLiveReader` mantiene las direcciones publicadas por USUMCheatMenu solo como
candidatas rápidas. Si no describen ningún slot de la party del mismo tick, la
resolución se hace en la capa RAM, antes del adapter:

1. la doble captura estable conserva los seis PK7 y su base guest;
2. esos PK7 exactos localizan una copia única de party en el backing FCRAM host;
3. dentro de esa región se busca el multiconjunto completo de Max HP con stride
   `0x330` y se validan Displayed/Actual HP en rango, sin imponer el orden de party;
4. la diferencia entre la party host demostrada y su base guest traduce cada
   candidata, sin asumir un alias fijo;
5. solo una candidatura única con dos lecturas RPC idénticas y flag activo
   antes/después puede producir `health_game`;
6. la base se revalida por Pokémon en cada tick y se elimina al terminar la
   batalla.

La fila no se identifica por su índice ni solo por HP. La captura física alpha.59
demostró una permutación `4,2,3,1,5,6`; la captura alpha.60 demostró además que
Eevee y Porygon podían empezar ambos a 19/19, haciendo indistinguibles Max,
Displayed y Actual. Alpha.61 lee la tabla `PARTY ON BATTLE INITIAL DATA` de USUM
en `0x3254EE60`, stride `0x104`, y exige un PK7 stored checksum-válido. La
identidad `(species, PID, TID, SID)` restringe el matching party↔fila; Max y HP
siguen validando la geometría. Si falta una identidad, solo se publican las
asignaciones comunes a todas las soluciones demostrables.

El estado de batalla es también un ciclo, no una comparación aislada. El par
`0x00040001/3` demuestra una batalla publicable. Las capturas físicas alpha.60 y
alpha.61 demuestran que `0x00040005/6` aparece tanto durante la selección forzada
como ya en overworld; no es un terminal ni una suspensión por sí solo. Durante
ese estado ambiguo el adapter conserva `state="battle"` sin `health_game` hasta
que los KO Displayed HP `>0→0` observados en filas validadas convergen a HP=0
en PartyData para las mismas identidades PK7. Entonces publica `state="none"`.
El par `0x00040000/1` sigue siendo una salida positiva observada, pero ya no se
presupone que todo final de combate deba atravesarlo.

La convergencia no acepta un miembro que ya estuviera a 0 al establecer el
baseline: debe existir una transición visible dentro del episodio. Por ello un
Pokémon previamente debilitado no puede convertir una selección forzada en
final. La traza registra `battle-idle-evidence` con observados, convergidos y
pendientes, y `battle-end.reason` declara qué prueba cerró el episodio.

No existe sustitución en UI de una muestra inválida por HP overworld. El journal
de diagnóstico conserva todos los episodios del reader y una copia inmutable para
que una reentrada del flag o un reinicio posterior no destruya la evidencia.

## RealTimeSnapshot

### B2/W2 / melonDS (v0.2.6-alpha.1)

El adaptador `b2w2` publica únicamente la party nominal PK5. Las direcciones
son conocimiento exclusivo de `app/b2w2_live.py`. Antes de publicar exige
candidato único, dos capturas idénticas de contador+bloque, checksum/estructura
de todos los PK5 y una identidad PID/TID/SID común con el guardado activo. No
expone writers ni carriles opcionales todavía.

Contrato consumido por las capas superiores. Agrupa equipo, proceso, memoria
auxiliar, batalla, medallas y diagnóstico de un ciclo lógico.

### Autoridad del progreso absoluto (alpha.64)

`badge_source` forma parte del contrato, no es solo texto de diagnóstico. Los
cuatro backends pueden publicar una lectura RAM validada o un valor recuperado
del último save. El save puede adelantar el contador persistido, pero no reducir
un progreso live más nuevo porque puede no haberse guardado aún. Solo las
procedencias RAM declaradas en `badge_source_is_live()` pueden representar un
descenso real por carga de state/partida anterior. Las fuentes desconocidas
quedan cerradas por defecto.

USUM añade una traza de transición específica para la última validación física
de Kahunas. La traza observa el contrato ya publicado; no introduce otra ruta de
lectura ni altera el valor.

## RealTimeCore

Gestiona secuencia, historial válido, eventos, acceso común a operaciones vivas
y grabación. No contiene offsets de ningún juego.

### Recarga externa del guardado (alpha.67)

El watcher del save constituye una frontera de sesión: publica el `main`
consolidado, cancela el timer anterior, elimina el baseline de salud y reinicia
el historial del Core para no comparar estados incompatibles. Si la Run sigue
conectada, debe rearmar después el monitor para cualquier backend incluido en
`REALTIME_READ_GAME_KEYS`. Una conexión marcada como activa sin timer ni
snapshot no es un estado realtime válido. Los juegos sin backend registrado no
se programan. Esta regla es común; no modifica offsets ni validadores de los
adaptadores.

Cuando hay una grabación activa, mezcla las peticiones normales de memoria con
`adapter.diagnostic_memory_requests()`. Así la UI no conoce direcciones y cada
juego decide qué bloques pequeños merece la pena adjuntar.

## Eventos

El motor común modela actualmente:

- `party_changed`
- `order_changed`
- `role_changed`
- `moves_changed`
- `level_changed`
- `pokemon_fainted`
- `badge_changed`
- `battle_state_changed`

Durante esta fase siguen como observación paralela para ORAS; los automatismos
maduros se migrarán uno a uno cuando exista paridad de pruebas.

## Recorder y Replay (alpha.2)

Desde Configuración se puede iniciar una captura manual. `RealTimeSessionRecorder`
guarda NDJSON con:

- snapshots;
- eventos;
- diagnóstico por carril;
- estado técnico del adaptador;
- bloques auxiliares solicitados durante la grabación.

Al detenerla se puede crear un ZIP con manifest. `RealTimeReplay` abre tanto ese
ZIP como un NDJSON suelto y permite inspeccionarlo offline.

El objetivo no es grabar continuamente al usuario, sino poder capturar de forma
explícita un bug difícil de reproducir y convertirlo en una prueba repetible.

## Regla de migración de juegos

Un juego nuevo no debe introducir llamadas RPC/emulador dentro de `ui.py`.
Debe implementar un adaptador y registrarlo en `RealTimeRegistry`.

Checklist mínima:

1. identidad segura de proceso/juego;
2. captura estable de party;
3. resolver común para bloques dinámicos;
4. carriles opcionales aislados;
5. lectura PC/inventario si se soportan;
6. escritura read → validate → write → read-back;
7. `runtime_state()` y diagnóstico;
8. snapshots sintéticos/replays como tests;
9. pruebas de reset/state-load y copias viejas de RAM.

## X/Y — estado histórico en alpha.4

X/Y demostró dos independencias: no dependía de ORAS y tampoco de Azahar.
`XYMultiRealTimeAdapter` intenta primero la ruta ya validada de Azahar/RPC y, si
no está disponible, prueba Citra/GDB. La última ruta que funcionó queda preferida
para las siguientes capturas y escrituras, evitando mezclar emuladores dentro de
una misma sesión. En alpha.4, party, roles y movimientos eran read/write y PC,
MT/inventario y batalla seguían deshabilitados hasta disponer de validadores
propios. Esas capacidades se incorporaron en alphas posteriores; las operaciones
que cambian el tamaño de party iniciadas por RoleRun continúan protegidas.


## Citra — alpha.5: sesión GDB persistente y bootstrap

El Bridge de Citra no trata GDB como un transporte stateless. El stub clásico puede mantener la CPU detenida hasta recibir `continue` y además apaga su servidor cuando el debugger real se desconecta. Desde 0.2.1-alpha.8 la ventana de RoleRun **no posee ese socket**: un proceso auxiliar local (`citra_broker`) conserva una única sesión `CitraGDBClient` con Citra. Los lectores/escritores del Core se conectan al broker y pueden cerrar sus leases (o incluso cerrar toda la UI) sin desconectar el debugger. Al volver a abrir RoleRun, la nueva instancia reutiliza el broker existente. Si Citra se reinicia, el broker invalida el socket obsoleto y el siguiente intento vuelve a bootstrapear el GDB Stub.

Esto deja una frontera más correcta entre Core y Bridge: Azahar puede abrir/cerrar RPC por operación; Citra mantiene estado de transporte sin que el adaptador X/Y ni la UI tengan que conocer esa diferencia.
