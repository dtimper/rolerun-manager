RoleRun Manager v0.2.2-alpha.22

Objetivo de esta alpha
======================
Diagnóstico seguro del localizador PC live de Pokémon Sol/Luna.

Qué corrige
===========
Alpha.21 sí encontraba una copia host de la party, pero cuando el fallback
Items -> Misc -> BoxLayout -> BoxPokemon rechazaba la candidatura, el bloque
`except` sobrescribía la evidencia interna antes de escribir el JSON.

Por eso un diagnóstico podía mostrar:
  party_target_count: 1
  evaluated: []

Alpha.22 conserva esa evidencia.

Qué NO cambia
=============
- No habilita escrituras Equipo <-> PC en Sol/Luna.
- No asume ninguna dirección nueva.
- No relaja host==guest.
- No convierte offsets de archivo en direcciones RAM sin demostración.

Prueba
======
1. Mantén el main actual; no hace falta guardar la partida.
2. Abre Pokémon Sol en el overworld y pulsa F5.
3. Abre CAJAS PC y reproduce el error.
4. Envía:
   Documentos\RoleRun Manager\Logs\sm_pc_diagnostic_latest.json

El JSON debe indicar version 0.2.2-alpha.22 y, a diferencia de alpha.21,
`evaluated` debe contener la candidatura y el motivo exacto de rechazo.

Validación automática
=====================
303 tests pasan.
