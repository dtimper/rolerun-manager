ROLERUN MANAGER v0.3.2-dev
============================

NOVEDAD PRINCIPAL
-----------------
La aplicación usa ahora un único flujo guiado:

1. Abrir y leer la partida guardada.
2. Elegir rol.
3. Elegir uno de los movimientos generados.
4. Elegir uno de los seis Pokémon del equipo.
5. Elegir el movimiento que debe olvidar.
6. Revisar y aplicar el drafteo.

El drafteo permanece bloqueado hasta que el guardado ha sido reconocido.
La selección del guardado lo lee automáticamente: ya no existe un botón separado
para "Leer equipo".

SEGURIDAD
---------
La aplicación sigue sin sobrescribir directamente el archivo cargado:
- crea un backup verificado;
- genera un archivo nuevo;
- vuelve a leerlo para validar el cambio.

INSTALACIÓN
-----------
1. Copia el contenido sobre tu carpeta actual del repositorio.
2. Conserva la carpeta oculta .git.
3. Ejecuta preparar_motor.bat.
4. Ejecuta instalar_y_abrir.bat.
