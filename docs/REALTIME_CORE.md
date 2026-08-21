# RoleRun Real-Time Core — 0.2.1

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

ORAS/Azahar es la implementación de referencia. Desde `0.2.1-alpha.3`, X/Y fue el primer segundo adaptador. En `0.2.1-alpha.4` el mismo adaptador lógico X/Y puede elegir automáticamente Azahar/RPC o Citra/GDB, demostrando que el Core tampoco está acoplado a un único emulador. PC/MT/batalla siguen pendientes de calibración específica X/Y.

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

## RealTimeSnapshot

Contrato consumido por las capas superiores. Agrupa equipo, proceso, memoria
auxiliar, batalla, medallas y diagnóstico de un ciclo lógico.

## RealTimeCore

Gestiona secuencia, historial válido, eventos, acceso común a operaciones vivas
y grabación. No contiene offsets de ningún juego.

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

## X/Y — alpha.4

X/Y demuestra ahora dos independencias: no depende de ORAS y tampoco de Azahar. `XYMultiRealTimeAdapter` intenta primero la ruta ya validada de Azahar/RPC y, si no está disponible, prueba Citra/GDB. La última ruta que funcionó queda preferida para las siguientes capturas y escrituras, evitando mezclar emuladores dentro de una misma sesión. Party, roles y movimientos son read/write en ambos transportes; PC, MT/inventario y batalla específica no se habilitan hasta disponer de validadores propios. En Citra alpha.4 las medallas usan temporalmente el `main` como fallback para evitar un barrido GDB grande que pueda congelar builds antiguas; su calibración live queda para la siguiente iteración.


## Citra — alpha.5: sesión GDB persistente y bootstrap

El Bridge de Citra no trata GDB como un transporte stateless. El stub clásico puede mantener la CPU detenida hasta recibir `continue` y además apaga su servidor cuando el debugger real se desconecta. Desde 0.2.1-alpha.8 la ventana de RoleRun **no posee ese socket**: un proceso auxiliar local (`citra_broker`) conserva una única sesión `CitraGDBClient` con Citra. Los lectores/escritores del Core se conectan al broker y pueden cerrar sus leases (o incluso cerrar toda la UI) sin desconectar el debugger. Al volver a abrir RoleRun, la nueva instancia reutiliza el broker existente. Si Citra se reinicia, el broker invalida el socket obsoleto y el siguiente intento vuelve a bootstrapear el GDB Stub.

Esto deja una frontera más correcta entre Core y Bridge: Azahar puede abrir/cerrar RPC por operación; Citra mantiene estado de transporte sin que el adaptador X/Y ni la UI tengan que conocer esa diferencia.
