RoleRun Manager v0.2.6-alpha.24 — los roles de Negro 2 ya funcionan

Tus tres fallos eran EL MISMO. Te lo explico porque importa.

QUÉ PASABA

Negro 2 no tenía hecha la parte de escribir roles. Cuando le asignabas un rol a
un Pokémon, RoleRun apuntaba el cambio en su lista de "cosas por hacer"... y
nadie lo hacía nunca. Por eso seguían todos en SIN ROL y los EV a cero.

Y aquí viene lo importante: RoleRun no lee la partida mientras tenga cambios
pendientes, para no pisar lo que estás preparando. Como ese cambio de rol no se
iba a aplicar jamás, la lista nunca se vaciaba... y RoleRun dejaba de leer la
partida. Por eso la vida tampoco se actualizaba.

Un solo fallo, tres síntomas.

QUÉ HE HECHO

He implementado la escritura de roles para Negro 2. Ahora, cuando asignas un rol:

  - se escribe la marca correspondiente en el Pokémon,
  - se escriben los EV del rol,
  - y se RECALCULAN sus estadísticas, porque cambiar EV sin recalcular dejaría
    los números antiguos y un PS máximo que no cuadra.

Dos detalles que he cuidado:

  - Si sube el PS máximo, el PS actual sube lo mismo. Es decir, si estaba a
    medias, sigue a medias; no se cura ni se hace daño de la nada.
  - Un Pokémon debilitado sigue debilitado. Subir su PS máximo no lo revive.

Y como siempre en RoleRun: antes de escribir vuelve a leer, comprueba que es el
Pokémon correcto, escribe, vuelve a leerlo y verifica que la marca y los EV son
los que pidió. Si algo no cuadra, lo deshace todo.

MUY IMPORTANTE: PRUEBA CON CUIDADO

Esto escribe en tu partida en memoria. Está probado con 28 pruebas automáticas,
pero TÚ eres la primera persona que lo va a usar de verdad. Te sugiero:

1. Haz una copia de seguridad de tu partida antes (o usa un save state).
2. Asigna un rol a UN SOLO Pokémon primero.
3. Comprueba en RoleRun que ya no pone SIN ROL.
4. Entra en el juego, mira la ficha de ese Pokémon y comprueba:
   - que tiene la marca puesta,
   - que sus estadísticas han subido de forma coherente,
   - que el resto (mote, nivel, ataques, PP) está intacto.
5. GUARDA en el juego y comprueba que sigue todo bien.
6. Si va bien, asigna los otros cinco.

Después de eso, comprueba también que la vida vuelve a actualizarse sola, ya sin
cambios atascados en la lista.

LO QUE SIGUE PENDIENTE

La curación de Negro 2 sigue sin estar disponible: no tiene su propia escritura
todavía y no quería abrirla de rebote. Es la siguiente de la lista, junto con
mochila/MT, las bajas con sustitución y las medallas.
