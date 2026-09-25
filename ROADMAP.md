# RoleRun Manager — roadmap

> `docs/CURRENT_STATE.md` es la fuente canónica del estado funcional. Las
> secciones cronológicas inferiores se conservan como historial y reflejan lo
> que estaba pendiente en cada alpha, no necesariamente lo que sigue pendiente.

## Prioridades vigentes a 25-09-2026

Todo lo que sigue a esta sección es historial: muchas casillas `[ ]` de más
abajo ya se cerraron después (combate de seis, X/Y cambiando el tamaño de la
party, etc.). Esta lista es lo que de verdad queda abierto.

- [x] Publicar una Release nueva: `v0.4.0` (25-09-2026) reúne todo lo añadido
  desde `v0.3.1`. Para las siguientes, `tools/publicar_version.py`.
- [ ] Estado alterado en la barra flotante: ORAS muestra un estado equivocado
  (parálisis como sueño) y BDSP no muestra ninguno — el offset `0x94` de
  `PlayerWork._playerParty` no lleva el estado vivo. Confirmado, sin arreglar.
- [ ] USUM, combate de seis: la sonda de combate no distingue salvaje de
  entrenador. Hueco teórico (roster del rival sin limpiar entre combates), no
  observado nunca en partida.
- [ ] Diamante/Perla y Platino: sin ninguna dirección de RAM medida; ocultos
  del selector.

**Aparcado hasta nuevo aviso**: HeartGold/SoulSilver (carril de combate sin
estabilizar; la escritura está encendida desde el 06-09-2026 aceptando un riesgo
residual, ver `MELONDS_GEN4_ESCRIBE` en `app/ui.py`). Oculto del
selector junto con DP/Pt.

## Prioridades vigentes en v0.2.6-alpha.13

- [x] Implementar la primera party B2/W2 de solo lectura para Pokémon Negro 2
  (España) en melonDS 1.1, con doble captura, PK5 completos e identidad fuerte.
- [x] Validar visualmente que RoleRun muestra la party y los PS correctos y que
  se actualizan en vivo (confirmado en Negro 2/melonDS 1.1 el 26-08-2026).
- [ ] Investigar por separado batalla/KO, PC, roles, curación, movimientos,
  inventario y progreso de B2/W2; no habilitar escrituras por analogía.
- [x] Inventariar toda la paridad 3DS/BDSP en `docs/B2W2_REALTIME_PARITY.md` y
  publicar los metadatos contenidos en el PK5 demostrado sin abrir escrituras.
- [x] Mantener visibles en la barra los miembros SIN ROL y conservar roles de
  Run mientras B2/W2 no pueda escribir marcas PK5.
- [x] Resolver las dos copias de batalla B2/W2 y publicar PS inmediatos en la
  barra usando la copia rápida y la otra como testigo de convergencia.
- [x] Validar visualmente daño acompasado y parálisis correcta en la barra.
- [x] Demostrar e implementar la matriz PC B2/W2 de 24×30 en melonDS, con
  doble lectura y validación integral. Mantener escrituras y KO cerrados hasta
  disponer de sustitución transaccional segura.
- [ ] Validar visualmente el seguimiento de un movimiento PC↔PC y uno
  Equipo↔PC realizados desde el juego; implementación y regresión listas.

- [x] Añadir metadatos completos y exclusivos de X/Y a la pestaña global de
  MT y comprobar visualmente potencia, precisión y PP en Pokémon X/Azahar.
- [x] Cubrir la transacción X/Y de MT reutilizable con readback y rollback sin
  leer ni escribir la mochila.
- [x] Validar físicamente que una MT poseída y compatible cambia el movimiento
  elegido en Pokémon X y continúa disponible después de enseñarla (confirmado
  por el usuario el 25-08-2026).

- [x] Confirmar visualmente que X/Y muestra Budew, Ledyba y Skitty en Caja 1,
  posiciones 1–3 (validado en RoleRun conectado a Pokémon X/Azahar el
  25-08-2026).
- [x] Validar físicamente en Pokémon X/Azahar el cambio de un rol fijo: EV y
  stats finales cambian al instante sin curar el daño existente ni borrar el
  estado (confirmado por el usuario el 25-08-2026).
