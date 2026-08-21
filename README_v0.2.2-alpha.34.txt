RoleRun Manager v0.2.2-alpha.34 — Sol/Luna · corrección del preflight Equipo ↔ PC

OBJETIVO
-------
Esta build corrige exclusivamente el error de alpha.33 que impedía llegar a la escritura 1↔1 desde RoleRun al exigir que los 0x104 bytes actuales del slot fueran un PartyData estándar contiguo.

QUÉ CAMBIA
----------
El estado live demostrado de Sol/Luna es sparse: 0xE8 bytes PK7 stored al inicio del slot y 0x16 bytes de stats en +0x158, stride 0x1E4. Por tanto alpha.34 valida la ventana de inyección por igualdad host/guest y por identidad fuerte del prefijo stored, sin interpretar 0xE8..0x103 del estado previo.

El Pokémon que ENTRA desde el PC sí se construye como EncryptedPartyData completo de 0x104 antes de escribir. Después RoleRun exige que el mirror sparse +0x158 converja al nuevo Pokémon. Si no ocurre, restaura party y PC y no publica el cambio.

PRUEBA
------
1. Abre CAJAS PC y confirma que la lectura live es correcta.
2. Desde RoleRun usa CAMBIAR POR UN POKÉMON DEL EQUIPO / CAMBIAR CON PC.
3. Comprueba directamente en Pokémon Sol que el entrante sustituye al saliente y hereda su rol.
4. Comprueba que el saliente ocupa el hueco de PC del entrante.
5. Haz el cambio inverso desde RoleRun.

Todavía no se habilitan operaciones que cambian el tamaño del equipo.
