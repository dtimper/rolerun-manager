RoleRun Manager v0.2.2-alpha.25
=====================================

OBJETIVO
--------
Corregir el bloqueo/lentitud de alpha.24 al descubrir el PC vivo de Pokémon Sol/Luna y probar una referencia live específica sin convertirla en una suposición.

CAMBIO CLAVE
------------
LiveHeX/PKHeX-Plugins publica para Pokémon Sol/Luna v1.2.0:
- Caja 1 / Slot 1: 0x330D9838
- tamaño de slot: 232 bytes (0xE8)

RoleRun usa 0x330D9838 SOLO como candidata. Para aceptarla exige:
1. Matriz completa de 32 cajas x 30 slots x 0xE8.
2. Todos los slots no vacíos superan sanity/checksum/estructura PK7.
3. Doble lectura guest estable.
4. Base host derivada exclusivamente mediante una party host ya demostrada.
5. Doble lectura host estable.
6. Los 0x36600 bytes host y guest son idénticos.
7. Ninguna identidad del equipo vivo aparece duplicada en el PC.
8. Si existe un testigo reciente de party -> PC, debe aparecer dentro de la matriz.

Si cualquiera de esas pruebas falla, NO se publica el PC y NO se escribe ningún byte.

RENDIMIENTO
-----------
El escaneo bruto de ~256 MiB de FCRAM usado por alpha.23/24 ya NO se ejecuta automáticamente al abrir CAJAS PC. Si la referencia no valida, RoleRun aborta rápido y deja diagnóstico. Esto evita que un worker Python de búsqueda masiva compita por el GIL y vuelva lenta la interfaz mientras navegas por cajas.

PRUEBA
------
1. No guardes la partida para actualizar el main; conserva el caso en el que el main no tenía Pokémon en PC.
2. Abre Pokémon Sol y RoleRun alpha.25.
3. Pulsa F5.
4. Entra en CAJAS PC.
5. Comprueba si aparecen los Pokémon actuales de las cajas.
6. Cambia Caja 1 -> Caja 2 -> Caja 3 varias veces: la navegación debe ser inmediata.
7. Si el PC aparece, mueve un Pokémon dentro del PC desde el juego y comprueba que RoleRun se actualiza al refrescar/reconciliar.
8. Si falla, envía Documentos\RoleRun Manager\Logs\sm_pc_diagnostic_latest.json. El JSON debe indicar version 0.2.2-alpha.25 y stage livehex-sm-v120-reference-proof.

SEGURIDAD
---------
- PC de Sol/Luna sigue SOLO LECTURA en esta alpha.
- No se habilitan movimientos Equipo <-> PC desde RoleRun todavía.
- ORAS/X/Y no cambian.
