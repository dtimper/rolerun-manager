RoleRun Manager 1.13.0-alpha.39

OBJETIVO DE ESTA BUILD
- Abandonar como vía principal los dos métodos de medallas que han fallado en tu Azahar.
- Detectar las medallas por una tercera evidencia independiente: el historial de equipos con los que se ganó cada gimnasio.
- Dejar un diagnóstico visible para que, si todavía falla en tu PC, sepamos exactamente qué lector produjo el 0.
- NO se implementa Prisma; los roles siguen exactamente como estaban.

NUEVO MÉTODO: SUBE / BADGEVICTORY
- ORAS conserva un bloque SubEventLog (SUBE) separado de Misc y EventWork.
- Dentro existe una tabla de 8 gimnasios x 6 huecos de equipo. Cada hueco guarda el ID de especie del Pokémon usado al conseguir esa medalla.
- Si el registro del gimnasio N contiene al menos una especie válida, esa victoria ocurrió.
- RoleRun cuenta esa progresión directamente: 0, 1, 2... 8.
- Esto funciona con randomizer: no importa qué especies salieran, solo que sean especies válidas de Gen 6.

POR QUÉ ES DISTINTO DE ALPHA.35-38
- No lee el byte Misc.Badges.
- No lee los flags Received Badge de EventWork.
- No intenta deducir una medalla a partir de una zona desbloqueada.
- Busca una estructura histórica dedicada a las victorias de gimnasio.

LOCALIZACIÓN EN RAM
- El bloque tiene cinco firmas SUBE a posiciones conocidas. RoleRun exige que encajen todas, además de validar la tabla 8x6.
- Se escanean varias bandas del heap alrededor de las estructuras ORAS conocidas, no solo el MiB anterior a la party.
- Si hay una copia vieja y otra activa, gana la que tenga más progreso.
- Cuando se identifica la copia viva, se cachea su dirección. Un state-load puede hacer 8 -> 5 sin que RoleRun cambie de copia.
- Si no se encuentra, hay un backoff de 8 segundos antes de reintentar el escaneo grande para evitar stutter.

FALLBACKS
1. SUBE vivo / historial de gimnasios.
2. EventWork vivo / Received Badge.
3. Misc vivo / contador.
4. Mejor dato disponible del main, incluyendo SUBE guardado.

DIAGNÓSTICO NUEVO
Tras uno o varios segundos, la esquina superior derecha debe terminar mostrando algo parecido a:
- medallas SUBE:8       -> éxito del método nuevo en RAM viva.
- medallas main:8       -> el historial guardado ya demuestra las 8, aunque no se localizó SUBE vivo.
- medallas EventWork:0  -> SUBE no fue localizado y el fallback EventWork sigue dando 0.
- medallas Misc:0       -> SUBE/EventWork no dieron lectura válida y Misc sigue en 0.

PRUEBA MANUAL 1 — TU PARTIDA ACTUAL (PRIORITARIA)
1. Abre Azahar y carga la misma partida de la captura, donde la ficha de entrenador enseña las 8 medallas.
2. Abre RoleRun Manager y comprueba abajo: 1.13.0-alpha.39.
3. Entra en la Run y espera 5-15 segundos en overworld. La primera calibración puede ser más lenta porque busca SUBE en RAM.
4. MEDALLAS debería pasar automáticamente a 8.
5. Mira también la línea verde de la esquina superior derecha y anota qué aparece tras `medallas` (ideal: SUBE:8).
6. No uses ningún +/-.

PRUEBA MANUAL 2 — TIEMPO REAL REAL
Solo si la prueba 1 da 8:
1. Carga un state anterior a un gimnasio con N medallas.
2. Espera a que RoleRun muestre N y preferiblemente `medallas SUBE:N`.
3. Derrota al líder y recibe la medalla normalmente.
4. Sin guardar dentro del juego, espera unos segundos. Debe cambiar N -> N+1.
5. Carga de nuevo el state anterior. Debe volver N+1 -> N.

SI SIGUE EN 0
- No hace falta adivinar otro método todavía. Haz una captura donde se vea la línea verde superior de RoleRun completa.
- Con `SUBE`, `EventWork`, `Misc` o `main` sabremos cuál fue exactamente la última fuente disponible y podremos atacar el punto preciso.

VERIFICACIÓN AUTOMÁTICA
- 43/43 pruebas específicas de ORAS/medallas superadas.
- 95/95 pruebas no-UI de integración superadas.
- Compilación sintáctica completa de app/tests correcta.
- La suite que importa customtkinter no puede ejecutarse en este contenedor porque esa dependencia gráfica no está instalada; el código UI modificado sí pasa compileall.
