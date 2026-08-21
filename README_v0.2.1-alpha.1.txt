RoleRun Manager 0.2.1-alpha.1
===============================

REAL-TIME CORE · primera integración
------------------------------------
Esta build inaugura la rama 0.2.1. El objetivo ya no es añadir parches
específicos a ORAS, sino convertir ORAS en la implementación de referencia de
un sistema de tiempo real reutilizable por el resto de juegos.

Qué cambia por dentro
---------------------
Se añade app/realtime/ con cuatro contratos principales:

1. RealTimeGameAdapter
   Cada juego traduce sus offsets, bloques y particularidades a operaciones
   comunes. ORAS/Azahar es el primer adaptador real.

2. RealTimeSnapshot
   Un ciclo lógico contiene en un único objeto:
   - Equipo vivo estable.
   - Proceso/emulador.
   - Bloques auxiliares vigilados.
   - Estado/PS de batalla.
   - Medallas y fuente utilizada.
   - Diagnóstico por carril.

3. RealTimeCore
   Secuencia snapshots, conserva la última captura válida, genera eventos
   semánticos y centraliza las lecturas/escrituras vivas.

4. RealTimeEvent Engine
   Compara snapshots sin conocer offsets y puede producir eventos comunes:
   equipo, orden, rol, moveset, nivel, baja, medalla y estado de batalla.
   En esta alpha trabaja en paralelo a la lógica histórica de ORAS: no sustituye
   todavía los automatismos cerrados, para evitar regresiones.

ORAS ya pasa por el Core
------------------------
La UI deja de montar directamente tres lecturas independientes para el monitor.
Ahora RealTimeCore encapsula:
- party estable;
- sonda de batalla;
- medallas.

También pasan por el Core:
- lectura viva del PC;
- lectura viva de MT/MO;
- escrituras verificadas en RAM.

Los algoritmos maduros de ORAS (medallas alpha.41+, mochila alpha.45, PC,
marcadores, muertes, etc.) NO se han reescrito: el adaptador los reutiliza. La
prioridad de esta build es cambiar la arquitectura sin perder comportamiento.

Aislamiento de fallos
---------------------
Batalla y medallas son carriles opcionales. Si una animación o estructura
transitoria hace fallar uno de ellos, el snapshot de party continúa siendo
válido. El fallo queda registrado como diagnóstico en vez de tumbar el monitor.

Registro para pruebas offline
-----------------------------
Se incorpora RealTimeSessionRecorder. Puede guardar snapshots en NDJSON,
incluidos (cuando se solicite) los bloques auxiliares de RAM y los eventos
semánticos. Aún no se activa automáticamente desde la interfaz: queda como base
para añadir en una alpha posterior un botón de "paquete de diagnóstico" que nos
permita reproducir sesiones de otros juegos sin tener físicamente esa partida.

Registro multi-juego
--------------------
RealTimeRegistry permite registrar un Core por juego. En esta build solo ORAS
está registrado. El siguiente juego podrá añadirse como otro adaptador sin que
Dashboard/OBS tengan que aprender otra arquitectura.

Qué NO cambia
-------------
- Medallas: se mantiene el detector que ya reconoce correctamente las 8.
- MTs: se mantiene la mochila viva validada de alpha.45.
- Roles: se mantiene Líbero, Asesino, Mago, Tanque, Prisma, Support.
- PC y buscador: sin cambios funcionales.
- Muertes automáticas y delay visual: sin cambios funcionales.
- Motor .NET: no necesita recompilarse.

Pruebas manuales recomendadas
-----------------------------
Esta build debe sentirse igual que alpha.45. Comprueba:
1. Abrir una Run ORAS sin ejecutar preparar_motor.bat.
2. Detección automática de 8 medallas.
3. Equipo vivo y cambios de rol.
4. Sustituir un movimiento mediante MT: debe seguir leyendo la mochila viva.
5. Abrir PC y buscador global.
6. Cambiar un Pokémon entre Equipo y PC y comprobar la sincronización.
7. Si puedes, cargar un state anterior y comprobar que RoleRun recupera el
   estado real sin quedarse bloqueado.

Verificación automática
------------------------
- 160/160 tests superados usando un stub mínimo de CustomTkinter para el único
  test que importa la UI sin preparar esa dependencia en Linux.
- Nuevos tests del Real-Time Core: secuenciación, eventos, aislamiento de
  carriles, recorder, registry y compatibilidad del adaptador ORAS.
- compileall correcto.

Siguiente fase sugerida
-----------------------
0.2.1-alpha.2: extraer al Core el sistema común de resolución/caché de bloques
vivos y añadir el generador de paquete de diagnóstico/replay desde la UI. Después
podremos empezar a implementar X/Y reutilizando esa infraestructura.
