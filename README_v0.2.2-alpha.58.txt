RoleRun Manager v0.2.2-alpha.58 — diagnóstico USUM primer KO

NOTA DE ESTADO 2026-08-22
Este README conserva el procedimiento original de alpha.58. El estado canónico
y la investigación vigente están en docs/CURRENT_STATE.md. En el snapshot
alpha.58 el archivo `latest` se reemplazaba al comenzar una nueva traza y una
prueba no aislada podía escribir en la ruta real. Ambos defectos de
infraestructura/diagnóstico quedaron corregidos después; se conserva aquí el
procedimiento original como historia.

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
