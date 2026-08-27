# RoleRun Manager Design Evolution

## Cambios posteriores a alpha.100 — pestaña global de MT

- `GlobalTMView` añade el catálogo MT como página principal sin conocer RAM,
  perfiles ROM ni writers.
- El controlador agrega por movimiento el resultado ya demostrado de
  `_tm_flow_candidates()` para los seis miembros y conserva separadas fuente,
  posesión y validez RoleRun.
- La selección MT→Pokémon desemboca en `IntegratedTMTeachFlow` con la MT
  preseleccionada; no se crea una segunda ruta de aplicación.
- La lista y las seis tarjetas son persistentes: hover solo configura estado y
  colores. El scroll no forma parte del estado que se reconstruye.
- Tras confirmar, la superficie se conserva hasta el readback; entonces el
  controlador actualiza inventario, party y matriz sobre la misma vista.
- La composición fue revisada iterativamente a 1920×1080 hasta coincidir con el
  viewport real. La validación física BDSP/Ryujinx continúa pendiente.

## Base demostrada

- Origen: `RoleRun Manager Dev`, versión `0.2.2-alpha.86`.
- Copia de trabajo: `RoleRun Manager Design Evolution`.
- Rama / HEAD de partida: `main` /
  `0659aa624a68df7cd4d116d59c62090b911752ef`.
- Comparación inicial: 951 archivos fuera de `.git`, 74.302.609 bytes y hash
  agregado idéntico
  `4025b7627611bf439ef592f776aff2b079288242626e4fc069d0d8f009474f1a`.
- Baseline previa: 581 tests superados.
- El prototipo rechazado no se utilizó como shell, estructura ni código base.

## Arquitectura de presentación

La composición histórica permanece en `app/ui.py`, pero el nuevo código visual
se separa en:

- `app/ui_state/`: navegación, mensajes de operación, selección Equipo/PC,
  intención de drag, flujo MT y resolución de rutas;
- `app/ui_components/`: barra inferior, Estado de la Run, información de rol y
  superficies integradas compatibles con selectores históricos;
- `app/ui_views/`: Equipo/PC, MT, Drafteos y guía del formato.

Estos módulos reciben datos y callbacks. No conocen offsets, transporte,
readers, writers ni formatos de save.

## Contratos preservados

- Equipo↔PC continúa usando `PendingTeamChange`,
  `_prepare_pc_team_change()` y los writers existentes.
- MT continúa usando `_build_tm_candidates()`,
  `_tm_move_compatible_with_role()` y `_queue_tm_teach()`.
- Drafteos conserva generación, reroll y consumo en el mismo punto funcional.
- Bajas conservan detección, `LivePartyWatch`, vida, persistencia,
  `replace-fainted`, Cementerio, readback y rollback.
- Un resultado visual preparado nunca se publica como confirmado antes de la
  comprobación independiente del juego.
- En BDSP live, Equipo y PC conservan juntos el último estado confirmado hasta
  recibir el readback del cambio.

## Límites demostrados

No existe writer demostrado para PC→PC ni para reordenación física
Equipo→Equipo. Ambas interacciones se muestran como no disponibles y no crean
una proyección falsa. Las pruebas sintéticas verifican presentación y routing,
pero no sustituyen la validación física ya exigida a cada función realtime.

## Verificación visual

Las capturas canónicas están en `diagnostics/design_evolution/` e incluyen:

- Equipo/PC a 1100×720 y 1360×768;
- MT, pasos 1–3;
- Drafteos, pasos 1–3;
- guía integrada de Ayuda;
- sustitución de baja integrada;
- editor de rol integrado;
- Configuración a 1440×900 con escala 125 %.

Suite final de alpha.87: 608 tests superados con
`py -3.14 -m pytest -q -p no:cacheprovider`.

## Alpha.88 — primera fase de densidad e información

- La cabecera ancha incorpora un resumen accionable de vidas, curaciones,
  medallas y drafteos. Por debajo de 1380 px de cabecera se oculta para no
  solapar las acciones; la barra lateral conserva el resumen compacto.
- Equipo/PC ya no calcula su alto desde una resta fija a la ventana: usa el
  cuerpo disponible y conserva un fallback de geometría para el primer render.
  La captura 1900×1010 muestra seis miembros, 30 slots y ficha completa a la vez.
- `SavePokemon` acepta datos de entrenamiento opcionales. Solo BDSP los rellena
  en esta versión, desde el PB8 que ya supera sanity, checksum y doble lectura.
  Otros backends muestran `No disponible`; no se les atribuyen offsets comunes.
- Drafteos usa una matriz 3×2 y candidatos de altura acotada. Las descripciones
  proceden del `ss_wazainfo` hermano al `personal_masterdatas`; el lenguaje se
  conserva y se muestra, no se traduce ni se infiere.

