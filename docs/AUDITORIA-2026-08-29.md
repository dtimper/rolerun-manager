<!-- Auditoría generada el 2026-08-29 por 57 agentes de lectura.
     1498 lecturas de código. Cada hallazgo pasó por dos
     refutadores independientes y solo se conserva lo que ambos dieron por real.
     Solo lectura: no se ejecutó el programa ni ningún emulador. -->

# INFORME DE AUDITORÍA — RoleRun Manager
**Solo lectura. 29-08-2026. 13 defectos confirmados, agrupados en 11 problemas. Ordenados por daño real, no por elegancia.**

---

## 1. Se pierden datos de la Run, sin aviso y sin vuelta atrás

### 1.1 El historial y la configuración se reescriben enteros, sin átomo y sin copia — y una lectura fallida se interpreta como "no hay nada"
`app/run_service.py:375-381` (lector del historial), `:384-396`, `:498`, `:569`, `:691`, `:728`, `:758` (los seis escritores) y `:368-373` (`save` de config.json).

**Qué le pasa al usuario.** Dos caras del mismo defecto.

*Historial:* si `history.json` queda ilegible un instante —un `OSError` transitorio de OneDrive o del antivirus basta; el `except` captura `OSError`, no solo `JSONDecodeError`—, el lector devuelve lista vacía. El siguiente evento (basta con que muera un Pokémon: `register_detected_faint` escribe historial solo) reescribe el archivo con ese único evento. La partida entera de registro desaparece. La pantalla dice "0 evento(s) guardados" y "La historia comienza aquí", el botón LIMPIAR HISTORIAL se deshabilita solo, y el Ctrl+Z de contadores responde "Nada que deshacer". No hay copia de `history.json` en ningún sitio del repositorio.

*Configuración:* `config.json` guarda TODO el estado vivo (contadores, roles fijados, hidden_roles, bajas pendientes, Cementerio, drafteos guardados, atajos) y se escribe con `write_text`, que trunca a cero antes de escribir. Se llama decenas o cientos de veces por sesión. Un corte, un cierre forzado o un disco lleno durante esa ventana deja la Run imposible de abrir: `open_or_create` (`run_service.py:245`) parsea sin `try`, y como el slug se recalcula igual cada vez, cada intento vuelve a estrellarse con "No se pudo abrir la Run: Expecting value…". La única salida es `force_new`, es decir, una Run vacía.

**Qué cambiar.** (a) Las siete escrituras de `history.json` y `config.json` deben ser atómicas: volcar a `.tmp` y `os.replace`, exactamente como ya hace `app/game_source_service.py:129-140` en este mismo repositorio. (b) El lector de historial debe distinguir "no existe" de "no puedo leerlo": ante un archivo que existe pero no parsea, renombrarlo a un lateral fechado, avisar de forma ruidosa y **prohibir** que un escritor lo reemplace con una lista vacía. (c) Conservar la copia anterior de `config.json` en la carpeta `backups/` de la Run, que ya se crea (`run_service.py:238`) y hoy no se usa para esto.

*Matiz honesto:* la corrupción exige un fallo externo (corte, bloqueo, disco lleno). No pasa a diario. Cuando pasa, es total y silenciosa. Y `list_projects` (`:317-337`), que se traga el error con `continue`, hoy no tiene ni un llamador: es código muerto, así que la "desaparición del selector" que se describía en el hallazgo original no ocurre.

---

### 1.2 Ctrl+Z devuelve contadores que no pagó el usuario y deja la contrapartida en su sitio
`app/ui.py:889-899` (`_capture_edit_snapshot`) y `:928-940` (`_restore_edit_snapshot`). **Dos hallazgos que son el mismo defecto.**

**Qué le pasa al usuario.** El snapshot de deshacer copia siete campos, y `saved_drafts`, `pending_faints` y `graveyard_pokemon` no están entre ellos. Pero `counters` sí, y al restaurar se persiste el proyecto entero. Consecuencias:

