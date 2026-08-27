RoleRun Manager v0.2.6-alpha.29 — la baja ya tiene salida

Tenías razón en todo, y los cuatro síntomas venían de MUY poco.

QUÉ PASABA

Cuando un Pokémon cae, RoleRun espera a que TERMINE el combate antes de
ofrecerte el sustituto (para no interrumpirte a mitad de pelea). Para saber que
el combate ha terminado, cada juego tiene que ir avisando de si estás dentro o
fuera de combate.

Negro 2 no avisaba. Nunca.

Así que la baja se quedaba marcada como "combate aún sin terminar" para siempre.
Y de ahí salían tres de tus cuatro síntomas de golpe:

  - no aparecía la opción de sustituir (requiere combate terminado),
  - curar al debilitado no lo devolvía (la limpieza requiere lo mismo),
  - reiniciar tampoco servía (la baja se guarda en tu Run).

Además faltaba otro aviso: si resolvías la baja desde el PC del propio juego,
RoleRun no se enteraba. También arreglado.

EL HUECO QUE SE MOVÍA DE ROL

Esto era distinto, y también tenías razón. La casilla pertenece al ROL, no al
Pokémon, y es justo la casilla que heredará el sustituto. Pero un Pokémon SIN
ROL podía colarse en el hueco del caído, empujando el hueco visible a otro rol.

Por eso veías el puesto de Support vacío cuando quien había caído era el Asesino.

Ahora, mientras haya una baja pendiente, su casilla queda reservada y visible.

SOBRE QUE NO SE DESCUENTE LA VIDA DURANTE EL COMBATE

Esto NO lo doy por resuelto. Con los avisos de combate ya en su sitio es probable
que funcione, pero no lo he podido demostrar, así que quiero que lo mires
específicamente en la prueba.

QUÉ DEBES PROBAR AHORA

Save state antes.

1. Ponle rol a dos o tres Pokémon, como la otra vez.
2. Deja que uno con rol se debilite EN COMBATE. Mira si RoleRun te descuenta la
   vida en ese momento o al salir del combate. Dime cuál de las dos.
3. Al salir del combate, comprueba que:
   - la casilla vacía es la DEL ROL DEL CAÍDO (no otra),
   - y que RoleRun te abre el selector de sustituto.
4. Elige sustituto y comprueba en el juego: caído en la Caja 4, sustituto en el
   equipo con el rol heredado, casilla de origen vacía.
5. Prueba aparte: deja caer a otro, NO uses el selector, y cúralo en un Centro
   Pokémon. Debería volver a aparecer en su casilla.
6. Prueba aparte: deja caer a otro y resuélvelo tú desde el PC del juego
   (guárdalo y saca a otro). RoleRun debería enterarse solo.

El punto 2 es el que más me interesa.
