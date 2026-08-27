RoleRun Manager v0.2.2-alpha.101

Esta versión añade la primera transacción realtime de EV por rol para Pokémon
Perla Reluciente 1.3.0 en Ryujinx. Los roles fijos maximizan dos estadísticas y
limpian las otras cuatro; Líbero permite elegir exactamente dos.

La operación verifica el Pokémon y sus stats vivos antes de escribir, actualiza
core y stats calculados conjuntamente, comprueba el resultado y restaura ambos
bloques si falla cualquier paso. La capacidad queda pendiente de validación
física antes de considerarse cerrada.

Suite: 667 passed en 22,98 s con py -3.14 -m pytest -q.
