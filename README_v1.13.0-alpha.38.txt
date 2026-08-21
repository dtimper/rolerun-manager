RoleRun Manager 1.13.0-alpha.38

OBJETIVO DE ESTA BUILD
- Corregir de raíz la detección automática de MEDALLAS en ORAS/Azahar.
- No se implementa Prisma en esta versión; los roles quedan exactamente como estaban.

FALLO RAÍZ ENCONTRADO EN ALPHA.37
1. Alpha.37 estaba leyendo ocho flags de tipo TRAINER BATTLE como si fueran las medallas.
2. En ORAS Gen 6 los flags persistentes de medalla recibida son consecutivos:
   0x807 Stone · 0x808 Knuckle · 0x809 Dynamo · 0x80A Heat
   0x80B Balance · 0x80C Feather · 0x80D Mind · 0x80E Rain.
3. Por eso alpha.37 podía localizar correctamente EventWork vivo y aun así devolver 0.
4. Además, si RAM contenía una copia antigua de EventWork y otra activa, el ranking
   comparaba primero parecido con main y solo después progreso. Una copia vieja con
   0 medallas podía ganar precisamente por parecerse más al último guardado.

CAMBIOS DE ALPHA.38
- La fuente primaria pasa a los ocho flags Received Badge reales: 0x807..0x80E.
- El escáner rápido de EventWork se adapta al patrón real de 2 bytes de esos flags.
- La huella de EventWork excluye los dos bytes de medallas para admitir un main atrasado.
- Se valida que las medallas formen la progresión normal 1..N para reducir falsos positivos.
- En la calibración inicial, si hay varias copias compatibles, se prioriza primero la
  que refleja más progreso de medallas y después el parecido con main.
- Una vez cacheada la copia activa, se mantiene esa misma base: un state-load hacia
  atrás puede reducir el contador sin que RoleRun vuelva a saltar a una copia antigua.
- Misc.Badges continúa como fallback automático si EventWork no puede localizarse.
- Se mantiene todo lo demás de alpha.37/36: tiempo real, MTs, PC/equipo, delay de bajas,
  Cementerio en Caja 4, selector de sustituto, Barra Flotante y OBS.

VERIFICACIÓN TÉCNICA
- PKHeX confirma para ORAS: Misc en 0x4200 (0x130 bytes) y EventWork en 0x14A00
  (0x504 bytes). El layout EventWork es 0x178 ushort + 0xD00 flags.
- 35/35 pruebas específicas de escritura/sincronización ORAS superadas.
- 87/87 pruebas no-UI de integración disponibles en este entorno superadas.
- Añadidas regresiones específicas para:
  * demostrar que los flags usados por alpha.37 NO cuentan como medallas;
  * comprobar 0, 3 y 8 Received Badge;
  * seleccionar la copia viva de 8 frente a una copia stale de 0 más parecida a main;
  * seguir 7 -> 8 sin volver a escanear RAM.

PRUEBA MANUAL RECOMENDADA
A. PARTIDA ACTUAL
1. Abre Azahar y carga tu Zafiro Alfa normalmente.
2. Abre RoleRun Manager y confirma abajo: 1.13.0-alpha.38.
3. Quédate en overworld unos segundos, sin tocar manualmente MEDALLAS.
4. Si tu partida tiene 8 medallas, Dashboard, Barra Flotante y OBS deben pasar a 8.

B. TIEMPO REAL
1. Si puedes usar una partida/state anterior al siguiente gimnasio, comprueba primero N medallas.
2. Derrota al líder y deja que el juego entregue la medalla.
3. RoleRun debe actualizar N -> N+1 automáticamente, sin guardar/cerrar el juego y sin +/-. 

C. REGRESIÓN DE STATE-LOAD
1. Con RoleRun ya sincronizado, carga un state anterior que tenga un número distinto de medallas.
2. El contador debe volver a reflejar la RAM de la partida cargada tras la reconciliación.

IMPORTANTE
- No hace falta pulsar + o -: MEDALLAS sigue siendo 100 % automático en ORAS.
- No se ha tocado el sistema de roles ni se ha introducido Prisma todavía.