- **Drafteos infinitos.** Guardar una tirada cuesta 1 drafteo. Ctrl+Z devuelve el contador y el movimiento sigue esperando en MOVIMIENTOS. Repetible sin límite, sin ventana temporal (entre guardar y deshacer no hay nada que resetee el historial de edición). Contradice literalmente el contrato de `app/drafteos_guardados.py`: "Se paga al guardar".
- **Vidas resucitadas.** Una baja detectada en vivo descuenta la vida y añade la baja. El repintado que sigue a la baja ya empuja ese estado a la pila, así que el primer Ctrl+Z que el usuario pulse después devuelve la vida y deja la baja registrada pidiendo sustituto, con su evento en `history.json` diciendo 4→3. `config.json` queda escrito con la contradicción.
- **Caso inverso:** enseñar un guardado ya lo borró de disco; Ctrl+Z retira el cambio pendiente pero no devuelve el guardado. El drafteo pagado se evapora (mitigado en parte por Ctrl+Shift+Z y por el auto-aplicado en vivo).

El toast dice solo "CAMBIO DESHECHO". No dice qué.

**Qué cambiar.** Dos cosas, y la segunda importa más. (a) Incluir `saved_drafts`, `pending_faints` y `graveyard_pokemon` en captura y restauración: ninguna mitad de un cobro puede viajar sola. (b) Lo que **no** es una edición del usuario no debe entrar nunca en la pila de deshacer: tras `register_detected_faint` y tras el ajuste automático de medallas (`ui.py:8789`), refrescar el snapshot de referencia para que la siguiente transición no confunda una muerte detectada por el juego con un paso deshacible. Nótese que el deshacer por historial (`run_service.py:473-478`) ya excluye deliberadamente las bajas; Ctrl+Z se salta esa decisión.

Cobertura: **cero**. No hay un solo test en `tests/` que ejercite capturar o restaurar.

---

## 2. Dejan el programa —o el juego— inservible

### 2.1 La barrera "Volviendo a Equipo y PC…" puede quedarse para siempre
`app/ui.py:16458` (`_retire_tm_close_when_ready`), programada una sola vez en `:16377`.

**Qué le pasa al usuario.** Al cerrar el selector de MT aparece una barrera opaca sobre el contenido. La comprobación que la retira se ejecuta **una vez**: sin `else`, sin reintento, sin tope, sin estado de fallo. Si en ese instante no sale afirmativa, la barrera —un Toplevel `overrideredirect` + `-topmost` sobre `self.content`— se queda tapando y bloqueando la página entera. Solo se sale cerrando la aplicación. Y peor: `_hide_busy_indicator` (`:22076-22087`) solo destruye la ventana si el diccionario de motivos queda vacío, así que con "tm-flow" clavado **ninguna** retirada posterior de ningún otro flujo puede quitarla ya, y encima le repone el texto.

Vías reales verificadas (el cierre normal con la X sobre una página quieta sí funciona): el flujo de MT **no se anula al navegar** —`render_page` destruye `_draft_view` y `_global_tm_view` pero nunca `_tm_teach_flow`—, y su `<Escape>` sigue enganchado a la raíz, así que pulsar Escape en otra página levanta la barrera cuando `_team_pc_view` ya es None; el botón "CONSULTAR MOVIMIENTOS" del propio selector, que cierra y navega a la vez, dejando dos plazos fijos (16 ms contra 34 ms) compitiendo sin que nadie los ordene; y que la firma del archivo de partida cambie mientras el selector está abierto (el emulador vuelca a disco: el modo de uso normal), lo que hace `_team_pc_cached_data()` devolver None.

**Qué cambiar.** Darle la misma forma que a su hermano `_retire_team_pc_loader_when_ready` (`:14395-14422`): reintentar con contador de intentos y, al agotarse, retirar la barrera de todos modos y publicar un estado de fallo visible. Un fallo ruidoso es preferible a una barrera eterna. Y desatar el `<Escape>` del selector cuando su frame muere, o anular `_tm_teach_flow` en `render_page`.

---

### 2.2 Un botón "reservado" fantasma congela Ryujinx cada vez que el usuario vuelve al juego
`app/ui.py:3239` (limpieza de `_gamepad_reserved_buttons`), guardas en `:1698-1703` y `:3240-3245`.

**Qué le pasa al usuario.** El juego queda suspendido: 0% de CPU, reloj parado, sin música, con la ventana pintada pero muerta. RoleRun no dice nada.

