RoleRun Manager v0.2.2-alpha.73 — mochila y MT live de BDSP

QUÉ AÑADE

El selector de MT de Perla Reluciente lee ahora las cantidades actuales de la
mochila directamente desde Ryujinx. Ya no presenta el último guardado como si
fuera el estado en tiempo real.

EVIDENCIA Y SEGURIDAD

- La estructura pertenece exclusivamente a Perla Reluciente 1.3.0.
- Se validan exactamente 3.000 registros y dos lecturas idénticas antes de usarla.
- La partida real demostró un Antiparalizador consumido: 10 en el save y 9 en RAM.
- Las siete MT poseídas coincidieron en ID y cantidad.
- La lectura se hace en segundo plano y no bloquea la ventana.
- No existe escritura RAM: BDSP sigue estrictamente en modo de solo lectura.
- Enseñar una MT desde RoleRun continúa pendiente hasta GUARDAR CAMBIOS.
- Mantén desactivado el GDB Stub.

VALIDACIÓN AUTOMATIZADA: 519 tests superados.

PRUEBA FÍSICA MÍNIMA PENDIENTE

1. Reinicia RoleRun y confirma que muestra alpha.73.
2. En el juego, abre la mochila y elige una MT que tengas al menos una vez.
3. En RoleRun, abre EQUIPO, pulsa un hueco de movimiento y comprueba que esa MT
   aparece con la misma cantidad.
4. Sin guardar la partida, usa esa MT dentro del juego sobre un Pokémon que pueda
   aprenderla.
5. Vuelve a abrir el selector de RoleRun: la cantidad debe haber bajado una unidad
   o la MT debe haber desaparecido si solo quedaba una.

No pulses GUARDAR CAMBIOS en RoleRun durante esta prueba.
