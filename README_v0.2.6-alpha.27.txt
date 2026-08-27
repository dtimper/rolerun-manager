RoleRun Manager v0.2.6-alpha.27 — que no se vuelva a congelar el seguimiento

Esta versión no añade nada nuevo: cierra de raíz el fallo que nos ha costado tres
rondas de diagnóstico.

QUÉ PASABA

RoleRun no lee la partida mientras tengas cambios preparados, para no pisar lo
que estás montando. Muy razonable... salvo si uno de esos cambios es algo que ese
juego todavía no sabe escribir: entonces no sale nunca de la lista, y RoleRun se
queda esperando para siempre.

Te pasó dos veces:

  - con CURAR en Negro 2 (lo tapé quitando el botón),
  - y con los roles, que se manifestó como TRES fallos distintos a la vez:
    "los roles no funcionan", "los EV siguen a cero" y "la vida no se refleja".

QUÉ CAMBIA

Ahora solo detienen la lectura los cambios que RoleRun puede escribir de verdad.
Si algo no tiene escritura para ese juego, se queda en la lista para que puedas
guardarlo por archivo, pero ya no bloquea el seguimiento en vivo.

Así, si en el futuro abro una función a medias por error, el síntoma será "esa
función no hace nada" y no "RoleRun entero deja de actualizarse".

QUÉ DEBES PROBAR

Poco: usa RoleRun con normalidad y comprueba que la vida y los cambios del juego
se siguen reflejando siempre.

Si quieres forzarlo: haz un drafteo que cambie ataques en Negro 2 (eso todavía no
tiene escritura) y comprueba que, aun así, la vida de tu equipo se sigue
actualizando sola.

LO SIGUIENTE

Las bajas con sustitución automática, que es el corazón de una RoleRun. Ya tiene
todas sus piezas listas y validadas por ti: combate, roles y PC.