- [x] Validar físicamente una entrada PC→Líbero en X/Y y elegir sus dos EV
  (confirmado por el usuario el 25-08-2026).
- [x] Implementar el movimiento exacto PC→PC de X/Y con origen, caja y slot de
  destino explícitos, precondiciones, readback y rollback de ambos bloques.
- [x] Validar físicamente el movimiento PC→PC de X/Y a una casilla vacía de otra
  caja y confirmar que el juego conserva exactamente el destino solicitado
  (confirmado por el usuario el 25-08-2026).
- [x] Demostrar físicamente el contador X/Y de cuatro bytes en `0x08CE1C74`, la
  compactación de la party y el PK6 vacío final.
- [x] Implementar Equipo→PC y PC→Equipo X/Y con destino exacto, contador como
  commit final, precondiciones, readback semántico y rollback verificado.
- [x] Validar físicamente desde RoleRun el movimiento PC→PC con vacío PK6
  válido, sin duplicados ni Huevo corrupto (confirmado en Pokémon X/Azahar
  263745c con v0.2.4-alpha.14).
- [ ] Completar la validación física del ciclo X/Y Equipo→casilla PC exacta→
  primer rol libre, sin duplicados ni pérdidas.
- [x] Implementar para X/Y una transacción de rol, EV y estadísticas runtime
  con precondiciones, readback y rollback de las dos regiones físicas.
- [x] Validar físicamente la curación completa X/Y en Pokémon X/Azahar
  (confirmado por el usuario el 25-08-2026).

- [x] Validar físicamente el resultado PC→Equipo de Sol/Luna tras una apertura
  limpia: la party viva se publicó sin duplicar el PC, Decidueye apareció en
  Caja 1:1 y el slot PK7 corrupto quedó vacío (confirmado por el usuario el
  25-08-2026).

- [ ] Validar físicamente que cada flecha mueve exactamente una casilla en
  Equipo/PC, que ambos pasos MT muestran selector y que el drawer mantiene un
  único foco visible.

- [x] Validar físicamente una ficha de un Pokémon exclusivamente almacenado en
  el PC y confirmar que naturaleza, seis stats, IV y EV ya aparecen
  (confirmado por el usuario el 24-08-2026).
- [x] Publicar en la UI la matriz BDSP viva completa aunque la identidad y la
  posición coincidan con el guardado incompleto.
- [x] Impedir que cualquier atajo global Win32 secuestre teclas fuera del juego:
  solo se registra mientras el emulador compatible está en primer plano.
- [x] Validar físicamente que los contadores flotantes responden desde la
  primera interacción (confirmado por el usuario el 24-08-2026).

- [ ] Diseñar y demostrar una captura exclusiva de mando compatible con SDL2
  antes de ofrecer mapeo de gamepad; no duplicar inputs hacia Ryujinx.

- [x] Validar físicamente en Pokémon X/Azahar 263745c que un descenso de PS
  aparece en RoleRun después de la animación y converge al salir del combate.
- [x] Validar físicamente en Pokémon X/Azahar 263745c un KO simple completo:
  descuento único de vida, selector postcombate y elección correcta del
  sustituto (confirmado por el usuario el 25-08-2026).
- [x] Validar físicamente en Pokémon X/Azahar 263745c dos KO dentro del mismo
  combate: dos vidas exactas y dos selectores de sustitución consecutivos
  resueltos correctamente (confirmado por el usuario el 25-08-2026).
- [ ] Validar físicamente que el menú inmersivo conserva el modo de ventana de
  Ryujinx, captura flechas/Z/X y recupera la barra al cerrar desde su raíz.

- [x] Validar físicamente en BDSP/Ryujinx la curación completa y los cambios
  de Pokémon en el equipo (confirmado por el usuario el 23-08-2026).
- [x] Validar físicamente en BDSP/Ryujinx el intercambio
  de roles por arrastre, los EV al entrar desde PC, las acciones sobre
  movimientos incompatibles y la preferencia ON/OFF de la barra flotante.

