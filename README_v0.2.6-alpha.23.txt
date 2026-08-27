RoleRun Manager v0.2.6-alpha.23 — la vida se actualiza DURANTE el combate

Tu captura fue decisiva: Mareep debilitado (0/22), Azurill a 4/20, y la barra
flotante pintando a los seis a tope. Gracias, porque el arreglo anterior se
quedaba corto y sin esa imagen no lo habría visto.

QUÉ PASABA

RoleRun tiene una lectura especial para el combate: la que usa para no
enseñarte el daño ANTES de que el juego lo muestre en pantalla.

Esa lectura se rompe con facilidad: al cambiar de Pokémon, con la animación a
medias, o con un estado (veneno, quemadura...) que RoleRun todavía no tiene
demostrado. Y cuando se rompía, RoleRun se quedaba SIN PUBLICAR NADA de vida.

Ahí está el fallo: esa lectura solo manda sobre el Pokémon que está luchando.
Los otros cinco se leen del equipo normal, donde no hay nada que destripar. Pero
un fallo del que lucha congelaba a los seis.

Por eso tu Mareep aparecía a vida llena estando debilitado.

QUÉ CAMBIA

Cuando esa lectura especial no se puede validar, RoleRun ya publica la vida del
equipo normal. Prefiero adelantarte unos segundos el daño de UN Pokémon antes
que enseñarte un debilitado con la vida llena todo el combate.

Lo que NO cambia: cuando el combate sí se detecta bien, sigue mandando la
lectura que respeta la animación, exactamente como validaste en alpha.5.

QUÉ DEBES PROBAR AHORA

1. Entra en combate y recibe daño. La vida debe bajar en la barra flotante
   MIENTRAS luchas, no solo al salir.
2. Deja que uno se debilite y comprueba que aparece a 0 al momento.
3. Cambia de Pokémon en mitad del combate y comprueba que las vidas siguen bien.
4. Envenena o quema a alguien y comprueba que la vida sigue actualizándose.

Si algo sigue sin moverse, mándame otra captura como la de antes: me sirve
muchísimo más que cualquier descripción.
