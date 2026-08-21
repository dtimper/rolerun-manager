RoleRun Manager 1.13.0-alpha.42

OBJETIVO DE ESTA BUILD
- Rework completo de roles solicitado tras validar las 8 medallas en alpha.41.
- Mantener intacta la detección automática de medallas de alpha.41.
- Sustituir Paladín por Prisma y aplicar las nuevas reglas también a los drafteos.

ORDEN DE ROLES
Líbero -> Asesino -> Mago -> Tanque -> Prisma -> Support

LÍBERO / ASESINO / MAGO / SUPPORT
Conservan las reglas que ya tenían en alpha.41.

TANQUE
- Puede usar movimientos de daño físicos y especiales.
- No puede usar movimientos de daño que recuperen PS al usuario (Puño Drenaje, Gigadrenado, etc.).
- Puede usar protecciones.
- Puede usar Acua Aro y Arraigo como únicas formas permitidas de recuperación mediante movimiento.
- Un movimiento de estado es válido si aumenta Defensa física y NO aumenta Defensa Especial.
- Ejemplos válidos: Corpulencia, Defensa Férrea, Danza Triunfal.
- Ejemplos inválidos: Danza Aleteo, Paz Mental, Masa Cósmica, Recuperación.
- La vieja excepción global de Velocidad NO vuelve legal un movimiento para Tanque si no aumenta Defensa física.

PRISMA
- Puede usar movimientos de daño físicos y especiales.
- No puede usar movimientos de daño que recuperen PS al usuario.
- Puede usar protecciones.
- Puede usar Acua Aro y Arraigo como únicas formas permitidas de recuperación mediante movimiento.
- Un movimiento de estado es válido si aumenta Defensa Especial y NO aumenta Defensa física.
- Puede aumentar además Ataque, Ataque Especial, Velocidad u otras stats mientras cumpla lo anterior.
- Ejemplos válidos: Amnesia, Paz Mental, Geocontrol, Danza Aleteo, Bálsamo Osado.
- Ejemplos inválidos: Corpulencia, Danza Triunfal, Masa Cósmica, Recuperación.
- La vieja excepción global de Velocidad NO vuelve legal un movimiento para Prisma si no aumenta Defensa Especial.

DRAFTEOS
Tanque:
1. Subir Defensa Física
2. Protección
3. Recuperación Pasiva (Acua Aro / Arraigo)
4. Ataque Físico sin drenaje
5. Ataque Especial sin drenaje

Prisma:
1. Subir Defensa Especial
2. Protección
3. Recuperación Pasiva (Acua Aro / Arraigo)
4. Ataque Físico sin drenaje
5. Ataque Especial sin drenaje

Asesino, Mago y Support conservan exactamente sus categorías previas.

COMPATIBILIDAD CON RUNS ANTERIORES
- El sexto marcador físico de Pokémon que antes RoleRun llamaba Paladín pasa a mostrarse como Prisma.
- No se remapean los seis bits físicos del Pokémon: así actualizar no convierte silenciosamente Tanques/Asesinos/Magos/Supports ya existentes en otros roles.
- Los nombres Paladín/paladin persistidos se migran a Prisma al cargar la Run.
- OBS genera prisma.html, pero paladin.html continúa funcionando como alias de Prisma para no romper escenas antiguas.
- El SaveEngine empaquetado sigue entendiendo internamente el nombre histórico Paladín; la app traduce Prisma solo en ese borde de compatibilidad.

ATAJOS POR DEFECTO EN RUNS NUEVAS
Alt+1 Líbero
Alt+2 Asesino
Alt+3 Mago
Alt+4 Tanque
Alt+5 Prisma
Alt+6 Support
Si una Run tenía atajos personalizados, se conservan por rol.

MEDALLAS ORAS
No se ha cambiado la detección de alpha.41. La partida que ya detectaba 8 debe seguir detectando 8.
No hace falta ejecutar preparar_motor.bat para probar esta build si RoleRun ya abre correctamente.

PRUEBAS MANUALES RECOMENDADAS
1. Abre tu Run ORAS y confirma que las medallas siguen marcando 8.
2. Comprueba el orden visual: Líbero, Asesino, Mago, Tanque, Prisma, Support.
3. Abre Drafteos y confirma que aparece Prisma y ya no aparece Paladín.
4. Genera un drafteo de Tanque: deben salir las cinco categorías nuevas indicadas arriba.
5. Genera un drafteo de Prisma: deben salir sus cinco categorías nuevas.
6. Cambia un Pokémon a Tanque y comprueba ejemplos: Corpulencia válida; Masa Cósmica/Danza Aleteo inválidas; Puño Drenaje inválido; Acua Aro válido.
7. Cambia un Pokémon a Prisma: Danza Aleteo/Paz Mental válidas; Masa Cósmica/Corpulencia inválidas; Gigadrenado inválido; Arraigo válido.
8. Comprueba que Asesino, Mago y Support se comportan igual que antes.

VERIFICACIÓN AUTOMÁTICA
- 9/9 pruebas nuevas específicas del rework de roles.
- 109/109 pruebas no-UI seleccionadas superadas (incluyen ORAS, medallas alpha.41, Azahar RPC, roles en vivo y RunService).
- compileall de app, tests y main.py correcto.
- Los tests que importan customtkinter no se ejecutan en el entorno de empaquetado porque esa dependencia gráfica no está instalada aquí.
