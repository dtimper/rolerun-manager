RoleRun Manager v0.3.3-dev

MEJORAS PRINCIPALES
- El paso 4 aparece automáticamente mediante un desplazamiento suave al elegir movimiento.
- Las fichas muestran el rol detectado desde los marcadores del juego.
- Las fichas muestran sprites cuando hay conexión a Internet; después quedan guardados en resources/sprites.
- Tras aplicar un drafteo, la interfaz vuelve correctamente al inicio del flujo.

MAPEO DE MARCADORES
● Círculo: Líbero
▲ Triángulo: Tanque
■ Cuadrado: Asesino
♥ Corazón: Mago
★ Estrella: Support
◆ Rombo: Paladín

Con cero o varios marcadores activos se muestra SIN ROL.

INSTALACIÓN
1. Copia todo el contenido sobre la carpeta actual, conservando .git.
2. Ejecuta preparar_motor.bat, porque el motor ahora también lee los marcadores.
3. Ejecuta instalar_y_abrir.bat, que instalará Pillow además de CustomTkinter.
