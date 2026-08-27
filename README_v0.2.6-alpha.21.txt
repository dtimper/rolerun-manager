RoleRun Manager v0.2.6-alpha.21 — los PS ya no reconstruyen la pantalla

Primera mejora de las gordas de fluidez, y por fin con números tuyos de verdad.

LO QUE HE MEDIDO

He montado la pantalla de Equipo y PC de verdad y la he cronometrado en tu
Windows. Resultado:

  - 642 elementos en pantalla
  - 845 milisegundos cada vez que RoleRun la reconstruye entera

Y RoleRun la reconstruía entera muchísimas veces. En combate, el seguimiento lee
la partida cada 250-450 milisegundos, y CADA vez que cambiaban los PS de alguien
se rehacía la pantalla completa. Solo para mover unas barras de vida.

Por eso notabas tirones justo en los momentos en los que más importa.

QUÉ CAMBIA

Ahora, cuando solo cambian los PS, RoleRun mueve las barras y ya está:

  - antes: 845 milisegundos
  - ahora: 8 milisegundos
  - es 103 veces más rápido

Y con cuidado: si el equipo ha cambiado de verdad (se debilita alguien, entra un
Pokémon del PC, haces una sustitución), RoleRun sigue reconstruyendo la pantalla
como siempre. La vía rápida solo sirve para acelerar; nunca decide qué se
enseña. Ante la mínima duda, hace lo de antes.

También me he asegurado de que la barra de vida rápida se pinta EXACTAMENTE
igual que si se reconstruyera la pantalla: mismo color, mismo tamaño, mismo
texto. El color y el texto se calculan ahora en un solo sitio para que no puedan
acabar diciendo cosas distintas.

QUÉ DEBES PROBAR AHORA

Esto se nota sobre todo en combate:

1. Entra en un combate en Negro 2 con RoleRun abierto en Equipo y PC.
2. Recibe y haz daño, usa objetos de curación, y fíjate en las barras de vida
   de RoleRun mientras tanto.
3. Comprueba que las barras se mueven de forma suave y que la pantalla ya NO
   parpadea ni se queda congelada en cada golpe.
4. Comprueba que el número de PS y el color de la barra son correctos
   (verde, dorado por debajo de la mitad, rojo por debajo de un cuarto).
5. Deja que alguien se debilite y comprueba que RoleRun reacciona igual que
   antes: registra la baja y te ofrece el sustituto.

El punto 5 es importante: ahí RoleRun SÍ debe reconstruir la pantalla, y quiero
confirmar que ese camino sigue intacto.

Lo siguiente será quitar las otras reconstrucciones innecesarias: cuando llega
una imagen, cuando se confirma un cambio y cuando se recarga el PC.
