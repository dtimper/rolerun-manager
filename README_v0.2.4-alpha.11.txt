RoleRun Manager v0.2.4-alpha.11

Esta versión corrige la causa que alpha.10 no alcanzaba: X/Y podía devolver por
RPC los bytes recién escritos mientras la memoria anfitriona que consume el
juego conservaba al Pokémon dentro del equipo.

RoleRun resuelve ahora una única región anfitriona coherente para la party, su
contador y el PC completo, y aplica allí la transacción Equipo↔PC. Antes de
confirmar exige readback estable de ambas vistas; ante cualquier divergencia
restaura y comprueba los tres bloques originales.

La siguiente comprobación física es una sola retirada Equipo→PC en Pokémon X.
