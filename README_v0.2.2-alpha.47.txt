RoleRun Manager v0.2.2-alpha.47
=====================================

USUM — DIAGNÓSTICO ACOTADO DEL LAYOUT PC

Objetivo de esta build:
- NO intentar todavía una nueva corrección de CAJAS PC.
- Demostrar por qué la referencia 0x33015AB0 deja de formar PK7 válidos en la
  partida real, sin volver a escanear FCRAM ni escribir memoria.

Al abrir CAJAS PC, si la matriz 32x30 vuelve a fallar, RoleRun genera:
  Documentos\RoleRun Manager\Logs\usum_pc_diagnostic_latest.json

El diagnóstico contiene:
- doble lectura estable de 0x36600 bytes desde 0x33015AB0;
- clasificación de los 960 slots live por caja;
- primer prefijo continuo de slots/cajas PK7 válidos;
- hasta 12 primeros slots inválidos con dirección y bytes;
- comparación de esos slots contra el main configurado;
- BoxesUnlocked y CurrentBox leídos del BoxLayout del main;
- CurrentboxOffset guest 0x33015AA7;
- confirmación fcram_scan_attempted=false.

PRUEBA FÍSICA:
1. Abre UltraSol/UltraLuna y alpha.47.
2. Entra una sola vez en CAJAS PC.
3. Espera al aviso (debe aparecer sin congelar RoleRun).
4. Pasa `usum_pc_diagnostic_latest.json` al chat.
5. No uses ENVIAR AL PC ni PC→Equipo en esta build diagnóstica.

No se ha relajado sanity/checksum ni se publican cajas parciales como reales.
Regresión interna: 395/395 tests.
