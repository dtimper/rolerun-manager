RoleRun Manager v0.2.6-alpha.33 — buscar la mochila y el dinero

Primero: el combate de Negro 2 está TERMINADO y validado por ti. Daño en tiempo
real, muerte en el momento, vida descontada, selector, sustitución y recuperación
al curar. Todo el ciclo.

QUÉ QUEDA Y POR QUÉ NO PUEDO HACERLO YA

A Negro 2 le faltan cuatro cosas: mochila, MT, utilidades (dinero, objetos) y
medallas.

Las cuatro necesitan saber EN QUÉ PARTE DE LA MEMORIA guarda el juego esos datos.
Y eso no está descubierto todavía. Podría probar direcciones al azar, pero sobre
tu partida no pienso hacerlo.

Así que toca buscarlo, y para eso necesito tu ayuda un momento.

CÓMO LO VOY A BUSCAR (no es a lo loco)

En estos juegos, cada hueco de la mochila son dos números seguidos: QUÉ objeto es
y CUÁNTOS tienes. Si tú me dices cuántas Poké Balls y cuántas Pociones tienes
exactamente, puedo buscar esos pares concretos en la memoria y quedarme solo con
los sitios donde aparecen VARIOS de tus objetos juntos.

Encontrar un número suelto sería casualidad. Encontrar dos o tres de tus objetos
pegados, con sus cantidades exactas, ya no lo es.

Además leo dos veces con una pausa: lo que no aparezca en las dos lecturas era
basura temporal y se descarta.

QUÉ TIENES QUE HACER

1. Abre melonDS con tu partida de Negro 2.
2. CIERRA RoleRun Manager.
3. Dentro del juego, abre la MOCHILA y apunta:
   - cuántas Poké Ball tienes,
   - cuántas Pociones tienes,
   - cuántos Caramelos Raros tienes (si tienes),
   - y cuánto dinero tienes exactamente.
   Si de algo no tienes, no pasa nada: lo dejas vacío.
4. Doble clic en:

       buscar_mochila_b2w2.bat

5. Te irá preguntando esas cantidades. Escribe cada número y pulsa INTRO.
   Si de algo no tienes, pulsa INTRO sin escribir nada.
6. Tardará unos segundos leyendo. NO toques el juego mientras.
7. Te dirá cuántas coincidencias ha encontrado y dónde ha guardado el archivo.
8. Avísame.

El archivo se guarda en:

    diagnostics\manual\b2w2_bag_latest.json

CUANTOS MÁS OBJETOS ME DES, MEJOR

Con uno solo saldrán demasiados sitios posibles. Con dos o tres, la búsqueda se
vuelve muy precisa. Si tienes pocos objetos distintos, dímelo y lo enfoco de otra
forma.

Solo lee. No escribe nada en tu partida.
