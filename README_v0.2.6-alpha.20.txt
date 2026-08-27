RoleRun Manager v0.2.6-alpha.20 — B2/W2 deja de rebuscar en la memoria

Mejora de rendimiento en Blanco 2 / Negro 2.

QUÉ HACÍA ANTES

Cada vez que RoleRun leía tu equipo o tus cajas, se ponía a rebuscar por toda la
memoria de melonDS hasta encontrar dónde estaba la partida. Y lo hacía SIEMPRE,
aunque ya lo hubiera encontrado un segundo antes. Con el seguimiento del PC
recuperado en la versión anterior, esa búsqueda pasó a repetirse cada pocos
segundos.

QUÉ HACE AHORA

RoleRun se acuerda de dónde está y va directo. Sigue comprobando cada vez que lo
que lee es correcto: hace la misma doble lectura de seguridad de siempre y sigue
verificando los datos de cada Pokémon. Lo único que se ahorra es la búsqueda.

Y no se relaja ninguna seguridad:

- Si abres o cierras otra ventana de melonDS, vuelve a buscar desde cero.
- Vuelve a buscar cada minuto de todas formas, por si acaso.
- Si al ir directo algo no cuadra (por ejemplo tras cargar un save state),
  vuelve a buscar sin darte ningún error.
- Si cierras melonDS, se le olvida.

Tampoco he tocado la lectura de seguridad que RoleRun hace justo antes de
escribir en la partida. Esa se queda como está: ahorra tiempo quitarla, pero a
costa de seguridad, y eso no compensa.

QUÉ DEBES PROBAR AHORA

1. Abre Negro 2 en melonDS y carga la partida en RoleRun.
2. Usa RoleRun un rato con Equipo y PC abierto: cambia de caja, mira fichas.
   Debería ir igual o más suelto que antes.
3. Mueve algo desde el juego y comprueba que RoleRun se sigue enterando solo
   (esto es lo que arreglamos en la versión anterior; aquí solo confirmo que no
   se ha roto).
4. Carga un SAVE STATE en melonDS y comprueba que RoleRun se recupera y sigue
   mostrando tu equipo correctamente, sin quedarse en error.
5. Si tienes paciencia: abre una segunda ventana de melonDS y comprueba que
   RoleRun avisa de lectura ambigua en vez de enseñarte datos de la otra.

El punto 4 es el más importante de todos.