El mecanismo: el conjunto de botones reservados solo se limpia en la línea 3239, y el flanco de soltar el botón se consume antes, dentro de los `return` tempranos de las ramas "menú abierto" (`:3212`) y "RoleRun en primer plano" (`:3230`). Con el atajo **de fábrica** (`floating_menu` → botón Guide) el menú se abre en milisegundos, mucho antes de que el dedo suelte, así que el botón se queda dentro del conjunto para siempre. A partir de ahí, las dos únicas liberaciones automáticas de la retención de Ryujinx exigen que ese conjunto esté vacío, y no lo está. Cada vez que el usuario pincha en RoleRun y vuelve al juego, el juego se congela. Y también con solo pulsar cualquier atajo de mando mientras juega, sin tocar RoleRun.

*Menos grave de lo que parece:* no hay que matar el emulador. Abrir y cerrar el menú flotante lo descongela, y cerrar RoleRun también. El problema es que el usuario no tiene forma de saberlo. Requiere BDSP + Ryujinx + mando, y no tener activado `disable_input_when_out_of_focus`.

**Qué cambiar.** Descontar los botones ya soltados **antes** de los `return` de esas dos ramas (o descontarlos contra los pulsados de cada tick, no solo en la rama del emulador). Y añadir una barrera de seguridad: si la retención lleva N ticks activa sin overlay ni botón físicamente pulsado, liberar. Ninguna condición de liberación debería depender de un conjunto que puede quedar sucio.

---

### 2.3 Un fallo escribiendo en la carpeta de OBS mata el bombeo de sprites de toda la sesión
`app/ui.py:21773` (`_sync_obs_state` sin proteger) y `:21777` (el reenganche del sondeo, después).

**Qué le pasa al usuario.** Si la sincronización con OBS lanza —antivirus, backup, OneDrive; el disparador que el propio código nombra en `ui.py:1067`—, la excepción sale de `_poll_sprite_queue` antes de reprogramarse. El sondeo no vuelve a existir: solo hay dos `after` para él, el del arranque y el suyo propio. Consecuencias: la especie cuya descarga estaba en vuelo queda atascada para siempre (su id se quedó en el conjunto "en vuelo", que solo se limpia dentro del bucle muerto, y recargar la partida no lo desatasca), se pierde el aviso "IMÁGENES NO DISPONIBLES", y los sprites dejan de aparecer al terminar de bajar.

Y si ocurre durante el arranque no son siluetas: es un cuelgue. La barrera inicial exige todas las especies de la party en caché y **no tiene timeout por decisión explícita** (`ui.py:22566`). RoleRun no sale de la pantalla de carga hasta que se mate el proceso.

*Menos grave de lo alegado:* las especies ya descargadas reaparecen solas, porque `_sprite_source` repuebla la caché desde disco por su cuenta. Y la carpeta OBS no es configurable a una unidad extraíble: está fijada bajo Documentos.

**Qué cambiar.** Envolver la llamada como ya se hace en `ui.py:1063-1067` con el comentario "La edición de la Run no debe bloquearse si OBS no puede escribir", y avisar con el toast que ya está al lado. Y mover el reenganche del sondeo a un `finally`, como hace `_poll_gamepad`, para que ninguna excepción futura del cuerpo vuelva a matar el bombeo. Es el único sondeo autorreenganchado sin esa red.

---

### 2.4 MOVIMIENTOS se queda en "COMPROBANDO LA MOCHILA DE MT…" para siempre, y se lleva por delante los drafteos ya pagados
`app/ui.py:13767-13770` (`_resolve_global_tm_profile`), panel de espera en `:13905-13921`, drafteos en `:13930`.

**Qué le pasa al usuario.** En **HeartGold/SoulSilver, Diamante/Perla y Platino** la página nunca se pinta: el perfil devuelve None porque esas claves no están en `LIVE_TM_GAME_KEYS`, el único reintento vuelve a fallar, y nadie repinta jamás. Sin ningún mensaje —el selector individual sí avisa en ese caso (`:16499-16504`); la página global no.

El daño no es no ver las MT. Los **drafteos guardados se pintan en esa misma página**, detrás de la misma compuerta, y esa es su única superficie en todo el programa. Un drafteo que ya costó su contador queda inalcanzable, y el aviso al guardarlo dice "te espera en MOVIMIENTOS" (`:22759`), que es falso.

