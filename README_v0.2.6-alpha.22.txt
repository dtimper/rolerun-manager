RoleRun Manager v0.2.6-alpha.22 — el parpadeo y los PS de Negro 2

Los dos fallos que me contaste eran el MISMO fallo. Te cuento qué pasaba.

EL PARPADEO DE LA BARRA FLOTANTE

RoleRun mira la partida una vez por segundo. Cuando comprobaba que no había
cambiado nada, en vez de dejar la barra en paz, la destruía entera y la volvía a
construir desde cero, incluidas las dos imágenes que carga del disco.

Es decir: parpadeaba precisamente PORQUE no pasaba nada. Por eso lo veías cada
segundo, sin parar, y por eso llevaba tantas versiones.

Ahora, si no hay novedad, no se toca la barra.

Y he hecho algo más: cuando SÍ cambia la vida de alguien, la barra tampoco se
reconstruye. Solo se mueve la barrita de vida. Así tampoco parpadea en combate,
que es cuando la vida cambia todo el rato.

LOS PS DE TU MAREEP

Negro 2 era el único juego que no avisaba a RoleRun de los cambios de vida.

La comprobación que usa RoleRun para ver si algo ha cambiado en el equipo IGNORA
la vida a propósito: su trabajo es detectar si entra o sale un Pokémon, no si le
han quitado PS. Todos los demás juegos, después de esa comprobación, avisan
aparte de la vida. Negro 2 no lo hacía. Resultado: la ventana principal se
quedaba con los PS antiguos.

Ya está arreglado.

UNA COSA QUE NECESITO SABER

He dejado a propósito un caso en el que RoleRun NO actualiza la vida: cuando no
puede confirmar si estás en combate o no. Es deliberado, porque durante un
combate RoleRun usa la copia "de presentación" para no adelantarte el daño antes
de que el juego te lo enseñe.

Si lo de tu Mareep pasó en una de estas situaciones, dímelo:

  - ¿estaba envenenado, quemado, dormido o congelado?
  - ¿fue dentro de un combate o paseando por el mapa?
  - ¿fue justo al entrar o al salir de un combate?

Con eso puedo confirmar si queda algo más por arreglar.

QUÉ DEBES PROBAR AHORA

1. Abre RoleRun con la barra flotante encima del juego y déjala quieta un rato
   sin hacer nada. NO debe parpadear ni una vez.
2. Entra en combate y recibe daño. La vida debe bajar en la barra flotante de
   forma suave, sin parpadeos.
3. Abre la ventana principal de RoleRun en Equipo y PC y comprueba que los PS
   también se actualizan ahí (esto es lo que no funcionaba con tu Mareep).
4. Envenena o quema a un Pokémon y mira si la vida se sigue actualizando o se
   queda parada. Si se queda parada, avísame: es la pista que me falta.