- [x] Implementar curación completa BDSP con doble lectura, readback y rollback.
- [x] Interpretar Equipo→Equipo como intercambio de roles con EV y selección
  explícita de stats para Líbero, sin habilitar reordenación física no probada.
- [x] Recuperar en la ficha las incompatibilidades rojas y las rutas comunes de
  sustituir/eliminar movimientos.
- [x] Aplicar automáticamente los EV del rol heredado al entrar desde el PC.
- [x] Convertir la barra flotante en una preferencia persistente ON/OFF.

- [x] Validar físicamente la interacción final de la pestaña global MT: hover
  sin flicker, scroll estable, `YA LO CONOCE`, selector centrado y regreso sin
  cargador intermedio. El writer y el consumo ya están validados.

- [ ] Carga inicial: continúa mostrando una vista parcialmente compuesta durante
  unos tres segundos en la prueba física posterior a alpha.100. Se detiene el
  parcheo incremental tras varios intentos que desplazaron el síntoma; queda
  aplazada hasta rehacer la investigación de publicación de ventana.

- [x] Validar físicamente la navegación, apertura y salida del flujo integrado
  de MT posterior a alpha.100.

- [x] Condicionar la retirada del loader a la publicación observada de la vista
  final y completar el eje horizontal de acciones del inspector.

- [x] Sustituir las capturas operativas inestables por una pantalla autónoma y
  separar las reglas direccionales de Equipo, PC y acciones de la ficha.

- [x] Preservar la barrera en apertura y MT, eliminar bindings huérfanos y
  completar la navegación por teclado hasta la acción del inspector PC.

- [x] Esperar el readback de swaps BDSP live y estabilizar apertura, mensajes
  de carga y fantasma de arrastre.

- [x] Unificar apertura de Run, PC, PC↔Equipo y demás esperas bajo una barrera
  visual independiente con fondo oscuro estable y actividad que no depende del
  mainloop de Tkinter.

- [x] Mantener inmutable la luminosidad del frame congelado durante navegación,
  retirar el tirador residual del drawer y mostrar actividad animada aun cuando
  Tkinter está construyendo la vista de destino.

- [x] Llevar vidas, curaciones, medallas y drafteos a la cabecera común en
  pantalla ancha, con degradación compacta sin solapamientos.
- [x] Encajar Equipo, las 30 casillas PC y la ficha completa a 1080p; corregir
  sprites/texto recortados y rediseñar el botón de información de rol.
- [x] Publicar en BDSP live naturaleza, stats, IV y EV desde campos PB8
  demostrados, sin abrir ninguna escritura nueva.
- [x] Completar tarjetas de movimientos BDSP con potencia, precisión, PP y las
  descripciones del bundle de mensajes activo.
- [x] Densificar Drafteos, eliminar `LISTO`, ampliar contexto y añadir transición.
- [x] Repartir Equipo en seis tarjetas completas, aislar el scroll en el PC y
  garantizar un borde de selección continuo.
- [x] Jerarquizar las tarjetas de Drafteos con sprites grandes, limitar el fade
  al contenido, añadir retorno desde Movimientos e indicar trabajos en curso.
- [x] Sustituir el resumen desplegable de la cabecera por cuatro controles
  independientes y accesibles desde cualquier página.
- [x] Mostrar las 30 casillas PC sin scroll, alinear el final de Equipo con la
  fila 21–25 y mantener visibles las seis acciones del primer paso de Drafteos.
- [x] Dar protagonismo a Equipo con seis fichas completas, estrechar PC a tres
  columnas con scroll y simplificar las acciones de la ficha de equipo.
- [x] Convertir la barra lateral en un menú desplegable y añadir navegación
  espacial con flechas, `Z` para aceptar y `B` para limpiar el selector.
- [x] Sustituir los nombres de contadores por símbolos y retirar cualquier
  control manual de Medallas.
- [x] Integrar las siluetas definitivas de los seis roles, compactar PS/stats y
  mantener visibles los cuatro movimientos en todas las tarjetas de Equipo.
- [x] Completar la ficha con movimientos sin numerar y seis recuadros IV/EV.
- [x] Convertir minimizar en barra flotante y animar el menú lateral sin tapar
  Configuración ni reconstruir prematuramente la página visible.
