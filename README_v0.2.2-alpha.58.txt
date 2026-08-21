RoleRun Manager v0.2.2-alpha.58 — diagnóstico USUM primer KO

Esta build NO cambia todavía la lógica de muerte. Añade una traza segura del carril HP de batalla para identificar por qué el primer Pokémon activo puede registrar su baja tarde mientras un sustituto posterior sí lo hace al momento.

PRUEBA
1. Abre UltraSol/UltraLuna y RoleRun fuera de combate.
2. Entra en un combate con al menos dos Pokémon disponibles.
3. Deja que se debilite el Pokémon que sale inicialmente.
4. Saca otro Pokémon y deja que también se debilite en el mismo combate.
5. Termina el combate.
6. Cierra RoleRun y envía el archivo:
   Documentos\RoleRun Manager\Logs\usum_battle_health_trace_latest.jsonl

La traza registra únicamente flag/HP de batalla y la party testigo. No escribe RAM ni escanea FCRAM.
