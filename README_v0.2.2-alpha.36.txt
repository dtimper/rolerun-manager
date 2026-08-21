RoleRun Manager v0.2.2-alpha.37 — Sol/Luna · Equipo ↔ PC completo

OBJETIVO DE ESTA BUILD
Completar las dos operaciones de PC que faltaban después de validar el swap 1↔1 en alpha.35:
- ENVIAR AL PC: reduce el equipo y compacta la party.
- PC → EQUIPO con hueco libre: aumenta el equipo y asigna el primer rol libre de izquierda a derecha.

IMPLEMENTACIÓN SEGURA
- Reutiliza la matriz BoxPokemon live ya demostrada host↔guest.
- Reutiliza el writer alpha.35: PartyData 0x104 + mirror runtime +0x158 + BoxPokemon 0xE8.
- ENVIAR AL PC no reconstruye los miembros desplazados: copia sus PartyData y mirrors live ya demostrados para compactar.
- Si la party tiene menos de 6 miembros, el slot final vacío se toma de un slot vacío live ya demostrado.
- En 6→5, el último slot queda con PK7 vacío canónico (sanity/checksum/species = 0) y mirror de stats vacío.
- PC→Equipo solo ocupa party_count+1 y obliga al primer rol libre según ROLE_ORDER.
- La UI de Sol/Luna no proyecta ningún traslado antes de que el juego lo confirme.
- Cualquier fallo ejecuta rollback y verifica host+guest antes de devolver error.

PRUEBAS AUTOMÁTICAS
345/345 tests pasan.
122 archivos Python compilan correctamente.

PRUEBAS MANUALES RECOMENDADAS
1. Con 6 Pokémon, usa ENVIAR AL PC sobre un miembro intermedio.
   - Debe desaparecer del equipo dentro de Pokémon Sol.
   - Los posteriores deben compactarse sin huecos.
   - Debe aparecer en el hueco PC elegido por RoleRun.
2. Repite con 5→4 y, si quieres, 4→3.
3. Con un hueco libre en el equipo, desde CAJAS PC mete un Pokémon al equipo.
   - Debe entrar al final de la party.
   - Debe desaparecer de su hueco del PC.
   - Debe recibir el primer rol libre de izquierda a derecha.
4. Prueba ida y vuelta y guarda/reinicia la emulación para comprobar persistencia.
5. RoleRun debe impedir enviar al PC al último Pokémon del equipo.
