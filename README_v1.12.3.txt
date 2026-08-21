RoleRun Manager 1.12.3
======================

Esta revisión consolida el PC como parte del Team Builder y cambia la filosofía de roles para que el programa informe y facilite sin tomar decisiones por el jugador.

NOVEDADES PRINCIPALES
---------------------
- Los Pokémon que ya estaban en el PC no reciben un rol automáticamente por sus marcas o por su moveset. Permanecen SIN ROL hasta que el usuario les asigna uno expresamente en RoleRun Manager.
- Los roles asignados expresamente desde el Manager pueden gestionarse también dentro del PC y se conservan al mover el Pokémon al equipo.
- Corregida la previsualización de intercambios Equipo ↔ PC: durante un cambio pendiente, el Pokémon que sale del equipo aparece en el hueco del PC que va a ocupar y el Pokémon entrante deja de mostrarse en la caja.
- CAMBIAR ROL, tanto en Equipo como en PC, permite previsualizar cada rol antes de aceptarlo. Los movimientos incompatibles se muestran en rojo.
- Cambiar de rol nunca obliga a borrar movimientos incompatibles. El cambio puede guardarse y la tarjeta del Pokémon sigue señalando en rojo los movimientos que no encajan.
- Cuando existen movimientos incompatibles, aparece ELIMINAR ATAQUES INCOMPATIBLES como acción voluntaria.
- Eliminado el botón REVISAR EQUIPO: la comprobación de movimientos es automática y permanente en las tarjetas.
- Asignar un rol ocupado a un Pokémon activo sigue solicitando confirmación y deja al anterior propietario SIN ROL, sin tocar su moveset.
- El motor nativo añade escritura de roles en Pokémon almacenados en las cajas y expone de forma explícita el primer hueco libre del PC.

ACTUALIZACIÓN DEL MOTOR
-----------------------
Esta versión SÍ necesita recompilar el motor nativo una vez.

La forma recomendada es ejecutar instalar_y_abrir.bat. El instalador detecta automáticamente un motor anterior y ejecuta preparar_motor.bat.

abrir_rolerun.bat también comprueba desde esta versión el marcador del motor y lanza preparar_motor.bat automáticamente si todavía falta actualizarlo.
