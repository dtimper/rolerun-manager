RoleRun Manager v0.2.6-alpha.17 — arranque y seguimiento más fiables

Tres arreglos que afectan a todos los juegos, no solo a B2/W2.

1) El seguimiento en vivo podía dejar de actualizarse al guardar en el juego

Si guardabas dentro del juego justo mientras RoleRun estaba leyendo la partida,
RoleRun podía quedarse "conectado" pero sin volver a leer nada, hasta el
siguiente guardado. Todo parecía normal, simplemente dejaba de actualizarse.
Ya no ocurre: la lectura que queda obsoleta vuelve a poner en marcha el
seguimiento.

2) Un fallo al leer el archivo de guardado se tomaba como una respuesta

Cuando RoleRun necesita distinguir si has reiniciado la partida o si has hecho
un cambio jugando, compara la memoria con tu archivo de guardado. Si esa lectura
fallaba, RoleRun daba por hecha una respuesta que en realidad nunca obtuvo.
Ahora reconoce que no lo sabe, lo apunta y lo vuelve a intentar.

3) Sin Internet, RoleRun podía quedarse en la pantalla de carga para siempre

RoleRun esperaba a tener todas las imágenes de tu equipo antes de abrirse. Si no
había Internet y alguna imagen no estaba descargada aún, esa espera no terminaba
nunca. Ahora, si una imagen no se puede descargar:

- se muestra una silueta en su lugar,
- aparece un aviso que NO bloquea nada,
- y RoleRun abre la partida con normalidad.

La imagen se vuelve a intentar la próxima vez que se recargue la partida.
Además, las descargas tienen ahora un límite de 8 segundos y no se lanzan varias
descargas de la misma especie a la vez.

QUÉ DEBES PROBAR AHORA

Sigue pendiente la prueba de la alpha.16 (retirar del PC al equipo en Negro 2),
que es la más importante. Y si quieres comprobar lo de esta versión:

1. Desconecta el WiFi del PC.
2. Abre RoleRun y carga una partida que tenga algún Pokémon cuya imagen no
   hayas visto antes.
3. Comprueba que RoleRun ABRE la partida (antes se quedaba cargando), que ese
   Pokémon aparece con una silueta gris y que sale un aviso que puedes ignorar.
4. Vuelve a conectar el WiFi, guarda dentro del juego y comprueba que la imagen
   real aparece.
