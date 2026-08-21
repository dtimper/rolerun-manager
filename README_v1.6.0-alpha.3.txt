ROLERUN MANAGER v1.6.0-alpha.3
================================

Corrección de lectura de guardados .dsv mientras DeSmuME está abierto.

- El motor abre el archivo con uso compartido de lectura/escritura.
- Reintenta automáticamente si DeSmuME está escribiendo justo en ese instante.
- La lectura se realiza desde una instantánea en memoria y el manejador se cierra inmediatamente.
- Sigue siendo recomendable cerrar o pausar el juego antes de GUARDAR CAMBIOS para evitar que el emulador sobrescriba el guardado modificado.
- Se mantiene la compatibilidad con .sav y el pie original de DeSmuME.
