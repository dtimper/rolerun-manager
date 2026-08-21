RoleRun Manager 1.13.0-alpha.6
================================

CAMBIOS INMEDIATOS EN ORAS
--------------------------
Después de pulsar F5 y obtener una sincronización válida con Azahar, ya no hace
falta pulsar GUARDAR CAMBIOS para los cambios que RoleRun sabe escribir de forma
segura en vivo:

- Cambiar un rol del equipo.
- Transferir/intercambiar roles, también desde la barra flotante.
- Aplicar un movimiento normal de drafteo o borrar un movimiento compatible.

Al confirmar la acción en la interfaz, RoleRun la envía automáticamente a
Azahar, verifica el resultado y actualiza RoleRun, OBS y la barra. Verás el
aviso `CAMBIO APLICADO AL MOMENTO` cuando haya terminado.

SEGURIDAD
---------
La comodidad no elimina ninguna comprobación:

- Dos capturas idénticas antes de escribir.
- Identidad, movimiento anterior, checksum y PP comprobados.
- Lectura posterior obligatoria.
- Restauración del PK6 original si el resultado no se puede verificar.

Las acciones compuestas se agrupan antes de enviarse para que, por ejemplo, una
transferencia de rol llegue al juego como una sola operación validada.

TÚ DECIDES CUÁNDO GUARDAR
--------------------------
Esta función solo modifica la RAM que Azahar tiene abierta. No pulsa Guardar en
el juego ni modifica main, estados, ubicación, historia, dinero o inventario.
Guarda desde el menú del juego cuando quieras conservar los cambios; si
reinicias o cargas un estado sin guardar, RoleRun recuperará automáticamente el
equipo real de Azahar, igual que en la alpha.5.

LÍMITES ACTUALES
----------------
MTs, inventario, PC, roles de caja y traslados Equipo ↔ PC todavía no tienen una
escritura de RAM suficientemente segura. Esas operaciones siguen quedando
pendientes y requieren el flujo manual con Azahar cerrado. Si una cola mezcla
una de ellas con un cambio vivo, RoleRun no aplica solo una parte.

PRUEBA RÁPIDA
-------------
1. Abre ORAS y pulsa F5.
2. Cambia un rol o termina un drafteo eligiendo el movimiento que olvidar.
3. Sin pulsar GUARDAR CAMBIOS, comprueba que el cambio aparece en Azahar tras
   el aviso de confirmación.
4. Si quieres que sobreviva a un cierre o Reset, guarda desde el menú del juego
   cuando tú decidas.

La barra flotante conserva el sistema anti-flicker: la confirmación es una capa
temporal y la actualización del equipo se publica una sola vez.