- [x] Encajar los cuatro movimientos de Equipo en una fila, integrar IV/EV bajo
  cada stat y anclar el tooltip al botón real del rol.
- [x] Corregir la geometría de la capa lateral, esperar su cierre antes de
  navegar y eliminar la reentrada que dejaba capturas oscuras superpuestas.
- [x] Retirar el cierre inerte de la primera pantalla de Drafteos y reservar la
  vuelta al inicio para los pasos posteriores.
- [x] Impedir que seleccionar la pestaña ya visible reconstruya su árbol.
- [x] Separar la barrera de navegación en una superficie compuesta independiente
  y retirar el frame estable solo después de componer por completo el destino.
- [x] Convertir el lateral en un drawer precalculado de ancho fijo y verificar su
  cadencia real sin relayout del contenido durante el deslizamiento.
- [x] Pestaña global de MT implementada sobre el selector/writer actual, con
  catálogo completo, posesión y reglas RoleRun separadas. Validada físicamente
  en BDSP/Ryujinx tras alpha.100.
- [x] Validar físicamente la transacción BDSP de EV por rol de alpha.101. El
  recálculo de stats/HP, precondiciones, readback y rollback ya disponen de
  regresiones automatizadas; Líbero y la asignación fija automática quedaron
  validados en Ryujinx el 23 de agosto de 2026.

- [x] Partir de una copia byte a byte del RoleRun original alpha.86 y mantener
  intactos tanto el original como el prototipo rechazado.
- [x] Reducir navegación, eliminar Dashboard y Modo Libre, e integrar Estado de
  la Run y la barra inferior de operaciones.
- [x] Unificar Equipo y PC con seis casillas, inspector, búsqueda, flechas,
  drag seguro y alternativa mediante botones.
- [x] Integrar MT y Drafteos completos sin cambiar compatibilidad, consumo ni
  writers.
- [x] Integrar Ayuda, bajas y los selectores normales; conservar únicamente la
  barra flotante y el fantasma técnico temporal como ventanas separadas.
- [x] Reorganizar Configuración y centralizar la apertura segura de rutas.
- [ ] Validación manual breve de la navegación y presentación alpha.87.

### Estado realtime heredado de alpha.86

La paridad BDSP/Ryujinx se dirige y verifica mediante la matriz maestra
`docs/BDSP_REALTIME_PARITY.md`; este roadmap conserva únicamente el resumen de
hitos.

- [x] BDSP/Ryujinx: validar físicamente el bridge GDB de solo lectura, Title ID
  y módulo principal `SwitchPlayer.nss` en Perla Reluciente 1.3.0.
- [x] BDSP/Ryujinx: demostrar la cadena de cajas 40×30 mediante coincidencia
  exacta de los 11 PB8 ocupados con el save.
- [x] BDSP/Ryujinx: demostrar por separado `PokeParty` runtime, sus seis
  identidades y HP; no reutilizar la prueba de cajas como si fuera party.
- [x] Ryujinx: aislar la causa del lag observado con GDB mediante comparación
  física A/B; no convertir GDB en transporte permanente si degrada el juego.