Caso adicional permanente: en ORAS/XY/SM/USUM, cancelar el diálogo de ROM deja la página igual de colgada hasta salir y volver a entrar.

**Qué cambiar.** Separar las dos columnas: la lista de drafteos guardados no depende de la mochila de MT y debe pintarse aunque el perfil sea None. Los drafteos los limita el rol, no el backend del juego. Y cuando el perfil sea None por juego no soportado, decirlo en pantalla en lugar de dejar el rótulo de carga. De fondo: `LIVE_TM_GAME_KEYS` es un alias de `ROLE_EV_WRITER_GAME_KEYS`, lo que ató "poder mostrar MT" a "poder escribir rol y EV", que son cosas distintas (HGSS sabe leer su tabla; lo que no está demostrado es escribirla).

---

## 3. Funciones que no hacen nada y no lo dicen

### 3.1 "Elegir sustituto" es un botón muerto en ORAS y X/Y
`app/ui.py:9944-9947`.

La barra ofrece el botón en cuanto hay una baja lista, sin mirar el juego (`:6234-6245`, y otra vez en `:9976-9982`). Pero el método sale por un `return False` mudo —en una función declarada `-> None`, huella de un copiar-pegar de `_ensure_live_pc_matrix_loaded`— cuando la clave no está en `FULL_MATRIX_LIVE_PC_GAME_KEYS`. ORAS y X/Y quedan fuera. El usuario pulsa y no pasa absolutamente nada: ni selector, ni cambio de estado, ni aviso. Y ese botón es la **única** reentrada posible tras cerrar el selector, porque el planificador automático exige que la baja no haya sido mostrada ya. No es que ORAS no soporte el selector: la apertura automática sí lo abre allí.

*No bloquea la Run:* "No sustituir" funciona, y hacer el cambio dentro del juego se reconcilia solo. Pero es exactamente el fallo silencioso que las reglas del proyecto prohíben.

**Qué cambiar.** O aplicar la misma compuerta al pintar la acción (no ofrecer lo que no se puede hacer), o que la salida publique el motivo real en la barra de operaciones. Y corregir el `return False` de una función `-> None`.

### 3.2 El mando se cae al cambiar de sección desde Movimientos
`app/ui.py:12804-12806` (destruye la vista) y `:3354-3356` (`_active_navigation_view` devuelve al dueño muerto).

Con el mando conectado en BDSP: estás en Movimientos, navegas a Ayuda, Configuración o Registro, y pulsas la cruceta. La autoridad de navegación sigue apuntando a la vista ya destruida —`_set_navigation_owner` nunca se llama con None y `_render_page_body` no la limpia para esas páginas—, el resalte intenta escribir color sobre un canvas muerto, y el `except Exception` de `_poll_gamepad` (`:3246-3253`) se come el error, cierra el mando y lo pone a None. El mando revive solo a los ~2 s y se vuelve a caer en la siguiente pulsación. Sin ningún aviso.

*Alcance real, más estrecho de lo alegado:* solo desde **Movimientos**. Equipo y PC y Drafteos protegen sus repintados widget a widget; `GlobalTMView._update_highlight` (`app/ui_views/global_tm_view.py:348-356`) no, a diferencia de su propio `_apply_keyboard`. Solo con Ryujinx/BDSP, que es donde existe el mando. El teclado está a salvo porque la vista desata sus bindings al destruirse: el agujero es exclusivo de la ruta del mando, que no pasa por bindings.

**Qué cambiar.** Limpiar la autoridad cuando muere su dueño: en `render_page`, junto a cada `destroy()`, soltar la autoridad si apunta a esa vista, y anularla al final de `_render_page_body` para las páginas que no publican vista navegable. Alternativa más barata: que `_active_navigation_view` descarte al dueño cuyo frame ya no exista (hay `_widget_alive` a mano). Y proteger `_update_highlight` como ya está protegido `_apply_keyboard`. Nota aparte: `_smooth_render_page` anula `_draft_view` y `_team_pc_view` al intercambiar superficie, pero no `_global_tm_view` ni la autoridad.

---

## 4. Reglas del formato mal aplicadas

