RoleRun Manager v0.2.2-alpha.72 — movimientos entre cajas BDSP

QUÉ AÑADE

Mientras CAJAS PC está visible, RoleRun comprueba de forma acotada si un
Pokémon se ha movido entre dos cajas dentro del juego. No hace falta cambiar de
pestaña ni alterar el equipo para actualizar origen y destino.

SEGURIDAD Y RENDIMIENTO

- Se reutiliza la matriz 40×30 ya demostrada; no hay direcciones nuevas.
- Se realiza una lectura cada 2,5 segundos y nunca hay dos simultáneas.
- Si nada cambia, RoleRun no reconstruye la pantalla.
- El sondeo se detiene al salir de CAJAS PC, minimizar RoleRun, usar la barra
  flotante, cambiar de Run o encontrar un error.
- BDSP continúa estrictamente en modo de solo lectura.
- Mantén desactivado el GDB Stub.

VALIDACIÓN AUTOMATIZADA: 510 tests superados.

VALIDACIÓN FÍSICA

Completada el 22/08/2026 en Perla Reluciente 1.3.0 sobre Ryujinx 1.3.3 con GDB
desactivado. Un Aipom se movió entre dos cajas con la party estable; RoleRun
actualizó origen y destino. Siete comprobaciones posteriores sin cambios no
repintaron la página y el usuario no observó parpadeos.

PRUEBA FÍSICA MÍNIMA

1. Reinicia RoleRun y confirma que muestra alpha.72.
2. Abre CAJAS PC y deja visible la caja donde está un Pokémon reconocible.
3. Dentro del juego, mueve ese Pokémon a un hueco vacío de otra caja sin tocar
   el equipo.
4. Vuelve a la caja de origen en RoleRun y espera hasta cuatro segundos: el
   hueco debe quedar vacío sin cambiar de pestaña.
5. Ve en RoleRun a la caja de destino: el Pokémon debe aparecer con icono, nivel
   y rol correctos.
6. Mantén la vista quieta unos diez segundos y confirma que no parpadea ni se
   reconstruye continuamente.

No uses los botones de RoleRun para moverlo; esta prueba valida solo lectura.
