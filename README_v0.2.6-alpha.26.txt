RoleRun Manager v0.2.6-alpha.26 — curación de Negro 2

El botón CURAR vuelve a Negro 2, esta vez con la escritura hecha de verdad.

(Lo quité en alpha.16 precisamente porque no estaba implementado: se quedaba
pidiendo seis curaciones que nadie hacía, y de paso bloqueaba el seguimiento en
vivo. Ahora ya funciona.)

QUÉ HACE CURAR

Lo mismo que un Centro Pokémon:

  - PS al máximo,
  - se quita el estado alterado (veneno, quemadura, sueño, parálisis...),
  - y los PP de los cuatro movimientos al tope, contando los Más PP que le hayas
    dado a cada movimiento.

UN DETALLE DEL QUE ESTOY CONTENTO

Para poner los PP al máximo hace falta saber cuántos PP tiene cada movimiento.
RoleRun ya tenía esa tabla... pero de SEXTA generación (la de ORAS). Y varios
movimientos cambiaron de PP entre generaciones, así que usarla en Negro 2 habría
sido dar por hecho algo sin comprobarlo.

He sacado la tabla de quinta generación del propio PKHeX que RoleRun ya usa para
leer y escribir partidas: 559 movimientos, exactamente los que existen en quinta.
Queda guardada en el repositorio junto con la herramienta que la genera, por si
algún día hay que rehacerla.

Y si algún movimiento tuviera un PP que RoleRun no puede demostrar, NO cura.
Prefiero que no haga nada antes que inventarse un número sobre tu partida.

MÁS DETALLES DE SEGURIDAD

  - Curar a quien ya está curado no escribe ni un byte.
  - Antes de escribir vuelve a leer y comprueba que son los Pokémon correctos.
  - Después de escribir vuelve a leer y comprueba PS, estado y PP uno a uno.
  - Si algo no cuadra, lo deshace todo.

QUÉ DEBES PROBAR AHORA

Otra vez: save state antes, por favor.

1. Deja el equipo tocado: alguien con poca vida, alguien envenenado o quemado,
   y gasta PP de algún movimiento.
2. Pulsa CURAR en RoleRun.
3. Comprueba en el juego, mirando la ficha de varios Pokémon:
   - PS llenos,
   - sin estado alterado,
   - PP de cada movimiento al máximo (ojo a los que tengan Más PP: deben quedar
     por encima del PP normal, no en el normal).
4. Comprueba que NO ha cambiado nada más: mote, nivel, ataques, roles, EV.
5. Guarda en el juego y vuelve a comprobarlo.
6. Prueba también a pulsar CURAR con todo el equipo ya curado: no debería pasar
   nada raro.

Si algo no cuadra, captura y me lo cuentas.

LO QUE QUEDA EN NEGRO 2

Mochila y MT, las bajas con sustitución automática, y las medallas. Después,
los otros cuatro juegos de DS.
