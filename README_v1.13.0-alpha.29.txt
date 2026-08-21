RoleRun Manager 1.13.0-alpha.29
================================

Objetivo de esta alpha: mantener estable la Barra Flotante y completar el flujo
de PC/muerte desde ORAS sin depender de guardar el archivo main.

CAMBIOS
- Los swaps Equipo <-> PC hechos dentro de ORAS se reflejan también en Cajas PC.
- Mover Pokémon entre roles desde la Barra Flotante no repinta la ventana principal.
- Un Pokémon debilitado desaparece de la Barra Flotante desde que se registra la baja.
- ELIGE AL SUSTITUTO DE... espera a que termine el combate: se exige detectar batalla
  y después dos lecturas consecutivas de overworld.
- Si el combate acaba mientras está activa la Barra Flotante, RoleRun vuelve de forma
  controlada a la ventana principal y abre el selector.
- Caja 4 continúa reservada como Cementerio.

PRUEBAS RECOMENDADAS
1. Con Barra Flotante activa, intercambia desde el PC del juego un Pokémon del equipo
   por otro. Comprueba que la barra no se cierra y que el saliente aparece en la caja
   desde la que salió el entrante al abrir Cajas PC.
2. Desde la Barra Flotante arrastra un Pokémon de un rol ocupado a otro. Comprueba que
   ambos intercambian rol y que la barra permanece abierta.
3. Deja que un Pokémon llegue a 0 PS. Debe desaparecer de la barra, bajar una vida y
   NO debe abrirse el selector mientras el combate siga activo.
4. Termina el combate. Tras confirmarse el overworld debe aparecer una única ventana
   ELIGE AL SUSTITUTO DE..., incluso si estabas usando la Barra Flotante.
5. Elige sustituto. Comprueba que entra en el equipo y el muerto termina en Caja 4.

VALIDACIÓN AUTOMÁTICA
90/90 pruebas superadas.
