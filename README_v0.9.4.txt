ROLERUN MANAGER v0.9.4 · OBS PERMANENTE
========================================

Esta versión separa la aplicación de los datos del usuario.

RUTA PERMANENTE DE DATOS:
Documentos\RoleRun Manager\

RUTA PERMANENTE PARA OBS:
Documentos\RoleRun Manager\OBS\

Configura las fuentes de OBS una sola vez para leer esa carpeta. Las próximas
actualizaciones de RoleRun Manager mantendrán exactamente las mismas rutas.

La carpeta OBS contiene:
- vidas.txt
- curaciones.txt
- medallas.txt
- drafteos.txt
- libero.html
- tanque.html
- asesino.html
- mago.html
- support.html
- paladin.html

Al abrir otra Run, esos mismos archivos pasan a mostrar automáticamente la Run
activa. El programa conserva además una copia OBS dentro de cada Run por
compatibilidad y diagnóstico.

MIGRACIÓN
---------
Al arrancar, RoleRun Manager busca Runs antiguas dentro de la carpeta del
programa y las copia a Documentos\RoleRun Manager\Runs sin sobrescribir datos
ya existentes.

IMPORTANTE
----------
Después de instalar esta versión tendrás que cambiar las rutas de OBS una última
vez para que apunten a Documentos\RoleRun Manager\OBS. Desde entonces no será
necesario volver a cambiarlas en futuras actualizaciones.
