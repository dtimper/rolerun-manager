RoleRun Manager v0.2.6-alpha.30 — arreglado el error al sustituir

Buenas noticias primero: de tu última prueba, tres de cuatro cosas ya funcionan.

  - la casilla que queda vacía es la correcta,
  - se abre el selector de sustituto,
  - y curar al debilitado lo devuelve a su sitio.

EL ERROR AL SUSTITUIR

Ese mensaje raro:

  argument 2: TypeError: expected LP_PROCESSENTRY32W instance
  instead of pointer to PROCESSENTRY32W

no tenía nada que ver con la sustitución, aunque saliera ahí.

RoleRun le pregunta a Windows por la lista de procesos para encontrar melonDS.
Para eso tiene que describirle a Windows qué forma tienen los datos. El problema:
esa descripción se estaba creando NUEVA en cada consulta, y además se guardaba en
un sitio COMPARTIDO por todas las partes del programa.

Como ahora RoleRun hace varias cosas a la vez (vigilar el equipo, vigilar el PC,
y escribir), dos de ellas podían pisarse esa descripción a media consulta. La que
llegaba tarde encontraba una descripción que ya no era la suya, y fallaba.

Es como si dos personas rellenaran el mismo formulario a la vez.

Arreglado de dos formas, para que no vuelva:

  - la descripción se crea UNA vez, no en cada consulta;
  - y Negro 2 usa su propia línea con Windows, en vez de la compartida con el
    resto del programa.

Y de paso he puesto un turno: ahora las lecturas y escrituras de Negro 2 no
pueden solaparse entre ellas. Esto ya lo señalaba la auditoría como un riesgo,
pero hasta ahora no se había manifestado.

LO QUE SIGUE SIN ESTAR ARREGLADO

Que la vida se descuente al TERMINAR el combate y no en el momento del golpe
mortal. Me confirmaste que sigue pasando. No lo doy por cerrado y lo miro
después de esta prueba.

QUÉ DEBES PROBAR AHORA

Save state antes.

1. Repite lo de la otra vez: deja caer a un Pokémon con rol.
2. Al salir del combate, elige el sustituto en el selector.
3. Esta vez NO debería salir ningún error. Comprueba en el juego:
   - el caído está en la Caja 4 (Cementerio),
   - el sustituto está en tu equipo,
   - la casilla de donde salió el sustituto está vacía,
   - y el sustituto ha heredado el rol del caído.
4. Guarda en el juego y vuelve a comprobarlo.

Si vuelve a salir un error, mándame la captura con el mensaje completo.
