RoleRun Manager v0.2.2-alpha.39 — Sol/Luna · refresco inmediato PC tras ENVIAR AL PC

Objetivo único de esta build:
- conservar intacta la mecánica Equipo → PC validada en alpha.38;
- hacer que el Pokémon recién enviado aparezca inmediatamente en los selectores PC de RoleRun, sin visitar CAJAS PC.

Cambio técnico:
- el writer ya escogía y verificaba el primer hueco libre de la matriz PC live;
- alpha.39 devuelve esa posición confirmada a la capa UI después del éxito;
- el override live existente publica inmediatamente el Pokémon en esa casilla;
- no se cambian offsets, payloads, compactación, elección de hueco ni rollback.
