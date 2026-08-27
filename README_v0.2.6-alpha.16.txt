RoleRun Manager v0.2.6-alpha.16 — retirada B2/W2 y botón CURAR

Dos fallos corregidos en Blanco 2 / Negro 2.

1) Retirar un Pokémon del PC al equipo no podía funcionar nunca

Al retirar, RoleRun dejaba la casilla del PC "en blanco" de una forma que el
propio RoleRun no reconocía como casilla vacía. Al comprobar el resultado se
rechazaba a sí mismo y deshacía la operación entera. Por eso la retirada
fallaba siempre, aunque todo lo demás estuviera bien.

Ahora la casilla liberada queda exactamente igual que cuando retiras desde el
propio juego. Eso está demostrado con la captura que hicimos en Negro 2: al
retirar dentro del juego, RoleRun leyó las 717 casillas vacías sin ningún error.

2) El botón CURAR aparecía en B2/W2 sin poder curar

Al pulsarlo, RoleRun se quedaba con seis peticiones de curación que nadie
ejecutaba ni retiraba, y mientras existieran esas peticiones el seguimiento en
vivo de la partida dejaba de actualizarse. El botón se retira de B2/W2 hasta que
la curación esté realmente implementada y probada en el juego.

QUÉ DEBES PROBAR AHORA (prueba física guiada, en Negro 2 con melonDS)

Necesito que hagas esto tú porque hay que verlo dentro del juego:

1. Abre melonDS con tu partida de Negro 2 y conecta RoleRun como siempre.
2. Deja el equipo con 5 Pokémon (si tienes 6, deposita uno en el PC).
3. Desde RoleRun, retira del PC un Pokémon SIN objeto equipado y mándalo al
   equipo.
4. Comprueba en RoleRun que el equipo pasa a 6 y que la casilla del PC de donde
   salió queda vacía.
5. Entra en el juego, abre el equipo y el PC, y comprueba lo mismo allí: 6
   miembros, en el orden correcto, y la casilla del PC vacía.
6. Guarda dentro del juego y avísame.

Si algo no cuadra, dime exactamente qué viste en RoleRun y qué viste en el juego.
No hace falta que busques nada técnico.

Nota: la curación de B2/W2 sigue sin estar disponible a propósito. Es la
siguiente en la lista.
