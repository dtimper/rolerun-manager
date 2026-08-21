RoleRun Manager 1.13.0-alpha.8
================================

CORRECCIÓN URGENTE DEL PC EN ORAS 1.4
-------------------------------------
La alpha.7 usaba para las cajas la dirección de memoria de ORAS 1.0. Por eso,
al intentar cambiar el rol de un Pokémon del PC, RoleRun mostraba el aviso de
checksum/especie y no escribía ningún byte.

La alpha.8 usa la base correcta de ORAS 1.4. Después de pulsar F5, cambia un
rol de un Pokémon de caja: debe aplicarse automáticamente y la marca debe
aparecer también al abrir esa caja dentro del juego.

No se ha relajado ninguna protección: antes de escribir sigue comprobándose el
PK6 completo del hueco, y cualquier fallo sigue cancelando la operación.

El resto de la alpha.7 se mantiene igual: roles del equipo, movimientos,
inventario y MTs estándar siguen siendo operaciones vivas; los traslados
físicos Equipo ↔ PC continúan protegidos hasta tener una ruta completa y segura.
