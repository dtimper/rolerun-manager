ROLERUN MANAGER v1.6.0-alpha.2
================================

Corrección de compatibilidad con guardados .dsv de DeSmuME en Pokémon Blanco / Negro.

- Extrae automáticamente el bloque SAV interno de 512 KiB antes de cargarlo con PKHeX.Core.
- Conserva intacto el pie propio de DeSmuME al volver a guardar.
- Mantiene compatibilidad directa con archivos .sav estándar.
- La misma lectura corregida se usa al validar el archivo generado.

Esta versión requiere volver a ejecutar preparar_motor.bat.
