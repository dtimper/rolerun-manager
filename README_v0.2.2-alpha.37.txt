RoleRun Manager v0.2.2-alpha.37 — Sol/Luna · Equipo ↔ PC autosuficiente

CAMBIOS CLAVE
- ENVIAR AL PC ya no requiere abrir CAJAS PC antes.
- La propia operación demuestra la matriz PC viva de la sesión antes de escribir.
- ENVIAR AL PC elige el primer hueco libre REAL del PC live, no el que indique un main antiguo.
- PC → EQUIPO también recalibra automáticamente la matriz si la sesión/caché cambió.
- Se mantienen verificación y rollback de BoxPokemon + PartyData + mirror runtime.

PRUEBAS RECOMENDADAS
1. Arranca RoleRun y Pokémon Sol. NO abras CAJAS PC.
2. Desde EQUIPO pulsa ENVIAR AL PC sobre un miembro intermedio. Debe reducirse la party y el Pokémon debe aparecer en el primer hueco libre real.
3. Abre CAJAS PC y devuelve ese Pokémon al equipo con un hueco libre. Debe recibir el primer rol libre de izquierda a derecha.
4. Repite tras reiniciar Azahar/RoleRun para comprobar que la matriz se recalibra sin pasos manuales.
5. Si el main está desfasado y su primer hueco libre está ocupado en vivo, RoleRun no debe sobrescribirlo.

VALIDACIÓN INTERNA
- 346/346 tests.
- 122 archivos Python compilan.