- [ ] BDSP: party, roles, movimientos y HP/batalla ya están incorporados en
  Adapter/Core/UI de solo lectura. Alpha.67 queda validada para watcher, KO y
  selector. Alpha.68 demostró que el HP lógico se adelanta 6,167 s al inicio
  de la animación visible; alpha.69 sincroniza el compromiso con el final de la
  barra y queda validada físicamente en combate salvaje simple. Alpha.70 integra
  el PC de solo lectura, pero su primera prueba demostró refresco tardío y nivel
  sin ancla. Alpha.71 corrige la omisión causal y queda validada físicamente para
  cambios equipo→PC y PC→equipo realizados dentro del juego. Alpha.72 incorpora
  seguimiento PC↔PC acotado mientras la pestaña está visible y queda validada
  físicamente, incluido el reposo sin repintados. Alpha.73 incorpora la mochila
  y las MT desde el array live de 3.000 registros demostrado, sin fallback al
  save ni escrituras. Alpha.74 corrige la apertura diferida de SUSTITUIR, la
  previsualización persistente de ELIMINAR ATAQUE, la herencia de rol en swaps
  preparados por RoleRun y la migración atómica del layout histórico de esta
  Run. Alpha.75 elimina el guardado diferido y añade el writer transaccional de
  movimientos/roles de party y consumo de MT. Alpha.76 distingue la ausencia
  normal de BattleProc, hereda el rol antes de publicar un intercambio PC y
  garantiza seis celdas físicas incluso durante un conflicto. La prueba física
  combinada de MT y cambio 1↔1 dentro del PC queda validada por el usuario.
  Alpha.77 añade el reader de los ocho SystemFlags de medallas demostrado por
  OpenDPR, PKHeX y el Ryujinx físico actual, y conecta el valor absoluto a
  Run/UI/OBS. La sincronización inicial 0→2 quedó validada físicamente el
  2026-08-22; queda pendiente validar una transición nueva 2→3 y OBS. Alpha.78
  añade el intercambio Equipo↔PC 1↔1 transaccional sobre los 344 bytes completos;
  alpha.79 corrigió un selector vecino, no el modal que abre el botón de Equipo;
  la segunda prueba física lo demostró sin alcanzar el writer. Alpha.80 conecta
  ese punto de entrada exacto a la matriz RAM y el usuario validó que ya muestra
  Pidgeotto live. La misma prueba demostró que el filtro inmediato descartaba el
  `PendingTeamChange` antes de iniciar el writer; alpha.81 abre esa compuerta solo
  para el swap 1↔1 probado. El usuario validó físicamente alpha.81: el cambio
  se reflejó correctamente dentro del juego. El caso 1↔1 queda cerrado.
  Dos capturas físicas posteriores demostraron exactamente el contrato de cola
  6→5→6: seis objetos fijos, `m_memberCount`, PB8 vacío canónico y un único slot
  de caja, sin cambios vecinos. Alpha.82 implementa ambas direcciones con
  precondiciones, readback y rollback. El usuario validó físicamente desde
  RoleRun el ciclo sexto→PC→sexto en SP 1.3.0 / Ryujinx. Retirar un miembro
  intermedio quedó demostrado después mediante una captura nativa completa:
  los objetos permanecen fijos, cada PB8 posterior se copia literalmente al
  slot anterior, el último recibe el vacío canónico y el contador cambia al
  final. Alpha.83 implementa esa compactación con readback y rollback completo;
  el usuario validó físicamente la operación iniciada desde RoleRun y confirmó
  que todos los cambios se reflejaron correctamente. Alpha.84 compone esas
  unidades ya demostradas para sustituir atómicamente un Pokémon debilitado
  entre party, PC y Cementerio, con regresiones de éxito, rechazo y rollback;
  el usuario validó físicamente el caso de un KO en SP 1.3.0 / Ryujinx: selector
  postcombate, sustituto en party, debilitado en Caja 4 y un único descuento de
  vida. La prueba posterior de dos KO también quedó validada: dos vidas exactas, dos
  selectores consecutivos sin minimizar, dos miembros en Cementerio y dos
  sustitutos en party. El marcador de uno de esos sustitutos también coincidió
  dentro del juego con el rol heredado por RoleRun. Reconexión, OBS y combates
  especiales siguen separados.
  Alpha.85 incorporó Caramelo Raro ×999, Repelente Máximo ×999 y dinero máximo
  como transacciones RAM inmediatas. La prueba física validó Caramelo Raro y
  dinero, pero demostró que la identidad `79` usada por el tercer botón era
  Repelente normal. Alpha.86 corrige Repelente Máximo a `77` y, como ese objeto
  está ausente en la partida, reproduce el alta del bolsillo General mediante
  `max(SortNumber)+1`, demostrada por OpenDPR y PKHeX. El usuario validó
  físicamente el resultado Repelente Máximo ×999; las tres utilidades quedan
  cerradas. El editor manual de roles para un
  Pokémon que permanece dentro del PC queda descartado por decisión de producto.
