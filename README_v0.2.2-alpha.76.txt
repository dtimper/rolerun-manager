RoleRun Manager v0.2.2-alpha.76 — BDSP: herencia PC y BattleProc ausente

Esta versión corrige dos primeras divergencias demostradas en Perla Reluciente
1.3.0 sobre Ryujinx HostMappedUnsafe:

- un cambio 1↔1 realizado dentro del PC del juego hereda y verifica el rol del
  Pokémon saliente antes de publicar la nueva party, por lo que RoleRun nunca
  muestra al entrante como una séptima tarjeta por conflicto de marcador;
- la ranura TypeInfo de BattleProc exactamente nula y estable se reconoce como
  clase todavía no cargada fuera de combate. Los punteros no nulos inválidos,
  una batalla activa y cualquier precondición inestable siguen bloqueando toda
  escritura.

No se ha añadido ninguna dirección, fallback de HP ni writer de cajas. Los
cambios Equipo↔PC se siguen realizando dentro del juego y RoleRun los observa.

Verificación automatizada: 65 pruebas BDSP y 542 pruebas completas superadas.

Validación física completada el 2026-08-22:

El usuario confirmó la prueba combinada de SUSTITUIR fuera de combate y cambio
1↔1 dentro del PC del juego. La MT se aplica en tiempo real y el equipo vuelve a
RoleRun con seis tarjetas y el rol heredado, sin reproducir los fallos alpha.75.
