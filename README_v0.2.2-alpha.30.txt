RoleRun Manager v0.2.2-alpha.30

Objetivo de esta build: habilitar la primera escritura segura del PC de Pokémon Sol/Luna iniciada desde RoleRun.

HABILITADO EN ESTA ALPHA
- Sustitución directa 1↔1 Equipo ↔ PC desde el botón CAMBIAR CON PC.
- El Pokémon entrante hereda SIEMPRE el rol del Pokémon saliente.
- El Pokémon saliente ocupa exactamente el hueco del PC del entrante y conserva su marcador como último rol utilizado.

SEGURIDAD
1. La matriz PC tiene que haber sido demostrada previamente host FCRAM == guest RPC.
2. Antes del swap se relee completa y se comprueba la identidad fuerte del Pokémon entrante.
3. La party host se rederiva desde esa misma traducción PC host↔guest y se compara con la party guest actual.
4. Se comprueban nuevamente party stored, party stats y slot PC inmediatamente antes de escribir.
5. Para convertir un PK7 stored en PK7 de party, nivel/PS/stats se calculan con Personal de la ROM/capa efectiva de Sol/Luna configurada, incluyendo randomizers/mods.
6. Tras escribir se verifica party + PC inmediatamente y en un segundo ciclo para detectar restauraciones del juego.
7. Si falla una escritura/verificación, RoleRun restaura y vuelve a comprobar los bloques originales antes de devolver error.

SIGUE BLOQUEADO
- Enviar al PC sin sustituto (reduce el tamaño del equipo).
- Añadir desde PC a un hueco libre (aumenta el tamaño del equipo).
- Editar el marcador/rol de un Pokémon que permanece dentro de una caja.
- Sustitución automática por muerte desde RoleRun.

PRUEBA RECOMENDADA
1. Abre CAJAS PC y confirma que aparecen los Pokémon reales.
2. Ve a EQUIPO y pulsa CAMBIAR CON PC sobre un miembro.
3. Elige un Pokémon de una caja.
4. Comprueba en Pokémon Sol que el entrante aparece en el mismo slot y con el rol del saliente.
5. Comprueba que el saliente ocupa exactamente el hueco del PC que dejó el entrante.
6. Repite el swap al revés y con otro rol.
7. Guarda dentro del juego, reinicia la emulación y confirma persistencia.