- [x] BDSP: establecer baseline real del save, revisión, mod y configuración de
  Ryujinx e incorporar el transporte GDB genérico sin offsets ni escrituras.

### Aparcado hasta nuevo aviso

- [x] USUM: validar físicamente que alpha.65 recupera 0→1 al abrir RoleRun con
  el Lizastal Z ya presente en la mochila viva.
- [x] USUM: corregir la primera divergencia del primer Kahuna: la ancla
  `_tm_guest_inventory_anchor` demostrada era ignorada en favor de una caché de
  escritura distinta.

- [ ] USUM: validar físicamente los incrementos 1→2, 2→3 y 3→4 de los Kahunas;
  el primer incremento 0→1 ya está validado y la traza recoge valor y
  procedencia sin intervención técnica.
- [x] Auditar los fallos alpha.59–63 en los cuatro backends 3DS y separar los
  contratos comunes de las estructuras RAM exclusivas de USUM.
- [x] Impedir que un fallback de `main` stale reduzca progreso realtime más
  nuevo en ORAS, X/Y, SM o USUM.
- [x] Verificar el rollback inmediato de utilidades en los dos writers Gen 7.
- [x] Corregir el parser PC USUM para usar `personal_uu` de PKHeX.

- [x] USUM/UI: validar físicamente que dos bajas listas encadenan sus selectores
  sin minimizar/restaurar RoleRun.
- [x] USUM: validar físicamente alpha.62 con dos KO durante un combate; ambos se
  comprometen, el estado ambiguo termina por convergencia y los selectores quedan
  preparados después del final real.
- [x] UI: hacer que cerrar o resolver el primer selector avance la cola de bajas
  y reintente mientras una sustitución anterior siga aplicándose.
- [x] USUM: reemplazar el supuesto terminal obligatorio `0x00040000/1` por la
  convergencia demostrada KO visible→PartyData dentro del estado ambiguo
  `0x00040005/6`.
- [x] USUM: validar físicamente en alpha.61 que Porygon y Eevee se detectan y
  comprometen inmediatamente con el mapeo PK7 de filas.
- [x] USUM: sustituir la desambiguación imposible por Max/HP repetidos por la
  identidad PK7 checksum-válida alineada con cada battle row.
- [x] USUM: eliminar el supuesto `battle row N == party slot N`; resolver una
  correspondencia demostrable y rechazar grupos ambiguos.
- [x] USUM: distinguir el estado suspendido de selección forzada del terminal
  físico de batalla para no abrir el selector antes de tiempo.
- [x] USUM: dejar de tratar la base de HP del cheat como localizador permanente;
  resolverla por party host↔guest, estructura completa, unicidad y readback.
- [x] Aislar todos los tests de `Documentos\RoleRun Manager` y corregir el doble
  Windows de `test_faint_picker_floating.py` sin alterar funcionalidad.
- [ ] X/Y: validar/activar operaciones RoleRun que cambian el tamaño de party.
- [ ] X/Y/Citra: mantener validado el ciclo de reinicio y reconexión GDB.
- [ ] Bridge DS para BW/HGSS/Pt/DP. B2/W2 tiene ya una primera party PK5 de
  solo lectura en melonDS dentro de la serie v0.2.6.
- [x] Frontera genérica GDB RSP para Ryujinx en modo solo lectura.
- [x] Adapter realtime BDSP: alpha.67 queda físicamente validada para conexión,
  watcher, KO, persistencia y selector en un combate salvaje simple.
- [x] BDSP/UI: demostrar con alpha.68 la relación entre HP lógico,
  `BUIStatusWindow._currentHP` y `HpBar.IsAnimation`.
- [x] BDSP/UI: validar físicamente que alpha.69 espera a que la barra llegue a
  cero y termine su animación antes de comprometer la muerte.
- [x] BDSP/party: validar una reordenación juego→RoleRun de dos miembros y
  comprobar que identidad, icono y rol permanecen asociados al Pokémon.
- [x] BDSP/PC: alpha.71 validada físicamente al depositar y recuperar varios
  miembros desde el PC del juego; refresco inmediato y datos conservados. Las
  escrituras iniciadas por RoleRun siguen cerradas.
