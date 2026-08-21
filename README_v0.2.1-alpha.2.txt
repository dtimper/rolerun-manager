RoleRun Manager 0.2.1-alpha.2
===============================

REAL-TIME CORE · resolver común + diagnóstico/replay
----------------------------------------------------
Esta build continúa la generalización iniciada en alpha.1. ORAS debe sentirse
igual por fuera; el trabajo importante está en que los próximos juegos puedan
reutilizar las soluciones que ya hemos validado.

1. LiveBlockResolver común
--------------------------
Se extrae a infraestructura común el patrón que resolvió los problemas más
difíciles de ORAS con copias viejas/desplazadas de RAM:

- validar primero una dirección cacheada;
- conservarla mientras siga siendo estructuralmente válida (también si un
  state-load hace retroceder el progreso);
- probar direcciones conocidas solo como candidatos, nunca como verdad;
- ejecutar barridos caros únicamente cuando fallan los candidatos baratos;
- validar y puntuar todos los candidatos;
- elegir el mejor, cachearlo e invalidarlo si deja de ser válido;
- aplicar cooldown después de un barrido fallido.

La mochila MT/MO de ORAS ya usa este resolver común. Por tanto, la solución que
permitió que medallas y selector de MT compartieran la misma mochila viva deja
de ser un parche exclusivo de ORAS y pasa a ser la plantilla para X/Y, SM, USUM,
etc.

2. Diagnóstico desde Configuración
----------------------------------
En una Run ORAS aparece una nueva tarjeta:

REAL-TIME CORE · DIAGNÓSTICO Y REPLAY

Permite:
- VER ESTADO: muestra proceso, perfil, medallas, batalla, carriles, eventos y
  direcciones de RAM resueltas por el Core.
- INICIAR GRABACIÓN: comienza una captura manual de snapshots/eventos.
- DETENER Y GENERAR PAQUETE: crea un ZIP listo para compartir y depurar.
- ABRIR REPLAY: valida/inspecciona un ZIP o NDJSON grabado previamente.
- CARPETA: abre Documentos/RoleRun Manager/Logs/Realtime Diagnostics.

La grabación NO escribe RAM ni modifica el guardado. Durante ella el Core añade
solo bloques pequeños ya localizados que resulten útiles para depuración; no
vuelca las 31 cajas completas en cada tick.

3. Paquete reproducible
-----------------------
El ZIP contiene:
- session.ndjson: snapshots, eventos, diagnósticos, bloques auxiliares y estado
  técnico del adaptador;
- manifest.json: versión, Run, juego, rango de secuencias y número de frames;
- LEEME.txt.

RealTimeReplay puede abrir tanto el ZIP como el NDJSON directamente. Así, cuando
falle una transición en otro juego, podremos estudiar exactamente qué vio el
Core sin depender de volver a estar delante de esa partida.

4. Diagnóstico por adaptador
----------------------------
ORAS expone ahora al Core el bridge utilizado (Azahar/RPC), cachés relevantes y
resoluciones del LiveBlockResolver. Mientras se graba, los bloques pequeños ya
calibrados se incorporan automáticamente al snapshot de diagnóstico.

Qué NO cambia
-------------
- Detección de medallas ORAS: conserva el método validado que detecta 8.
- MTs vivas: siguen usando la mochila correcta; ahora pasa por resolver común.
- PC y buscador global: sin cambios funcionales.
- Roles y marcadores: sin cambios funcionales.
- Muertes, sustituciones, OBS y barra flotante: sin cambios funcionales.
- No hace falta ejecutar preparar_motor.bat.

Pruebas manuales recomendadas
-----------------------------
1. Abrir ORAS normalmente y confirmar que todo sigue igual que alpha.1.
2. Verificar medallas, PC, buscador y selector de MT.
3. Ir a CONFIGURACIÓN > REAL-TIME CORE · DIAGNÓSTICO Y REPLAY.
4. Pulsar VER ESTADO y comprobar que muestra proceso/carriles.
5. Pulsar INICIAR GRABACIÓN, jugar/moverte unos segundos y DETENER Y GENERAR
   PAQUETE.
6. Pulsar ABRIR REPLAY y seleccionar el ZIP recién generado: debe reconocerlo y
   mostrar frames, secuencias, adaptador, medallas y eventos.

Verificación automática
------------------------
- 161/161 tests no-UI superados.
- Regresiones nuevas del resolver común: ranking inicial, caché tras state-load,
  barrido solo cuando hace falta y caché validada.
- Regresiones de recorder: captura de bloques diagnósticos, ZIP/manifest y replay
  directo desde el paquete.
- Todos los tests ORAS live-write/medallas/MT continúan pasando.
- compileall correcto.

Siguiente fase sugerida
-----------------------
Con alpha.2 ya disponemos de Snapshot, eventos, adaptadores, resolver de RAM y
replay. El siguiente paso natural es comenzar X/Y como segundo adaptador real y
usar esta infraestructura para medir cuánto código específico del juego queda.
