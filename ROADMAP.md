## 0.2.1-alpha.18

- [x] X/Y: implementar Caramelo Raro ×999, Repelente Máximo ×999 y dinero máximo con escritura viva verificada.
- [x] Global: permitir Sustituto a Asesino y Mago sin añadirlo a los pools de drafteo.
- [x] Global: añadir catálogo MOVIMIENTOS por rol, buscable y filtrado por el juego cargado.
- [x] Global: eliminar la compatibilidad de especie como restricción al enseñar MT desde RoleRun.
- [ ] Validación empírica en AzaharPlus de las tres utilidades X/Y de alpha.17.

## 0.2.1-alpha.12

- [x] X/Y: resolver el primer depósito en PC cuando el último `main` no tiene anchors de cajas.
- [x] X/Y: impedir que una operación `party-to-box` no soportada se proyecte como si hubiera ocurrido en vivo.
- [x] Mantener intacto el bug de reinicio Citra/GDB mientras continúa la paridad funcional.
- [ ] X/Y: validar una escritura viva segura para operaciones que cambian el tamaño de la party; hasta entonces se hacen desde el PC del juego.

## 0.2.1-alpha.11

- [x] X/Y: integrar la matriz PC viva 31×30 con la pestaña CAJAS PC y la reconciliación de cambios hechos desde el juego.
- [x] Reutilizar la lógica Gen 6 validada de ORAS para Mover/Sacar/Dejar.
- [x] Mantener protegidas las operaciones X/Y que cambian el tamaño de party iniciadas desde RoleRun.
- [x] Aparcar temporalmente el bug de reinicio Citra/GDB para no bloquear la paridad funcional de X/Y.

## 0.2.1-alpha.10

- Robustez X/Y/Citra: reinicio interno autónomo mediante broker watchdog.
- Eliminar falsos positivos de muerte antes de añadir más juegos.
- Resolver compatibilidad de MT desde la capa efectiva que ejecuta el emulador.
- Mantener ORAS y las funciones validadas de alpha.8 sin regresiones.

## 0.2.1-alpha.8

Prioridad de robustez X/Y/Citra:
- broker GDB persistente y reconexión de la UI sin reiniciar juego;
- bajas live por slot;
- mochila MT corregida y primera MT sin guardar.

## 0.2.1-alpha.7
- X/Y: medallas live en Azahar/Citra.
- X/Y: sonda de batalla y flujo de debilitados/sustitución.
- X/Y: corregir y validar mochila MT/MO.

# RoleRun Manager — Roadmap actual

## 0.1.x — Gestor sin tiempo real
- [x] Runs, drafteos, roles, PC, inventario, historial y OBS basados en guardado.

## 0.2.0 — ORAS en tiempo real
- [x] Azahar RPC.
- [x] Party, roles, movimientos, PC, MT/inventario, medallas y bajas.
- [x] Sincronización juego <-> RoleRun y OBS.

## 0.2.1 — Real-Time multi-juego
- [x] alpha.1: Real-Time Core + ORAS como adaptador de referencia.
- [x] alpha.2: resolver común de RAM + diagnóstico/recorder/replay.
- [x] alpha.3: primer soporte X/Y (party, roles, movimientos, medallas, diagnóstico/replay).
- [x] alpha.4-5: X/Y multi-emulador (Azahar RPC + Citra GDB persistente) y modelo live sin Guardar cambios.
- [x] alpha.6: X/Y PC vivo + mochila/MTs vivas + tabla/compatibilidad leída de la ROM.
- [x] X/Y: medallas, batalla, bajas/sustituciones y PC/MT vivos incorporados en la etapa alpha.6-alpha.10.
- [ ] X/Y: validar/activar operaciones iniciadas desde RoleRun que cambian el tamaño de party.
- [ ] X/Y/Citra: retomar el bug de reinicio del GDB Stub cuando la paridad funcional esté más avanzada.
- [ ] Sol/Luna sobre Azahar.
  - [x] Party + marcadores/roles vivos.
  - [x] Movimientos de equipo vivos.
  - [x] MT + utilidades de inventario vivas.
  - [x] PC live juego → RoleRun: cajas, niveles/habilidades, Equipo ↔ PC y herencia automática de rol.
  - [ ] RoleRun → juego para Equipo ↔ PC: alpha.33 reabre el swap 1↔1 con EncryptedPartyData 0x104 completo + verificación sparse independiente; pendiente validación física. Después se ampliará a cambios de tamaño.
  - [ ] Muertes, sustituciones automáticas, Cementerio y progreso equivalente a medallas.
- [ ] Ultra Sol/Ultra Luna sobre Azahar.
- [ ] Bridge DS + Blanco/Negro y Blanco 2/Negro 2.
- [ ] Bridge Switch + BDSP.

## Después del núcleo multi-juego
- [ ] Automatización completa de combates importantes/drafteos.
- [ ] Hub interno ampliado.
- [ ] Integración OBS avanzada.
- [ ] Empaquetado/instalador y fase beta.
