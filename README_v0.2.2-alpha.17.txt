RoleRun Manager v0.2.2-alpha.17 — Pokémon Sol/Luna · CALIBRACIÓN MT MULTI-ANCLA
================================================================================

OBJETIVO DE ESTA ALPHA
----------------------
Corregir el falso bloqueo observado al pulsar "+" en alpha.16:
"No se pudo demostrar una única party host antes de leer la mochila de MT".

CAUSA CORREGIDA
---------------
Alpha.16 exigía que existiera exactamente una copia host de la party antes de intentar
localizar la mochila. Esa unicidad era una condición intermedia innecesaria: Azahar puede
mantener copias/buffers idénticos de la party aunque solo una de ellas pertenezca al backing
FCRAM que mantiene la misma relación de direcciones con la mochila guest real.

QUÉ CAMBIA
----------
- RoleRun ya no elige una party host duplicada ni aborta solo porque haya varias.
- Prueba TODAS las parties host que coinciden exactamente con stored PK7 + stats + stride.
- Para cada ancla intenta demostrar la mochila con la lógica exacta/estructural de alpha.16.
- Una ruta solo cuenta si la mochila host encontrada coincide también byte por byte con la
  dirección guest derivada y leída mediante Azahar RPC.
- Solo se acepta el selector si al FINAL existe exactamente una ruta completa
  host-party -> host-bag -> guest-bag.
- Si hay cero rutas completas, se aborta.
- Si hay dos o más rutas completas igualmente válidas, también se aborta.
- Antes de devolver la lista de MT se relee de nuevo el bloque host y guest para detectar
  cambios ocurridos durante la calibración.
- La caché de mochila se invalida mientras se comparan las anclas para impedir que una
  calibración anterior haga parecer válida una party distinta del mismo proceso.

DIAGNÓSTICO
-----------
Si todavía no puede demostrarse la mochila, RoleRun genera:
Documentos\RoleRun Manager\Logs\sm_utility_diagnostic_latest.json

El diagnóstico de alpha.17 incluye ahora el número de parties host candidatas, cada ancla,
la ruta aceptada/rechazada y el motivo del rechazo.

LO QUE NO CAMBIA
----------------
- Tabla MT efectiva leída de la ROM real.
- Lectura de mochila viva.
- MT reutilizable: no se consume.
- Compatibilidad determinada por reglas RoleRun, no por especie vanilla.
- Sustituto permitido para Asesino/Mago.
- Writer PK7, checksum, identidad, relectura y rollback.
- Roles, movimientos, Caramelo Raro, Repelente Máximo y dinero.
- ORAS/X/Y.

PRUEBAS AUTOMÁTICAS
-------------------
285/285 tests pasan en esta build.

PRUEBA MANUAL PRINCIPAL
-----------------------
1. Abre Pokémon Sol/Luna en el overworld.
2. Pulsa F5 en RoleRun.
3. En Equipo pulsa "+" en un hueco de movimiento.
4. Debe abrirse el selector mostrando las MT que posees realmente.
5. Enseña una MT y comprueba inmediatamente el movimiento dentro del juego.
6. Comprueba que la MT sigue en la mochila.
7. Guarda/reinicia y comprueba persistencia.

Si el punto 4 todavía falla, enviar directamente sm_utility_diagnostic_latest.json.
No hace falta repetir pruebas a ciegas.
