RoleRun Manager v0.2.2-alpha.29

Objetivo de esta build: cerrar la sustitución juego → RoleRun en Pokémon Sol/Luna sin crear miembros SIN ROL ni bucles de escritura.

Reglas de entrada al equipo:
- Sustitución directa 1↔1: el entrante hereda SIEMPRE el rol del Pokémon saliente.
- Entrada a un hueco sin sustitución: primer rol libre de izquierda a derecha.
- La decisión se conserva durante toda la transición; no se recalcula como una asignación genérica si Azahar tarda en estabilizar PC/party.

Seguridad alpha.29:
1. RoleRun publica la party real leída por RPC.
2. Retiene la intención de rol derivada del before/after real.
3. Relee el PC completo y exige host == guest.
4. Con esa prueba rederiva/revalida la party host actual.
5. Solo entonces escribe el marcador del entrante.
6. Si la party cambia otra vez o la prueba falla, no escribe ningún byte y vuelve a demostrar el estado antes de reintentar.

Prueba recomendada:
1. Con seis roles ocupados, intercambia desde el PC del juego un Pokémon del equipo por otro del PC.
2. El entrante debe recibir el rol del saliente automáticamente.
3. No debe quedar SIN ROL ni aparecer un séptimo slot lógico.
4. Dashboard, barra y CAJAS PC deben mostrar una sola copia de cada Pokémon.
5. Repite con otro rol y luego con una entrada a hueco libre para comprobar primer rol libre.

Equipo↔PC iniciado desde RoleRun sigue bloqueado en Sol/Luna en esta alpha.
