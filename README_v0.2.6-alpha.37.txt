RoleRun Manager v0.2.6-alpha.37 — RoleRun ya sabe leer tu mochila

Programada la lectura. Todavia no se ve en la pantalla del programa: primero
quiero que confirmemos que lee bien.

COMO LEE

Con el mismo cuidado que el resto de Negro 2:

  - lee dos veces seguidas y las dos tienen que salir identicas;
  - comprueba que cada bolsillo esta "apretado" (los objetos al principio y el
    resto vacio, que es como lo guarda el juego);
  - comprueba que cada objeto puede estar en ESE bolsillo (una MT no puede
    aparecer entre las medicinas);
  - comprueba que las cantidades tienen sentido (entre 1 y 999);
  - y que no haya un objeto repetido en dos huecos.

Si algo de eso falla, NO te enseña media mochila inventada: la rechaza entera y
te dice por que.

YA HE COMPROBADO UNA COSA IMPORTANTE

He metido tu mochila real (las 8 cosas que salieron en la lectura anterior) por
el validador y pasa entera. Los 8 objetos son validos en su bolsillo.

Eso importa porque si la lista de objetos de PKHeX no cubriera alguno de los
tuyos, el programa te lo habria rechazado.

QUE DEBES PROBAR AHORA

1. melonDS abierto con tu partida. RoleRun CERRADO.
2. Doble clic en:

       comprobar_mochila_b2w2.bat

3. Te enseñara tu mochila ordenada por bolsillos: OBJETOS, OBJETOS CLAVE,
   MT y MO, MEDICINAS y BAYAS.
4. Abrela en el juego y COMPARA bolsillo por bolsillo.
5. Dime si sobra algo, falta algo o alguna cantidad no cuadra.

Si te sale un mensaje que empieza por "El lector RECHAZO la mochila", copiamelo
entero: significa que algo de la estructura no es como creo.

Cuando confirmes que lee bien, lo siguiente sera enseñarlo dentro de RoleRun, y
despues las MTs.
