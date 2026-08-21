RoleRun Manager v0.2.2-alpha.48
=====================================

USUM — DIAGNÓSTICO PC CORREGIDO CONTRA EL MAIN

Objetivo de esta build:
- Repetir la prueba de CAJAS PC de alpha.47, pero corrigiendo el bug que
  impedía que el diagnóstico usara el `main` configurado.
- NO habilitar todavía escrituras de PC ni aceptar una matriz parcial.

Alpha.47 confirmó de nuevo que la candidata 0x33015AB0 deja de parsear
PK7 válidos en Caja 8, hueco 1, pero el diagnóstico auxiliar falló con:
  UnboundLocalError: save_path

Alpha.48 conserva correctamente el path del guardado y, si la matriz vuelve
a fallar, genera:
  Documentos\RoleRun Manager\Logs\usum_pc_diagnostic_latest.json

El JSON debe incluir ahora, además del error RAM:
- `saved_boxlayout.boxes_unlocked_raw`;
- `saved_boxlayout.current_box_raw`;
- `guest_current_box_reference`;
- comparación por cajas RAM vs main;
- primeros slots inválidos con bytes live y bytes del save;
- `contiguous_fully_valid_boxes`;
- `fcram_scan_attempted=false`;
- NO debe existir `diagnostic_error`.

PRUEBA FÍSICA:
1. Abre UltraSol/UltraLuna y alpha.48.
2. Entra una sola vez en CAJAS PC.
3. Espera al aviso. No debe congelarse.
4. Pasa `usum_pc_diagnostic_latest.json` al chat.
5. No uses ENVIAR AL PC ni PC→Equipo en esta build diagnóstica.

Regresión interna: 396/396 tests.
