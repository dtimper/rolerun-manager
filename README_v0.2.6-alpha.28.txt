RoleRun Manager v0.2.6-alpha.28 — bajas y sustitución en Negro 2

Esto es el corazón de una RoleRun, y ya está.

Lo he podido hacer ahora porque sus tres piezas las validaste tú estos días: el
combate, los roles y el PC.

QUÉ HACE AHORA

Cuando un Pokémon de tu equipo cae a 0 PS en Negro 2:

  - RoleRun lo detecta,
  - te descuenta una vida,
  - lo registra en el historial,
  - y te abre el selector para elegir sustituto.

Al elegirlo:

  - el debilitado se va al Cementerio (Caja 4),
  - el sustituto entra en el equipo,
  - y hereda el rol del que ha caído.

UN DETALLE QUE ME IMPORTABA

Esta operación toca TRES sitios a la vez: el sustituto sale de su caja, el
debilitado va al Cementerio, y la casilla de donde salió el sustituto queda
vacía. Si algo se corta a medias, lo último que quiero es que un Pokémon
desaparezca.

Por eso escribo en un orden concreto: primero copio al debilitado al Cementerio,
después meto al sustituto en el equipo, y solo al final vacío su casilla de
origen. Así, en cualquier momento intermedio, como mucho hay un Pokémon
duplicado (recuperable), nunca uno perdido.

Hay una prueba automática que lo comprueba escritura por escritura.

Y como siempre: si algo no cuadra, deshace las tres posiciones.

QUÉ DEBES PROBAR AHORA

Save state antes, por favor. Esto mueve Pokémon de sitio.

1. Ten al menos un Pokémon en el PC que puedas usar de sustituto, SIN objeto
   equipado, y deja la Caja 4 (Cementerio) con hueco.
2. Deja que un miembro de tu equipo se debilite EN COMBATE.
3. Comprueba que RoleRun:
   - te descuenta una vida,
   - te abre el selector de sustituto.
4. Elige el sustituto y comprueba EN EL JUEGO:
   - el debilitado está en la Caja 4,
   - el sustituto está en tu equipo,
   - la casilla de donde salió el sustituto está vacía,
   - el equipo sigue teniendo el mismo número de miembros.
5. En RoleRun, comprueba que el sustituto ha heredado el rol del caído.
6. Guarda en el juego y vuelve a comprobarlo todo.

Prueba también, si puedes, que un Pokémon se debilite FUERA de combate (por
veneno andando) y comprueba que también lo detecta.

LO QUE QUEDA EN NEGRO 2

Mochila y MT, utilidades (dinero, objetos) y medallas.

Aviso sobre mochila/MT: esa necesita una dirección de memoria que todavía no
está demostrada. Cuando lleguemos, lo primero será prepararte una captura guiada
para obtenerla; no me la puedo inventar.
