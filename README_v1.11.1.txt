RoleRun Manager 1.11.1

PARCHE DE BORRADO DE MOVIMIENTOS

- Un movimiento eliminado ya no se representa escribiendo un movimiento "-" en el guardado.
- El motor escribe el ID 0 real de hueco vacío.
- Al eliminar un movimiento, los movimientos posteriores se compactan hacia la izquierda.
- El único hueco vacío queda siempre en el cuarto slot.
- PP y PP Ups se desplazan junto con su movimiento; el último slot se limpia por completo.
- Si se eliminan varios movimientos del mismo Pokémon, se procesan de derecha a izquierda para evitar borrar un movimiento distinto tras la compactación.
- Tras escribir el guardado, el motor lo vuelve a cargar y comprueba los cuatro slots. Si detecta una modificación inesperada, descarta el archivo generado.

IMPORTANTE:
Esta actualización modifica el motor de guardados. Ejecuta preparar_motor.bat una vez antes de usar la versión parcheada.