### 4.1 Faltan seis movimientos en los datos, y el mismo hueco produce el falso positivo y el falso negativo
`data/moves.json:64` (`asesino_subir_ataque`), `:83` (`mago_subir_ataque_esp`), `:430` (`global_self_boosts`). **Dos hallazgos, un solo error de datos.**

**Cara ruidosa.** Tambor (187) y Luminicola (294) no están en ningún pool. Un Snorlax con Tambor al que se asigna Asesino, o un Volbeat con Luminicola al que se asigna Mago, muestra el movimiento en rojo con "No es compatible con el rol", se queda en preparación, y el diálogo ofrece eliminarlo. Tambor sube solo el Ataque y Luminicola solo el Ataque Especial: es literalmente lo que la ficha del rol permite (`app/role_content.py:30` y `:36`, "boosts que aumenten al menos el Ataque"). Y en ORAS conectado, aceptar ese diálogo puede traducirse en una escritura real sobre la partida viva que borra un movimiento legal.

**Cara muda.** Los mismos IDs tampoco están en `global_self_boosts`, y el Support se valida **por resta**: todo movimiento de estado es legal salvo los que figuren en esa lista. Resultado: un Support con Tambor, Luminicola o Acupresión (367) pasa en verde, pese a que su ficha dice que no puede aumentar sus propias estadísticas. Peor: como la misma lista gobierna qué MT ofrece el "+", RoleRun puede **ofrecer** MT32 Doble Equipo a un Support y etiquetarla "Compatible".

Que esto es un olvido y no una decisión se demuestra solo: `global_self_boosts` es casi exactamente la unión de los pools de rol, así que hereda sus huecos; y el pool de Asesino ya incluye Deslome (868), que hace lo mismo que Tambor pagando PS.

**Qué cambiar.** Añadir 187 y 294 a los pools de Asesino y Mago **y** a `global_self_boosts`; añadir 367 a `global_self_boosts`. Decidir explícitamente si evasión (104, 107) y ratio de crítico (116) cuentan como "estadística" en este formato, y dejar constancia de la decisión, igual que se hizo con Deseo y Campo de Hierba. Si la intención fuese excluir Tambor, entonces lo que hay que corregir es la ficha del rol, porque hoy dice otra cosa.

### 4.2 El drafteo de Líbero puede sacar dos veces la misma categoría
`app/draft_engine.py:109` y `:117`; `data/moves.json:10` y `:23`; `data/roles.json` (bloques Prisma y Support).

`prisma_problemas_estado` y `support_problemas_estado` son la misma lista de 11 IDs, con el mismo título, bajo dos claves. El dedup es por clave, no por título ni por contenido, así que en un **3,85%** de los drafteos de Líbero salen dos tarjetas rotuladas "PROBLEMAS DE ESTADO" alimentadas del mismo pool. Cuatro categorías útiles en vez de cinco.

*Refutado del hallazgo original:* la iluminación doble de tarjetas es **imposible** —la selección se identifica por clave, y las claves son distintas por construcción—. Y el 1,1% de movimientos repetidos entre tarjetas no es imputable a esto (solo 0,35% lo es); el resto viene de que `support_ataque_estado` es casi un superconjunto de los demás pools de Support, que es otra pregunta de diseño.

**Qué cambiar.** Unificar las dos claves en una sola de `data/moves.json` referenciada desde los dos roles: es lo que ya son de facto. Y ampliar el test correspondiente para que exija títulos únicos y no dependa de una única semilla — hoy comprueba claves únicas, que el propio dedup ya garantiza por construcción, así que esa aserción no puede fallar.

---

## 5. Rendimiento visible

### 5.1 La actualización en sitio de PS de la barra flotante nunca se aplica
`app/ui.py:9546` (el llamador anula la firma) contra `:3706-3708` (la ruta rápida la necesita).

`_publish_live_health` pone la firma anterior a None justo antes de llamar al repintado forzado, y la ruta rápida devuelve False si esa firma es None. Resultado: **cada cambio de PS en combate reconstruye la barra flotante entera** en vez de mover la barrita: dos PNG releídos de disco, un LANCZOS por sprite de rol (el propio proyecto lo mide en 3,77 ms) y unos 40 widgets recreados en el hilo de Tk. El log de perf del usuario lo confirma: las 9 muestras de la sesión salen con `"applied": False`. La optimización no se ha aplicado ni una sola vez.

