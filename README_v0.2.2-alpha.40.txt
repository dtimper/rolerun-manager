RoleRun Manager v0.2.2-alpha.40 — Sol/Luna · muertes, Cementerio y sustitución

Esta build porta a Sol/Luna el flujo de bajas ya existente en RoleRun.

VALIDAR EN JUEGO
1. Empieza con al menos 2 Pokémon en el equipo y una vida > 0.
2. Provoca una baja real en combate (PS > 0 → 0).
3. Comprueba que VIDAS baja exactamente en 1 y que no vuelve a bajar en ticks posteriores.
4. Al terminar el combate, RoleRun debe abrir una única ventana «ELIGE AL SUSTITUTO DE…».
5. Elige un Pokémon del PC que NO esté en Caja 4.
6. Verifica en Pokémon Sol: el sustituto entra en el mismo slot y hereda el rol del debilitado.
7. Verifica CAJAS PC: el sustituto desaparece de su hueco y el debilitado aparece en Caja 4 (Cementerio).
8. Comprueba Dashboard, barra flotante y OBS: el muerto ya no figura como activo y el nuevo miembro sí.
9. Guarda/reinicia y confirma persistencia.

PRUEBA DE SEGURIDAD
- Si un Pokémon ya estaba a 0 PS antes de abrir RoleRun, no debe descontar una vida nueva.
- Si retiras manualmente al debilitado desde el PC del propio juego antes de elegir sustituto, RoleRun debe cerrar/resolver la baja sin restar otra vida.

Nota: no se ha añadido ningún offset de batalla supuesto para Gen 7. La detección usa únicamente los PS de la party PK7 live ya demostrada y el flujo estable de dos muestras antes del selector.