Límites deliberados: esta fase no escribe EV, no recalcula stats y no crea la
pestaña global de MT. Ambas peticiones quedan especificadas en `ROADMAP.md` y
se implementarán sobre los writers ya demostrados o sobre una nueva transacción
con evidencia completa, respectivamente.

Suite completa alpha.88: **614 passed** en 22,66 s con
`py -3.14 -m pytest -q -p no:cacheprovider`.

## Alpha.89 — jerarquía visual y respuesta

- Equipo usa seis filas equivalentes; cada tarjeta tiene un contenedor interior
  que protege el borde de selección e incorpora identidad, PS, naturaleza,
  habilidad y objeto. El único scroll local es el de la matriz PC.
- Drafteos conserva la matriz 3×2, pero convierte cada opción en una ficha con
  sprite de 112 px, datos jerarquizados y cuatro chips de movimientos.
- La transición se implementa sobre colores e imágenes de `IntegratedDraftFlow`;
  no modifica el atributo alpha de la ventana. Movimientos conserva una ruta
  explícita de vuelta al drafteo que lo abrió.
- `CenteredLoadingIndicator` proporciona una señal animada no modal para las
  lecturas de PC y mochila MT. La carga inicial incorpora el mismo patrón.

La fase no cambia modelos funcionales, compatibilidad, consumo, readers ni
writers. EV por rol y la pestaña global de MT continúan como trabajo separado.

Suite completa alpha.89: **620 passed** en 22,92 s con
`py -3.14 -m pytest -q -p no:cacheprovider`. Se revisaron capturas sintéticas
de Equipo/PC y Drafteos a 1900×1040.

## Alpha.90 — viewport completo y controles permanentes

- La cabecera deja de ser una barra accionable: contiene cuatro tarjetas
  independientes con `−`, valor y `+`. La autoridad automática de progreso se
  conserva y deshabilita su edición manual cuando corresponde.
- Equipo ocupa cinco sextas partes de la altura útil de la matriz PC; así sus
  seis tarjetas terminan en la fila 21–25 y la fila 26–30 permanece exclusiva
  de la caja. La caja es una cuadrícula fija 5×6 sin scroll.
- Equipo/PC y Drafteos ajustan su superficie al canvas visible y reaccionan a
  cambios de tamaño sin basarse en la altura total de la ventana.
- El primer paso de Drafteos conserva los seis sprites grandes y añade a cada
  ficha naturaleza, stats, IV y EV sin ocultar ningún botón `ELEGIR`.

No cambia ningún contrato funcional. Suite completa alpha.90: **620 passed** en
23,29 s con `py -3.14 -m pytest -q -p no:cacheprovider`; revisión visual sintética de
Equipo/PC y pasos 1–3 de Drafteos a 1900×1040.

## Alpha.91 — equipo protagonista y control por teclado

- La barra lateral colapsada deja 209 px adicionales a las vistas y se despliega
  como una capa con fondo oscurecido y cierre exterior.
- Equipo ocupa el bloque dominante; cada una de sus seis fichas publica los
  datos de combate y composición útiles sin depender del inspector. PC usa una
  matriz estrecha de tres columnas con scroll local.
- `SpatialSelection` separa la geometría de navegación de Tk. Equipo/PC,
  Drafteos y MT enlazan las teclas en el toplevel, respetan campos de texto y
  comparten flechas, `Z` y `B`.
- La señal de carga permanece animada durante escrituras/readback realtime. Las
  lecturas de mochila ORAS/X/Y usan un worker sin modificar la autoridad de los
  datos: ORAS mantiene el fallback documentado y X/Y exige RAM válida.

No se añaden offsets ni writers. EV por rol y la pestaña global de MT continúan
como fases funcionales separadas.

Suite completa alpha.91: **625 passed** en 22,22 s con
`py -3.14 -m pytest -q -p no:cacheprovider`. Revisión visual a 1900×1040 de
Equipo/PC, menú lateral desplegado, Drafteos y MT.

## Alpha.92 — siluetas de rol y continuidad visual

- Las seis siluetas suministradas se almacenan como recursos originales. La UI
  recorta por alfa y genera el dorado al tamaño requerido sin inferir ni volver
  a dibujar su geometría.
- Equipo reorganiza cada ficha: mote/nivel, PS compacto, stats 2×3,
  habilidad/objeto y cuatro movimientos. La tarjeta completa abre el inspector;
  el icono conserva la acción independiente de ayuda y tooltip.
- El inspector centra sus campos, elimina la numeración de movimientos y añade
  una matriz 2×3 específica para IV/EV. Drafteos comparte la jerarquía 2×3 y
  muestra el icono del rol.
- Minimizar selecciona la barra flotante. El lateral anima su ancho con una
  curva suave y el cambio de pestaña conserva el árbol anterior como búfer
  hasta que el nuevo está listo, eliminando el vacío previo al repintado.

No cambia ningún contrato funcional ni realtime. Suite completa alpha.92:
**631 passed** en 23,10 s con
`py -3.14 -m pytest -q -p no:cacheprovider`; revisión visual sintética a
1900×1040 de Equipo/PC, ficha, Drafteos y lateral.

