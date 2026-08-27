RoleRun Manager v0.2.6-alpha.25 — la ficha ya no sale vacía y los EV se reparten

Lo primero: el writer de roles de la versión anterior FUNCIONA. Confirmaste que
la marca se escribió en el juego y que la barra flotante muestra LÍBERO. Bien.

Los dos fallos que quedaban:

1) LA FICHA SALÍA CON TODO EN "—"

RoleRun tiene una comprobación para decidir si la partida ha cambiado. Esa
comprobación mira si ha entrado o salido alguien, si han cambiado de orden, de
rol, de ataques o de nivel. A propósito NO mira estadísticas, IV ni EV.

Negro 2 solo refrescaba la ficha cuando esa comprobación decía "algo cambió".
Así que en cuanto RoleRun releía tu partida desde el archivo guardado (por
ejemplo, al guardar tú dentro del juego), perdía las estadísticas y ya no las
recuperaba nunca.

Por eso al ponerle un rol a uno "aparecían los stats": cambiar el rol SÍ activaba
esa comprobación.

Ahora RoleRun también refresca cuando ve que tiene datos que a la ficha le
faltan. Ocurre una vez y se acabó, no se repite en bucle.

2) LOS EV NO SE REPARTÍAN

El reparto de EV de cada rol estaba limitado a una lista de juegos... escrita a
mano en SIETE sitios distintos del código. Negro 2 no estaba en ninguno.

Ahora esa lista está en un único sitio con nombre propio, y Negro 2 está dentro.
Lo he dejado así aposta para que no vuelva a pasar: olvidarse de un juego en uno
de siete sitios era cuestión de tiempo.

OJO CON LÍBERO: en Líbero RoleRun NO reparte los EV automáticamente, y es
intencionado. Primero te pregunta qué dos características quieres. Como el rol
que probaste fue justo Líbero, es normal que no vieras reparto.

QUÉ DEBES PROBAR AHORA

1. Abre RoleRun y comprueba que la ficha de CUALQUIER Pokémon (aunque esté
   SIN ROL) ya muestra estadísticas, BASE, IV y EV con números.
2. Guarda dentro del juego y comprueba que la ficha SIGUE mostrando esos datos
   (antes se quedaban en "—" justo después de guardar).
3. Asigna un rol que NO sea Líbero (por ejemplo Tanque o Mago) y comprueba:
   - en RoleRun, que los EV de ese Pokémon cambian,
   - en el juego, que sus estadísticas suben de forma coherente.
4. Prueba Líbero y comprueba que RoleRun te pregunta las dos características
   antes de escribir nada.

Si en el paso 3 los EV siguen sin moverse, mándame captura de la ficha.
