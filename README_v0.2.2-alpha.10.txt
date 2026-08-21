RoleRun Manager v0.2.2-alpha.10

Build de diagnóstico y recuperación de roles Sol/Luna.

Cambios clave:
- Mantiene el lector sparse que sí detecta tu party en Azahar.
- Restaura los swaps de rol como una sola transacción, igual que alpha.4.
- Si una escritura falla, RoleRun hace diagnóstico byte a byte antes del rollback.
- Archivo a compartir si falla: Documentos\RoleRun Manager\Logs\sm_write_diagnostic_latest.json
- Movimientos/MT/PC/inventario/progreso SM siguen bloqueados hasta cerrar esta revalidación.

Prueba recomendada:
1) Con Sol/Luna en overworld y la party detectada en vivo, cambia un rol desde la interfaz normal.
2) Si funciona, prueba un intercambio desde la barra flotante.
3) Si falla cualquiera, NO repitas: sube sm_write_diagnostic_latest.json.
