RoleRun Manager v0.2.2-alpha.65 — primer Kahuna detectado desde RAM viva

La prueba física con Kaudan/Hala demostró que UltraSol entregó Lizastal Z, pero
RoleRun mantuvo el contador en 0. La RAM viva contenía de forma estable los IDs
807 y 813 y el parser devolvía correctamente 1 Kahuna; el main aún contenía solo
807 y devolvía 0.

La causa estaba después de demostrar la mochila: el lector de progreso guardaba
la prueba de solo lectura en _tm_guest_inventory_anchor, pero después consultaba
otra caché reservada a escrituras (_utility_block_cache). Al no encontrarla,
descartaba el 1 live y publicaba el 0 del main.

Alpha.65 consume la ancla correcta inmediatamente y la relee de forma estable en
los ticks posteriores. No añade direcciones, no cuenta victorias, no fuerza el
contador y no escribe la mochila.

VALIDACIÓN AUTOMATIZADA: 448 tests superados.

PRUEBA FÍSICA MÍNIMA

1. Cierra la instancia anterior de RoleRun y abre alpha.65 con UltraSol abierto.
2. No repitas el combate ni modifiques manualmente el contador.
3. Espera unos segundos fuera de combate.
4. Comprueba que MEDALLAS cambia de 0 a 1 por el Lizastal Z que ya está en la
   mochila viva.