- [x] BDSP/PC: alpha.72 validada al mover un miembro entre dos cajas sin cambiar
  la party; origen/destino se actualizan y los polls estables no repintan.
- [ ] BDSP/MT: alpha.74 queda validada físicamente para abrir SUSTITUIR, crear un
  hueco por borrado y reflejar el decremento live de una MT consumida dentro del
  juego. Alpha.75 implementa movimiento+PP+consumo directamente en Ryujinx con
  readback y rollback; falta la validación física de esa transacción.

## Capacidades incorporadas después del roadmap histórico

- [x] Sol/Luna: party, roles, movimientos, inventario/MT, PC, muertes y progreso
  de Kahunas en el backend Azahar.
- [x] UltraSol/UltraLuna: backend dedicado con party, roles, movimientos,
  inventario/MT, PC y progreso de Kahunas.
- [x] UltraSol/UltraLuna: detección de muertes y fallback post-combate.
- [x] UltraSol/UltraLuna: validar físicamente el final postcombate de alpha.62.
- [x] UltraSol/UltraLuna: validar físicamente la cola de varios selectores de
  alpha.63 en el emulador.
- [ ] UltraSol/UltraLuna: validar físicamente la detección automática de los
  cuatro Kahunas; es la última capacidad realtime pendiente de 3DS.

## Registro cronológico conservado

### 0.2.1-alpha.18

- [x] X/Y: implementar Caramelo Raro ×999, Repelente Máximo ×999 y dinero máximo con escritura viva verificada.
- [x] Global: permitir Sustituto a Asesino y Mago sin añadirlo a los pools de drafteo.
- [x] Global: añadir catálogo MOVIMIENTOS por rol, buscable y filtrado por el juego cargado.
- [x] Global: eliminar la compatibilidad de especie como restricción al enseñar MT desde RoleRun.
- [x] Validación empírica en Pokémon X/Azahar 263745c de las tres utilidades
  X/Y: Caramelo Raro ×999, Repelente Máximo ×999 y dinero máximo.

### 0.2.1-alpha.12

- [x] X/Y: resolver el primer depósito en PC cuando el último `main` no tiene anchors de cajas.
- [x] X/Y: impedir que una operación `party-to-box` no soportada se proyecte como si hubiera ocurrido en vivo.
- [x] Mantener intacto el bug de reinicio Citra/GDB mientras continúa la paridad funcional.
- [ ] X/Y: validar una escritura viva segura para operaciones que cambian el tamaño de la party; hasta entonces se hacen desde el PC del juego.

### 0.2.1-alpha.11

- [x] X/Y: integrar la matriz PC viva 31×30 con la pestaña CAJAS PC y la reconciliación de cambios hechos desde el juego.
- [x] Reutilizar la lógica Gen 6 validada de ORAS para Mover/Sacar/Dejar.
- [x] Mantener protegidas las operaciones X/Y que cambian el tamaño de party iniciadas desde RoleRun.
- [x] Aparcar temporalmente el bug de reinicio Citra/GDB para no bloquear la paridad funcional de X/Y.

### 0.2.1-alpha.10

- Robustez X/Y/Citra: reinicio interno autónomo mediante broker watchdog.
- Eliminar falsos positivos de muerte antes de añadir más juegos.
- Resolver compatibilidad de MT desde la capa efectiva que ejecuta el emulador.
- Mantener ORAS y las funciones validadas de alpha.8 sin regresiones.

### 0.2.1-alpha.8

Prioridad de robustez X/Y/Citra:
- broker GDB persistente y reconexión de la UI sin reiniciar juego;
- bajas live por slot;
- mochila MT corregida y primera MT sin guardar.

### 0.2.1-alpha.7
- X/Y: medallas live en Azahar/Citra.
- X/Y: sonda de batalla y flujo de debilitados/sustitución.
- X/Y: corregir y validar mochila MT/MO.

## Roadmap histórico de la etapa 0.1–0.2.1

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
- [x] Empaquetado/instalador (v0.5.0: instalador sin requisitos, publicado y probado
  automáticamente por GitHub). Fase beta pendiente.
