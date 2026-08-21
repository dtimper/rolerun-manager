ROLERUN MANAGER v0.3.0-dev
==========================

OBJETIVO DE ESTA VERSIÓN
- Leer el equipo de un guardado compatible mediante PKHeX.Core.
- Elegir un Pokémon y uno de sus cuatro huecos.
- Sustituir el movimiento en una COPIA NUEVA del guardado.
- Recargar esa copia y validar automáticamente que el cambio quedó escrito.

SEGURIDAD
- La v0.3 se niega a sobrescribir el archivo original.
- Antes de cada prueba crea un backup verificado en /backups.
- El resultado se guarda junto al original con el nombre *_rolerun_v03_FECHA.bin.
- Cierra la emulación antes de manipular guardados.

PRUEBA RECOMENDADA
1. Usa una copia de SaveData.bin.
2. Pulsa LEER EQUIPO.
3. Pulsa PROBAR CAMBIO DE MOVIMIENTO en un Pokémon.
4. Sustituye un movimiento por otro fácilmente reconocible.
5. Prueba el archivo nuevo en una carpeta de guardado separada.
6. Conserva siempre el original y el backup.

LIMITACIONES
- Interfaz y nombres de movimientos en inglés por ahora.
- No comprueba todavía si el Pokémon aprende legalmente el movimiento.
- No conecta todavía el resultado de la ruleta con el editor.
- No edita el guardado en vivo ni con el emulador abierto.
