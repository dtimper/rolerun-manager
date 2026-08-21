RoleRun Manager v0.2.2-alpha.31

OBJETIVO DE ESTA BUILD
Diagnosticar de forma segura por qué la sustitución Equipo ↔ PC de alpha.30 podía aparecer aplicada en RoleRun sin que Pokémon Sol adoptase al nuevo miembro.

QUÉ CAMBIA
- Las escrituras Equipo ↔ PC iniciadas desde RoleRun quedan TEMPORALMENTE BLOQUEADAS en Sol/Luna.
- No se proyecta ningún swap en la UI y ningún PendingTeamChange llega al writer público.
- Roles, movimientos, MT, utilidades, lectura del equipo y lectura/sincronización del PC siguen funcionando.
- El monitor guarda ahora los 6 slots runtime completos de party: 6 × 0x1E4 bytes.
- Cuando una sustitución REAL hecha dentro del propio Pokémon Sol cambia la identidad de un slot, RoleRun compara el antes/después completo y escribe un diagnóstico.

ARCHIVOS DE DIAGNÓSTICO
Documentos\RoleRun Manager\Logs\sm_party_runtime_transition_latest.json
Documentos\RoleRun Manager\Logs\sm-party-runtime-AAAAmmdd-HHMMSS-ffffff.json

El JSON conserva para cada slot cambiado:
- identidad fuerte antes/después;
- dirección runtime;
- todos los offsets diferentes;
- recuentos por zonas: stored, hueco runtime, stats y cola runtime;
- los 0x1E4 bytes completos antes y después en hexadecimal.

PRUEBA RECOMENDADA
IMPORTANTE: si vienes de alpha.30 y probaste un swap falso, reinicia la emulación desde un estado limpio/guardado real antes de empezar. No guardes dentro del juego el estado falso de alpha.30.

1. Abre alpha.31 y Pokémon Sol.
2. Entra al overworld y pulsa F5.
3. Abre CAJAS PC una vez y espera a que RoleRun muestre el estado real.
4. Desde el PC DEL PROPIO JUEGO, haz una sustitución 1↔1 (por ejemplo Decidueye ↔ Ledyba).
5. Espera a que Dashboard/barra/PC de RoleRun reflejen el cambio.
6. Haz el swap inverso o una segunda sustitución diferente y vuelve a esperar la sincronización.
7. Envía los dos archivos timestamped `sm-party-runtime-*.json` más recientes. Si solo hay uno, envía `sm_party_runtime_transition_latest.json`.

POR QUÉ NO SE ESCRIBE TODAVÍA
La zona conocida de party permite leer de forma fiable el PK7 stored y 22 bytes de stats, pero la prueba física de alpha.30 demostró que sustituir solo esos fragmentos no basta para que Pokémon Sol adopte otro miembro. Alpha.31 mide primero qué más cambia realmente dentro de los 0x1E4 bytes del slot. No se rellenarán bytes desconocidos por intuición.
