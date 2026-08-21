RoleRun Manager 1.13.0-alpha.4
================================

SINCRONIZACIÓN PROTEGIDA CON AZAHAR
-----------------------------------
Esta alpha añade la primera escritura en vivo para Omega Rubí / Zafiro Alfa.
Después de una sincronización F5 confirmada, GUARDAR CAMBIOS puede aplicar al
equipo abierto en Azahar los roles y los cambios normales de movimientos sin
cerrar, reiniciar ni sustituir el archivo main.

FLUJO RECOMENDADO
-----------------
1. Abre ORAS en Azahar y sitúate fuera de combates, animaciones o menús que
   estén cambiando el equipo.
2. Pulsa F5. RoleRun debe mostrar `ORAS en vivo` y seis (o el número real de)
   Pokémon validados.
3. Prepara un cambio de rol o un cambio/borrado normal de movimiento.
4. Pulsa GUARDAR CAMBIOS y confirma `Aplicar cambios en Azahar`.
5. RoleRun realiza dos capturas idénticas, comprueba identidad, movimiento
   previo, checksum y PP; después escribe solo el PK6 almacenado del Pokémon y
   vuelve a leerlo.
6. Cuando aparezca el aviso verde, continúa jugando. Guarda desde el menú del
   juego cuando quieras que Azahar lo persista en `main`.

QUÉ SE ESCRIBE
--------------
- Roles: los seis marcadores PK6 que RoleRun usa para Líbero, Tanque, Asesino,
  Mago, Support y Paladín.
- Movimientos normales de drafteo/reemplazo: ID, PP y checksum del PK6.
- Al borrar un movimiento se compactan también PP y PP-Ups, igual que el motor
  de guardado tradicional.

QUÉ NO SE TOCA
--------------
- El archivo `main` abierto por RoleRun.
- Estados de Azahar, ubicación, historia, dinero, inventario o progreso de la
  partida.
- La parte de estadísticas de combate separada del PK6 en la RAM de ORAS.

GARANTÍAS DE ESTA ALPHA
-----------------------
- No empieza a escribir si la doble captura no coincide o si el Pokémon/movimiento
  ya cambió dentro del juego.
- Tras escribir, vuelve a leer y exige que el rol y los cuatro movimientos
  coincidan exactamente con lo solicitado.
- Si una lectura posterior falla o no coincide, RoleRun restaura el bloque PK6
  original en RAM e informa del resultado. El archivo `main` sigue intacto.
- La barra flotante recibe el mismo aviso compacto, sin reabrir la ventana
  principal ni alterar el arreglo anti-flicker de la 1.12.

LÍMITES INTENCIONADOS
---------------------
- Solo ORAS en Azahar, perfil de memoria `sango-1` / `sango-2`.
- Solo roles y movimientos del equipo que no consumen objetos.
- MTs, inventario, roles del PC y traslados Equipo ↔ PC se bloquean juntos:
  RoleRun no aplica una parte y deja otra pendiente. Para esas operaciones,
  cierra Azahar y usa el flujo normal de guardado hasta la siguiente alpha.
- F5 sigue siendo solo lectura. No ejecuta por sí mismo Guardar cambios ni el
  guardado interno del juego.

SI ALGO FALLA
-------------
- `cambió ese movimiento dentro del juego`: pulsa F5, revisa el moveset actual
  y prepara otra vez el cambio.
- `equipo cambió durante todas las lecturas`: sal de la animación o combate y
  vuelve a intentarlo.
- `no se pudo confirmar la restauración`: no sigas editando. Haz una captura
  del aviso y guarda desde el menú del juego solo si el equipo visible está como
  esperabas; de lo contrario, carga tu último estado seguro antes de continuar.

Esta alpha no intenta falsificar un guardado interno del juego. Ese paso queda
separado deliberadamente: mantener la historia y ubicación reales en ejecución
es más seguro que manipular `main` o un estado de Azahar mientras la partida
está abierta.
