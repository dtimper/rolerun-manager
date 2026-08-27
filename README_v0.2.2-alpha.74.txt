RoleRun Manager v0.2.2-alpha.74 — movimientos y marcadores BDSP

QUÉ CORRIGE

- SUSTITUIR vuelve a estar disponible en movimientos ocupados de BDSP. La
  mochila se valida al pulsar, en segundo plano, sin bloquear la interfaz.
- ELIMINAR ATAQUE conserva la compactación y el hueco libre aunque llegue un
  nuevo snapshot de Ryujinx antes de guardar.
- Un Pokémon que entra mediante CAMBIAR CON PC hereda siempre el rol del que
  sale. El marcador se escribe en el guardado junto con la sustitución.
- Las Runs antiguas migran los marcadores al orden definitivo:
  círculo=Líbero, triángulo=Asesino, cuadrado=Mago, corazón=Tanque,
  estrella=Prisma y rombo=Support.

SEGURIDAD

- BDSP continúa sin ningún writer RAM.
- Los cambios quedan pendientes hasta GUARDAR CAMBIOS.
- La migración de marcadores es un lote indivisible y solo cambia el contrato
  de la Run después de releer y validar físicamente los seis bits de la salida.
- El guardado mantiene backup, copia anterior visible, reemplazo atómico y
  restauración ante fallo.
- Los intercambios hechos directamente dentro del PC del juego se siguen
  observando en solo lectura; RoleRun no inventa una normalización RAM.
- Mantén desactivado el GDB Stub.

VALIDACIÓN AUTOMATIZADA: 523 tests superados.

PRUEBA FÍSICA

1. Guarda normalmente dentro del juego y ciérralo antes de aplicar cambios.
2. Reinicia RoleRun y confirma que muestra alpha.74. Si GUARDAR CAMBIOS aparece
   activo por la migración de marcadores, púlsalo y vuelve a abrir el juego.
3. En EQUIPO, pulsa SUSTITUIR junto a un ataque rojo: debe abrir el selector de
   MT y mostrar las cantidades actuales.
4. Pulsa ELIMINAR ATAQUE en otro ataque rojo: debe desaparecer, compactarse los
   restantes y aparecer un botón + en el cuarto hueco.
5. Usa DESCARTAR si solo querías comprobar la previsualización. Para validar la
   escritura, prepara una sustitución por MT, cierra el juego, pulsa GUARDAR
   CAMBIOS y vuelve a abrirlo; comprueba movimiento, PP y cantidad de MT.

VALIDACIÓN FÍSICA ACTUAL

- Confirmados SUSTITUIR, ELIMINAR ATAQUE y la compactación visual.
- Confirmado el decremento live después de consumir una MT dentro del juego.
- Pendiente: aplicar desde RoleRun una MT o marcador, guardar, reiniciar y
  comprobar movimiento, PP, cantidad y marcador dentro del juego.
