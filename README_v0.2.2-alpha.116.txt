RoleRun Manager v0.2.2-alpha.116
================================

Esta versión corrige dos regresiones demostradas de alpha.115:

- una pulsación normal del mando ya no activa el autorrepetido; el primer
  movimiento es inmediato y mantener una dirección inicia la repetición tras
  450 ms;
- Drafteos recibe los datos live de naturaleza, estadísticas, estadísticas
  base, IV y EV aunque no hayan cambiado la identidad ni los movimientos del
  equipo persistido.

No se modifica lógica RAM ni se realizan escrituras nuevas.
