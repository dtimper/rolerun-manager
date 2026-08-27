RoleRun Manager v0.2.6-alpha.32 — la vida y las bajas, ya en tiempo real

Tu traza lo resolvió. Gracias, porque sin ella habría estado adivinando.

QUÉ DESCUBRÍ CON TU CAPTURA

Tres cosas, todas medidas en tu partida, ninguna supuesta:

1. Negro 2 NO actualiza la ficha de tu equipo mientras dura el combate.
   A los 27 segundos tu Patrat estaba a 3 de 16 PS en pantalla, y la ficha del
   equipo seguía diciendo 16 de 16. A los 39 segundos estaba a 0, y la ficha
   seguía diciendo 16 de 16. Solo se actualizó a los 47, al acabar el combate.

   Esa ficha era justo la fuente a la que RoleRun estaba mirando.

2. RoleRun SÍ tenía el dato bueno, en la información de combate... pero lo
   estaba tirando a la basura.

   RoleRun leía dos sitios y exigía que ambos hablaran del mismo Pokémon. En tu
   combate, el segundo sitio se quedó congelado describiendo a otro Pokémon de
   tu equipo, con un nivel imposible (516). Estaba obsoleto. Como no coincidían,
   RoleRun descartaba la lectura ENTERA... incluida la buena.

3. Mi sospecha sobre el "estado" del Pokémon al morir era FALSA. Se mantuvo en 0
   todo el combate. Descartada.

QUÉ CAMBIA

Ahora manda la información que se ve en pantalla, y el segundo sitio solo sirve
para confirmar. Si está obsoleto, se ignora en vez de tirarlo todo.

Lo que NO he tocado:

  - sigue teniendo que ser un Pokémon de tu equipo, identificado sin ambigüedad;
  - unos PS imposibles se siguen rechazando;
  - un estado que no tengo demostrado se sigue rechazando;
  - y cuando los dos sitios coinciden, RoleRun sigue SIN adelantarte el KO antes
    de que el juego lo enseñe, igual que validaste en su día.

Las pruebas automáticas usan los bytes REALES de tu captura, no valores que me
haya inventado.

UNA LIMITACIÓN QUE AHORA SÍ ESTÁ DEMOSTRADA

Durante el combate solo se puede saber la vida del Pokémon que está luchando.
La de los otros cinco sale de la ficha del equipo, que el juego no actualiza
hasta el final. Es una limitación del juego, no de RoleRun.

QUÉ DEBES PROBAR AHORA

1. Entra en combate y recibe daño. La vida del Pokémon que está luchando debe
   bajar en RoleRun MIENTRAS peleas.
2. Deja que se debilite. La vida (el corazón) debe descontarse EN ESE MOMENTO,
   no al terminar el combate.
3. Comprueba que RoleRun no te adelanta el golpe: la barra debe bajar cuando lo
   ves en pantalla, no antes.
4. Al terminar, el selector de sustituto debe funcionar como la última vez.
