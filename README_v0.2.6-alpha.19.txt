RoleRun Manager v0.2.6-alpha.19 — RoleRun vuelve a mirar el PC del juego

Esto arregla el fallo que encontraste con el Azurill.

QUÉ PASABA

RoleRun leía las cajas del PC del juego al cargar la partida, y a partir de ahí
no las volvía a mirar nunca. Por eso, cuando moviste el Azurill del hueco 7 al 2
dentro del juego, RoleRun se quedó enseñándotelo en el 7. Y al intentar
retirarlo al equipo desde esa pantalla desfasada, se lió.

POR QUÉ PASABA

RoleRun tenía antes dos pantallas separadas, "Equipo" y "PC". Se unificaron en
una sola, la que usas ahora. La comprobación que decide si hay que vigilar el PC
del juego se quedó preguntando por la pantalla vieja, que ya no existe como tal.
Como esa pantalla nunca está activa, la vigilancia no se ponía en marcha jamás.

No era un problema de Negro 2 ni de melonDS: afectaba igual a Perla Reluciente.

QUÉ CAMBIA AHORA

RoleRun vuelve a vigilar el PC del juego mientras tienes Equipo y PC abierto, y
lo relee al entrar en esa pantalla. Si mueves algo desde el juego, RoleRun se
entera solo en un par de segundos.

IMPORTANTE: tu partida nunca estuvo en peligro

Aunque la pantalla estuviera desfasada, RoleRun comprueba la identidad y la
posición reales en la memoria del juego antes de escribir nada, y deshace la
operación si no cuadran. Lo que viste fue un problema de lo que se mostraba, no
de lo que se escribió.

LO QUE TODAVÍA NO SÉ

No he podido demostrar el mecanismo exacto de la duplicación que viste. Lo que
sí está demostrado y arreglado es lo que te dejó en esa situación. Si vuelve a
ocurrirte, dímelo con el mayor detalle posible y lo instrumentaré para cazarlo.

QUÉ DEBES PROBAR AHORA

1. Abre Negro 2 en melonDS y carga la partida en RoleRun.
2. Con Equipo y PC abierto en RoleRun, mueve un Pokémon de una caja a otro hueco
   DENTRO DEL JUEGO.
3. Espera dos o tres segundos SIN tocar nada en RoleRun.
4. Comprueba que RoleRun lo enseña ya en su hueco nuevo.
5. Ahora sí, prueba a retirarlo al equipo desde RoleRun y comprueba en el juego
   que el resultado es correcto y que NO aparece duplicado.

Si en el paso 4 sigue apareciendo en el hueco antiguo, dímelo: significaría que
queda otra causa distinta y la buscaré.
