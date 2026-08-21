RoleRun Manager 1.13.0-alpha.30
================================

Objetivo de esta alpha: coherencia total entre ORAS, Cajas PC, bajas y Barra Flotante.

CAMBIOS PRINCIPALES
-------------------

1. PC DEL JUEGO -> ROLERUN
- Cuando cambia la composición del equipo desde el PC de ORAS, RoleRun hace una lectura viva y estable de las cajas en segundo plano.
- Se cubren los tres flujos del PC del juego:
  * MOVER POKÉMON: sustitución directa equipo <-> PC.
  * SACAR POKÉMON: el equipo crece y el hueco origen del PC queda vacío.
  * DEJAR POKÉMON: el equipo disminuye y RoleRun localiza la casilla real donde ORAS depositó al Pokémon.
- Cajas PC muestra la diferencia viva respecto al último main sin exigir guardar la partida.

2. BAJAS DURANTE EL COMBATE
- RoleRun lee un carril de party de batalla de ORAS exclusivamente para observar PS actuales.
- La transición PS > 0 -> 0 se detecta durante el combate, aunque la party normal de ORAS todavía no haya copiado esos PS.
- En ese momento se descuenta una vida y el Pokémon deja de aparecer en RoleRun/OBS/Barra Flotante.
- Esta lectura de batalla es solo lectura y no se usa para reorganizar el equipo.

3. SELECTOR AL TERMINAR EL COMBATE
- El selector de sustituto sigue sin interrumpir el combate.
- Tras la baja, RoleRun observa el cambio batalla -> overworld.
- Después de dos lecturas consecutivas fuera de combate, sale automáticamente de Barra Flotante y abre una única ventana ELIGE AL SUSTITUTO DE...
- Si el primer 0 PS solo pudiera verse ya fuera del combate, existe una ruta de respaldo que infiere el fin del combate tras dos lecturas estables de overworld.
- El Pokémon muerto continúa enviándose a Caja 4 (Cementerio).

4. COHERENCIA ENTRE VISTAS
- Un Pokémon con baja pendiente se oculta mediante la misma proyección en Dashboard, Equipo, OBS y Barra Flotante.
- Ya no puede aparecer muerto en la ventana normal mientras falta en la barra.

5. BARRA FLOTANTE
- Los mensajes verdes/técnicos de reconciliación (por ejemplo ESTADO DE ORAS RECUPERADO) quedan suprimidos en la HUD.
- Se conserva el mecanismo estable de apertura/render de la alpha.24/28; los cambios de esta alpha se ejecutan alrededor de la barra, no reescribiendo su sistema de ventanas.

CEMENTERIO
----------
Caja 4 queda reservada para Pokémon debilitados y no se ofrece como origen de sustitutos.

VALIDACIÓN AUTOMÁTICA
---------------------
97 pruebas superadas.
