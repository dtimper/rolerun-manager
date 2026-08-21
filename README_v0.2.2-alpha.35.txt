RoleRun Manager v0.2.2-alpha.35 — Sol/Luna · swap Equipo ↔ PC con ambas representaciones live

Objetivo de esta build
----------------------
Corregir el fallo observado en alpha.34 al cambiar un Pokémon desde RoleRun: el PK7 stored del entrante se escribía, pero el mirror runtime de stats de la party seguía perteneciendo al Pokémon saliente. Esa mezcla hacía fallar la validación PK7 y obligaba al rollback.

Cambio técnico
--------------
El swap 1↔1 escribe y verifica dentro de la misma transacción:
- BoxPokemon: 0xE8 bytes del Pokémon saliente.
- PartyOffset: EncryptedPartyData completo de 0x104 bytes del Pokémon entrante.
- Mirror runtime de stats: 0x16 bytes cifrados del mismo EncryptedPartyData en slot+0x158.

No se proyecta ningún cambio en la UI hasta confirmar host↔guest, party sparse y PC. Si falla cualquier etapa, se restaura todo.

Prueba manual
-------------
1. Abrir CAJAS PC.
2. Desde RoleRun cambiar Ledyba por Decidueye.
3. Verificar en Pokémon Sol que Ledyba aparece realmente en el equipo y hereda Líbero.
4. Verificar que Decidueye ocupa el hueco de Ledyba en el PC.
5. Hacer el cambio inverso desde RoleRun.

Todavía no se habilitan PC→hueco libre ni Equipo→PC reduciendo el equipo.