Fuera de combate no ocurre (esa mitad del arreglo sí funciona). Ocurre exactamente cuando el usuario está mirando la barra.

**Qué cambiar.** No anular la firma antes de intentar el camino rápido: el `force=True` ya se salta por sí solo la comparación de igualdad, así que la anulación es innecesaria ahí. Moverla a la rama en que la barra no está visible. **Cuidado al tocarlo:** el mismo idioma aparece en otros seis sitios (`:1079, 2306, 2388, 7517, 8801, 11764, 11839`) y allí es correcto, porque cambia la composición y no la vida. Y añadir una prueba que ejercite el llamador de verdad: la actual sustituye el repintado por un contador y por eso no ve nada.

---

## 6. En discusión (una lente los refutó)

1. **`floating_bar.json` leído del disco 60 veces por segundo** (`app/ui.py:1711`). El derroche es real y no hay caché, pero medido cuesta ~5 ms/s: 1,3% del presupuesto de tick. Discrepancia sobre si es un síntoma o solo una incoherencia con la caché que el propio repo ya aplicó al `Config.json` de Ryujinx. *Apunte gratis: bastaría condicionar la comprobación a que haya algún botón pulsado.*

2. **Repintado redundante al pasar el ratón por una tarjeta de equipo** (`app/ui_views/team_pc_view.py:1933`). La escritura sin comparar existe, pero el coste real es 1-3 ms por entrada, no un tirón; y la reproducción alegada es falsa (sprite y estadísticas no están enganchados). Lo que sí parece real, y es otra cosa, es que posar el ratón sobre el sprite **apaga** el resalte.

3. **La prueba del doble cobro de drafteos no vigila la rama que nombra** (`tests/test_drafteos_guardados.py:161`). El corte de texto llega hasta el final del método e incluye el `else`, así que la aserción de orden se cumple sola. Discrepancia sobre si reportarlo: hoy **no hay doble cobro** —el código es correcto—, es una red de regresión falsa, no un síntoma.

---

## 7. Lo que esta auditoría NO ha podido mirar

- **No se ejecutó nada.** Prohibido pytest, prohibido modificar archivos, y la aplicación no se lanzó. Todo se sostiene en lectura de código y datos. Lo único ejecutado fue inspección del `customtkinter` instalado para confirmar que `configure` lanza sobre un widget destruido mientras `cget` no.
- **Ningún emulador real.** No se verificó ni un solo offset, ni una lectura de party, ni una escritura en memoria viva de Ryujinx, Azahar o melonDS. Los adaptadores por juego (pk4/pk6/pk7, cementerio en caja de ORAS, salud en combate) quedan sin auditar: comprobarlos exige jugar, y la regla del proyecto prohíbe probar escrituras en la partida viva.
- **Rendimiento solo por lectura y por el log del usuario.** No hay perfilado propio de una sesión real. Las cifras citadas vienen de `perf_2026-08-28.jsonl` y de mediciones puntuales en esta máquina.
- **Concurrencia.** No se auditó el hilo de fondo de `win_hotkeys` ni sus interacciones con el hilo de Tk. Hay una señal que merece un ángulo propio: `_foreground_is_supported_emulator`, un método de un widget Tk, se invoca desde ese hilo 10 veces por segundo.
- **Los datos del formato, solo por muestreo.** No se hizo un barrido exhaustivo de los 20 pools de `data/moves.json` contra el catálogo de movimientos ni contra la disponibilidad real en los cinco juegos. Los seis IDs reportados salieron de revisar las categorías de boost; es probable que haya más huecos del mismo tipo, especialmente en `global_self_boosts`, que se derivó de los pools de rol y por tanto hereda todos sus olvidos.
- **La cobertura de tests en su conjunto.** Se comprobó caso por caso que ningún test cubre cada hallazgo, pero no se evaluó cuántas de las ~894 pruebas son de inspección de texto (`inspect.getsource`) en vez de conductuales. Por lo visto en `tests/test_drafteos_guardados.py`, esa proporción merece una revisión propia: una prueba que solo lee el código fuente no puede impedir un cambio de comportamiento.
