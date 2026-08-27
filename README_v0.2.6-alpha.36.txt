RoleRun Manager v0.2.6-alpha.36 — la mochila entera, descifrada

Ya sé exactamente cómo guarda Negro 2 tu mochila. Y no es una suposición.

QUÉ HA PASADO

Tu última lectura encontró cuatro grupos de objetos:

  - Poké Ball y Ataque X
  - Videomisor, Bloc de Amigos y Mapa   -> objetos clave
  - MT21                                 -> el bolsillo de MTs
  - Poción y Antiparalizador             -> medicinas

Fíjate en que cada grupo tiene objetos del MISMO tipo. Eso ya dice que son
bolsillos separados.

LA PARTE QUE ME CONVENCE DEL TODO

Medí la distancia entre el principio de cada bolsillo en TU partida: 1240, 1572
y 2008 bytes.

Luego fui a PKHeX (el programa de referencia para partidas de Pokémon, que
RoleRun ya usa por dentro) y le pregunté cómo dice ÉL que está organizada la
mochila de Negro 2. Su respuesta: 1240, 1572 y 2008.

Exactamente los mismos números. Tres veces seguidas.

No es que yo asuma que tu partida se parece a lo que dice PKHeX: es que lo he
medido en tu memoria y coincide al byte. Eso ya no es casualidad.

QUÉ SÉ AHORA

  - Dónde empieza tu mochila.
  - Dónde empieza cada bolsillo dentro de ella.
  - Que cada hueco son dos números: qué objeto y cuántos.
  - Qué objetos son válidos en cada bolsillo (sacado de PKHeX).
  - Dónde está tu dinero.

QUÉ DEBES PROBAR AHORA

Nada. Esta versión no cambia el programa: solo he guardado el conocimiento y la
herramienta que lo genera.

Lo siguiente que haré es programar la LECTURA de la mochila, para que RoleRun te
enseñe tus objetos y tus MTs. Cuando esté, te pediré que compares lo que enseña
RoleRun con lo que ves en el juego.

Después vendrán las MTs y el dinero.
