RoleRun Manager v0.2.2-alpha.20

OBJETIVO DE ESTA BUILD
- Abrir el bloque PC de Pokémon Sol/Luna con una primera fase deliberadamente SOLO LECTURA.
- Demostrar en Azahar real la matriz completa de cajas PK7 antes de habilitar cualquier escritura Equipo ↔ PC.

CADENA DE DEMOSTRACIÓN
1. RoleRun usa las dimensiones reales de cajas devueltas por PKHeX/SaveEngine para el main abierto.
2. Dentro de ESE main busca la matriz de cajas mediante identidades fuertes (especie + PID + TID + SID) y posiciones caja/slot conocidas.
3. El offset hallado dentro del archivo nunca se usa como dirección RAM.
4. De la matriz del main se extraen varios PK7 completos y distribuidos como testigos exactos.
5. Esos PK7 solo se buscan en la región RW host de Azahar que contiene una copia de party ya demostrada por contenido.
6. Cada candidatura host se traslada a guest mediante el delta respecto a la party correspondiente.
7. La matriz completa se lee dos veces en host y dos veces por Azahar RPC.
8. Solo se acepta si las cuatro lecturas son idénticas y todos los huecos se parsean como PK7 válidos o vacíos.
9. Si hay cero o más de una base guest válida, RoleRun no publica una caja falsa.

RENDIMIENTO
- La localización inicial del PC se ejecuta en un hilo de background; no debe congelar Tk.
- Una matriz demostrada queda cacheada para esa sesión de Azahar.
- Las siguientes sincronizaciones releen directamente la matriz completa host+guest y vuelven a validarla; no repiten el escaneo FCRAM mientras la prueba siga siendo válida.

SEGURIDAD DE ALPHA.20
- PC Sol/Luna es SOLO LECTURA.
- ENVIAR AL PC, Equipo ↔ PC y cambio de rol de Pokémon en caja están bloqueados en sesión live SM.
- Estos botones no crean cambios pendientes falsos.
- Haz los movimientos desde el PC del propio Pokémon Sol/Luna; RoleRun debe detectarlos.
- ORAS/X/Y conservan su comportamiento anterior.

DIAGNÓSTICO
- Si la matriz no puede demostrarse, RoleRun conserva la última vista conocida y no sustituye el PC por cajas vacías.
- Diagnóstico: Documentos\RoleRun Manager\Logs\sm_pc_diagnostic_latest.json
- El diagnóstico contiene bases/candidaturas y motivos de rechazo, no un volcado completo de las cajas.

PRUEBA MANUAL RECOMENDADA
1. Abrir Pokémon Sol/Luna en overworld y pulsar F5.
2. Entrar en CAJAS PC de RoleRun.
3. La primera validación puede tardar algo, pero la ventana debe seguir respondiendo.
4. Comparar varios Pokémon y varias cajas con el PC del juego.
5. Desde el juego, mover un Pokémon de una casilla del PC a otra y comprobar que RoleRun lo refleja.
6. Desde el juego, sacar un Pokémon del PC al equipo y comprobar party + casilla vacía en RoleRun.
7. Desde el juego, dejar/intercambiar un Pokémon del equipo con el PC y comprobar ambas partes.
8. Cambiar una marca de rol a un Pokémon guardado en caja desde el juego y comprobar que RoleRun lee el nuevo marcador.
9. Volver a abrir CAJAS PC: la segunda lectura debería ser bastante más rápida por la caché validada.
10. Probar un botón de escritura de PC desde RoleRun: alpha.20 debe bloquearlo e indicar que esta fase es solo lectura.

REGRESIÓN AUTOMÁTICA
- 297/297 tests.