## Alpha.93 — ficha compacta y transición no reentrante

- Equipo distribuye sus cuatro movimientos en una única fila. El tooltip se
  ancla al botón de rol y no a coordenadas de otro contenedor.
- La ficha integra IV y EV como dos líneas bajo cada stat; desaparece la matriz
  inferior redundante y habilidad/objeto recuperan ese espacio.
- El inicio de Drafteos carece de un cierre sin destino. Desde cualquier paso
  posterior, una flecha vuelve explícitamente a la selección de Pokémon.
- La capa oscura del lateral es un widget Tk nativo con el tamaño exacto del
  contenido visible. El lateral anima su ancho sin provocar un relayout.
- El cambio de página espera al fin real de esa animación. La captura que actúa
  como barrera visual resuelve solo tareas idle: no llama al bucle completo de
  eventos dentro del render, evitando navegaciones o repintados reentrantes.

No cambia ningún contrato funcional ni realtime. Suite completa alpha.93:
**635 passed** en 23,37 s con `py -3.14 -m pytest -q`; revisión visual a
1920×1080 de Equipo/PC, tooltip, Drafteos, apertura lateral en tres fotogramas,
cambio de pestaña y escala 125 %.

## Alpha.94 — barrera de composición independiente

- Seleccionar la página ya activa no ejecuta `render_page()` ni intercambia el
  body. La acción se limita a cerrar el lateral.
- La barrera de navegación es un `Toplevel` transitorio, sin bordes y con su
  propio frame compuesto. Conserva una captura completa del origen mientras el
  doble buffer de widgets termina el destino debajo.
- El primer cambio de opacidad fuerza a DWM a componer la nueva página sin
  hacerla perceptible. Tras 120 ms de asentamiento, un fade de 150 ms retira la
  superficie estable; la geometría no participa en la animación.
- El drawer lateral se construye una sola vez a 285 px y se conserva fuera del
  viewport cuando está cerrado. La animación modifica solo X con ease-out
  cúbico; no ejecuta pack/grid ni cambia el ancho de sus descendientes.
- La herramienta sintética registra cada posición real del drawer y declara por
  separado las dos barreras de transición, lo que evita confundir un fade todavía
  vivo con un repintado incompleto.

No cambia ningún contrato funcional ni realtime. Suite completa alpha.94:
**637 passed** en 22,95 s con `py -3.14 -m pytest -q`. La grabación
`alpha94-automated-navigation-final-60fps.mp4` y su storyboard a 30 fps confirman
que el contacto visual solo mezcla dos páginas completas. Se verificó además
el estado asentado a escalas 100 % y 125 % y la navegación inerte al destino ya
activo.

## Alpha.95 — frame inmutable e indicador independiente

- El frame limpio capturado antes de abrir el drawer se transfiere directamente
  a la barrera de navegación. Retirar el scrim ya no obliga a capturar otra vez
  mientras DWM recompone la luminosidad del contenido.
- Al concluir el cierre, el drawer sale de `place`; no queda una ventana fuera
  del viewport capaz de repintar el tirador `<` sobre el rail colapsado.
- El indicador de carga se pinta sobre el HWND de la captura mediante un worker
  GDI. No depende de `after`, así que sus doce radios siguen rotando mientras el
  hilo Tk construye sincrónicamente el árbol de destino.
- Elegir de nuevo la pestaña activa descarta cualquier captura transferida que
  ya no tenga consumidor.

La grabación de control `alpha95-navigation-control-60fps.mp4` y el contacto
ampliado `alpha95-spinner-contact-sheet.png` demuestran que los radios avanzan
mientras el resto del frame permanece estable. La captura asentada conserva
solo el tirador `>`. No cambia ningún contrato funcional ni realtime.

## Alpha.96 — loaders fuera del árbol reconstruido

- `_show_loading_overlay` y `_show_busy_indicator` crean la misma superficie
  independiente: captura oscura estable, mensaje y spinner GDI.
- La apertura de Run cubre la ventana completa; las operaciones internas cubren
  el contenido sin alterar el rail lateral.
- El indicador no usa una barra indeterminada gobernada por `after`, por lo que
  permanece móvil durante trabajo síncrono de Tk.
- La finalización de PC retira la barrera después de `_smooth_render_page()`, no
  antes de construir las cajas y tarjetas definitivas.
- La barrera de navegación aplica el oscurecido al frame autoritativo antes de
  publicarlo.

El preview fuerza un bloqueo real de 1,7 segundos del mainloop. La grabación
`alpha96-activity-overlay-control-60fps.mp4` y el contacto a 20 fps demuestran
que el spinner avanza mientras el fondo permanece completo, uniforme e
inmutable. `alpha96-navigation-dark-control.png` verifica el origen oscuro de
la navegación. No cambia ningún contrato funcional ni realtime.
