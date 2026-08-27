RoleRun Manager v0.2.2-alpha.86 — Repelente Máximo BDSP corregido

- Corrige la identidad de la utilidad: Repelente Máximo es el objeto BDSP 77;
  el 79 que alpha.85 modificó es Repelente normal.
- Si el Repelente Máximo todavía no existe en la mochila, RoleRun crea su
  registro con el siguiente orden válido del mismo bolsillo, igual que BDSP y
  PKHeX, sin pedir que se consiga antes una unidad.
- El writer conserva el Repelente normal y los otros 2.998 registros intactos,
  relee guest/host, verifica el resultado completo y mantiene rollback.
- Caramelo Raro ×999 y dinero máximo quedaron validados físicamente en
  alpha.85; no se modifican sus rutas.
- La corrección queda limitada a Perla Reluciente 1.3.0 / Ryujinx y no toca
  backends 3DS.

Verificación: 130 pruebas BDSP dirigidas y 581 pruebas completas superadas.

Validación física completada: el usuario confirmó «Repelente Máximo ×999» en la
mochila. Las tres utilidades BDSP quedan cerradas para SP 1.3.0 / Ryujinx.
