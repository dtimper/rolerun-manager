RoleRun Manager v0.2.2-alpha.33 — Sol/Luna · CAMBIAR CON PC 1↔1 desde RoleRun

Objetivo de esta build
----------------------
Reactivar correctamente la sustitución directa iniciada desde RoleRun entre un miembro del Equipo y un Pokémon de Cajas PC.

Cambio técnico principal
------------------------
Alpha.30 escribía solo la representación sparse que RoleRun usaba para leer y podía producir un falso positivo: RoleRun veía el cambio pero Pokémon Sol no lo adoptaba.

Alpha.33 usa la representación completa EncryptedPartyData de 0x104 bytes por miembro, con stride 0x1E4, en la misma PartyOffset ya demostrada para Sol/Luna. Antes de escribir exige que esa representación contigua:
- sea PK7 válida;
- sea estable en doble lectura;
- coincida host ↔ guest;
- tenga exactamente las mismas identidades que la party sparse live ya validada.

Después de escribir NO basta con releer esos mismos 0x104 bytes. RoleRun exige además que su reader live histórico (stored en el slot + stats runtime en slot+0x158) converja al nuevo Pokémon y vuelva a confirmarlo tras una espera. BoxPokemon también debe quedar exacto host↔guest.

Operación habilitada
--------------------
- CAMBIAR CON PC / CAMBIAR POR UN POKÉMON DEL EQUIPO (1↔1).
- El Pokémon entrante hereda siempre el rol del saliente.
- La UI no proyecta el cambio antes de la confirmación live.

Todavía bloqueado
-----------------
- ENVIAR AL PC sin sustituto.
- PC → un hueco libre del equipo.
- Cambiar directamente el rol de un Pokémon que permanece dentro del PC.

Estas operaciones cambian el tamaño del equipo y no se habilitarán hasta validar físicamente el writer 1↔1 en Pokémon Sol.

Prueba recomendada
------------------
1. Abre CAJAS PC y comprueba el estado real.
2. Desde EQUIPO pulsa CAMBIAR CON PC en un miembro y elige un Pokémon del PC.
3. Comprueba dentro de Pokémon Sol que el entrante sustituyó realmente al saliente y heredó su rol.
4. Comprueba que el saliente quedó en el mismo hueco del PC.
5. Haz el swap inverso desde RoleRun.

Si la escritura no es adoptada por el juego, RoleRun no debe proyectarla como éxito: debe abortar y restaurar party + PC.
