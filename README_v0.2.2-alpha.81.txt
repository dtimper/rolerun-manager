RoleRun Manager v0.2.2-alpha.81 — el swap BDSP alcanza el writer

- Conserva el selector live de alpha.80, validado físicamente con Pidgeotto.
- Corrige la compuerta que descartaba el cambio Equipo↔PC después de confirmarlo.
- Solo habilita el intercambio 1↔1 ya demostrado; no abre cambios de tamaño.
- Conserva intactas las precondiciones, readback y rollback del writer alpha.78.
- Añade una regresión que fallaba antes del arreglo con cero operaciones encoladas.

Verificación: 64 pruebas BDSP dirigidas y 559 pruebas completas superadas.

Prueba pendiente: cambiar Slowpoke por Pidgeotto desde CAMBIAR CON PC y comprobar
que Pidgeotto queda en el equipo del juego y Slowpoke ocupa Caja 1:1.
