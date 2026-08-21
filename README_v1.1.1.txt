ROLERUN MANAGER v1.1.1
=========================

NOVEDAD: CARPETAS OBS SEPARADAS POR JUEGO

Los archivos permanentes de OBS ahora se generan en:

  Documentos\RoleRun Manager\OBS\BDSP
  Documentos\RoleRun Manager\OBS\USUM

Cada carpeta contiene sus propios contadores, HTML, state.json y sprites.
De esta forma, las escenas de BDSP y USUM pueden permanecer configuradas simultáneamente sin sobreescribirse.

Al abrir por primera vez una Run, el programa copia automáticamente los archivos OBS antiguos de la raíz a la carpeta de ese juego si todavía no existen. Los archivos originales no se eliminan.

IMPORTANTE: tendrás que cambiar en OBS las rutas una sola vez:
- escena BDSP -> carpeta OBS\BDSP
- escena USUM -> carpeta OBS\USUM

Las siguientes actualizaciones conservarán esas rutas.
