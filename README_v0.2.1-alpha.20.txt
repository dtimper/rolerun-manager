RoleRun Manager v0.2.1-alpha.20
==================================

Objetivo de esta build
----------------------
Corregir exclusivamente la utilidad Dinero máximo de Pokémon X/Y en tiempo real.

Qué cambia
----------
- La ruta principal de dinero ya no depende de que el bloque Misc del main configurado sea idéntico a la copia viva.
- RoleRun reutiliza la mochila/MT viva ya calibrada para identificar de forma segura el layout X/Y v1.0 o v1.5.
- Solo si la base de mochila coincide con uno de esos layouts conocidos se usa su dirección correspondiente de Money.
- Antes de escribir, RoleRun relee el u32 de dinero y exige un valor dentro del rango 0..9.999.999.
- La escritura sigue siendo de 4 bytes, con relectura y rollback si AzaharPlus no confirma el cambio.
- El localizador Misc anterior se conserva como fallback.

Prueba manual
-------------
1. Abre Pokémon X en AzaharPlus con RPC activo y entra al overworld.
2. Abre RoleRun alpha.20.
3. Pulsa Dinero máximo.
4. Comprueba en el juego que el saldo queda en 9.999.999.
5. Si aparece un error, no pruebes otras operaciones: captura el mensaje exacto.

Regresiones
-----------
La suite automatizada de esta build pasa 233/233 tests.
