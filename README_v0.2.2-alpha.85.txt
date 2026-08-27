RoleRun Manager v0.2.2-alpha.85 — utilidades realtime BDSP

CORRECCIÓN HISTÓRICA (alpha.86): la prueba física demostró que el ID 79 es
Repelente normal. Repelente Máximo es el ID 77. Este README conserva el alcance
de la entrega alpha.85, pero no debe usarse como evidencia de identidad.

- Caramelo Raro ×999, Repelente Máximo ×999 y dinero máximo se aplican
  automáticamente en Perla Reluciente 1.3.0 / Ryujinx.
- Alpha.85 usó Caramelo Raro 50 y, erróneamente, 79 para el botón rotulado
  Repelente Máximo; la corrección está en alpha.86.
- El máximo real de dinero de BDSP es 999.999 ₽.
- Cada acción relee party, mochila y MYSTATUS, exige sesión estable y compara
  guest/host antes de escribir.
- Los objetos conservan flags y orden; si un objeto nunca obtuvo una posición
  válida en la mochila, la acción se cierra sin inventarla ni escribir RAM.
- El readback verifica el bloque completo de 3.000 objetos, MYSTATUS y party.
- Cualquier fallo restaura los bytes anteriores y verifica el rollback.
- No se modifica ningún backend 3DS ni se habilita el cambio manual de rol de
  Pokémon que permanecen dentro del PC, descartado por decisión de producto.

Verificación: 115 pruebas BDSP dirigidas y 580 pruebas completas superadas.

Validación física pendiente: una única prueba conjunta de los tres botones.
