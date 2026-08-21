RoleRun Manager v0.3.1-dev

NOVEDAD PRINCIPAL
- Ya no se escribe manualmente el movimiento.
- En Drafteo, pulsa ELEGIR sobre una de las opciones generadas.
- Ve a Partida guardada, selecciona un Pokémon y el ataque que debe olvidar.
- El programa crea un backup, genera un guardado nuevo, lo recarga y valida el cambio.

FLUJO DE PRUEBA
1. Ejecuta preparar_motor.bat.
2. Abre instalar_y_abrir.bat.
3. Genera un rol en Drafteo.
4. Pulsa ELEGIR en un movimiento.
5. Ve a Partida guardada.
6. Abre y lee tu guardado de prueba.
7. Pulsa ENSEÑAR [MOVIMIENTO] en el Pokémon deseado.
8. Elige qué ataque debe olvidar y confirma.

SEGURIDAD
- No se sobrescribe el archivo cargado.
- Cada aplicación crea un backup verificado.
- El archivo resultante se recarga para comprobar que el movimiento quedó escrito.
- Después de aplicar un drafteo, el archivo resultante pasa a ser el guardado de trabajo para que los cambios posteriores sean acumulativos.

NOTA SOBRE LEGALIDAD
RoleRun se juega con ataques randomizados. Esta versión no comprueba si la especie aprende legalmente el movimiento; solo exige que el movimiento exista en la base compatible con el guardado.
