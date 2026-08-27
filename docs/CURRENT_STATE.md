# RoleRun Manager — estado funcional canónico

- Fecha de corte: 2026-08-27
- Versión de aplicación: `v0.2.6-alpha.15`

Este documento es la fuente canónica del estado funcional actual. `CHANGELOG.md`
y los `README_v*` conservan la evolución histórica; `ROADMAP.md` conserva tanto
prioridades actuales como hitos antiguos. Si una afirmación histórica contradice
este documento, hay que comprobar código, tests, logs y validación física y
actualizar aquí el resultado demostrado.

## Foco activo: Design Evolution

La numeración funcional queda fijada así: `v0.2.1` corresponde a BDSP,
`v0.2.2` a USUM, `v0.2.3` a Sol/Luna, `v0.2.4` a X/Y, `v0.2.5` a ORAS y
`v0.2.6` a B2/W2. El changelog conserva los nombres históricos anteriores para no
borrar trazabilidad.

### v0.2.6 Alpha.15 — instrumentación de rendimiento

La auditoría del 27-08-2026 dejó como hipótesis sin medir el coste real en
Windows del motor .NET, del render completo y del walk de memoria de melonDS.
Alpha.15 no corrige ni optimiza nada: añade la medición que faltaba para poder
decidir con evidencia. El modo se activa con `ROLERUN_PERF=1` y está apagado por
defecto con coste cero.

Primeras cifras demostradas en esta máquina: cada invocación del motor .NET paga
un suelo de **~72 ms** antes de cargar PKHeX.Core y abrir la partida, así que la
carga de una run acumula ≥290 ms solo en arranques de proceso; `append_history`
cuesta 2,5–8,1 ms por evento en NTFS. Detalle y método en
`docs/PERF_INSTRUMENTATION.md`. Baseline completa: **906 passed**.

### v0.2.6 Alpha.14 — destino vivo de depósito y ventana maximizada

El fallo físico del 27-08-2026 demostró que Equipo/PC mostraba correctamente
los slots vivos de melonDS, pero `send_pokemon_to_pc` dejaba B2/W2 en la rama
clásica y volvía a leer el PC del save. Así podía escoger Caja 1/slot 1 desde el
archivo aunque esa posición estuviera ocupada en RAM, y el writer la rechazaba
correctamente. La acción conserva ahora la coordenada exacta de la matriz viva;
la relectura de RAM previa a escribir, el readback y el rollback no se relajan.

La carga inicial continúa centrada y no invasiva. Cuando la partida ya está
validada y compuesta, la raíz se maximiza con el estado normal `zoomed` de
Windows, no con fullscreen/F11. Ambas correcciones tienen regresión automática;
el depósito y la presentación final quedan pendientes de validación física.

### v0.2.6 Alpha.5 — presentación de daño y parálisis B2/W2

La validación física de alpha.4 encontró dos divergencias. La copia lógica de
PS se actualiza antes de que el juego presente la animación y adelantaba el
resultado en la barra; la copia retrasada converge después y pasa a gobernar la
presentación. La fuente rápida permanece como testigo lógico y ambas deben
conservar identidad. No se añade un retraso fijo.

La misma prueba demostró que el runtime nominal B2/W2 expuso `1` para una
parálisis visible. Ese valor no es el bitmask persistente PKHeX que la UI común
interpretaba como sueño. Solo el caso observado se traduce a `64` (PAR); otros
valores runtime no demostrados se ocultan en vez de etiquetarse por suposición.
El usuario confirmó físicamente el 26-08-2026 que la barra ya acompasa el daño
sin adelantarlo y muestra correctamente `PAR`. Ambos arreglos quedan cerrados
para combate simple de Negro 2 España/melonDS 1.1.

### v0.2.6 Alpha.4 — PS inmediatos de combate B2/W2

La traza temporal de 1.308 muestras resolvió las dos copias: ambas comenzaron
con Tepig a 8/24; `0x0225B5FC` publicó 0 PS a los 9.037 ms y
`0x0225B1B4` convergió a 0 a los 12.399 ms. El reader usa la segunda como fuente
inmediata y la primera como testigo retrasado, exige especie, nivel, habilidad,
PS máximos e identidad única contra la party y hace doble lectura. Fuera de
combate ambas filas se demostraron vacías y la party normal volvió a 24/24.

El adapter publica `BattleState.health_game` y la UI actualiza la salud de la
barra cada 250 ms durante el combate. El KO automático permanece deshabilitado:
B2/W2 todavía no dispone de PC/reemplazo seguro y no debe descontar una vida que
no pueda completar de extremo a extremo. Regresiones dirigidas: **26 passed**.

### v0.2.6 Alpha.3 — Pokémon sin rol visibles y primera evidencia de combate

La barra flotante solo consultaba ocupantes con un rol canónico y descartaba
la lista de miembros SIN ROL que la vista principal sí coloca en huecos libres.
Además, el adapter B2/W2 reemplazaba el rol persistido por SIN ROL cuando el PK5
no tenía todavía una marca física, aunque B2/W2 sigue sin writer de marcas.
Ahora barra y equipo usan la misma colocación de seis celdas; un miembro SIN ROL
es visible con esa etiqueta, y el adapter conserva el rol persistido salvo que
exista exactamente una marca viva que constituya evidencia nueva.

La captura guiada `b2w2_battle_capture_latest.json` observó a Tepig/especie 498,
nivel 6, habilidad 66 y PS máximos 24 en dos estructuras idénticas. Ambas
publicaron `24→21` durante el daño y desaparecieron al salir del combate. Los PS
están en `0x0225B1B4` y `0x0225B5FC`, separados por `0x448`. Al existir dos
copias todavía no se ha elegido autoridad ni activado combate/KO en producción.

Regresiones dirigidas de B2/W2 y barra: **23 passed**.
El usuario confirmó físicamente el 26-08-2026 que Tepig vuelve a aparecer
correctamente en la barra flotante de Negro 2/melonDS. El bug de visibilidad de
miembros SIN ROL queda cerrado para este entorno.

### v0.2.6 Alpha.2 — metadatos PK5 y matriz completa de paridad

El PK5 de party ya demostrado publica ahora estado, naturaleza, estadísticas
reales, IV, EV, PP, PP Up, huevo y las seis marcas. Los offsets y el orden
proceden de `PKHeX.Core/PKM/PK5.cs` y se contrastaron contra el Tepig vivo de
Negro 2/melonDS: nivel 6, 19/24 PS, naturaleza 21, stats
`(24,13,9,10,12,11)`, IV `(10,16,23,6,13,11)` y PP `(31,30,0,0)`.
La lectura sigue siendo doble, con checksum e identidad; todas las escrituras
B2/W2 permanecen cerradas. `docs/B2W2_REALTIME_PARITY.md` enumera los carriles
de 3DS/BDSP pendientes para no omitir ninguna mecánica.

Regresiones dirigidas: **10 passed**. La lectura directa de melonDS quedó
comprobada. El usuario validó físicamente en la UI de RoleRun los IV, EV,
habilidad, objeto y movimientos el 26-08-2026. Los PP no tienen representación
visual en la interfaz actual: su lectura interna no se considera por tanto una
validación visual ni se añade una vista nueva fuera del alcance del diseño.
Naturaleza/estado/huevo quedan pendientes de una muestra física específica.

### v0.2.6 Alpha.1 — B2/W2 en melonDS, party de solo lectura

Pokémon Negro 2 (España) en melonDS 1.1 dispone de una primera ruta en el
Real-Time Core. La lectura real del 26-08-2026 publicó Tepig, nivel 5 y 22/22 PS
con la misma identidad PID/TID/SID que el guardado activo.

La primera divergencia del intento anterior estaba antes de la UI: además de la
party nominal `0x0221E3AC`, exigía una supuesta copia fija en `0x02247A2C` que
la sesión actual refutó. Alpha.1 relee dos veces `count + party`, exige un único
mapeo anfitrión y valida checksum y estructura de cada PK5. El adapter rechaza
cualquier RAM sin identidad fuerte común con el guardado seleccionado.

La sincronización inicial y el monitor salen antes de las rutas heredadas. Toda
mutación B2/W2 está cerrada en la compuerta de UI. PC, roles, curación, MT,
inventario, batalla, bajas y progreso no están demostrados. El usuario confirmó
físicamente el 26-08-2026 que la conexión, el equipo, los PS y su actualización
en vivo funcionan correctamente en Pokémon Negro 2/melonDS 1.1.
Baseline completa de `v0.2.6-alpha.1`: **876 passed** en 36,65 s.

### v0.2.5 Alpha.9 — drafteo de Líbero ordenado y validaciones ORAS

El usuario confirmó físicamente en ORAS/Azahar que el dinero infinito se
refleja correctamente, que las cinco opciones de Support aparecen completas y
que el drafteo propio de Líbero respeta su composición. Para facilitar su
lectura, las tres categorías auxiliares aleatorias se publican primero y
ocupan la fila superior; daño físico y daño especial permanecen como resultados
fijos y ocupan la fila inferior centrada. Esta modificación solo cambia el
orden de presentación, no los pools ni el sorteo.

No queda otra funcionalidad ORAS nueva identificada como pendiente en el
alcance actual. La única comprobación necesaria antes de cerrar el juego es la
validación física de la enseñanza de una MT ya implementada: debe cambiar el
movimiento y la MT debe seguir disponible por ser reutilizable en ORAS.

### v0.2.5 Alpha.8 — dinero ORAS resuelto y drafteos de cinco categorías

La dirección nominal del bloque Misc de ORAS contenía una muestra cero que el
resolver aceptaba porque dinero y PB estaban dentro de sus rangos. La
comparación del bloque completo con el testigo del guardado demostró que no era
la copia viva. El resolver rechaza ahora esa coincidencia parcial, localizó el
bloque real y la escritura terminó con readback de `9.999.999 ₽` en
`0x08C6DDD0`. El usuario confirmó después en la interfaz del juego que el dinero
infinito funciona; esa validación física queda registrada en Alpha.9.

Los conjuntos de cinco resultados ya no crean tres filas: usan una composición
3+2 con la segunda fila centrada. La vista de diagnóstico a 1920×1080 mostró
las cinco tarjetas y sus acciones completas sin scroll. Líbero posee además un
drafteo propio de cinco categorías: daño físico, daño especial y tres
categorías auxiliares distintas tomadas de los pools compatibles con la
generación activa. Los IDs permitidos del juego siguen siendo el límite del
catálogo, por lo que no entran movimientos futuros.

### v0.2.5 Alpha.7 — dinero independiente de la mochila y MT ORAS completas

La investigación del dinero infinito localizó la primera divergencia antes de
la escritura: el dinero está en el bloque Misc, pero se trataba como si formara
parte de una bolsa y recibía el desplazamiento dinámico del inventario. El
writer resuelve ahora el bloque Misc con su propio testigo, valida una captura
estable, escribe solo el campo de dinero y conserva readback y rollback. La
acción terminó localmente con el readback confirmado; queda pendiente mirar el
valor 999.999 ₽ en la interfaz del juego.

La tabla de movimientos queda fijada a la revisión ORAS y la UI consume sus
datos. La comprobación visual local mostró solo las dos MT realmente presentes
en la mochila viva: MT39 Truco Fuerza y MT54 Pistola Agua. Sus PP y, cuando
aplican, potencia y precisión se mostraron correctamente. La enseñanza física
de una MT continúa pendiente.

### v0.2.5 Alpha.6 — MT ORAS preparadas con inventario vivo obligatorio

La revisión del flujo completo demostró que el reader y el writer ORAS ya
trabajaban con la mochila RAM validada y trataban las MT como reutilizables,
pero la UI sustituía una lectura viva fallida por el inventario del último
guardado. Esa era la primera divergencia: una fuente obsoleta podía habilitar
el selector pese a que la sesión actual no estuviera demostrada. Se ha
eliminado únicamente ese fallback de ORAS; el guardado sigue sirviendo como
testigo de resolución, pero nunca como inventario operativo. La regresión
demuestra tanto el rechazo seguro como la publicación correcta desde RAM viva,
y el conjunto focalizado termina con `14 passed`. Falta enseñar físicamente
una MT en ORAS/Azahar y confirmar que el movimiento cambia y la MT permanece.

### v0.2.5 Alpha.5 — metadatos completos de equipo y PC ORAS

La ROM y el perfil Personal ORAS eran correctos, pero la sincronización inicial
vaciaba la referencia al perfil después de capturar y antes de publicar los
Pokémon. Esa primera divergencia impedía enriquecer el equipo con stats base y
dejaba las fichas del PC sin naturaleza, stats finales, IV ni EV. El perfil se
prepara ahora antes de cada captura inicial, refresco externo y resincronización
manual, se conserva durante la publicación y las cajas ORAS se refrescan al
terminar la carga inicial. Las regresiones están en verde y la comprobación
local visible confirmó en Dwebble de PC naturaleza Ingenua, stats finales,
stats base, IV y EV. El usuario confirmó después físicamente esos metadatos en
equipo y PC de ORAS/Azahar. La herencia de rol y EV no se modificó.

### v0.2.5 Alpha.4 — intercambio Equipo↔PC ORAS con rol y EV completos

La UI ya incorporaba al `PendingTeamChange` la distribución de EV calculada
para el rol que hereda el Pokémon entrante. La revisión del flujo demostró que
`ORASLiveWriter` consumía el rol pero ignoraba ese mapa de EV antes de construir
la extensión de party; por ello una transferencia podía parecer correcta en
roles y conservar estadísticas incompatibles con ese rol. El writer escribe
ahora los seis EV en orden nativo PK6, valida la distribución y reconstruye las
estadísticas antes del readback. La regresión byte a byte está en verde. Queda
pendiente una única validación física del intercambio Equipo↔PC en ORAS/Azahar.

### v0.2.5 Alpha.3 — perfil Personal ORAS fijado para roles

La ROM ORAS configurada se leyó directamente y contiene 825 entradas Personal;
Quagsire (especie 195, forma 0) devuelve las estadísticas base esperadas. El
mensaje que afirmaba lo contrario procedía de la UI: un cambio de rol con EV
no activaba la precarga que sí se hacía para intercambios Equipo↔PC. Ahora todo
`PendingRoleChange` con EV exige el perfil exacto antes de escribir y el writer
conserva una referencia estable a ese perfil durante la transacción. Las
regresiones automatizadas están en verde y el usuario confirmó físicamente el
intercambio Houndoom↔Quagsire en ORAS/Azahar: rol, EV y estadísticas se
actualizaron correctamente.

### v0.2.5 Alpha.2 — roles, EV y estadísticas vivas ORAS preparados

La revisión extremo a extremo demostró dos partes de la misma divergencia: la
UI no incluía ORAS entre los backends que construyen y propagan EV al cambiar
de rol, y `ORASLiveWriter` solo modificaba el marcador. El backend ya disponía
de los datos Personal y de la extensión viva PK6 necesaria; no se ha añadido
ninguna dirección RAM ni se ha trasladado ningún offset desde otro juego.

Los cambios de rol ORAS incluyen ahora los EV automáticos, el selector de dos
estadísticas para Líbero y el recálculo inmediato de PS máximos y estadísticas.
La transacción exige captura estable, identidad, rol y EV anteriores, nivel y
estadísticas runtime coherentes; escribe por separado PK6 almacenado y extensión
viva, relee ambos y restaura sus bytes originales si el readback diverge. Las
regresiones de éxito, precondición obsoleta y rollback están en verde. Falta la
validación física en ORAS/Azahar antes de cerrar esta capacidad.

### v0.2.5 Alpha.1 — curación completa ORAS validada

El backend ORAS acepta ahora `PendingPartyHeal` sobre la estructura PK6 ya
demostrada. La operación restaura estado, PS y PP, conserva la identidad de los
seis slots, realiza readback desde Azahar y revierte todos los bytes afectados
si cualquier comprobación falla. Las regresiones automatizadas de éxito y
rollback están en verde. El usuario confirmó físicamente en ORAS/Azahar que la
curación completa restaura correctamente el equipo dentro del juego.

### v0.2.4 Alpha.14 — representación vacía segura del PC X/Y

La revisión física completa localizó el Huevo corrupto en Caja 1:11: sus
`0xE8` bytes eran cero. Los vacíos válidos de la misma matriz eran no nulos y
coincidían exactamente entre sí. La primera divergencia estaba en dos ramas de
`XYLiveWriter` que heredaban el supuesto de que cero representaba un BoxPokemon
vacío.

Las rutas PC→Equipo y PC→PC derivan ahora el vacío desde dos lecturas estables
de la matriz viva y solo escriben una plantilla no nula, parseada como vacía,
repetida al menos dos veces y sin empate. El origen, destino y plantilla se
excluyen de inferencias circulares; readback y rollback siguen siendo exactos.
La validación física del usuario en Pokémon X/Azahar 263745c confirmó que un
nuevo movimiento PC→PC conserva el Pokémon exacto en el destino y deja el
origen vacío sin materializar ningún Huevo. El slot afectado anteriormente se
recuperó recargando el estado limpio, por lo que no fue necesaria una reparación
RAM tardía.

La party real posterior al depósito tenía `count=4`, slots 1–4 ocupados y 5–6
vacíos. La distribución de tarjetas que muestra huecos en el menú es propia de
Pokémon X y no demuestra un agujero en memoria.

En la misma sesión física de Pokémon X/Azahar 263745c, el usuario validó las
tres utilidades X/Y de forma independiente: Caramelo Raro ×999, Repelente
Máximo ×999 y dinero máximo. Las tres se reflejaron correctamente dentro del
juego; queda cerrada su validación empírica para este perfil.

También quedó validado el carril de salud: durante un combate salvaje, RoleRun
actualizó correctamente los PS tras recibir daño y conservó el valor real al
salir del combate. El botón de curación restauró correctamente el equipo dentro
del juego. Una prueba controlada posterior cubrió el ciclo completo de una baja:
la transición de PS positivos a cero descontó exactamente una vida, al terminar
el combate apareció el aviso de elegir sustituto y la elección incorporó
correctamente el sustituto. Estas observaciones validan lectura de PS en
combate, convergencia postcombate, writer de curación y el flujo simple de
KO→compromiso→sustitución para Pokémon X/Azahar 263745c. No constituyen todavía
una prueba de reconexión durante la batalla ni de combates especiales. Una
segunda prueba física cubrió dos KO dentro del mismo combate: RoleRun descontó
las dos vidas exactas y presentó y resolvió consecutivamente los dos selectores
de sustitución. Con ello queda validada también la cola múltiple en un combate
salvaje para este perfil.

### v0.2.4 Alpha.13 — testigos PC vivos en X/Y

La captura física posterior a alpha.12 y una lectura RPC independiente
demostraron `count=5`, los cinco PK6 ocupando exactamente los slots 1–5 y el
slot 6 vacío. El hueco inferior izquierdo mostrado por el menú de Pokémon X es
su disposición visual con cinco miembros, no un hueco interno en la party.

El depósito de Budew se rechazaba antes de escribir porque la pantalla componía
la Caja 1 con los overrides de la matriz viva, mientras `_pc_box_witnesses`
seguía leyendo exclusivamente los ocupantes del último `main`. Ahora ambos
consumen la misma proyección viva. El writer conserva intactas sus
precondiciones, readback y rollback. Falta repetir físicamente el depósito.

### v0.2.4 Alpha.12 — compuerta completa Equipo↔PC X/Y

La revisión de extremo a extremo demostró una contradicción entre las
operaciones que la interacción automática preparaba y las que la frontera
final de UI permitía alcanzar al Core. `move-box-slot`, swaps y sustituciones
cruzaban esa frontera, pero `party-to-box` y `box-to-party` se rechazaban antes
del writer aunque este ya implementaba sus precondiciones, readback y rollback.
El flujo manual de cambios pendientes conservaba además una lista anterior.

Ambas compuertas declaran ahora la misma matriz X/Y de cinco operaciones. No se
han relajado los validadores RAM ni se ha añadido ninguna dirección. La
regresión comprueba la frontera real de UI; la capacidad sigue pendiente de
validación física completa en Pokémon X/Azahar.

### v0.2.4 Alpha.11 — autoridad física de Equipo↔PC X/Y

La validación física de alpha.10 demostró que el RPC de Azahar podía aceptar
la escritura y devolverla en su readback mientras el juego conservaba a Budew
en la party. La primera divergencia restante era la fuente usada para escribir
y confirmar: el estado invitado leído por RPC no era prueba suficiente del
estado anfitrión que Pokémon X terminaba consumiendo.

En la sesión real se identificó una única región anfitriona cuyos seis slots
de party, contador y matriz PC completa coinciden a la vez con las estructuras
invitadas ya validadas. El writer no fija esa dirección: vuelve a resolver la
party completa por estructura e identidad, exige un único candidato y comprueba
que contador y PC comparten exactamente el mismo desplazamiento. La operación
se compromete sobre esa autoridad y solo se confirma si party, contador y
destino PC coinciden también tras una segunda lectura estable y por RPC. Ante
cualquier discrepancia se restauran los tres bloques.

Las regresiones automatizadas de X/Y pasan. La capacidad no se considera aún
cerrada: falta comprobar físicamente una sola retirada Equipo→PC iniciada desde
RoleRun con alpha.11.

### v0.2.4 Alpha.10 — despacho real de Equipo↔PC X/Y (incompleto)

La causa del traslado visible solo en RoleRun estaba entre la operación de UI
y el writer: la compuerta X/Y no despachaba `party-to-box` ni `box-to-party`.
El primer cambio quedaba meramente proyectado; por eso el siguiente PC→PC no
podía encontrar en RAM el origen mostrado por la interfaz y el writer lo
rechazaba de forma segura. La compuerta incluye ahora ambos tipos ya soportados
por el writer, sin modificar sus precondiciones, readback ni rollback. La run
persistida del usuario no contiene la operación fallida anterior. Las 50
regresiones X/Y relacionadas pasaron en esa versión, pero la prueba física
posterior demostró que el readback RPC no equivalía al commit físico. Alpha.11
conserva este arreglo de despacho y corrige la siguiente divergencia sin borrar
la evidencia histórica.

El usuario validó físicamente en Pokémon X/Azahar que Prisma acepta y ofrece
correctamente movimientos que provocan problemas de estado. Esta parte queda
cerrada para X/Y; su comprobación en los demás juegos se hará cuando corresponda
a cada backend.

### v0.2.4 Alpha.9 — destinos PC exactos y nuevo Prisma

La investigación de los fallos de arrastre X/Y localizó la primera divergencia
en la composición de la operación, no en las direcciones ni en el writer RAM.
La UI eliminaba el destino concreto para Equipo→PC, solicitaba testigos de rol
para PC→PC en vez de testigos ocupados de la caja y rechazaba toda retirada a
una casilla libre mediante un guard antiguo de Gen 6. El backend X/Y ya tenía
demostradas las transacciones exactas y sus verificaciones. La UI entrega ahora
esas coordenadas y testigos correctos y solo conserva el bloqueo para ORAS.

La regla común de Prisma cambia de Protección a Problemas de Estado: acepta el
pool explícito de movimientos que causan directamente veneno, intoxicación,
parálisis, sueño o quemadura. La disponibilidad final se intersecta con los IDs
del juego activo, de modo que un movimiento posterior no puede aparecer en un
título anterior. Tanque conserva su categoría de Protección. La cobertura
automatizada está completa; quedan pendientes una prueba física X/Y de los tres
movimientos PC y una comprobación de drafteo/compatibilidad Prisma antes de
declarar ambas capacidades cerradas. Baseline completa: **834 tests superados**
con `python -m pytest -q`.

### v0.2.4 Alpha.8 — Equipo↔PC con cambio de tamaño en X/Y

La prueba física controlada en Pokémon X/Azahar demostró que
`0x08CE1C74` es el contador de cuatro bytes little-endian de la party: con seis
miembros contenía 6 y, al depositar uno desde el juego, pasó a 5. La lectura
simultánea de la party situada en `0x08CE1CE8` demostró además que los miembros
posteriores se compactan literalmente hacia la izquierda y que el antiguo
último slot activo recibe el PK6 vacío cifrado canónico. Las palabras situadas
antes del contador no se han identificado semánticamente y permanecen fuera de
toda escritura.

El writer X/Y implementa ahora depósito y retirada con casilla PC exacta. Antes
de escribir exige dos capturas iguales de party y contador, rango 1–6, prefijo
compacto, identidad estable, origen/destino coherente y testigos ocupados de la
misma caja. Conserva cada bloque original, hace readback tras cada unidad,
escribe el contador solo al final y verifica el resultado semántico completo.
Si algo diverge, restaura y verifica todos los bytes, también con el contador
como último paso. ORAS no hereda esta capacidad.

Las regresiones automatizadas demuestran la transacción y su recuperación. La
dirección, el tamaño, la compactación y el vacío final sí están validados
físicamente; el ciclo completo iniciado desde RoleRun todavía requiere una
única validación manual de ida y vuelta antes de declararlo cerrado. Baseline
completa: **831 tests superados** con `python -m pytest -q`.

### v0.2.4 Alpha.7 — MT globales X/Y

La pestaña MT de X/Y mostraba nombre y PP, pero potencia, precisión y
descripción quedaban ausentes. El trazado demostró que el backend X/Y alcanzaba
en la UI el mismo fallback limitado que ORAS, mientras que solo BDSP y Gen 7
tenían una fuente completa. La tabla Gen 7 no era intercambiable: Placaje
(`move_id=33`) vale 50 de potencia en X/Y y 40 en Gen 7.

X/Y dispone ahora de una tabla independiente de 621 movimientos fijada a
generación 6 y `x-y`. La comprobación visual conectada a Pokémon X/Azahar
mostró MT83 Acoso con potencia 20, precisión 100 y 20 PP, además de las seis
tarjetas de compatibilidad. Las regresiones del writer demuestran que enseñar
una MT reutilizable escribe únicamente el PK6 de la party, no consulta ni
modifica la mochila, verifica movimientos y PP y revierte los bytes originales
si el readback falla. El usuario confirmó físicamente el 25-08-2026 que enseñar
una MT poseída y compatible cambia el movimiento dentro de Pokémon X y que la
misma MT continúa disponible después. Queda así cerrada la validación física
del writer de MT reutilizable para Pokémon X/Azahar. Baseline completa:
**826 tests superados**.

### v0.2.4 Alpha.6 — publicación inicial del PC vivo de X/Y

La matriz X/Y corregida en alpha.5 devolvía por lectura directa exactamente
Budew, Ledyba y Skitty en Caja 1, posiciones 1–3, pero RoleRun seguía mostrando
la caja vacía. El trazado hasta la UI demostró la siguiente primera divergencia:
la sincronización inicial solo programaba la reconciliación del PC X/Y cuando
`diff_live_party` detectaba además un cambio de party. Si la party ya coincidía,
el resultado válido del reader no llegaba al modelo visual y permanecía el PC
vacío del guardado.

La apertura validada de X/Y programa ahora una única reconciliación del PC vivo
después de publicar la party, aunque esta no haya cambiado. Una regresión aísla
esa condición y exige el refresco. La comprobación visual en la sesión real de
Pokémon X/Azahar mostró los tres ocupantes correctos en sus posiciones 1–3.
El usuario confirmó después, en la misma combinación de juego y backend, que
el movimiento PC→PC conserva exactamente la casilla vacía de destino solicitada,
incluido el cambio entre cajas. Con ello queda físicamente validado el writer
PC→PC introducido en alpha.4. También confirmó físicamente que una entrada
PC→Líbero abre el selector de distribución, permite elegir las dos estadísticas
y aplica la configuración EV correspondiente.
No se modificó ningún writer ni otro backend. Baseline completa: **821 tests
superados**.

### v0.2.4 Alpha.5 — lectura viva del PC X/Y sin anchors

La sesión real de Pokémon X en Azahar (`kujira-1`, proceso 11) demostró que la
matriz poblada del PC comenzaba en `0x08C861B8`, no en la candidata nominal
`0x08C861C8`. En esa matriz se descifraron exactamente tres PK6 válidos: Budew,
Ledyba y Skitty en Caja 1, posiciones 1–3. La lectura anterior no tenía anchors
posicionados del `main`, aceptaba la base nominal sin comprobarla y fallaba al
descifrar el primer slot; la UI ocultaba después ese fallo con el `main`
guardado, que no contenía Pokémon en el PC. Esta era la primera divergencia.

El lector conserva el rango local documentado y prueba sus alineaciones de
cuatro bytes, pero solo publica una recalibración si existe una única matriz
con al menos dos PK6 completos que superen descifrado, checksum, especie e
identidad estable. Una única aparición o varias candidatas se consideran
ambiguas y no se aceptan. La ruta es de solo lectura y no cambia ningún writer.

El readback directo posterior resolvió `0x08C861B8` y devolvió los tres Pokémon
reales. Las regresiones automatizadas cubren la apertura sin anchors, una caché
nominal obsoleta y el rechazo de dos matrices ambiguas. Baseline completa:
**820 tests superados**. La visualización dentro de RoleRun se confirmó en
alpha.6; el movimiento PC→PC sigue pendiente de confirmación física.

### v0.2.4 Alpha.4 — movimiento exacto dentro del PC de X/Y

X/Y permite ahora mover un Pokémon ya almacenado en el PC a una casilla vacía
concreta, incluso de otra caja. La operación reutiliza la matriz viva ya
demostrada de 31 cajas × 30 posiciones, con stride PK6 de `0xE8` bytes y bloque
vacío a cero. No se ha añadido ni inferido ninguna dirección RAM.

El writer resuelve de nuevo la matriz mediante sus testigos, exige identidad
estable en el origen y destino vacío, relee ambos justo antes de escribir y
aplica una transacción destino→origen. Cada paso tiene readback exacto y la
verificación final vuelve a descifrar ambos PK6; si cualquier comprobación
falla, restaura y verifica los dos bloques originales. La UI conserva caja y
slot exactos al preparar el cambio. Las operaciones que alteran el tamaño de la
party continúan deshabilitadas porque la sesión actual no demuestra el contador
de miembros ni su escritura segura.

Las regresiones cubren movimiento exacto, destino ocupado, identidad stale,
divergencia al vaciar el origen, rollback y preparación de coordenadas desde la
UI. El usuario validó físicamente el movimiento PC→PC exacto, también entre
cajas, en Pokémon X/Azahar el 25-08-2026. Baseline automatizada: **817 tests
superados**.

### v0.2.4 Alpha.3 — roles, EV y estadísticas vivas en X/Y

El flujo común guardaba el rol X/Y, pero lo excluía de la preparación de EV y
el writer heredado de ORAS solo escribía el PK6 almacenado. Las estadísticas
finales de X/Y residen en una región runtime separada, ya demostrada por el
reader y por la curación física. La nueva transacción valida identidad, EV
anteriores, nivel y estadísticas testigo; recalcula desde la tabla Personal de
X/Y; conserva el estado y los PS perdidos; escribe por separado el PK6 y
`PartyData`; verifica ambos readbacks y restaura ambos si falla alguno.

Las entradas PC→equipo hechas dentro del juego heredan igualmente los EV del
rol. Los cinco roles fijos se normalizan sin interacción y Líbero no escribe
nada hasta que el usuario selecciona dos estadísticas. Las regresiones cubren
recalculo efectivo, muestra EV stale, rollback de ambas regiones, rol fijo
automático y selector Líbero. El usuario confirmó físicamente el cambio de rol
fijo y la entrada PC→Líbero con elección de sus dos estadísticas en Pokémon
X/Azahar el 25-08-2026. Baseline automatizada: **811 tests superados**.

### v0.2.4 Alpha.2 — curación visible y baja sin sustituto en X/Y

La curación X/Y ya disponía de writer transaccional, pero dos compuertas de
composición de la UI seguían enumerando únicamente BDSP, Sol/Luna y USUM. Una
capacidad común incluye ahora X/Y y gobierna tanto `CURAR EQUIPO` como las
acciones `CURAR`/`MENÚ` de la barra flotante. El usuario validó físicamente el
25-08-2026 que la curación completa restaura correctamente el equipo en
Pokémon X/Azahar.

Una baja pendiente puede resolverse ahora con `NO SUSTITUIR`. La operación no
escribe RAM, no devuelve la vida descontada y no borra la muerte: archiva de
forma persistente la obligación de reemplazo, conserva la identidad en el
Cementerio y deja libre el rol. Si hay varias bajas, la decisión se toma para
cada una. La sesión real verificó visualmente `NO SUSTITUIR` junto a la baja
pendiente; su persistencia tras accionarlo sigue pendiente de validación física.

La carga inicial comparaba la party física completa con la party proyectada que
la UI muestra después de excluir bajas pendientes. Con dos bajas, esperaba seis
filas mientras solo podían componerse cuatro y la pantalla de carga no terminaba.
La compuerta compara ahora la misma proyección que renderiza la UI. Baseline
automatizada: **806 tests superados**.

### v0.2.4 Alpha.1 — estadísticas completas y curación X/Y

La sesión real de Pokémon X en Azahar demostró que el reader ya leía y
descifraba correctamente el bloque PK6 completo, incluida la extensión
`PartyData`, pero el parser Gen 6 compartido solo publicaba PS actuales y
máximos. Ahora el snapshot conserva naturaleza, IV, EV y los seis stats en el
orden canónico de RoleRun. La comprobación visual del 25-08-2026 confirmó los
valores completos de los seis miembros; por ejemplo, Delphox mostró 286 PS,
164 Ataque, 143 Defensa, 253 At. Esp., 255 Def. Esp. y 222 Velocidad. No se ha
añadido ninguna dirección RAM.

La curación completa de X/Y usa la misma estructura ya validada por su reader,
pero respeta su disposición física partida: `0xE8` bytes del PK6 almacenado y
`0x16` bytes de datos runtime en `slot + 0x158`. Restaura PS, estado y PP con
precondiciones, readback y rollback; las regresiones automatizadas cubren éxito
y restauración tras una escritura corrupta. La sesión real confirmó que la
acción sobre una party ya curada es idempotente, no bloquea la interfaz y no
altera el equipo. La curación efectiva de una party dañada queda pendiente de
validación física en Pokémon X/Azahar antes de declararse cerrada. La baseline
completa de esta entrega es de **803 tests superados**.

### Alpha.148 — selector EV del sustituto Líbero en BDSP

La selección fresca de dos estadísticas tras sustituir a un Líbero debilitado,
validada físicamente en Sol/Luna, se extiende a BDSP. El flujo común omitía la
clave `bdsp` aunque el backend ya consume el mapa EV del snapshot y ejecuta el
recalculo/readback posterior. La regresión demuestra que BDSP no prepara ni
aplica el reemplazo hasta recibir la selección y que conserva exactamente los
dos EV elegidos. ORAS y XY permanecen fuera por no tener demostrada esta
capacidad de escritura realtime.

### Alpha.147 — paridad segura de continuidad en USUM

La apertura física de Sol/Luna Alpha.146 quedó validada por el usuario: la
barrera se retira y `Equipo y PC` aparece completo. La auditoría posterior
demostró que UltraSol/UltraLuna conservaba el mismo rechazo determinista ante
dos sustituciones gestionadas. USUM recibe ahora los mismos testigos persistidos
de la Run y solo acepta dos entrantes cuando ambos están identificados y se
conservan los otros cuatro miembros. BDSP, XY y ORAS no usan este contrato de
continuidad y no se han modificado.

### Alpha.146 — arranque SM tras dos sustituciones gestionadas

El bloqueo indefinido del arranque quedó localizado antes de UI: la party viva
de Sol/Luna conservaba cuatro identidades exactas del último testigo, pero tenía
dos sustitutos distintos ya registrados en `managed_pokemon_roles`. El contrato
de continuidad de `SMLiveReader` solo aceptaba una sustitución gestionada y la
barrera inicial, correctamente, no publicaba una muestra que el reader rechazaba.

La continuidad admite ahora únicamente el caso demostrado: seis miembros en
ambos estados, exactamente dos entrantes persistidos por la Run y los otros
cuatro testigos conservados. La regresión verifica tanto el rechazo sin evidencia
como la aceptación con ambos testigos. La sesión física actual de Azahar produjo
`snapshot=true`, `continuity_proof=multiple-managed-replacements` y retiró la
pantalla inicial, mostrando después el selector EV pendiente del Líbero.

### Alpha.145 — elección EV del sustituto de un Líbero debilitado

La validación física de Alpha.144 confirmó que un sustituto de rol fijo recibe
correctamente sus EV. También aisló una divergencia anterior y específica de
Líbero: `_prepare_faint_replacement()` infería sus dos stats a partir de los EV
del Pokémon muerto y continuaba sin abrir el selector. Por tanto, el writer
funcionaba, pero recibía una decisión que el usuario no había tomado para el
nuevo Pokémon.

En Sol/Luna y UltraSol/UltraLuna la operación queda ahora detenida antes de
crear `PendingTeamChange`. RoleRun abre el selector EV en la superficie visible
y solo al confirmar dos stats reanuda la misma sustitución transaccional. La
regresión demuestra que mientras el diálogo está pendiente no se prepara ni se
aplica ningún cambio y que la selección nueva reemplaza al reparto anterior.
El usuario validó físicamente en Pokémon Sol/Azahar que, al sustituir a un
Líbero debilitado, el selector permanece abierto, exige dos estadísticas y
aplica el reparto elegido antes de completar la sustitución.

### Alpha.144 — EV heredados en sustituciones por baja de Sol/Luna

La comparación exacta con el flujo USUM demostró dos divergencias anteriores
al writer final: `_prepare_faint_replacement()` solo incorporaba los EV del rol
para USUM y `SMLiveWriter._apply_faint_replacement()` reconstruía el PK7
entrante sin consumir un reparto preparado. La sustitución heredaba la marca de
rol, pero podía conservar los EV que el Pokémon tuviera en el PC.

Sol/Luna prepara ahora el reparto del rol del debilitado dentro del snapshot de
la misma transacción. El writer valida que el rol declarado coincide, aplica
los seis EV antes de recalcular checksum y cifrado, y mantiene readback y
rollback conjuntos de equipo y PC. Las regresiones de UI y writer están
automatizadas. El usuario confirmó físicamente el 25-08-2026 que un sustituto
de rol fijo recibe correctamente el reparto correspondiente; esa prueba reveló
por separado la ausencia del selector para Líbero, corregida en Alpha.145.

### Alpha.143 — selector EV protegido frente al refresco flotante

La validación física de Alpha.142 demostró una segunda divergencia posterior:
el selector sí se abría sobre el emulador, pero el siguiente cambio de firma de
la barra flotante ejecutaba `_render_floating_bar()` y destruía sin distinción
todos los hijos del `Toplevel`, incluido el diálogo. Además, el diálogo cambiaba
su propietario a la ventana principal retirada después de crearse.

El render elimina ahora únicamente widgets reconstruibles y conserva las
ventanas modales registradas. El selector flotante mantiene como propietaria la
barra visible. Una regresión reproduce el refresco y demuestra que el contenido
normal se destruye mientras el diálogo permanece. El usuario confirmó
físicamente el 25-08-2026 que el selector permanece abierto hasta confirmar dos
stats y que el reparto se aplica correctamente.

### Alpha.142 — elección EV en entradas automáticas desde el PC del juego

La primera divergencia estaba en la orquestación común posterior a la lectura
live: al detectar que un Pokémon había entrado al equipo desde el PC del propio
juego, RoleRun construía inmediatamente el cambio de rol heredado. Para Líbero
esa transacción no contenía una elección de EV y podía alcanzar el writer sin
los dos stats requeridos.

En los tres backends cuya escritura EV está demostrada —BDSP, Sol/Luna y
UltraSol/UltraLuna— una entrada automática a Líbero queda ahora detenida antes
de escribir RAM. El selector se abre en la superficie visible activa y solo al
confirmar dos stats se reanuda la transacción con precondiciones, readback y
rollback. Los roles fijos incorporan su reparto normalizado en esa misma
transacción. La entrada PC→Líbero y la persistencia del selector quedaron
validadas físicamente por el usuario el 25-08-2026 en Pokémon Sol.

### Alpha.141 — selector Líbero visible y metadatos de MT Gen 7

El cambio de rol por arrastre desde la barra ya llegaba al flujo correcto de
rol y EV, pero el diálogo que debía elegir los dos stats de Líbero se alojaba
en la ventana principal retirada. Por eso el usuario solo lo veía al restaurar
RoleRun y la operación parecía no haberse aplicado. En contexto flotante el
selector se presenta ahora en un `Toplevel` visible sobre el emulador; no se
escribe el reparto hasta confirmar exactamente dos stats.

La UI de Gen 7 únicamente disponía antes de PP, de modo que potencia, precisión
y descripción aparecían como no disponibles aunque la MT funcionara. La tabla
`data/gen7_move_metadata.json` fija el version-group de Sol/Luna, conserva
procedencia y regla de derivación y aporta los datos españoles de los 760
movimientos introducidos hasta Gen 7. El usuario confirmó físicamente el
25-08-2026 que el selector flotante aparece y aplica el reparto y que las
tarjetas muestran correctamente los datos de las MT.

### Alpha.140 — SUSTITUIR y pestaña MT de Sol/Luna

La sesión real de Pokémon Sol/Azahar demostró que la antigua candidata de
Items era falsa: se calculaba restando el offset de BoxPokemon del save a su
dirección live y devolvía un bloque `0xDE0` completamente vacío. PKMN-NTR
documenta para SN/MN una dirección Items independiente, `0x330D5934`. Dos
lecturas guest estables de esa dirección produjeron una mochila no vacía y la
copia host derivada desde la party ya demostrada coincidió byte a byte.

RoleRun usa ahora esa dirección solo como candidata cerrada por esas mismas
pruebas de sesión. SUSTITUIR y la pestaña MT compartida reciben así el
inventario vivo; la enseñanza reutilizable de Gen 7 conserva la MT y verifica
el Pokémon, el movimiento anterior, PP, host, guest y rollback. Las pruebas
automatizadas y la visualización local quedan registradas en alpha.140. El
usuario confirmó físicamente en Pokémon Sol/Azahar que SUSTITUIR enseña el
movimiento, conserva la MT reutilizable y muestra correctamente sus datos; la
capacidad queda cerrada para esta combinación.


### Alpha.139 — PC vivo coherente y eliminación segura del slot PK7

La captura física del 25-08-2026 demostró dos divergencias independientes en
Sol/Luna. La UI publicaba el equipo desde RAM viva pero mantenía el PC derivado
de una lectura anterior del save; por eso mostraba un Pikipek antiguo aunque el
juego contenía Decidueye en caja 1:1. Sol/Luna consume ahora su matriz PC live
completa antes de retirar la barrera inicial.

Además, el traslado PC→Equipo escribía `0xE8` bytes a cero en el slot de origen.
La lectura viva confirmó esa firma exacta en caja 1:3 y el juego la mostraba
como huevo corrupto. El writer usa ahora el vacío PK7 cifrado canónico, verifica
su readback exacto y conserva rollback. El slot afectado de la sesión fue
reparado de forma acotada tras verificar la precondición, el resultado y que los
slots vecinos permanecieron intactos. El usuario confirmó físicamente el
25-08-2026 que Decidueye aparece de nuevo en Caja 1:1 y que el huevo corrupto
ha desaparecido. Quedan así validados tanto el PC vivo publicado como la
reparación y el vacío PK7 canónico de alpha.139.

### Alpha.138 — reanudación estable de Sol/Luna

La carga eterna tras reiniciar no procedía del transporte ni de una dirección
nueva: la party nominal era estructuralmente válida y cinco de sus seis
identidades coincidían, pero el reader había perdido su testigo de sesión. El
sexto miembro era el Pikipek gestionado que acababa de entrar desde el PC y la
party además se había reordenado; la prueba histórica solo admitía reemplazo o
reordenación por separado y rechazaba indefinidamente su combinación.

El reader recibe ahora las identidades fuertes persistidas por la run y solo
admite `single-managed-replacement-and-reorder` cuando el miembro entrante
coincide exactamente con una de ellas. La identidad equivocada permanece
cerrada. La barrera visual también espera los sprites del equipo y el último
refresco pendiente antes de descubrir la página.

Validación local en Pokémon Sol/Azahar: una apertura desde proceso nuevo resolvió
la party nominal mediante esa prueba, publicó los seis miembros con PS y sprites
completos y permitió seleccionar inmediatamente el Pikipek de Caja 1. Evidencia
local: `diagnostics/manual/sm-alpha138-first-published-frame.png` y
`diagnostics/manual/sm-alpha138-pc-selected.png`. Falta validar físicamente una
nueva transferencia inmediata después de otra apertura limpia.

### Alpha.137 — EV de rol en entradas PC→Equipo de Sol/Luna

La UI ya preparaba el reparto EV del rol para los traslados de Sol/Luna, pero
`SMLiveWriter._party_payload_from_box()` solo consumía rol y movimientos. Esa
era la primera divergencia: el Pokémon entraba con el rol correcto y los EV se
posponían a otra operación. El writer valida y aplica ahora los seis EV al PK7
entrante antes de reconstruir PartyData; marcador, EV, checksum, PS y stats se
confirman así dentro de la misma transacción party↔PC y comparten rollback.

Las regresiones cubren sustitución 1↔1, entrada a hueco libre y rechazo de un
snapshot incompleto antes de escribir. La suite completa queda en `782 passed`.
La validación física del 24-08-2026 intercambió el Pikipek de Caja 1 por la
segunda casilla: entró como Asesino con EV Ataque/Velocidad `252/252`, los otros
cuatro a cero y estadísticas finales recalculadas. Evidencia visual:
`diagnostics/manual/sm_alpha137_pc_to_team_evs.png`.

### Alpha.136 — entrenamiento por rol de Sol/Luna validado físicamente

La primera divergencia respecto de la paridad ya demostrada en USUM estaba en
dos fronteras propias de SM: la UI excluía `sm` al construir `old_evs/new_evs`
y `SMLiveWriter` solo escribía el marcador del rol. Sol/Luna ya publicaba los
EV y disponía de todos los campos necesarios para reconstruir PartyData, pero
ninguno de esos datos llegaba al writer como una transacción de entrenamiento.

La UI incluye ahora SM en ese contrato. El writer exige los EV anteriores y el
Personal efectivo de la ROM, valida IV, nivel, naturaleza, hiperentrenamiento y
estadísticas vivas, aplica la distribución del rol, recalcula PS y las cinco
estadísticas y preserva el daño sufrido. El PK7 almacenado y PartyData se
escriben con precondición, readback host/guest, comprobación semántica y
rollback verificado de ambas regiones. No se añaden direcciones ni offsets.

Las regresiones cubren la generación UI de EV para SM, checksum, orden binario
de los seis EV, recálculo de estadísticas y conservación de PS perdidos. La
validación física del 24-08-2026 en Pokémon Sol/Azahar reasignó Asesino a un
Pikipek de nivel 4: el readback cambió Ataque/Velocidad de EV `1/0` a
`252/252`, puso los otros cuatro EV a cero y recalculó sus estadísticas finales
de Ataque `11` a `14` y Velocidad `9` a `10`, manteniendo `17/17` PS. La
evidencia visual se conserva en `diagnostics/manual/sm_alpha136_role_dialog.png`
y `diagnostics/manual/sm_alpha136_role_readback.png`.

### Alpha.135 — curación de Sol/Luna operativa con destino demostrado

La primera divergencia estaba en la resolución del destino del writer. Cuando
Azahar retenía más de una copia anfitriona válida de la party, la curación
exigía directamente una relación party↔PC ya almacenada en caché. Por tanto,
fallaba de forma segura si era la primera escritura de la sesión, aunque el
backend SM ya disponía del procedimiento autocontenido que demuestra la matriz
PC completa y deriva de ella la única party con el mismo backing FCRAM.

La curación reutiliza ahora esa demostración antes de seleccionar el destino;
no añade direcciones, heurísticas ni fallbacks. Conserva la relectura previa,
la identidad estable, el readback host/guest, la validación semántica y el
rollback verificado. La regresión reproduce dos buffers de party candidatos y
demuestra que se establece primero la prueba PC completa y se selecciona
después el único destino revalidado.

Validación física local completada el 24-08-2026 en Pokémon Sol/Azahar: con la
aplicación iniciada desde el código corregido, `CURAR EQUIPO` cambió un Pikipek
de 11/17 a 17/17 en la memoria viva y no mostró el rechazo. Las capturas
`diagnostics/manual/sm_alpha134_heal_retry_ready2.png` y
`diagnostics/manual/sm_alpha134_heal_retry_after.png` conservan el antes y el
después. El usuario confirmó a continuación que la curación completa funciona
correctamente, cerrando también la restauración conjunta de estado y PP.

### Alpha.134 — implementación inicial de la curación completa de Sol/Luna

El primer writer añadido a la paridad SM restaura conjuntamente PS, estado y PP.
No reutiliza direcciones USUM: resuelve la party de Sol/Luna, exige identidad
estable y escribe las dos regiones de su formato sparse ya demostrado (stored
PK7 y PartyData). Antes de escribir relee todos los campos; después verifica
host, guest y una nueva captura semántica. Ante cualquier divergencia restaura
y comprueba ambas vistas de los bytes originales.

Las regresiones automatizadas demostraron la proyección y el paso por la UI. La
primera prueba física con daño real reveló que la resolución del destino todavía
dependía de una prueba PC previamente almacenada; esa causa se corrigió en
alpha.135. La validación física completa posterior cerró también PP y estado.
La comprobación visual local conservada en
`diagnostics/manual/sm_alpha134_heal_ready.png` demuestra que `CURAR EQUIPO`
aparece en la vista SM definitiva; la ejecución idempotente con los seis
miembros ya sanos no alteró su identidad, composición ni PS.

### Alpha.133 — primera base de paridad Sol/Luna validada en la partida real

La primera divergencia del arranque de Sol/Luna estaba en la barrera de
presentación, antes de las herramientas: `_finish_oras_initial_auto_sync`
trataba cualquier error inicial de transporte de SM como una conexión opcional
y retiraba la shell, mientras que solo BDSP esperaba una captura live con PS
resueltos. Por eso quedaba visible durante la conexión la composición
provisional del save con barras rojas y datos todavía incompletos.

SM comparte ahora únicamente el contrato demostrado de preparación visual: la
shell permanece oculta hasta que Azahar publica una party autoritativa y todos
los miembros tienen pares PS/PS máximos coherentes. No se han copiado offsets,
estructuras ni writers de USUM. La party SM expone además naturaleza, IV, EV,
stats finales y estado desde los campos PK7 ya validados; el adaptador obtiene
las stats base del perfil Personal de la ROM efectiva de Sol/Luna.

Verificación visual local completada el 24-08-2026 con Pokémon Sol en Azahar:
`diagnostics/manual/sm_initial_gate_loading.png` conserva el cargador completo
durante la conexión; `sm_initial_gate_ready.png` muestra la vista definitiva
con los seis PS resueltos; y `sm_initial_gate_detail_ready.png` muestra la ficha
de Decidueye con naturaleza, estadísticas finales y base, IV, EV, habilidad,
objeto y cuatro movimientos. Esta validación cierra la barrera visual y la
lectura de esos datos; no declara todavía paridad de writers o herramientas SM.

### Alpha.132 — incompatibilidades visibles también en la tarjeta de Equipo

La vista nueva calculaba correctamente las incompatibilidades de rol para la
ficha lateral, pero las cuatro cápsulas de movimientos de la tarjeta principal
se dibujaban sin consultar ese resultado. Ambas superficies comparten ahora el
mismo mapa por slot: un movimiento incompatible aparece en rojo desde la vista
general y, al seleccionar el Pokémon, la ficha conserva las acciones
`SUSTITUIR` y `ELIMINAR` ya conectadas al writer transaccional del backend.

La regresión verifica que tarjeta y ficha reciben exactamente el mismo mapa y
que un Pokémon almacenado en PC no hereda por error las restricciones del rol
activo del equipo. La comprobación visual local en la run USUM/Azahar confirmó
que `Cuchilla Solar` de Carnivine/Mago aparece en rojo tanto en la tarjeta como
en la ficha y que esta muestra `SUSTITUIR` y `ELIMINAR`. Validación física
completada en USUM/Azahar el 24-08-2026: `ELIMINAR` retiró `Cuchilla Solar` del
Carnivine tanto en RoleRun como en la partida real. La detección y la escritura
correctiva de movimientos incompatibles quedan cerradas para este entorno.

### Alpha.131 — contrato de MT reutilizable corregido

La primera divergencia no estaba en los writers de los juegos 3DS: las pruebas
existentes demuestran que ORAS, X/Y, SM y USUM escriben el movimiento sin tocar
la mochila. Estaba en la proyección común de la UI, que descontaba una unidad de
cualquier MT pendiente. El cambio conserva ahora en `PendingTMTeach` el contrato
de consumo: `False` para Gen 6/7 y `True` únicamente para BDSP. Inventario
pendiente, refresco tras readback, revisión e historial respetan ese mismo dato.

Las regresiones automatizadas cubren ambos comportamientos. Validación física
completada en USUM/Azahar el 24-08-2026: tras enseñar una MT que tenía cantidad
`x1`, la misma MT continuó disponible con `x1` tanto en la mochila del juego como
en RoleRun. La reutilización de MT de USUM queda cerrada.

### Alpha.130 — arrastre transaccional entre cajas USUM validado físicamente

USUM permite mantener un Pokémon del PC sobre una flecha para cambiar una caja
sin perder el arrastre y soltarlo después en una casilla vacía exacta. La
interacción cambia una sola caja por cada entrada en la flecha; permanecer sobre
ella no genera avances repetidos fuera de control.

El writer usa la matriz PC completa ya demostrada para UltraSol/Azahar: valida
origen, destino, identidad y transporte host/guest, copia el PK7 cifrado exacto,
escribe un vacío cifrado válido en el origen y exige dos readbacks semánticos.
Si falla cualquier comprobación, restaura y verifica ambos huecos. Los destinos
ocupados y los demás backends siguen rechazados.

Alpha.129 contenía el writer correcto, pero la captura del ratón retargeteaba
el puntero a la superficie de origen: las casillas vacías y las flechas nunca
recibían el gesto real. Alpha.130 mantiene la escritura y corrige esa primera
divergencia mediante el bindtag estable del `Toplevel`, sin `grab_set`.

Validación física completada en USUM/Azahar 263745c el 2026-08-24: Eevee se
movió caja 1/casilla 1 → caja 1/casilla 2 → caja 2/casilla 1, y el recorrido
inverso con `<` lo restauró en caja 1/casilla 1. Las capturas de cada frontera
se conservan en `diagnostics/manual/alpha130_*.png`.

### Cierre físico de BDSP — 24 de agosto de 2026

El usuario validó físicamente en Pokémon Perla Reluciente 1.3.0 / Ryujinx 1.3.3
la exclusividad final de teclado y mando de alpha.119: con RoleRun en primer
plano, navegar y aceptar dentro de la aplicación no mueve al personaje ni
interactúa en el juego; al devolver el foco a Ryujinx, los controles vuelven a
funcionar. Con esta comprobación se da por cerrado el desarrollo funcional de
BDSP hasta nuevo aviso. El siguiente foco es trasladar las capacidades nuevas a
UltraSol/UltraLuna sobre Azahar, demostrando por separado cada writer y dato RAM
específico de Gen 7.


### Alpha.119 — RoleRun posee en exclusiva los controles frente a Ryujinx

Cuando RoleRun está en primer plano durante una sesión BDSP, Ryujinx queda
retenido antes de leer el mando y se reanuda al devolver el foco. Esto impide
que flechas, aceptar o atrás naveguen RoleRun y actúen a la vez en el juego. La
prueba física local midió `0` avance de CPU durante 600 ms de retención y
confirmó la liberación posterior. La validación final de interacción con teclado
y mando reales queda pendiente de la comprobación breve del usuario.


### Alpha.118 — primer frame BDSP estable en la geometría final

La causa visual restante de alpha.117 no estaba en RAM ni en los PS: la vista
oculta se validaba antes de maximizar la ventana. El mapeo del HWND iniciaba un
segundo relayout que el cargador ya no cubría por completo. Alpha.118 mantiene
una superficie de carga maximizada e independiente, recompone la vista con la
raíz transparente en su tamaño final y solo la publica tras cuatro muestras
consecutivas de geometría, cajas y PS estables.

La validación física local se repitió dos veces desde procesos nuevos, con una
captura de pantalla cada 150 ms. Las dos secuencias muestran exclusivamente el
loader animado y después la interfaz completa; no aparece ningún frame blanco,
vacío, provisional o parcialmente compuesto. Evidencia conservada en
`diagnostics/ui/alpha118-startup-physical-19/` y
`diagnostics/ui/alpha118-startup-physical-20/`.

### Alpha.117 — primera apertura BDSP protegida por salud live

El vídeo físico `2026-08-24 14-50-17.mp4` demostró la primera divergencia: el
primer intento de transporte con Ryujinx fallaba durante el arranque y
`_finish_oras_initial_auto_sync()` declaraba completa la sonda igualmente. La
shell mostraba por ello los PS provisionales del save; unos trece segundos más
tarde un reintento live los sustituía por los correctos.

BDSP mantiene ahora la barrera animada ante ese fallo inicial. Solo la retira
después de publicar una captura live, demostrar pares HP/Max HP coherentes para
toda la party y completar la composición visual final. Un Pokémon realmente
debilitado con `0/Max HP` es válido; el placeholder `0/0` no lo es. Queda
pendiente validar físicamente una primera apertura desde un proceso RoleRun
nuevo. Esa validación pendiente queda resuelta y supersedida por la doble
captura física de alpha.118 descrita arriba.

### Alpha.116 — repetición deliberada y entrenamiento live publicado

La prueba física de alpha.115 refutó el umbral anterior: 200 ms era menor que
una pulsación humana normal y una sola acción podía atravesar varias casillas.
Alpha.116 mantiene el primer movimiento inmediato y exige 450 ms de pulsación
continua antes del autorrepetido; después repite cada 70 ms.

La ausencia de stats en Drafteos tenía una causa distinta. El lector BDSP sí
entregaba naturaleza, stats, stats base, IV y EV, pero la reconciliación solo
publicaba el snapshot cuando cambiaban identidad, rol o movimientos. Ahora una
mejora de esos campos de presentación también publica el snapshot live, sin
crear cambios pendientes ni escribir en el juego. Las regresiones automáticas
cubren ambas primeras divergencias. El usuario validó físicamente en BDSP que
un tap vuelve a mover una sola casilla y que Drafteos muestra naturaleza,
estadísticas, IV y EV. El autorrepetido se conserva algo lento, aceptado
expresamente para no prolongar este ajuste.

### Alpha.115 — foco exclusivo y repetición recuperada

La validación física de alpha.114 confirmó que el salto de extremos quedó
corregido, pero demostró una regresión de velocidad: se había eliminado la
repetición completa del D-pad junto con la ruta equivocada. Alpha.115 conserva
el propietario único y recupera la repetición controlada tras 200 ms, cada
52 ms mientras se mantiene la dirección.

El drawer es ahora un plano estrictamente vertical: Izquierda/Derecha no hacen
nada y no pueden volver a encender el cursor inferior durante su animación.
Drafteos conserva el marco dorado común; la tarjeta de Líbero deja de tener un
borde dorado fijo que parecía una segunda selección. Las capturas verificadas
son `diagnostics/ui/alpha115-draft-shared-focus.png` y
`diagnostics/ui/alpha115-sidebar-exclusive-focus.png`; la suite completa supera
**719 tests**. Queda pendiente la comprobación física del ritmo del D-pad.

### Alpha.114 — un solo recorrido para teclado y mando

La validación física de alpha.113 demostró que quedaba una segunda ruta: el
teclado respetaba el propietario visible, pero el mando elegía la vista por la
pestaña base. Dentro del flujo integrado de MT enviaba por ello las flechas a
Equipo/PC, que permanecía compuesto debajo. Alpha.114 elimina esa bifurcación:
dirección, aceptar y atrás del mando usan la misma autoridad que el teclado.

La repetición sintética del D-pad se separa del flanco inicial; una pulsación
corta en la aplicación solo puede publicar un movimiento. El foco de Drafteos
usa contraste marfil sobre controles dorados y fue inspeccionado a 1920×1080 en
`diagnostics/ui/alpha114-draft-focus-selected.png`. Las **718 pruebas** pasan;
queda pendiente la validación física con el mando real antes de cerrar la
navegación de BDSP.

### Alpha.113 — una sola autoridad de navegación

La primera divergencia de los saltos y selectores ausentes estaba en el
despacho de entrada, no en la geometría espacial: la página conservada como
buffer, la pantalla situada debajo del flujo MT y la vista visible podían
escuchar el mismo evento del `Toplevel`. El controlador concede ahora la
autoridad a una sola vista y la transfiere explícitamente al abrir/cerrar MT.

El drawer lateral forma parte de esa misma jerarquía: su foco oculta el cursor
de contenido, permite navegar sus entradas y restaura la selección original al
cerrarse. La composición se inspeccionó a 1920×1080 y la suite completa supera
715 tests. Queda pendiente la validación física breve de teclado y mando del
usuario antes de cerrar esta ergonomía.

### Alpha.112 — navegación jerárquica y stats base

La navegación de Equipo/PC, MT y Drafteos conserva ahora el cursor al volver
desde un nivel de detalle y permite alcanzar el menú lateral desde el extremo
izquierdo. La ficha pesada se redibuja de forma agrupada tras las ráfagas de
dirección y el mando aplica repetición controlada al mantener el D-pad.

Los seis stats base se obtienen de la misma tabla Personal BDSP validada que
usa la compatibilidad de MT, se incorporan al snapshot realtime y se presentan
entre el stat final y los IV/EV. La aplicación real conectada a Ryujinx mostró
los valores y procesó cinco entradas separadas 10 ms sin pérdidas. La suite
completa supera 713 tests. La ergonomía final con teclado y mando permanece
pendiente de validación física del usuario.

### Alpha.111 — atajos exclusivos del juego

El usuario confirmó físicamente que los stats del PC ya funcionan. La última
divergencia de interacción estaba en el alcance del foco: alpha.110 permitía
todavía que RoleRun fuese una ventana autorizada para parte del flujo. Alpha.111
aplica un único contrato a todas las acciones: sus teclas solo se registran si
el primer plano pertenece a un emulador compatible y la ejecución vuelve a
comprobar esa misma precondición para rechazar mensajes encolados.

La prueba Win32 sobre la aplicación real y la run activa confirmó para `D` y
`NUM 7`: libres con RoleRun delante, reservadas con Ryujinx delante y liberadas
de nuevo al regresar a RoleRun. Queda pendiente únicamente la validación breve
del usuario antes de dar BDSP por cerrado. La suite completa queda en **705
tests superados**.

### Alpha.110 — stats PC validados en la aplicación real

La prueba real de alpha.109 demostró una divergencia adicional: aunque el reader
y la proyección aislada eran correctos, la sesión no generaba ningún evento
`pc-reconcile-*`. La carga unificada terminaba antes de activar realtime y el
refresco posterior solo contemplaba la página histórica `pc`; la vista actual es
`team`. La captura completa se dispara ahora en cuanto la sincronización inicial
BDSP queda validada y la publicación repinta la vista unificada.

Se abrió el programa real contra Ryujinx y se seleccionó Ornita en caja 1/slot 8.
La traza produjo `pc-read` con 11 ocupados y `pc-reconcile-applied changed=true`;
la ficha mostró naturaleza Huraña, stats `44/31/21/19/18/30`, IV
`23/13/29/17/8/8` y EV a cero. La evidencia visual se conserva en
`diagnostics/ui/alpha110-real-app-ornita-verified.png`.

Las letras simples pueden mapearse de nuevo sin quedar secuestradas en Windows:
su `RegisterHotKey` existe solo mientras el emulador tiene el foco. Una
prueba Win32 real comprobó el ciclo de `D`: libre fuera, reservada dentro y libre
de nuevo al cambiar de aplicación.

La baseline automatizada queda en **705 tests superados**. La ficha PC fue
validada visualmente en la ejecución real; el mapeo de una letra concreta queda
pendiente únicamente de la prueba de uso elegida por el usuario.

### Alpha.109 — primera publicación completa de metadatos PC

La prueba física posterior a alpha.108 demostró que Ornita seguía mostrando
guiones. Una comparación directa en la misma ejecución separó las dos
fronteras: el objeto procedente del guardado tenía naturaleza/stats/IV/EV
vacíos; el reader vivo de Ryujinx devolvía para la misma identidad y caja 1,
slot 8 naturaleza Huraña, stats `44/31/21/19/18/30`, IV
`23/13/29/17/8/8` y todos los EV a cero. La primera divergencia estaba después
del reader: la reconciliación consideraba que identidad y posición iguales
implicaban que no había cambio, conservando el objeto incompleto del save.

BDSP publica ahora la matriz PB8 viva completa y usa una firma de presentación
para repintar únicamente cuando cambian campos visibles. La regresión cubre la
misma identidad en el mismo slot y comprueba caché y proyección final. La
composición se inspeccionó a 1920×1080 tanto en la ventana principal como en el
overlay.

La asignación física `D` demostró además que un `RegisterHotKey` global sin
modificadores secuestra la letra antes de que Windows la entregue al programa
con foco. Alpha.109 la rechazó preventivamente; alpha.110 sustituye esa medida
por registro condicionado al foco, permitiendo el mapeo solicitado sin afectar
a otras aplicaciones.

El usuario confirmó físicamente el 24-08-2026 que los contadores de la barra
flotante responden desde la primera interacción. La visualización física de los
stats PC corregidos queda pendiente de una única comprobación en alpha.109.
La baseline automatizada queda en **705 tests superados**.

### Alpha.108 — stats PC independientes del equipo

Alpha.108 corrigió una divergencia real del reader: el PB8 almacenado no
publicaba EXP y el adaptador no podía derivar el nivel sin un ancla del equipo.
La lectura posterior de Ornita demostró que esa capa ya devolvía nivel 15,
naturaleza, IV/EV y seis stats. Sin embargo, la UI continuó mostrando guiones;
alpha.109 localizó una segunda divergencia posterior en la reconciliación y
evita presentar alpha.108 como una corrección completa del síntoma visual.

Los contadores de la barra ya persistían correctamente; faltaba invalidar y
repintar su vista tras el clic. El repintado queda diferido fuera del callback.
La captura breve de teclas simples también se hace directa.

El mando continúa sin habilitarse: Ryujinx 1.3.3 usa `GamepadSDL2`, mantiene
`disable_input_when_out_of_focus=false` y Windows no tiene HidHide, ViGEm ni
HidGuardian. Detectar botones sin bloquear el dispositivo haría que RoleRun y
el juego recibieran la misma acción.

### Alpha.107 — datos PC y controles accionables

El reader BDSP ya conserva naturaleza/IV/EV extraídos del PB8 y el adaptador
calcula stats del PC solo con nivel anclado por identidad y PersonalTable
validada. Z avanza de MT a Pokémon, drafteos expone elegir/regenerar por separado,
Bolsa confirma sus envíos y el menú raíz incorpora acceso a Configuración.

La columna de mando queda explícitamente sin habilitar: el entorno físico usa
Ryujinx SDL2 con `disable_input_when_out_of_focus=false` y no dispone de un
filtro HID. La mera lectura desde RoleRun no impediría que el juego recibiera el
mismo input, incumpliendo el requisito de exclusividad.
La baseline automatizada queda en **699 tests superados**.

### Alpha.106 — navegación jerárquica sin alterar Ryujinx

La prueba física de alpha.105 demostró dos primeras divergencias: la ruta de
pausa ejecutaba `ShowWindow(SW_RESTORE)` y cambiaba el modo de ventana del
emulador; además, las vistas y el overlay registraban manejadores de `X`
simultáneos, por lo que una sola pulsación podía desmontar toda la superficie.
Alpha.106 elimina por completo la pausa y cualquier escritura sobre el estado
de ventana de Ryujinx. El Toplevel conserva foco y grab de teclado para que las
flechas no lleguen al juego. Una única capa dirige flechas/Z a la vista activa y
reserva X para sección → menú raíz → cierre. El cierre raíz restaura la barra de
forma síncrona. La navegación física queda pendiente de la prueba breve indicada
al usuario.
La baseline automatizada queda en **696 tests superados**.

### Alpha.105 — superficies inmersivas independientes

La prueba física de alpha.104 rechazó tres premisas de presentación: ocultar la
shell no independizaba sus canvases, `textvariable` y `text` competían en el
botón ON/OFF y `PostMessage` no equivalía a una tecla física para el input SDL
de Ryujinx. Alpha.105 crea un viewport propio para cada overlay, deja una sola
fuente textual en el selector y dirige SendInput F5 exclusivamente al HWND BDSP
validado. Equipo/PC, MT, Drafteos y Bolsa han sido inspeccionados a 1920×1080;
la pausa y el repintado ON/OFF quedan pendientes de confirmación física breve.
La baseline automatizada queda en **694 tests superados**.

### Alpha.104 — presentación física de PS y menú inmersivo

La validación física de alpha.103 demostró que el carril de HP ya refrescaba la
barra, pero también que los descensos positivos se publicaban antes de que la
barra del juego terminara. La primera divergencia estaba en
`BDSPRealTimeAdapter._presentation_gated_battle_state`: la compuerta demostrada
por alpha.68 solo cubría `HP=0`; cualquier `HP>0` se aceptaba directamente desde
BTL_PARTY. Alpha.104 aplica la misma evidencia de BUIStatusWindow a todo
descenso y añade una regresión 58→31 que conserva 58 hasta completar la
animación física.

El menú de juego usa la ventana BDSP/Title ID exacta y la tecla de pausa que la
instalación declara en su propio `Config.json`; no generaliza el comportamiento
a otros emuladores. Las vistas inmersivas y la temporización del daño quedan
pendientes de la prueba física breve indicada al usuario.

La baseline automatizada de esta versión queda en **691 tests superados** con
`python -m pytest -q`.

### Alpha.103 — salud viva y controles flotantes pendientes de validación

El usuario validó físicamente el 23-08-2026 en Perla Reluciente 1.3.0/Ryujinx
que la curación completa restaura correctamente todos los datos y que los
cambios de Pokémon del equipo se reflejan correctamente en el juego.

Alpha.103 incorpora el HP y el estado PB8 a la fuente viva que dibuja Equipo y
PC y la barra flotante. La lectura usa el campo de estado ya demostrado por el
writer de curación y los valores se contrastaron mediante reflexión contra la
DLL local `PKHeX.Core.dll`; la validación física de daño/estado y de los nuevos
controles flotantes sigue pendiente.

Verificación automatizada de alpha.103: **690 passed** en 23,51 s con
`python -m pytest -q`.

### Alpha.102 — cierre funcional BDSP pendiente de validación física

La party BDSP dispone de curación completa desde `Equipo y PC` y desde la barra
flotante. El writer modifica únicamente el PB8 identificado: PS actuales hasta
los PS máximos ya leídos, `Status_Condition` a cero y los cuatro PP según
WazaTable más PP Ups. Conserva identidad, EV, IV, rol y datos no implicados; usa
doble lectura, precondiciones host/guest, readback semántico y rollback.

Equipo→Equipo se interpreta en la UI como intercambio de roles y permanece
separado de la reordenación física no demostrada. Cada receptor recibe la
distribución EV de su nuevo rol; Líbero exige dos stats. La entrada PC→Equipo
incorpora la misma distribución en el snapshot y, tras el readback del cambio de
party, aplica el writer probado de rol+EV contra la identidad confirmada.

El inspector usa la evaluación común de reglas para pintar movimientos
incompatibles en rojo y exponer sustitución o eliminación. La barra flotante
tiene preferencia persistente ON/OFF y curación BDSP directa. Dos capturas
sintéticas a 1920×1080 confirman que los nuevos controles no desbordan Equipo ni
la ficha. Estas capacidades quedan pendientes de una única validación física
controlada en BDSP/Ryujinx antes de declararse cerradas. Suite completa:
**671 passed** en 22,69 s con `py -3.14 -m pytest -q`.

No se implementa un bypass genérico de MO. BDSP ya ofrece movimientos ocultos
desde el Pokétch sin enseñarlos; los títulos anteriores requieren investigación
por juego porque sus comprobaciones de campo no comparten un contrato demostrado.

### Pestaña global de MT — implementada, interacción final pendiente de validación

La navegación principal incorpora `MT`. La vista lee la mochila mediante el
reader realtime ya demostrado, muestra solo cantidades positivas confirmadas
y calcula cada miembro con `_tm_flow_candidates()`. Por tanto no duplica
compatibilidad, restricciones de rol ni escritores. Elegir una combinación
válida abre directamente el paso de movimiento a olvidar del flujo integrado;
confirmación, consumo, readback y rollback conservan la ruta anterior.

Las capturas `diagnostics/ui/global-tm-owned-hover.png`,
`global-tm-already-known-final.png` y `global-tm-centered-slots.png` demuestran
a 1920×1080 mochila poseída, estado `YA LO CONOCE` y selector centrado. Hover
actualiza propiedades sobre widgets persistentes; el readback actualiza la vista
sin desmontarla. Suite completa: **662 passed** en 23,85 s. El usuario confirmó
físicamente aprendizaje y consumo correctos en BDSP/Ryujinx; falta validar que
esta revisión final elimina flicker, salto de scroll y cargador posterior.

### Cambios posteriores a alpha.100: validación física y defecto abierto

La primera divergencia investigada de la apertura estaba antes de la barrera visual:
`_finish_save_load` publicaba deliberadamente una vista provisional con
`_pc_cache=None` y una caja, y solo después iniciaba la lectura PC. Además, la
primera publicación realtime podía reconstruir la página después de retirar el
cargador. La carga inicial lee ahora las cajas en el mismo worker de apertura,
instala la caché antes de crear la shell y mantiene la barrera hasta que la vista
final notifica su composición y termina el primer intento realtime. No existe un
timeout que pueda exponer una vista incompleta. Sin embargo, la validación
física posterior demuestra que la primera vista todavía aparece parcialmente
compuesta durante unos tres segundos. Por tanto, **la carga inicial sigue
abierta y no está corregida**. Después de varios cambios consecutivos que no
eliminaron el síntoma, se detiene el parcheo incremental y se aplaza este punto
hasta una investigación nueva de la publicación real de la ventana.

La primera divergencia al salir de MT era distinta: el flujo se destruía antes
de capturar el fondo y acto seguido se reconstruía `Equipo y PC`, aunque esa
vista seguía intacta debajo. La salida conserva primero el flujo MT completo,
lo retira después y revela la vista ya compuesta sin volver a renderizarla. Una
prueba Tk real a 1920×1080 conserva 30 botones PC, tres pasadas de layout,
paneles mapeados y ninguna barrera residual. La validación física posterior
confirma que la entrada, navegación y salida de MT ya se muestran correctamente.
El flujo MT queda validado en BDSP/Ryujinx; esta confirmación no se extiende a la
carga inicial.
Verificación automatizada: **655 passed** en 23,53 s con
`python -m pytest -q`.

Alpha.100 continúa la evolución quirúrgica de la interfaz original de RoleRun Manager.
La implementación se realiza exclusivamente en `RoleRun Manager Design
Evolution`; `RoleRun Manager Dev` y el prototipo rechazado permanecen fuera del
alcance. La comparación inicial demostró una copia exacta de 951 archivos,
74.302.609 bytes y SHA-256 agregado
`4025b7627611bf439ef592f776aff2b079288242626e4fc069d0d8f009474f1a`,
desde `main` / `0659aa624a68df7cd4d116d59c62090b911752ef`.

Alpha.100 vincula la retirada del cargador PC a evidencia de la vista publicada:
tres observaciones consecutivas con el conteo real de cajas y geometría válida.
MT reutiliza el estilo de frame estable oscurecido y el inspector permite
recorrer horizontalmente todas sus acciones. Verificación: **649 passed** en
22,37 s con `python -m pytest -q`. Validación física pendiente.

Tras dos intentos que solo desplazaron el defecto visual, alpha.99 abandona la
captura operativa de CTk: apertura, carga PC y MT usan una superficie opaca
autónoma. La navegación normal conserva su frame validado. Equipo y PC dejan de
compartir una cuadrícula geométrica ficticia; las seis filas de roles se recorren
en orden y `Z` transfiere el foco a las acciones de la ficha. `X` limpia la
selección. Verificación: **648 passed** en 22,78 s con
`python -m pytest -q`. Validación física pendiente.

Alpha.98 corrige dos primeras divergencias demostradas en alpha.97: `_clear_root`
destruía el Toplevel que debía proteger la apertura, y cerrar el flujo integrado
de MT abandonaba su referencia sin destruir sus bindings de teclado. La barrera
queda preservada, MT se retira de forma transaccional y el inspector PC participa
en la navegación con flechas. Verificación: **647 passed** en 22,58 s con
`python -m pytest -q`. Validación física pendiente.

La navegación, Equipo/PC, MT, Drafteos, Ayuda, bajas, Configuración y los
selectores normales ya están integrados en la ventana principal. La barra
flotante, el fantasma técnico de drag y la barrera transitoria de navegación
crean superficies independientes; esta última no contiene controles ni estado.

La prueba física de alpha.94 confirmó que el lateral ya se desliza fluido y que
el cambio de pestaña conserva la vista anterior hasta publicar el destino
completo. Permanecían tres defectos observables: variación zonal de luminosidad
durante esa espera, un tirador `<` residual junto al `>` y ausencia de actividad
animada durante el render síncrono. Alpha.95 transfiere el frame limpio anterior
al scrim, desmapea por completo el drawer al cerrarlo y dibuja el spinner desde
un worker GDI independiente del bucle Tk. La validación física de estos tres
ajustes queda pendiente.

Verificación alpha.95: **638 passed** en 22,71 s con
`py -3.14 -m pytest -q`. `alpha95-navigation-control-60fps.mp4` conserva el
origen completo durante la espera; `alpha95-spinner-contact-sheet.png` muestra
el avance de los radios a 20 fps sin variación del contenido circundante. La
captura asentada muestra únicamente el tirador `>`. Falta la comprobación
física breve de estos tres resultados en la aplicación real.

La validación física posterior de alpha.95 confirma navegación fluida,
publicación atómica, spinner móvil y desaparición del tirador `<` residual. Dos
capturas nuevas demostraron que los loaders CTk de apertura/PC pertenecían al
mismo árbol que se reconstruía: su animación se detenía y el de PC podía quedar
recortado con widgets parciales. Alpha.96 sustituye todas las entradas al sistema
común de espera por una superficie con HWND propio, conserva oscuro el origen de
la navegación y mantiene la carga PC hasta finalizar el render de destino.

Verificación alpha.96: **639 passed** en 22,95 s con
`py -3.14 -m pytest -q`. El preview bloqueó deliberadamente el mainloop durante
1,7 s; `alpha96-activity-overlay-control-60fps.mp4` y
`alpha96-activity-spinner-contact.png` demuestran movimiento continuo sin
recortes ni reconstrucción del fondo. La validación física de alpha.96 encontró
cuatro divergencias: la apertura podía congelar un shell parcial, BDSP
proyectaba el swap antes del readback y podía duplicar una identidad, el
arrastre dejaba trazas y los mensajes de carga podían solaparse. Alpha.97
conserva la barrera inicial hasta terminar la primera lectura PC, usa un
fantasma nativo, repinta una superficie fija de mensaje y publica Equipo/PC
BDSP solo después del resultado verificado. Su validación física queda pendiente.
Verificación alpha.97: **643 passed** en 22,86 s con
`python -m pytest -q`.
Las operaciones
funcionales reutilizan los mismos modelos, servicios, writers y comprobaciones
de alpha.86. Alpha.87 no añadió offsets, lectores, parsers, adapters ni rutas de
escritura RAM. Alpha.88 amplía exclusivamente la decodificación de campos ya
documentados dentro del PB8 BDSP existente; no incorpora direcciones ni writers.
PC→PC y la reordenación física Equipo→Equipo siguen rechazadas porque no existe
evidencia de writers que las soporten.

La sustitución de baja conserva `prompt_shown`, la cola de KO, la vida ya
descontada, Cementerio, precondiciones, readback y rollback. Su cierre es solo
visual y deja una acción persistente para reabrirla. La guía de roles comparte
una única fuente entre Ayuda y los popovers. Las Runs antiguas con Modo Libre
se migran a reglas siempre activas sin escribir en la partida.

Verificación automatizada actual: **637 passed** en 22,95 s. Capturas sintéticas
revisadas a 1100×720, 1360×768, 1440×900, 1900×1040 y escala 125 % en
`diagnostics/design/` y `diagnostics/design_evolution/`. La validación manual pendiente es únicamente
de presentación e interacción; las capacidades realtime conservan la
validación física ya registrada por sus versiones de origen.

Alpha.88 añade el resumen permanente de los cuatro contadores en la cabecera
ancha y compacta Equipo/PC y Drafteos para 16:9. En BDSP live, la ficha publica
naturaleza real/efectiva, stats calculados, IV y EV extraídos del mismo PB8 ya
validado. La tabla efectiva del mod publica además potencia, precisión y 826
descripciones no vacías; el bundle instalado es inglés y se rotula `EN`.

Alpha.101 implementa la asignación automática de EV por rol en BDSP y queda
**validada físicamente**. La transacción actualiza conjuntamente
marcador de rol, seis EV, stats calculados y PS; exige que PersonalTable,
IV/EV/nivel/naturaleza reproduzcan el bloque vivo anterior, hace readback del
core y calc en host/guest y revierte ambos si falla cualquier comprobación. Los
roles fijos maximizan su pareja y ponen a cero los otros cuatro stats; Líbero
exige elegir exactamente dos. El daño previo se conserva y un Pokémon a cero
PS no revive.

Validación física del 23 de agosto de 2026: **Líbero y asignación fija
correctos** en BDSP/Ryujinx. El usuario eligió las dos estadísticas de Líbero y
confirmó después que un rol fijo aplicaba automáticamente su pareja 252/252 y
limpiaba las otras cuatro. La capacidad de EV por rol queda cerrada.

La pestaña global de MT quedó validada físicamente en BDSP/Ryujinx el 23 de
agosto de 2026: solo muestra unidades poseídas, mantiene hover y scroll sin
flicker, distingue `YA LO CONOCE`, presenta el selector compacto y conserva la
vista hasta completar escritura y readback. El juego aprende el movimiento y
la mochila reduce exactamente una unidad.

Alpha.89 hace que las seis tarjetas de Equipo ocupen el panel completo y coloca
todo su contenido dentro del borde de selección. Solo la matriz PC tiene scroll.
Drafteos presenta sprites de 112 px y datos jerarquizados; su transición afecta
exclusivamente al contenido y nunca a la ventana completa. La consulta de
movimientos abierta desde el flujo conserva el drafteo y ofrece un retorno
explícito. Las cargas iniciales, del PC y de la mochila MT muestran un indicador
animado centrado. No se tocó lógica funcional ni ningún backend.

Verificación alpha.89: **620 passed** en 22,92 s con
`py -3.14 -m pytest -q -p no:cacheprovider`. Las capturas canónicas
`phase_h_team_pc_1900x1040.png` y `phase_h_draft_1900x1040.png` se revisaron
visualmente. La validación manual pendiente se limita a presentación,
transición y navegación; no se ha introducido una capacidad realtime nueva.

Alpha.90 elimina la interacción desplegable del resumen superior: vidas,
curaciones, medallas y drafteos son cuatro controles independientes visibles en
todas las páginas. Los controles manuales permiten restar y sumar directamente;
un contador automático conserva bloqueados esos botones para no introducir una
segunda fuente de verdad. En Equipo/PC, las seis fichas terminan junto a las
casillas 21–25 y las 30 posiciones del PC forman una matriz fija 5×6 sin scroll.
Drafteos muestra naturaleza, stats, IV, EV, movimientos y seis botones visibles
en una sola pantalla. El alto de ambas vistas se sincroniza con el viewport real.

Verificación alpha.90: **620 passed** en 23,29 s con
`py -3.14 -m pytest -q -p no:cacheprovider`. Se revisaron visualmente a
1900×1040 Equipo/PC y los tres pasos de Drafteos. No se modificó funcionalidad
realtime, persistencia, reglas, readers ni writers.

Alpha.91 convierte Equipo en la superficie principal: seis fichas completas
publican identidad, nivel, rol, PS/barra live, stats con naturaleza, habilidad,
objeto y movimientos. El PC se limita a tres columnas y desplaza localmente sus
treinta posiciones. La ficha de equipo conserva solo Cambio de rol y Enseñar
MT. La cabecera usa símbolos y Medallas no tiene controles manuales.

La navegación lateral es ahora una capa desplegable sobre contenido oscurecido.
Flechas, `Z` y `B` gobiernan selectores espaciales en Equipo/PC, Drafteos y MT
sin capturar teclas dentro de campos de texto. El indicador animado cubre
writers realtime y las lecturas de mochila ORAS/X/Y pasan a background sin
cambiar sus decisiones funcionales ni sus fallbacks. No se incorpora ninguna
dirección, estructura ni escritura nueva.

Verificación alpha.91: **625 passed** en 22,22 s con
`py -3.14 -m pytest -q -p no:cacheprovider`. La revisión visual sintética a
1900×1040 cubre Equipo/PC, menú lateral desplegado, Drafteos y MT. Queda
pendiente la validación manual de presentación y control por teclado; las
capacidades realtime heredadas no se reabren por este cambio de interfaz.

Alpha.92 compacta cada tarjeta de Equipo sin reducir su información: mote y
nivel comparten cabecera, la barra de PS ocupa aproximadamente un tercio, los
seis stats forman una matriz 2×3 y habilidad, objeto y cuatro movimientos quedan
visibles. Las seis siluetas aportadas por el usuario se conservan mediante su
canal alfa y se presentan en dorado como acceso a la guía de rol. La ficha
elimina la numeración de movimientos y separa IV/EV en seis recuadros.

La ventana principal no permanece minimizada: cambia a barra flotante o vuelve
maximizada cuando no puede abrirla. El menú lateral interpola su anchura durante
210 ms y reserva un carril al tirador. Los cambios de pestaña usan dos árboles
de widgets: la vista anterior deja de escuchar entradas pero sigue pintada hasta
que la nueva ha resuelto geometría y scroll. La primera divergencia del glitch
estaba en la destrucción anticipada de `IntegratedDraftFlow`, no en DWM ni en
los datos de la página.

Verificación alpha.92: **631 passed** en 23,10 s con
`py -3.14 -m pytest -q -p no:cacheprovider`. Se revisaron capturas sintéticas
a 1900×1040 de Equipo/PC, ficha seleccionada, Drafteos y menú lateral. Queda
pendiente la comprobación manual de presentación, tooltip, transición y cambio
entre ventana maximizada/barra; no se modificó ninguna capacidad realtime.

Alpha.93 coloca los cuatro movimientos de cada miembro en una sola fila y
reduce la ficha sin perder datos: cada stat publica valor, IV y EV antes de
habilidad y objeto. El tooltip se posiciona respecto del botón de rol, no con
coordenadas mezcladas entre la tarjeta y la ventana. Drafteos no muestra un
control de cierre en su primer paso; la flecha de los pasos siguientes vuelve
directamente a elegir Pokémon.

El vídeo físico `2026-08-23 17-50-55.mp4` permitió aislar dos fronteras de la
navegación. La capa oscura excedía el contenido al combinar un desplazamiento
horizontal con ancho relativo completo; ahora usa un rectángulo absoluto
acotado a la ventana. Además, la barrera de cambio llamaba a `update()` dentro
del propio intercambio: esa reentrada podía ejecutar temporizadores, resize y
otra navegación antes de terminar el árbol nuevo. Se conserva únicamente el
cálculo de geometría idle, el destino se renderiza tras el cierre real de 210 ms
y la captura anterior se retira después del primer repintado estable.

Verificación alpha.93: **635 passed** en 23,37 s con
`py -3.14 -m pytest -q`. La apertura lateral se inspeccionó a 30, 100 y 220 ms
a 1920×1080; sus anchos observados fueron 80, 201 y 285 px, y la capa oscura
coincidió exactamente con los 1.844 px restantes. También se comprobó escala
125 % y el render final Equipo/PC. Queda pendiente la validación manual breve de
la animación y del cambio de pestaña; no se alteró ninguna capacidad realtime.

Alpha.94 parte del vídeo físico `2026-08-23 18-20-30.mp4`. La primera
divergencia demostrada era que seleccionar Equipo y PC cuando ya estaba visible
ejecutaba de nuevo todo su render. La segunda estaba en la frontera de
composición: una etiqueta hija compartía el mismo orden de repintado que los
canvas de CustomTkinter y Windows podía publicar varios frames del destino
incompleto al retirarla.

La selección del destino actual ahora solo cierra el menú. Para una navegación
real, el último frame completo vive temporalmente en un `Toplevel` sin bordes,
con superficie DWM propia; la página nueva se construye debajo y el fundido no
empieza hasta que se han presentado varios frames estables. El drawer lateral
permanece maquetado a ancho fijo fuera del viewport y solo interpola su X. La
traza real a 1920×1080 redujo los intervalos del tramo visible desde unos 31 ms
a una mayoría de 4–5 ms, sin redimensionar descendientes.

Verificación alpha.94: **637 passed** en 22,95 s con
`py -3.14 -m pytest -q`. La grabación de control
`alpha94-automated-navigation-final-60fps.mp4` fue inspeccionada a 30 fps: el
contacto entre pantallas contiene únicamente dos páginas completas y su mezcla
de opacidad, sin paneles parciales. Se repitió el estado final a escala 125 % y
se comprobó que navegar a la pestaña activa no crea ninguna barrera ni render.
Queda pendiente la validación manual breve de la sensación del deslizamiento y
del cambio de pestaña. No cambia ninguna capacidad realtime.

Verificación alpha.88: **614 passed** en 22,66 s con
`py -3.14 -m pytest -q -p no:cacheprovider`. Las capturas sintéticas nuevas
cubren 1900×1010, 1360×768 y 1100×720. La lectura visual de naturaleza/stats/
IV/EV queda pendiente de una comprobación física breve en SP 1.3.0 / Ryujinx.

## Estado realtime heredado: BDSP / Ryujinx

La matriz exhaustiva y el orden de investigación se mantienen en
`docs/BDSP_REALTIME_PARITY.md`. Es el checklist maestro de esta etapa: una
capacidad dependiente de Ryujinx no se considera cerrada sin implementación,
regresión, suite completa y validación física.

El usuario ha aparcado USUM después de validar físicamente el primer Kahuna en
alpha.65. Los incrementos de los otros tres Kahunas conservan su estado
pendiente, pero no forman parte del trabajo activo hasta nuevo aviso.

El objetivo de esta etapa ha sido dotar a Pokémon Diamante Brillante/Perla
Reluciente de paridad realtime sobre Ryujinx. La baseline local demuestra Perla Reluciente
`1.3.0`, Title ID `010018E011D92000`, mod `Output` solo `romfs`, memoria
`HostMappedUnsafe` y una Run `SP-Timper` con save `SAV8BS` válido. El adapter y
bridge Switch están actualmente integrados para ese perfil exacto.

Se conserva GDB RSP como frontera diagnóstica de solo lectura y se ha añadido
el transporte permanente `RyujinxBridge`/HostMapped. Su cliente de captura
continúa abriendo solo consulta/lectura; alpha.75 añade un handle RW separado y
efímero exclusivamente dentro de transacciones BDSP ya precondicionadas.
`BDSPRealTimeAdapter` publica party, PC, inventario/MT y lane de batalla en el
Core. Roles y movimientos de la party, incluida la enseñanza consumible de MT,
tienen writer transaccional. El swap Equipo↔PC 1↔1 está validado físicamente;
alpha.82 cierra físicamente el cambio de tamaño de cola 5↔6 y alpha.83 añade la
compactación intermedia ya validada desde RoleRun. Alpha.84 incorpora la
sustitución por baja sobre esas mismas unidades demostradas, validada
físicamente para uno y dos KO. Alpha.85 añade las tres utilidades generales con
writer transaccional. La prueba física validó Caramelo Raro y dinero, y demostró
que el supuesto ID de Repelente Máximo era incorrecto. Alpha.86 corrige la
identidad y añade el alta exacta de un objeto todavía ausente; solo ese botón
queda pendiente de una prueba breve.
Progreso se limita al reader de medallas ya integrado. La prueba física del 2026-08-22
confirmó Title ID, `SwitchPlayer.nss` como módulo `main` y tres
fuentes independientes para SP 1.3.0: las cajas 40×30, la party runtime de
`PlayerWork._playerParty` y la party del cliente jugador dentro de
`BattleProc`. Los lectores de producción validan tamaño, conteo, punteros,
doble lectura, identidad y checksum donde corresponde; no trasladan ninguna
estructura de 3DS. Baseline y fuentes: `docs/BDSP_REALTIME_BASELINE.md`.

## Estado realtime vigente heredado de alpha.86

La primera divergencia de las utilidades estaba en la UI: BDSP rechazaba
`PendingInventoryChange` aunque el array vivo `SaveData.saveItem` ya estaba
demostrado. Alpha.85 abrió correctamente esa compuerta y la prueba física
confirmó Caramelo Raro ×999 y dinero 999.999. Sin embargo, el tercer botón dejó
`Repelente ×999`: el fallo no estaba en la transacción sino en la identidad
estática que asociaba `max-repel` con el registro `79`.

La causa queda demostrada por tres evidencias concordantes. El catálogo español
indexado de PKHeX contiene `77 = Repelente Máximo` y `79 = Repelente`; OpenDPR
declara `GOORUDOSUPUREE=77` y `MUSIYOKESUPUREE=79`; y la relectura física tras
alpha.85 mostró `SaveItem[79].Count=999` mientras `SaveItem[77]` seguía en
`Count=0, SortNumber=0`. La primera divergencia era
`BDSP_UTILITY_ITEM_IDS`, antes del writer. Evidencia canónica:
`diagnostics/manual/bdsp_alpha85_max_repel_identity_FAIL_alpha86_ROOT_CAUSE_20260823.json`.

Alpha.86 mapea Repelente Máximo exclusivamente a `77`. Como esta partida nunca
lo había poseído, el botón debe además crear su posición en la mochila. OpenDPR
demuestra que el primer alta asigna el siguiente orden del bolsillo y PKHeX
precisa el algoritmo: máximo `SortOrder` entre los IDs legales del mismo
bolsillo más uno. La mochila actual tiene máximo 16 en General, de modo que el
alta esperada de `77` usa 17. El registro `79` y los restantes 2.998 registros
se conservan byte a byte. Los 999 Repelentes normales producidos por alpha.85
permanecen en la partida; RoleRun no intenta una restauración tardía con un
valor que podría haber cambiado desde la prueba.

Para dinero, OpenDPR demuestra `SaveData.playerData.mystatus` y el orden
`name, id, gold`; PKHeX demuestra el máximo 999.999. En el único `PlayerWork`
físico de SP 1.3.0, `MYSTATUS` quedó localizado en `+0xE0` y `gold` en `+0xEC`.
Nombre, ID32, dinero, edición SP y dos medallas coincidieron con
el save; la doble lectura fue estable y el ID32 apareció una sola vez dentro
del objeto. Evidencia canónica:
`diagnostics/manual/bdsp_alpha85_money_and_utility_layout_PROOF_20260822.json`.

El carril exige fuera de combate dos capturas idénticas de party, mochila
y `MYSTATUS`, huella de sesión y coincidencia guest/host. Solo cambia el
`SaveItem` de 12 bytes del ID demostrado y/o los cuatro bytes de dinero. Conserva
todos los metadatos existentes; para un objeto General ausente, crea exactamente
el orden de bolsillo demostrado. El readback compara los 36.000
bytes de mochila, los 56 bytes de `MYSTATUS`, la party intacta y el valor
semántico. Un fallo restaura todos los destinos y verifica el rollback.

La UI aplica los tres botones automáticamente; desconectada no crea una cola de
save. El editor de rol para un Pokémon que permanece dentro del PC se declara
fuera de alcance por decisión del usuario; no bloquea el cierre de BDSP.
Caramelo Raro, Repelente Máximo y dinero: **validados físicamente** en SP 1.3.0
/ Ryujinx. El usuario confirmó que alpha.86 creó Repelente Máximo ×999, cerrando
la única validación pendiente del carril. Verificación alpha.86: **130 passed**
en el bloque BDSP dirigido y **581 passed** en 22,05 s en la suite completa.

Alpha.76 corrige dos divergencias demostradas en la primera prueba física del
writer de MT. La traza preservada contiene 439 snapshots y todos tienen seis
miembros; al cambiar Pidgeotto por Slowpoke la secuencia pasa de
`303,359,391,353,339,17` a `303,359,391,353,339,79`, nunca a siete. La tarjeta
adicional nacía después del adapter: BDSP publicaba al entrante con su marcador
de caja antes de aplicar la herencia del rol saliente, y el maquetador mostraba
el duplicado de `Mago` fuera de las seis casillas fijas. Ahora se escribe y
verifica primero el rol heredado y solo el readback confirmado puede sustituir
la party visible; si el writer está ocupado se conserva la captura anterior.

La misma sesión emitió 439 avisos `BattleProc contiene un TypeInfo inválido`.
Una doble lectura directa, estable y de solo lectura demostró que la ranura
TypeInfo era exactamente cero fuera de combate, no un puntero no nulo corrupto.
El reader acepta únicamente ese `nullptr` como clase no cargada. Cualquier valor
no nulo inválido, static fields incoherentes, flags inestables o batalla activa
continúan bloqueando la escritura. No se añadió dirección ni fallback de salud.
Evidencias:
`diagnostics/manual/bdsp_alpha75_pc_seventh_and_tm_battleproc_FAIL_20260822_210614.jsonl`
(SHA-256 `51BB6576F4421B4B0A37926E702C77CE0CEE9F658A7FE3C23F38F9E4CA831DC9`)
y `diagnostics/manual/bdsp_alpha75_battleproc_null_outside_battle_PROOF_20260822.json`.

La degradación de rendimiento del GDB Stub ha quedado demostrada físicamente.
Con GDB apagado el usuario observó una mejora clara; al reactivarlo sin ningún
cliente RoleRun, la lentitud regresó. El source exacto `e2143d43...` muestra la
causa: el debugger activa el modo global de depuración de ARMeilleure, sustituye
el dispatch rápido por ejecución bloque a bloque con PC preciso y separa la
caché PTC por `DebuggerMode`. El primer arranque sufrió además recompilación y
crecimiento JIT, por eso fue peor que el segundo. GDB queda rechazado como
transporte permanente y se conservará solo para diagnósticos puntuales.

Una comparación read-only simultánea demostró la alternativa HostMapped:
la vista Windows y GDB devolvieron exactamente los mismos 64 bytes de `main` y
los mismos 344 bytes de un PB8 mediante un único delta de sesión. La prueba
decisiva posterior reinició Ryujinx, mantuvo GDB apagado y redescubrió un mapa
de sesión distinto sin reutilizar ninguna dirección anfitriona. La huella fue
única; la cadena produjo 40 cajas, 1.200 slots, 11 PB8 ocupados y 1.189 vacíos,
todos con checksum correcto. El componente de producción repitió la lectura en
1,543 s después de verificar Title ID y revisión en el título activo de Ryujinx,
y solo abrió `PROCESS_QUERY_INFORMATION | PROCESS_VM_READ`.
Evidencia:
`diagnostics/manual/bdsp_sp130_gdb_performance_ab_20260822.json` y
`diagnostics/manual/bdsp_sp130_hostmapped_bridge_proof_20260822.json`, más
`diagnostics/manual/bdsp_sp130_hostmapped_no_gdb_PROOF_20260822.json`.

La captura física de HP sobre la colección de seis PB8 de `SaveData` terminó
con resultado negativo: pese al daño físico, el journal conservó solo el
baseline y ninguno de los seis HP cambió. Esa colección no se acepta como
autoridad HP live ni se incorpora al reader. Evidencia y SHA se registran en
`docs/BDSP_REALTIME_BASELINE.md`.

La primera divergencia quedó resuelta mediante el código IL2CPP exacto de
OpenDPR y dos capturas HostMapped acotadas. `SaveData.playerParty` es una copia
serializada; la party viva fuera de combate es el campo no serializado
`PlayerWork._playerParty`. Durante el combate tampoco es autoridad inmediata:
`BTL_PARTY` publicó `58/67` para el primer miembro mientras la party normal aún
publicaba `67/67`. Al huir, la party normal convergió a `58/67` y 608 ms después
desapareció el objeto de batalla.

La captura física posterior sí demostró KO y cambio forzado. `BTL_PARTY`
publicó Skitty `7/21→0/21` mientras `PlayerWork` permanecía en `21/21`. Tras
elegir a Shuppet, las filas se intercambiaron: Shuppet quedó en fila 1 con
`party_index=1` y Skitty en fila 2 con `party_index=0`. La party normal no
convergió a `0/21` hasta 23.096 ms después del KO y `BattleProc` desapareció
701 ms más tarde. Por tanto, el adapter aplica HP por `PokeID/party_index` y
exige coincidencia de especie, nivel y HP máximo antes de publicar la muestra;
nunca usa el número de fila como slot. La instrumentación candidata de miembro
activo no se promueve a producción porque no es necesaria para esta función.
Evidencia:
`diagnostics/manual/bdsp_sp130_runtime_party_graph_PROOF_20260822.json`,
`diagnostics/manual/bdsp_sp130_battle_to_party_convergence_AUTO_20260822_163121.jsonl`
(SHA-256 `46AE0D518B7FF0D474D96E57F71BCB7D49D52D5C6D984E4F797FFB46B4AF16C7`)
y `diagnostics/manual/bdsp_sp130_battle_lane_PROOF_20260822.json`, más
`diagnostics/manual/bdsp_sp130_ko_switch_PROOF_20260822.json` y su traza fuente
(SHA-256 `565B0335AEED1B1174E5FF6011040BB69FE2F1774A1A554A7483474A1435C617`).

El reader y el mapeo están validados físicamente. La primera prueba de la
integración alpha.66 no registró el KO ni al terminar el combate. La captura
independiente posterior leyó, desde el mismo Ryujinx aún abierto, la party
completa y al primer miembro a `0/58`; por tanto, las direcciones y el parser no
eran la frontera que falló.

La introspección de solo lectura del proceso RoleRun demostró la primera
divergencia: `_oras_live_active` seguía a `true`, pero no existían timer,
snapshot ni baseline de salud. El watcher del `main` había cargado la copia del
save y `_clear_oras_live_reconciliation()` había cancelado el monitor y
reiniciado el Core. `_reload_from_watched_save()` solo lo rearmaba para la clave
exacta `oras`, así que BDSP quedaba conectado solo nominalmente y no volvía a
leer RAM. No llegó ninguna muestra a LivePartyWatch ni al compromiso de muerte.

Alpha.67 rearma el monitor para todos y solo los backends declarados en
`REALTIME_READ_GAME_KEYS` y añade una traza integrada acotada de snapshots y
fronteras UI. No cambia offsets, parsers, mapeos de batalla ni escritores; BDSP
continúa en solo lectura. La evidencia causal se conserva en
`diagnostics/manual/bdsp_alpha66_save_watcher_monitor_stopped_PROOF_20260822.json`.
La corrección queda físicamente validada por el usuario el 2026-08-22: hubo
cuatro recargas del watcher antes del combate, el monitor siguió activo, se
observó una única transición `12→0`, se restó exactamente una vida, se retiró
el icono y el selector apareció correctamente tras el combate. La traza se
conserva en
`diagnostics/manual/bdsp_alpha67_save_watcher_ko_SUCCESS_20260822_174841.jsonl`
con SHA-256
`F90025A11E43FEE750B2DA399F666B56EFCFD55A7FDC4A8F7AC7FED5C8934487`.

La misma validación reveló una frontera visual: RoleRun cobró la muerte al
inicio del turno, antes de que la pantalla mostrara el golpe/KO. La traza prueba
que el compromiso coincidió con el HP lógico
`BTL_POKEPARAM.CORE_PARAM.hp=0`; no contiene todavía el estado de la barra
visible, por lo que no se aplica un retardo supuesto.

Alpha.68 añadió una lane diagnóstica de presentación. El source exacto y los
metadatos IL2CPP vivos demuestran que `BattleViewUISystem._statusWindows`
mantiene por separado HP mostrado, PokeID, `needHpApply` y
`HpBar.IsAnimation`. El TypeInfo nominal `main+0x04E70E40`, sus cuatro
ventanas y cada FieldInfo se validan antes de publicar la muestra.

La prueba letal de alpha.68 demuestra la primera divergencia visual. Para el
mismo Shuppet/PokeID, el HP lógico de batalla pasó `12→0` en la secuencia 586
(`1787415029.213`) y RoleRun comprometió la muerte 12 ms después, mientras la
ventana jugador seguía mostrando `12/58`. El objetivo visible `0` con
`HpBar.IsAnimation=true` no apareció hasta la secuencia 609
(`1787415035.380`), 6,167 s después; la barra terminó a `0/58` en la secuencia
611 (`1787415035.903`). La primera divergencia estaba, por tanto, en el adapter:
publicaba el cero de resolución lógica como `health_game` antes de que la lane
visible del mismo Pokémon hubiera presentado el KO.

Alpha.69 corrige solo esa frontera BDSP. Cuando el HP lógico cae a cero, el
adapter conserva el último HP positivo hasta observar en una ventana jugador
única, con PokeID y HP máximo coincidentes, la secuencia `0 + animación activa`
seguida de `0 + animación terminada`. No usa retardos fijos. Si falta o resulta
ambigua la presentación, no cobra anticipadamente; la convergencia posterior de
`PlayerWork` mantiene una salida segura. Un HP cero inicial continúa siendo
baseline y no genera una muerte retrospectiva. Evidencia fuente:
`diagnostics/manual/bdsp_alpha68_visible_hp_timing_FAIL_20260822.jsonl`
(SHA-256
`C9211DF2C2C341B50C30852F7670FA7381D39E857B97297C80B4BAB7F922A72F`) y
prueba causal:
`diagnostics/manual/bdsp_alpha68_visible_hp_timing_ROOT_20260822.json`.

El usuario validó físicamente alpha.69 el 2026-08-22 en Perla Reluciente 1.3.0
sobre Ryujinx 1.3.3, con GDB desactivado: el timing fue correcto y el selector
postcombate siguió funcionando. La traza confirma de extremo a extremo la
observación. En la secuencia 467 el HP lógico ya era 0, pero la ventana seguía
visible a 6/58 y el adapter publicó 6. En 498–499 la ventana visible mostró 0
con animación activa y el adapter continuó publicando 6. En la secuencia 500,
con 0 visible y animación terminada, publicó el primer cero; inmediatamente
después aparecen una sola `health-transition` y un solo `faint-registered`.
La función queda cerrada para combate salvaje simple dentro de esta combinación;
dobles y encuentros especiales no se infieren de esta prueba. Control:
`diagnostics/manual/bdsp_alpha69_visible_ko_sync_SUCCESS_20260822.jsonl`,
SHA-256
`855B56E05D904B0762D946C139DF871624DCD1A607A4CD9C957A90A7A1D2C151`.

La reordenación juego→RoleRun también queda validada físicamente en la misma
combinación. El usuario intercambió los dos primeros Pokémon y confirmó que
RoleRun mantuvo correctamente identidad, icono y rol. La traza demuestra la
parte estructural: las secuencias 886–893 cambiaron el orden de especies
`353,391,339,17,303,359` a `391,353,339,17,303,359` y después registraron la
vuelta al orden original, sin cambiar composición. La conservación visual del
icono y rol procede de la observación física del usuario, no se infiere del
journal. Control:
`diagnostics/manual/bdsp_alpha69_party_reorder_SUCCESS_20260822.jsonl`,
SHA-256
`D037D876FDBB464D2D1F444A54C202647F4119DBAA12E6A09B7CB006DEAD5672`.
Los cambios de conteo y composición party↔PC siguen pendientes.

Alpha.70 conecta al reconciliador común la cadena de cajas ya demostrada, sin
añadir offsets ni habilitar escrituras. `BDSPRealTimeAdapter.read_pc()` exige
40×30, doble lectura, longitud PB8, checksum y posiciones completas. Publica
forma, apodo, objeto, habilidad, movimientos, huevo y marcas de rol desde el
PB8 almacenado. El nivel solo se conserva si una ancla de save/party coincide
de forma única por especie, PID, TID y SID; no se calcula mediante una curva
supuesta. Party y PC se contrastan antes de publicar: si una identidad aparece
en ambas capturas asíncronas, la UI conserva la vista anterior y relee.

La ruta integrada se ejecutó sobre el Ryujinx físico abierto y leyó los 1.200
slots, 11 ocupados, en 1,459 s con `writes_enabled=false`. La traza alpha.70
registra posiciones/especies y una huella no reversible de identidad, además de
las fronteras de reconciliación, sin guardar PID/TID/SID crudos. Evidencia:
`diagnostics/manual/bdsp_alpha70_pc_read_probe_PROOF_20260822.json`.

La primera prueba física equipo→PC de alpha.70 **no valida la integración**.
RoleRun vio en la party los depósitos `6→5` y `5→4` y el reader PC demostró
11→12→13 ocupados, pero la caja no se actualizó hasta salir y volver a la
pestaña; entonces ambos depositados aparecieron como `Nv. 0`. Las conciliaciones
tardías recibieron `before/after=5/5` y `4/4`, por lo que ya no contenían la
ancla saliente que conserva el nivel. La primera divergencia de código era la
rama BDSP del monitor: a diferencia de los flujos ya funcionales, retornaba tras
publicar `party_changed` sin programar la lectura PC con los estados anterior y
nuevo. Evidencia preservada:
`diagnostics/manual/bdsp_alpha70_pc_refresh_level_FAIL_20260822.jsonl`, SHA-256
`ABA76FE8028E969A6AA6B9E4854AE86265AAF805BE5B58DC88786DB82235E33B`.

Alpha.71 corrige esa frontera sin modificar readers ni writers: publica la
party nueva y programa inmediatamente la conciliación usando el par real
anterior→nuevo. Así el saliente conserva nivel/rol por identidad fuerte y la
vista PC se repinta al finalizar la lectura, sin navegar. La regresión causal
reproduce un depósito `2→1` y exige que el worker reciba ambos snapshots y el
nivel 12 del saliente.

El usuario validó físicamente alpha.71 el 2026-08-22 en Perla Reluciente 1.3.0
sobre Ryujinx 1.3.3, con GDB desactivado. Los depósitos se reflejaron en CAJAS
PC sin cambiar de pestaña y con sus datos correctos; las recuperaciones también
se reflejaron correctamente en el equipo. La traza confirma seis transiciones
directas con snapshots anterior→nuevo (`4→3`, `3→4`, `4→5`, `5→4`, `4→5` y
`5→6`), cada una seguida por lectura y conciliación PC. La función queda cerrada
para cambios de composición realizados dentro del juego en esta combinación.
No valida todavía PC↔PC sin cambio de party ni ninguna escritura iniciada desde
RoleRun. Control:
`diagnostics/manual/bdsp_alpha71_pc_roundtrip_SUCCESS_20260822_190522.jsonl`,
SHA-256
`7662BD363815B8EF273008AB4CC69E48500549175F11AECB76E0FAA60AF4AC71`.

Alpha.72 implementa el caso PC↔PC sin inventar un evento de party. El análisis
estático demuestra que alpha.71 solo solicitaba la matriz al entrar en CAJAS PC
o ante `PARTY_CHANGED`; mover entre cajas no atraviesa ninguna de esas fronteras.
BDSP reutiliza ahora el reader 40×30 demostrado mediante un único sondeo cada
2,5 s, exclusivamente mientras la página está visible. Cada lectura programa la
siguiente al terminar, se pospone si otra conciliación está activa y se cancela
al salir/minimizar/cambiar de Run o ante error. Una proyección idéntica no repinta
la UI. Las escrituras continúan cerradas.

El usuario validó físicamente alpha.72 el 2026-08-22 en Perla Reluciente 1.3.0
sobre Ryujinx 1.3.3, con GDB desactivado. Sin cambiar la party de seis miembros,
Aipom (`species 190`) se movió de caja 1/slot 2 a caja 2/slot 2. El primer poll
posterior produjo exactamente `changed=true`, `override_slots=1` y
`emptied_slots=1`; los siete polls siguientes publicaron `changed=false`. El
usuario confirmó origen/destino correctos y ausencia de parpadeo. El seguimiento
PC↔PC realizado dentro del juego queda cerrado para esta combinación. Control:
`diagnostics/manual/bdsp_alpha72_pc_to_pc_poll_SUCCESS_20260822_191534.jsonl`,
SHA-256
`1A399AA247275C9A33085327628076D0FD8B64BEBE2107E81370223198101FDD`.

Alpha.73 incorpora la mochila/MT viva sin autorizar escrituras. La cadena
`[[[[main+4E7BE98]+B8]+10]+48]+20` no se aceptó solo por estar publicada:
PKHeX-Plugins `c8e23a43...` la liga explícitamente a SP 1.3.0; OpenDPR
`5b0cb0c8...` demuestra `PlayerWork.SaveData.saveItem`, el layout `SaveItem` y
`ItemSaveSize=3000`; PKHeX `26.07.07` demuestra que el ID es el índice y cómo se
interpretan cantidad y orden. En la partida real, el array declaró 3.000
registros y dos lecturas de sus 36.000 bytes fueron idénticas. Los 51 IDs
positivos coincidieron con el save; el único valor diferente fue Antiparalizador (#22),
10 en el último guardado y 9 en RAM, una divergencia positiva que demuestra que
la lane observa consumo posterior al guardado. Las siete MT poseídas coincidieron
exactamente en ID y cantidad.

`BDSPInventoryReader` valida raíz, longitud, estabilidad, cantidad, flags,
padding y orden antes de publicar. El selector realiza esta lectura en segundo
plano y nunca consulta RAM durante el render pasivo. El save se usa únicamente
como testigo diagnóstico: no sustituye una lectura live diferente. Las MT que
ya están en cambios pendientes se descuentan de la proyección. La tabla
MT→movimiento continúa viniendo del `personal_masterdatas` efectivo, cuya copia
actual tiene SHA-256
`BDA0D7F9E7B8F0472E15F5B78AF4524CAFB5D677FFC0AA7A6D499129D784248B`.
La lectura está automatizada y contrastada en el proceso real, pero la función
queda **pendiente de validación física del usuario** hasta observar dentro del
juego una cantidad y su cambio al consumir una MT sin guardar. Enseñar desde
RoleRun sigue siendo una operación sobre save pendiente de `GUARDAR CAMBIOS`;
no existe writer RAM BDSP. Evidencia:
`diagnostics/manual/bdsp_sp130_inventory_live_save_PROOF_20260822.json`.

Dobles, compañeros, multijugador y encuentros especiales conservan alcance
pendiente.

El parser PB8 se contrastó además con el mismo `PKHeX.Core 26.7.7` usado por
el motor de RoleRun y con los seis miembros reales: coincidieron identidad,
forma, apodo, objeto, habilidad, movimientos, huevo y marcas en los seis casos.
La evidencia anonimizada queda en
`diagnostics/manual/bdsp_sp130_runtime_pb8_fields_PROOF_20260822.json`.

Verificación alpha.73: reader/Adapter/UI BDSP **57 passed** en 0,74 s; bloque
afectado más consumidores Gen7 **112 passed** en 2,16 s. Suite completa:
**519 passed** en 21,12 s con `py -3.14 -m pytest -q` dentro del entorno de
tests aislado.

Alpha.74 corrige tres fronteras de preparación BDSP sin abrir escrituras RAM.
`SUSTITUIR` había quedado deshabilitado porque la tarjeta trataba como ausencia
de MT el `None` deliberado de la carga diferida alpha.73; ahora el enlace live
habilita la acción y el clic valida la mochila en background. `ELIMINAR ATAQUE`
sí generaba y compactaba el cambio, pero cada snapshot físico reemplazaba la
previsualización; ahora las ediciones pendientes se reaplican únicamente a la
copia visual fresca.

La lectura física de la party activa demostró además que `SP-Timper` todavía usa
el layout histórico: `Farigiraf=100000`, `Luto=010000`, `Diego=000001`,
`Shupete=000010` y `pezkeño=000100`. Esos bits corresponden semánticamente a
Líbero, Tanque, Prisma, Support y Mago bajo layout 1, pero no al orden canónico
círculo=Líbero, triángulo=Asesino, cuadrado=Mago, corazón=Tanque,
estrella=Prisma y rombo=Support. La migración BDSP se prepara ahora como lote
sobre el guardado y exige readback de todos los bits con layout 2 antes de
cambiar el contrato persistido. El binario empaquetado se comprobó sobre una
salida temporal: Shupete/Support pasó de `000010` a `000001` y el readback nuevo
devolvió Support. La partida activa no se tocó en esa comprobación.

Las sustituciones 1↔1 preparadas desde RoleRun heredan siempre la marca del
Pokémon saliente, incluido BDSP. Un intercambio realizado directamente dentro
del juego se sigue observando en solo lectura y no normaliza su marcador: esa
variante requiere demostrar antes un writer PB8 runtime con precondiciones,
readback y rollback.

La frase anterior describe el límite histórico de alpha.74. Alpha.75 demostró
el writer PB8 de marcadores de party y alpha.76 lo conecta a los intercambios
1↔1 observados dentro del PC: la herencia se escribe y verifica antes de publicar
la nueva composición. Sigue sin existir un writer de cajas ni fallback al save.

Validación física parcial de alpha.74, comunicada por el usuario el 2026-08-22:
`SUSTITUIR` se habilita y abre correctamente el selector, y
`ELIMINAR ATAQUE` conserva la eliminación, compacta los movimientos restantes y
deja disponible el hueco final esperado dentro de RoleRun. Esta observación
cierra la corrección visual y de interacción.

En la prueba física inmediatamente posterior, el usuario consumió una MT dentro
del juego y reabrió `SUSTITUIR`; RoleRun mostró satisfactoriamente la cantidad
reducida. Esto valida para la combinación probada la cadena
`saveItem RAM viva → BDSPInventoryReader → Adapter → carga background → selector`
y demuestra que no se estaba mostrando la cantidad stale del último guardado.
No se conserva una afirmación sobre qué MT concreta ni sus cifras porque la
observación del usuario no las especificó y el journal actual no registra las
cantidades individuales. Permanecen pendientes la escritura por save, el
movimiento/PP resultante, la herencia física del marcador y la migración efectiva
tras reiniciar.

Verificación automatizada: **523 passed** en 20,96 s con
`py -3.14 -m pytest -q`.

Alpha.75 sustituye el flujo diferido de movimientos BDSP por una transacción
runtime y elimina de su cabecera `DESCARTAR`/`GUARDAR CAMBIOS`. La estructura no
se ha supuesto: OpenDPR `5b0cb0c8...` demuestra que `PokemonParam` mantiene un
core almacenado de 328 bytes y 16 bytes calculados, que `CoreParam.SetWaza`
asigna el ID, reinicia PP Ups y usa `WazaTable.basePP`, y que
`PlayerWork.SaveData.saveItem` contiene los registros runtime de 12 bytes cuya
cantidad gobierna `PlayerWork.GetItem/SetItem`. Los lectores SP 1.3.0 ya
validados aportan la ruta exacta y las unidades mutables; no se añade ninguna
dirección nueva.

`BDSPLiveWriter` exige ausencia de batalla, dos capturas completas iguales,
identidad fuerte única, movimiento y cantidad esperados, punteros estables,
huella de sesión y coincidencia de bytes guest/host. Recalcula checksum y cifrado
PB8, escribe primero el core del Pokémon y después solo el `SaveItem` de la MT.
Verifica readback host, readback guest y una nueva lectura semántica de party y
mochila. Si falla cualquier paso, restaura en orden inverso todas las unidades
intentadas y vuelve a comprobarlas.

La UI aplica automáticamente cambios de rol, sustitución/eliminación de
movimientos y enseñanza de MT. Equipo↔PC, roles de caja, progreso y utilidades
de inventario siguen bloqueados y nunca caen al save. La implementación y sus
regresiones están completas, pero movimiento/PP/consumo permanecen
**pendientes de validación física en Ryujinx**; no se declaran cerrados hasta la
prueba manual indicada para alpha.75.

Verificación alpha.75: suite completa **533 passed** en 21,12 s con
`py -3.14 -m pytest -q`. El perfil Unity efectivo contiene 100 MT y los 512
movimientos activos disponen de PP base válidos. No se ejecutó una escritura
contra la partida real durante el desarrollo automatizado.

Verificación alpha.76: reader/writer/UI BDSP **65 passed** en 0,70 s; bloque
BDSP más consumidores del grid de roles **75 passed** en 1,36 s; suite completa
**542 passed** en 21,12 s con `py -3.14 -m pytest -q`. Una sonda posterior de
solo lectura contra el Ryujinx aún abierto devolvió `battle=None` a partir del
`TypeInfo=nullptr`; no se escribió ningún byte durante la investigación. La
enseñanza real de MT y la herencia del intercambio quedaron validadas
físicamente por el usuario el 2026-08-22 al responder que la prueba combinada
indicada funcionaba. El alcance registrado es: sustitución por MT fuera de
combate y cambio 1↔1 dentro del PC del juego sin séptima tarjeta y con el rol
heredado. No se extiende esa confirmación a escritores de cajas, utilidades,
progreso ni gasto posterior de PP, que no formaban parte de esa prueba.

Alpha.77 incorpora el progreso BDSP sin inferirlo del combate. OpenDPR
`5b0cb0c8...` demuestra que el propio juego calcula `BadgeCount` sumando los
ocho `PlayerWork.SaveData.systemFlags` 124–131; PKHeX 26.07.07 usa exactamente
los mismos flags. En el Ryujinx físico SP 1.3.0, el campo `PlayerWork+0x30`
resolvió dos veces el mismo `bool[1000]`, todos sus elementos fueron 0/1 y los
ocho testigos devolvieron `[1,1,0,0,0,0,0,0]`. El total 2 coincide con el save
y con su contador redundante `MYSTATUS.badge=2`.

`BDSPBadgeReader` publica ese valor como lane opcional, con doble lectura y
rechazo de raíz, longitud o contenido inválidos. El save no actúa como fallback.
La rama UI BDSP procesa el progreso antes de cualquier retorno por batalla,
party o herencia de rol y MEDALLAS queda gobernado automáticamente por RAM. Una
sonda integrada del adapter físico devolvió seis miembros, `badges=2`, fuente
`SystemFlags vivos · PlayerWork.SaveData` y diagnóstico OK. Evidencia:
`diagnostics/manual/bdsp_alpha77_badge_system_flags_PROOF_20260822.json`.
El usuario validó físicamente el 2026-08-22 la sincronización inicial: al abrir
alpha.77, RoleRun recuperó correctamente las dos medallas ya existentes. El
alcance exacto demostrado es la lectura integrada y el compromiso inicial 0→2;
la transición de una nueva medalla 2→3, su compromiso único y OBS siguen
pendientes de validación física.
Verificación alpha.77: **107 passed** en el bloque reader/Adapter/UI/Core y
**552 passed** en 21,06 s en la suite completa.

## Estado vigente de alpha.78

Alpha.78 abre únicamente el intercambio 1↔1 Equipo ↔ PC iniciado desde
RoleRun. La unidad se apoya en el contrato fuente de BDSP
`PokemonParam.DATASIZE=344`, `SerializedPokemonFull` y
`PokemonParam.CopyFrom()`, y en el grafo físico ya demostrado: la caja guarda
un PB8 completo de 344 bytes y la party lo divide en core de 328 y calc de 16.

El writer captura dos veces party y las 40×30 cajas, comprueba coordenadas e
identidades especie/PID/TID/SID, bloquea combate y reconexiones y vuelve a
validar la huella de Ryujinx inmediatamente antes de abrir escritura. Intercambia
party core, party calc y PB8 de caja con readback host/guest; después verifica
las dos identidades y el rol heredado. Cualquier fallo restaura y relee las tres
regiones. Añadir o retirar miembros sigue cerrado porque tamaño, compactación y
vacío runtime son contratos distintos aún no demostrados.

Estado: **IMPLEMENTADO Y CUBIERTO POR REGRESIONES; PENDIENTE DE VALIDACIÓN
FÍSICA EN SP 1.3.0 / RYUJINX**. Verificación: **60 passed** en el bloque BDSP
dirigido y **555 passed** en 21,15 s en la suite completa.

## Estado vigente de alpha.79

La primera prueba física de alpha.78 no alcanzó el writer. La RAM viva demostró
Slowpoke en la party y Pidgeotto en Caja 1:1, mientras el save sin actualizar
conservaba Pidgeotto en party y Slowpoke en Caja 1:1. El selector contextual
mostró Slowpoke porque `open_pc_selector()` consumía `_read_pc_data()` antes de
solicitar la matriz viva. Reader y adapter entregaban el valor correcto; la
primera divergencia estaba en la composición UI del modal.

Alpha.79 difiere la apertura del selector hasta terminar `read_pc()` en segundo
plano. La ocupación y coordenadas proceden exclusivamente de RAM; el save solo
puede enriquecer nombre/nivel por identidad fuerte. Un error ya no cae a la
copia antigua: bloquea la ventana con diagnóstico visible. El writer alpha.78
no cambia y continúa pendiente de su primera validación física real. Verificación
alpha.79: **62 passed** en el bloque BDSP dirigido y **557 passed** en 21,55 s
en la suite completa.

## Estado vigente de alpha.80

La validación física de alpha.79 reprodujo exactamente el mismo Slowpoke stale.
La corrección anterior había cubierto un selector vecino, no el botón probado:
las tarjetas de Equipo abren `_open_team_to_pc_swap_picker()`, cuyo título y
cabecera coinciden con la captura del usuario y que aún ejecutaba
`_read_pc_data(force=True)`. La traza no registró carga PC ni writer, confirmando
que el flujo live de alpha.79 nunca se ejecutó.

Alpha.80 conecta ese punto de entrada exacto al cargador de matriz viva antes de
construir cualquier tarjeta. Se añadieron eventos automáticos
`pc-selector-live-start`, `pc-selector-live-ready` y
`pc-selector-live-error`, además de una regresión que falla si el botón real
vuelve a consultar primero el save. El usuario validó físicamente esta frontera:
el modal mostró Pidgeotto, que era el ocupante RAM de Caja 1:1, en vez del
Slowpoke stale del save. Al confirmar, no obstante, Ryujinx mantuvo Slowpoke en
la party y la traza no registró ningún intento de escritura. Verificación
alpha.80: **63 passed** en el bloque BDSP dirigido y **558 passed** en 21,62 s
en la suite completa.

## Estado vigente de alpha.84

El selector de bajas común ya producía una operación completa con las dos
identidades fuertes, el slot vivo, el origen PC y un hueco de Cementerio. La
primera divergencia exclusiva de BDSP estaba inmediatamente después: la
compuerta UI no enviaba `replace-fainted` y el dispatch del writer la rechazaba.
No faltaba información que debiera aportar el usuario ni se necesitaba una
dirección RAM nueva.

Alpha.84 compone los contratos físicamente demostrados en alpha.81–83. Vacía el
origen PC con el PB8 canónico, conserva los 344 bytes exactos del debilitado en
Caja 4 y escribe al sustituto en el mismo objeto fijo core(328)+calc(16). El
conteo y el resto de la party no cambian. El rol heredado procede del debilitado
releído en RAM, no de una premisa de UI.

Antes de escribir exige dos capturas completas idénticas de party y cajas,
identidades/posiciones, HP=0 actual, rol único, Cementerio vacío, huella de
sesión y precondiciones guest/host. Después verifica semántica y bytes en los
seis slots de party y las 1.200 cajas. Un fallo restaura en orden inverso los
cuatro bloques y confirma host y guest. Las regresiones cubren éxito, fallo en
el cuarto write, miembro revivido y compuerta automática de UI.

Verificación: **121 passed** en el bloque BDSP y **572 passed** en 22,17 s en
la suite completa. Validación física posterior del usuario en SP 1.3.0 /
Ryujinx: el selector apareció tras el combate, el sustituto entró correctamente,
el debilitado pasó a la Caja 4 y se descontó exactamente una vida. Estado:
**implementado, probado automáticamente y validado físicamente para un KO
simple**. No se amplía esta validación a OBS, al marcador visto dentro del juego
ni a otros tipos de combate, que conservan comprobaciones propias.

Una segunda prueba física cubrió dos KO dentro del mismo combate. RoleRun
descontó exactamente dos vidas, mostró ambos selectores consecutivamente sin
necesidad de minimizar, incorporó los dos sustitutos y conservó los dos
debilitados en la Caja 4. Esto valida la cola múltiple de sustituciones y el
compromiso exactamente una vez para ese escenario. No demuestra reconexión,
OBS ni historial visual.

La inspección posterior de los marcadores dentro del juego confirmó que el
sustituto conserva exactamente el marcador correspondiente al rol mostrado en
RoleRun. La herencia de rol de `replace-fainted` queda así validada de extremo a
extremo. Esta evidencia no se extrapola a otros botones o flujos manuales de
cambio de rol.

## Estado vigente de alpha.83

La limitación restante de PC era retirar un miembro intermedio. OpenDPR
`5b0cb0c8...` demuestra que `PokeParty` dispone de `RemoveMember()` y una rutina
privada `scootOver()`, pero no conserva sus cuerpos; por tanto no demostraba qué
bytes, arrays u objetos debían mutar.

La captura física de solo lectura del 2026-08-22 retiró el slot 2 de una party
de seis. El objeto `PokeParty`, su array, los seis `PokemonParam` y todas las
direcciones core/calc permanecieron estables. Los PB8 completos coincidieron
byte a byte en la cadena 3→2, 4→3, 5→4 y 6→5; el antiguo slot 2 apareció exacto
en Caja 1:3; el vacío PC canónico apareció exacto en el slot 6; y
`m_memberCount` pasó 6→5. Solo cambió esa posición de caja. Evidencia:
`diagnostics/manual/bdsp_sp130_party_size_transition_AUTO_20260822_224902.json`,
SHA-256 `B65F6B7812314955CD090DB2AA6B68748402DDF17D4ADEA858D2A896254AEFCE`.

Alpha.83 reproduce exactamente ese flujo sobre los objetos fijos. La operación
completa queda cerrada por doble captura, correspondencia miembro/almacenamiento,
testigos guest/host, contador en último lugar, readback de los seis PB8 y de las
1.200 cajas, y rollback inverso verificado. Una regresión reproduce los doce
bloques del caso físico y otra provoca el fallo final para comprobar que party,
PC y contador vuelven íntegros.

Verificación: **117 passed** en el bloque BDSP y **568 passed** en 21,62 s en
la suite completa. Validación física posterior del usuario en SP 1.3.0 /
Ryujinx: la retirada intermedia iniciada desde RoleRun se reflejó correctamente
en el juego y en la aplicación. Estado: **causa y contrato demostrados; writer
probado automáticamente y validado físicamente**.

## Estado vigente de alpha.82

El bloqueo de cambios de tamaño exigía demostrar la representación runtime real.
La captura 6→5 del 2026-08-22 muestra que el `PokeParty`, su array y sus seis
direcciones de almacenamiento permanecen estables: Pidgeotto desaparece solo
del sexto objeto, ese objeto recibe el PB8 vacío canónico, Caja 1:3 recibe los
mismos 344 bytes y `m_memberCount` cambia 6→5. La captura inversa 5→6 reutiliza
exactamente las mismas direcciones y revierte esos tres contenidos y el contador.
Los cinco miembros restantes y los otros 1.199 slots de caja no cambian.

La evidencia queda preservada en
`diagnostics/manual/bdsp_sp130_party_size_transition_AUTO_20260822_222122.json`
(SHA-256 `718373E0D7061BECBB804EB1DC84E3CF765D830DD258BD47DA03BEB4F070F248`)
y `diagnostics/manual/bdsp_sp130_party_size_transition_AUTO_20260822_222322.json`
(SHA-256 `C2AEF1C40D2D4A8C3F8BE94FCABC13A5B79EEC89A82F3B1D6DA5380B58BF0BFE`).

Alpha.82 implementa únicamente ese contrato demostrado: enviar el último miembro
al primer vacío PC vivo y recuperar un miembro como nuevo último slot. El writer
revalida party/cajas completas, identidad, direcciones, vacío canónico y sesión;
escribe las unidades mínimas y el contador al final; hace readback guest/host y
semántico; protege los miembros y 1.199 slots vecinos; y revierte los cuatro
bloques con verificación si algo falla. Retirar un miembro intermedio sigue
bloqueado porque el algoritmo de compactación no está demostrado.

Las regresiones cubren éxito 6→5, éxito 5→6 con primer rol libre, rollback al
fallar el contador y rechazo previo de un miembro no final. Verificación:
**116 passed** en el bloque BDSP dirigido y **567 passed** en 21,00 s en la
suite completa. En ese corte quedó implementado y probado automáticamente; las
dos capturas probaban el comportamiento nativo, pero aún no sustituían la prueba
del writer alpha.82 que se completó después.

El usuario validó después el writer alpha.82 desde RoleRun en SP 1.3.0 /
Ryujinx: enviar el sexto miembro al PC y recuperarlo como sexto miembro produjo
el resultado correcto tanto en RoleRun como dentro del juego. El ciclo de cola
5↔6 queda **VALIDADO FÍSICAMENTE**. No demuestra la compactación al retirar un
miembro intermedio, que permanece bloqueada.

## Estado vigente de alpha.81

La primera divergencia del fallo de confirmación estaba en la compuerta común
de aplicación inmediata, antes del writer. `_prepare_pc_team_change()` creaba el
swap 1↔1, pero la rama BDSP de `_request_oras_live_auto_apply()` solo seleccionaba
roles, movimientos y MT; descartaba el `PendingTeamChange` y por eso no podía
existir ningún evento de escritura. La capa posterior y `BDSPLiveWriter` ya
declaraban y probaban ese mismo `swap-party-box`, lo que demuestra que no faltaba
una dirección ni una operación RAM nueva.

Alpha.81 abre la compuerta exclusivamente para el swap 1↔1 ya demostrado. Los
cambios de tamaño de party permanecen bloqueados. La regresión falló antes del
arreglo con cero IDs programados y pasa después; el bloque BDSP completo queda en
**64 passed** y la suite completa en **559 passed** en 21,44 s. El writer conserva
sus precondiciones, doble captura, readback semántico y rollback.

El usuario validó físicamente alpha.81 en Perla Reluciente 1.3.0 / Ryujinx el
2026-08-22: tras elegir Pidgeotto desde `CAMBIAR CON PC`, el intercambio se
reflejó correctamente dentro del juego. Queda cerrado el recorrido base
RoleRun → selector PC live → writer 1↔1 → readback → party publicada para
esta combinación. Esta validación no se extiende a entradas/salidas que cambian
el tamaño de la party, que continúan bloqueadas.

## Estado vigente de alpha.65

El usuario derrotó físicamente a Kaudan/Hala con alpha.63 abierta. UltraSol
entregó Lizastal Z, pero RoleRun mantuvo `medallas=0`. La lectura RPC posterior
demuestra un bolsillo Z-Crystals estable y válido con Normastal Z `807` y
Lizastal Z `813`; el contador puro devuelve 1. El `main` todavía contiene solo
`807` y devuelve 0.

La primera divergencia está en `USUMLiveWriter.read_kahuna_badges_for_game()`.
La ruta ItemsOffset demostraba la mochila y publicaba su prueba en
`_tm_guest_inventory_anchor`, pero el siguiente bloque consultaba por error
`_utility_block_cache["items"]`, reservada a utilidades de escritura. Al estar
vacía, se descartaba el 1 live y se devolvía el 0 del save antes de Adapter/UI.

Alpha.65 consume la ancla correcta tras demostrarla y la relee de forma estable
en ticks posteriores. Una sonda integrada de solo lectura sobre el proceso
físico actual devolvió 1 dos veces con procedencia
`Z-Crystals vivos · referencia ItemsOffset revalidada`. No se añadió ninguna
dirección ni escritura.

El usuario validó físicamente alpha.65 en UltraSol/Azahar el 2026-08-22: al
abrir la versión corregida con Lizastal Z ya presente en la mochila viva,
RoleRun detectó la medalla y mostró el incremento 0→1. Queda así cerrada la
recuperación del primer Kahuna para esta combinación. Sigue pendiente comprobar
los incrementos sucesivos 1→2, 2→3 y 3→4 al derrotar a los demás Kahunas.

La evidencia canónica está en
`diagnostics/manual/usum_alpha63_hala_badge_missing_FAIL_20260822_133454_*`.

Baseline alpha.65: **67 passed** en las fronteras progreso/adapter/Core y
**448 passed** en 20,37 s para la suite completa con `python -m pytest -q`.
La sonda física fue exclusivamente de lectura; no se escribió RAM ni el save.

## Historial de alpha.64

Alpha.63 quedó físicamente validada por el usuario: dos KO se registraron y los
dos selectores se abrieron consecutivamente sin minimizar RoleRun. La detección
de muertes, la salida por convergencia y la cola de sustituciones quedan cerradas
para esa reproducción de UltraSol/Azahar. No se cambió después su lógica RAM.

La auditoría transversal de alpha.64 está detallada en
`docs/3DS_BACKEND_AUDIT.md`. Ha corregido tres primeras divergencias demostradas:

- el consumidor común podía aceptar que un fallback del `main` redujera un
  contador de progreso live más nuevo;
- los writers de utilidades SM/USUM podían omitir de la transacción el write
  cuyo readback fallaba y afirmar una restauración no verificada;
- el parser de cajas USUM derivaba nivel/formas con `personal_sm` pese a que el
  PKHeX distribuido contiene `personal_uu` distinto.

USUM registra ahora automáticamente cada cambio de Kahunas o de procedencia en
`Documentos\RoleRun Manager\Logs\usum_kahuna_progress_trace_latest.jsonl`.
No contiene datos de Pokémon ni de mochila. La lectura del primer Kahuna quedó
validada físicamente en alpha.65; resta validar la progresión sucesiva de los
tres Kahunas restantes.

Baseline alpha.64: batería focal de las fronteras auditadas **123 passed** y
suite completa **446 passed** en 20,46 s con `python -m pytest -q` sobre Windows
en el entorno Python aislado. No se ejecutaron escrituras contra una partida ni
contra la RAM real durante estas pruebas.

## Historial y validación de alpha.63

### Validación física de alpha.62

El usuario validó físicamente en UltraSol que alpha.62 detecta dos KO durante
el combate y termina el episodio cuando ambos convergen a PartyData. La traza
conservada contiene `battle-idle-evidence` para las dos identidades y
`battle-end` con motivo `observed-ko-converged-to-party`. Las dos muertes se
comprometieron inmediatamente y quedaron listas para sustitución.

La evidencia canónica de esa ejecución se conserva con el prefijo
`diagnostics/manual/usum_alpha62_two_pending_second_picker_delayed_PROOF_20260822_131803`.
La traza tiene SHA-256
`0A6B8E37868F5154F957EBEB3B2ADB65F3AB153EEBCCA286EBFB61A888F249B1`;
también se preservaron `config.json`, `history.json` y ambos estados OBS.

### Nuevo fallo de UI demostrado

En la misma ejecución, Porygon y Registeel quedaron como `pending_faints` con
`battle_ended=true`. El primer prompt se persistió a las 13:14:01. Tras cerrarlo,
el segundo no se persistió hasta las 13:14:52, inmediatamente después de
minimizar y restaurar RoleRun.

El código explica exactamente esa diferencia: `close_picker()` destruía el
primer modal sin volver a programar la cola; `_on_main_map()` sí programaba la
revisión. Por eso restaurar la ventana era el disparador accidental. Reader,
snapshot, LivePartyWatch y compromiso de muerte habían completado correctamente
su trabajo antes de esta primera divergencia.

### Corrección alpha.63

- Cerrar un selector vuelve a programar la cola y permite abrir el siguiente
  pendiente sin remapear la ventana principal.
- Si la sustitución del selector anterior sigue aplicándose, la revisión se
  reintenta en vez de perderse.
- Las compuertas existentes mantienen como máximo un modal y una escritura a
  la vez. No se modifica ningún backend ni la lógica de detección de muertes.
- Dos regresiones fallaron antes de la corrección y pasan después.

### Validación alpha.63

- Regresiones causales: **2 passed**.
- Selector, barra, RunService y ciclo USUM alpha.59–62: **37 passed**.
- Suite completa: **428 passed** en 19,95 s con `python -m pytest -q`
  (Windows, Python 3.13.14, pytest 9.1.1, entorno aislado).
- Validación física completada por el usuario en UltraSol el 2026-08-22: tras
  dos KO, los dos selectores aparecieron consecutivamente sin minimizar ni
  restaurar RoleRun. El flujo reader→muerte→final de combate→cola de selectores
  queda físicamente validado para esta reproducción.
- La detección automática del primer Kahuna quedó validada posteriormente en
  alpha.65; los otros tres incrementos siguen pendientes de validación física.

## Historial de alpha.62

### Validación física heredada de alpha.61

El usuario validó físicamente el objetivo principal de alpha.61 en UltraSol,
Title ID `00040000001B5000`, proceso RPC `momiji` 11 y Azahar 263745c:

- Porygon/party slot 4 llegó a 0 en battle row 1 y RoleRun registró la muerte
  inmediatamente a las 03:53:08;
- Eevee/party slot 2 llegó a 0 en battle row 2 y RoleRun registró la muerte
  inmediatamente a las 03:53:21;
- el historial demuestra `vidas` 6→5→4 y la configuración conserva ambas
  identidades como `pending_faints` con `battle_seen=true`.

Queda por tanto validado físicamente el mapeo PK7 de battle rows y el compromiso
inmediato de ambas muertes. No queda validado el flujo completo de sustitución:
al finalizar el combate RoleRun no abrió el selector del PC.

La traza de control de este nuevo fallo se conserva en
`diagnostics/manual/usum_alpha61_two_kos_picker_missing_FAIL_20260822_035426.jsonl`
(219.579 bytes, SHA-256
`29625A347B403874C120095B3B7E7CDAFF2E0C5ABE8550912F01BF3D0A757818`).
Se preservaron con SHA verificado también `history.json`, `config.json`, los dos
estados OBS y el diagnóstico PC de la ejecución.

### Primera divergencia del selector ausente

La traza contiene 64 `battle-sample`, cuatro cambios de flags, un `battle-start`
y un `battle-suspend`, pero ningún `battle-end`. A las 03:53:28 el reader observa
`0x00040005/6` y lo mantiene como `state="battle"`. Por ello Adapter y UI no
reciben `none`; las dos pendientes terminan con `battle_ended=false` y
`battle_exit_samples=0`. La primera divergencia está de nuevo en
`USUMLiveReader`, antes de la compuerta de RunService y antes del selector.

Sin reiniciar la partida, Azahar ni RoleRun, el usuario confirmó que el combate
había terminado. Una lectura RPC de solo lectura posterior conserva los mismos
flags `0x00040005/6`, pero PartyData validada publica Eevee/slot 2 y
Porygon/slot 4 a 0 HP. La prueba completa se conserva en
`diagnostics/manual/usum_alpha61_postbattle_idle_party_PROOF_20260822_040601.json`.
En la captura alpha.60 del estado transitorio, esas mismas filas de batalla ya
estaban a 0 mientras PartyData aún mantenía Eevee y Porygon a 19. Esto demuestra
que el mismo par de flags corresponde tanto a sustitución forzada como a
overworld; el dato que los separa es la convergencia de los KO a PartyData.

La fuente técnica específica
[USUMCheatMenu `helpers.c`](https://github.com/pablogormi/USUMCheatMenu/blob/09c4c1b98f3cd9b88c4a537c5e22c249c72edb0e/Sources/helpers/helpers.c#L65-L69)
solo considera batalla cuando `0x30000158 == 0x00040001`. No documenta
`0x00040000/1` como paso terminal obligatorio. Alpha.60 había generalizado una
observación física de control que esta ejecución refuta.

### Corrección alpha.62

- El reader registra por proceso únicamente transiciones Displayed HP `>0→0`
  de slots cuya fila e identidad PK7 ya están validadas.
- En `0x00040005/6` sigue publicando batalla suspendida mientras esos KO no
  aparezcan a 0 en PartyData. Cuando todos convergen por la misma identidad,
  publica `none`, limpia el episodio y permite las dos muestras de salida que ya
  exige la UI.
- Un Pokémon que ya estaba a 0 al crear el baseline no cuenta como transición y
  no puede cerrar falsamente una sustitución forzada.
- La traza registra `battle-idle-evidence` y el motivo de `battle-end`.
- No se añaden direcciones RAM ni se modifica UI, RunService, LivePartyWatch,
  PC, writers, Sol/Luna u otros backends.

### Validación alpha.62

- La regresión causal reproduce el fallo de alpha.61 y falla antes del arreglo:
  **1 failed, 1 passed**.
- Regresión alpha.62 y ciclo/identidad alpha.60–61: **8 passed**.
- Flujo reader→RunService→selector/barra: **38 passed**.
- Batería USUM completa: **45 passed**.
- Suite completa: **426 passed** en 19,90 s con `python -m pytest -q`
  (Windows, Python 3.13.14, pytest 9.1.1, entorno aislado).
- En la prueba física posterior el reader sí terminó la batalla y preparó ambos
  selectores; esa validación reveló el fallo de cola de UI corregido en alpha.63.

## Historial de alpha.61 (detección de KO validada; selector postcombate superado por alpha.62)

### Nueva reproducción física y primera divergencia

- Traza preservada:
  `diagnostics/manual/usum_alpha60_restart_changed_active_FAIL_20260822_033047.jsonl`,
  222.053 bytes, SHA-256
  `B0A0CC9EC8D4E82FDA7A1FFAF489579652AA63BB22430E8F22261A4575AFC2EA`.
- Se preservaron además el historial, configuración y estado OBS de la misma
  ejecución. `vidas` permaneció en 6 y no apareció ningún `pending_faint`: la
  muerte no cruzó nunca la frontera reader→snapshot.
- UltraSol, Title ID `00040000001B5000`, proceso RPC `momiji` 11 y Azahar
  263745c. RoleRun se había reiniciado; Azahar y la partida seguían abiertos.

La batalla empieza con party
`[Registeel 18/18, Eevee 19/19, Kangaskhan 149/149, Porygon 19/19,
Tsareena 101/101, Carnivine 17/17]`. La tabla HP empieza en orden
`[19,19,149,18,101,17]`. Alpha.60 puede demostrar los slots 1, 3, 5 y 6,
pero no distinguir las filas 1 y 2: Eevee y Porygon comparten tanto Max como
HP actual. La fila 1 pasa a cero en la secuencia 8 y la fila 2 en la secuencia
73; ambas continúan sin identidad, PartyData permanece retrasado y
`LivePartyWatch` no recibe ninguna transición `>0→0`.

La salida `0x00040005/6` de las 03:29:51 sí queda registrada como
`battle-suspend`, no como `battle-end`. Por tanto el arreglo de ciclo de vida de
alpha.60 funcionó en esta ejecución; el fallo restante estaba exclusivamente en
la identidad de filas dentro de `USUMLiveReader`.

### Causa raíz finalmente demostrada

Max/Displayed/Actual HP describen salud, no identidad. El matching alpha.60 era
seguro al rechazar la ambigüedad, pero incompleto: cuando dos miembros empezaban
con los mismos valores no existía ninguna observación futura capaz de reconstruir
qué cero pertenecía a cuál sin otro campo de identidad.

La fuente técnica
[USUMCheatMenu `pokemon.h`](https://github.com/pablogormi/USUMCheatMenu/blob/master/Sources/pokeutil/pokemon.h#L61-L67)
declara `0x3254EE60 + 0x104*N` como `PARTY ON BATTLE INITIAL DATA`. Una sonda RPC
acotada y de solo lectura sobre el mismo proceso físico descifró y validó por
sanity/checksum los seis PK7 stored:

| Battle row | PK7 (especie/PID) | Party slot | Max HP de la fila |
|---:|---|---:|---:|
| 1 | Porygon / `BC0C2B25` | 4 | 19 |
| 2 | Eevee / `DB76FD4F` | 2 | 19 |
| 3 | Kangaskhan / `8C3FC66A` | 3 | 149 |
| 4 | Registeel / `8D65562F` | 1 | 18 |
| 5 | Tsareena / `080D79E3` | 5 | 101 |
| 6 | Carnivine / `8D826F23` | 6 | 17 |

La prueba derivada se conserva en
`diagnostics/manual/usum_alpha60_battle_row_identity_PROOF_20260822_034449.json`.
La correspondencia `4,2,3,1,5,6` coincide exactamente con las filas HP físicas.
Esta es la primera evidencia que desambigua directamente Porygon/Eevee y demuestra
la causa sin usar el síntoma como premisa.

### Corrección alpha.61

- Cada fila se enlaza ahora por `(species, PID, TID, SID)` obtenido de un PK7
  checksum-válido mediante doble lectura estable. Max y ambos HP siguen siendo
  precondiciones obligatorias de la fila.
- Una identidad ausente o duplicada no se adivina. Los Max únicos pueden seguir
  publicando sus filas demostradas; las ambiguas permanecen cerradas.
- El resolvedor host de una base HP desplazada valida el multiconjunto completo
  de Max HP y ya no exige el orden de party falsado por las capturas físicas.
- El mapeo se invalida en suspensión/reentrada/terminal. Se conserva íntegro el
  ciclo activo→suspendido→terminal de alpha.60.
- No se modifica SM, UI, `LivePartyWatch`, RunService, PC, writers, movimientos
  ni progresión.

### Validación y cierre

- Las dos regresiones nuevas fallaban con alpha.60 y pasan con alpha.61.
- Regresiones de batalla alpha.57–61: **13 passed**.
- Batería USUM completa: **44 passed**.
- Suite completa: **424 passed** en 19,86 s con `python -m pytest -q`
  (Windows, Python 3.13.14, pytest 9.1.1, entorno aislado).
- La reproducción física posterior sí validó el mapeo y compromiso inmediato de
  los dos KO de alpha.61, pero descubrió que el selector postcombate no se abría.
  Ese hallazgo da origen a alpha.62 y no altera esta baseline histórica.

## Historial de alpha.60 (conservado; invalidado parcialmente por la reproducción posterior)

Alpha.60 introdujo el ciclo activo/suspendido/terminal y un matching por
Max/Displayed/Actual. La reproducción posterior confirmó físicamente el ciclo,
pero demostró que el matching no podía resolver dos miembros a 19/19. Su baseline
histórica fue **422 passed**; no debe interpretarse como cierre físico del KO.

## Historial de alpha.59 (conservado; superado por la reproducción alpha.59 posterior)

- Baseline automatizada: **418 passed** en 20,31 s con
  `python -m pytest -q` (Windows, 2026-08-22).
- No hay ningún test fallido ni escritura de tests en los Logs persistentes del
  usuario.

### Hechos demostrados

- Azahar inició el proceso usado por SUCCESS a las 02:05:27. El módulo
  `Battle` del combate preservado cargó a los 66,525 s y descargó a los
  86,267 s. La traza publica los KOs de Registeel y Eevee a las 02:06:38 y
  02:06:50; el historial los compromete en esos mismos segundos.
- Un segundo combate del mismo proceso cargó a los 261,888 s. El historial
  vuelve a comprometer ambos KOs durante el combate, a las 02:09:53 y 02:10:04,
  antes de la descarga de `Battle` a los 279,306 s.
- El juego se reinició a los 323,283 s. En el siguiente combate, `Battle` estuvo
  cargado entre 334,903 s y 400,996 s; ambos KOs se comprometieron juntos a las
  02:12:09, ya fuera del módulo de batalla. Esto demuestra que Adapter, UI,
  `LivePartyWatch` y el compromiso postcombate seguían operativos.
- La copia llamada FAIL fue creada a las 02:12:44, después de otro reinicio a
  los 432,360 s y durante la carga de `TitleMenu` (437,841 s). Sus seis filas
  incompatibles demuestran que `0x30000158 == 0x00040001` también puede coexistir
  con memoria que no es la party de batalla; no contiene los ticks de los dos
  KOs físicos.
- La fuente pública de las direcciones es un cheat con direcciones absolutas; no
  aporta un puntero ni una prueba de estabilidad entre ciclos de proceso.

### Causa raíz demostrada

Alpha.56–58 convertía una base de heap estática y un flag insuficiente en un
localizador permanente. La validación por slot impedía publicar basura, pero no
podía recuperar la tabla real cuando esa candidata dejaba de describir la party;
el resultado era `validated_slots=[]`, `health_game=None` y ausencia total de
muestras para `LivePartyWatch`. Por eso podían fallar el primero y el segundo KO
por la misma divergencia y recuperarse ambos al volver a PartyData postcombate.

### Corrección implementada

Alpha.59 conserva la base publicada solo como candidata rápida. Cuando todas sus
filas fallan, `USUMLiveReader` calibra host↔guest con los seis PK7 exactos del
mismo tick, exige el vector completo de Max HP/stride, HP acompañantes en rango,
una sola candidata y dos readbacks RPC idénticos con flags antes/después. La base
se revalida cada tick y se descarta fuera de combate. Una búsqueda ambigua o sin
prueba continúa sin publicar HP.

La traza alpha.59 ya no se abre con `w` en cada reentrada. Registra episodios,
flag primario, flag de fase, base/fuente, prueba del resolver y conserva además
un archivo inmutable en `Logs\USUM-Battle-Traces`.

### Estado de cierre

La corrección automatizada y la causa técnica están cubiertas por regresiones.
La capacidad realtime de alpha.59 **sigue pendiente de validación física** y no
se declarará cerrada hasta observar un KO dentro del emulador tras reiniciar el
proceso del juego.

## Historial y baseline de alpha.58 (conservado)

## Checkpoint Git y baseline automatizada

- Snapshot funcional alpha.58: `369e53f983a21a56e5b835a109eeeab3db91a7d1`.
- Reglas permanentes: `b52634d67dd01b80187a281f12f4028d5251ff5a`.
- Entre ambos commits solo se añadió `AGENTS.md`; los archivos funcionales son
  idénticos.
- Comando de suite completa: `python -m pytest -q` desde la raíz.
- Baseline ejecutada en Windows, Python 3.13.14 y pytest 9.1.1: **413 passed,
  1 failed, 414 collected** en 20,35 s.
- Fallo preexistente y dependiente de Windows:
  `tests/test_faint_picker_floating.py::test_mapping_main_window_hides_a_still_visible_floating_bar_before_picker`.
  El doble `SimpleNamespace` no define `_foreground_belongs_to_this_process()`,
  método que `_on_main_map()` consulta solo en la rama `os.name == "nt"`.

Este párrafo describía exclusivamente la baseline alpha.58: entonces la suite
no era hermética y podía reemplazar archivos `*_latest` del usuario. La
infraestructura de tests posterior aisló todos los `LOG_DIR` mediante directorios
temporales; no debe interpretarse como una limitación vigente.

## Arquitectura y backends activos

La UI y raíz de composición siguen en `app/ui.py`. El motor común de partidas es
`engine/RoleRun.SaveEngine` mediante `app/save_engine_client.py`. El Core común
está en `app/realtime/`; offsets y validadores permanecen en cada backend.

| Juego | Save/PKHeX | Tiempo real actualmente registrado |
|---|---|---|
| DP, Pt, HGSS, BW, B2W2 | Sí | No |
| BDSP | Sí; proveedor Unity para MT randomizadas y PP base | Ryujinx HostMapped; party/PC/inventario/HP live; writer transaccional de roles y movimientos/MT de party |
| ORAS | Sí | Azahar RPC |
| X/Y | Sí | Azahar RPC y Citra GDB/broker |
| Sol/Luna | Sí | Azahar RPC |
| UltraSol/UltraLuna | Sí | Azahar RPC |

Los adaptadores registrados en `app/ui.py` son ORAS, XY, SM, USUM y BDSP. Los
bridges activos son Azahar RPC, Citra GDB y Ryujinx HostMapped; Citra se usa
actualmente para X/Y y HostMapped para Perla Reluciente 1.3.0. La frontera
Ryujinx GDB se conserva solo para diagnóstico. No existe bridge RAM para DS.

Estado funcional relevante:

- ORAS: party, roles, movimientos, PC, inventario/MT, progreso y muertes live.
- X/Y: party, roles, movimientos, PC, inventario/MT, batalla y progreso live;
  las operaciones iniciadas por RoleRun que cambian el tamaño de la party siguen
  protegidas hasta validación específica.
- SM: party, roles, movimientos, PC, inventario/MT, Kahunas y muertes live están
  implementados y sujetos a sus validadores Gen 7.
- USUM: paridad implementada para party, roles, movimientos, PC, inventario/MT,
  Kahunas y muertes. El carril de KO y la cola de selectores están validados
  físicamente en alpha.63; solo Kahunas sigue pendiente de validación física.

Las etiquetas visuales `stable`/`experimental` no sustituyen una validación
física de la combinación exacta juego/revisión/backend.

## Apéndice histórico: investigación alpha.58 del primer KO de USUM

> Esta sección conserva el estado anterior a las capturas SUCCESS/FAIL y a la
> reproducción alpha.59 de 03:02–03:05. Sus carencias de evidencia y pasos
> pendientes ya no describen el estado vigente; la conclusión actual está al
> principio de este documento.

### Comportamiento físico comunicado

1. RoleRun está conectado y comienza un combate.
2. El primer Pokémon enviado al campo cae a 0 HP.
3. RoleRun no descuenta vida ni retira su icono en ese momento.
4. Entra un segundo Pokémon y también cae a 0 HP.
5. La segunda muerte se registra inmediatamente durante el combate.
6. La primera solo se registra al finalizar el combate.

Alpha.58 es exclusivamente diagnóstica y no cambia el criterio de muerte de
alpha.57.

### Estado de la evidencia física

La ruta esperada es:

`C:\Users\PC\Documents\RoleRun Manager\Logs\usum_battle_health_trace_latest.jsonl`

El archivo presente el 2026-08-22 a las 01:43:18 no contiene la batalla física.
Su SHA-256 es
`8398A447E8D6C327CCF770F47B530DBD08D446BD81D505BB3E13A6140D4BB78B` y
solo contiene `battle-start` más una muestra separada por 1 ms:

| Fila | Party Max | Battle Max | Displayed | Actual | Candidatos por Max | Válida |
|---:|---:|---:|---:|---:|---|---|
| 1 | 60 | 61 | 0 | 0 | ninguno | no |
| 2 | 80 | 81 | 37 | 35 | ninguno | no |

La party son dos Pikachu sintéticos con HP 50/60 y 40/80. Los valores coinciden
exactamente con
`test_alpha56_battle_lane_still_rejects_when_no_slot_is_proven` en
`tests/test_usum_alpha43_foundation.py`. Esa prueba crea `USUMLiveReader` sin
redirigir `LOG_DIR`; `_battle_trace_start()` abre el archivo real con modo `w`.
La prueba alpha.58 siguiente sí usa `tmp_path`, pero no protege la anterior.
La hora coincide con la ejecución de la suite completa y con otros diagnósticos
sintéticos escritos en `Logs`.

No se encontró otra copia en Documentos, OneDrive, File History, alternate data
streams ni shadow copies disponibles. El historial de la run confirma compromisos
automáticos de muertes, pero no conserva battle rows, Max/Displayed/Actual HP ni
snapshots por tick. Por ello no permite reconstruir el orden causal.

**Conclusión vigente:** la causa raíz del bug físico no está demostrada. No es
válido identificar los dos Pikachu de la traza actual con los dos Pokémon de la
partida ni usar esa muestra sintética para elegir una corrección.

### Flujo demostrado por código

#### 1. RAM → `USUMLiveReader`

`app/usum_live.py::read_battle_probe()`:

- lee el flag `0x30000158` antes y después de los HP y exige `0x00040001`;
- lee Max HP desde `0x30002776`, Displayed HP desde `0x30002778` y Actual HP
  desde `0x30009760`, con stride `0x330`;
- itera las filas en el mismo índice que la party PK7 filtrada;
- una fila es válida solo si Battle Max coincide con Party Max del mismo índice
  y Displayed/Actual están en rango;
- para una fila válida, `health_game.current_hp` recibe **Displayed HP**;
- Actual HP solo viaja en `liveBattleActualHp` y en la traza;
- para una fila rechazada, el clon conserva el HP de party, que puede ir retrasado
  durante el combate;
- si no queda ninguna fila válida, devuelve `health_game=None`.

La traza alpha.58 registra por tick party, filas, candidatos por Max, slots
validados y motivos de rechazo, pero no registra directamente la llamada de UI
ni el resultado de `detect_fainted_transitions()`.

#### 2. Reader → adapter → snapshot

`app/realtime/usum_adapter.py::capture_monitor()` captura primero la party estable
y después llama a `read_battle_probe(raw.game)`. Construye
`RealTimeSnapshot.battle` con estado, `health_game` y pares de HP. Una sonda
rechazada conserva `state="battle"`, pero no entrega `health_game`.

`capture_full()` hace la misma lectura para establecer el baseline inicial de
alpha.57. Arrancar dentro de combate establece baseline sin cobrar muertes
retrospectivas; arrancar fuera deja estado `none` y party overworld como baseline.

#### 3. Snapshot → monitor de salud de UI

En `app/ui.py::_finish_oras_live_reconciliation()` para SM/USUM:

- con `probe_state == "battle"` y `probe_health` válido, compara contra el
  snapshot de salud anterior;
- si el estado anterior era `unknown`, la muestra se usa solo como baseline;
- con `probe_health=None`, no entrega una muestra nueva al detector;
- con `probe_state == "none"`, procesa `snapshot.game` como fallback overworld;
- no sustituye una sonda de combate inválida por HP overworld mientras sabe que
  el combate sigue activo.

#### 4. UI → LivePartyWatch

`app/ui.py::_process_oras_health_snapshot()` actualiza
`_oras_live_health_snapshot` y llama a
`app/live_party_watch.py::detect_fainted_transitions(before, after)`.

El detector empareja por `(species_id, PID, TID, SID)` y solo produce evento si
el mismo Pokémon pasa de `old_hp > 0` a `new_hp == 0`. No produce transición si:

- no existe snapshot anterior;
- el Pokémon no aparece con la misma identidad;
- el snapshot anterior ya tenía HP 0;
- la muestra nueva conserva HP positivo;
- la UI no llamó al detector porque `health_game` era `None`.

Para Gen 7, `source="battle-visible"` se compromete en el mismo tick lógico; el
retraso de un segundo solo se usa para `source="battle"` de ORAS.

#### 5. LivePartyWatch → compromiso

`RunProjectService.register_detected_faint()` exige identidad estable, evita una
pendiente activa duplicada, resta una vida, persiste `pending_faints` y añade
`pokemon_fainted_auto` al historial. La UI actualiza después layout, iconos y OBS.
El selector de sustitución continúa cerrado hasta confirmar salida del combate;
esto no retrasa el descuento de vida ni la retirada visual una vez registrada la
muerte.

### Primera divergencia

Con la evidencia disponible no puede localizarse la primera divergencia entre
la muerte que falla y la que funciona. El dato decisivo debía aparecer en el
primer tick físico donde cada Pokémon alcanzó Actual o Displayed HP 0:

- battle row y Max HP;
- party index/slot y Max HP;
- candidatos y slots validados/rechazados;
- `health_game` reconstruible y baseline anterior.

Sin esos ticks no se puede decidir si la primera diferencia ocurrió en el valor
RAM, el mapeo fila↔party, la validación Max HP, la elección Displayed frente a
Actual, el baseline de UI o una condición posterior. No se propone solución hasta
capturar de nuevo esa evidencia.

## Evidencia que entonces era necesaria (ya obtenida)

Reproducir una única batalla con alpha.58 y, antes de ejecutar tests o comenzar
otro combate, copiar `usum_battle_health_trace_latest.jsonl` a un nombre único
fuera de `Documentos\RoleRun Manager\Logs`. La captura debe comenzar con RoleRun
ya conectado fuera de combate y conservar desde `battle-start` hasta `battle-end`.

La siguiente investigación debe comparar tick por tick ambos Pokémon y registrar
para cada transición:

1. primera secuencia con Actual HP 0;
2. primera secuencia con Displayed HP 0;
3. Max HP y candidatos de la battle row;
4. party index, slot, HP y Max HP testigo;
5. pertenencia a `validated_slots` o motivo de rechazo;
6. `health_game` que se deriva de esa muestra;
7. baseline anterior de UI;
8. resultado esperado de `detect_fainted_transitions()`;
9. primer `pokemon_fainted_auto` correspondiente en el historial.

## USUM alpha.125 — EV automáticos en entradas desde PC

La inspección extremo a extremo demostró que `_prepare_pc_team_change()` ya
incluía en `incoming_snapshot` la distribución EV del rol para USUM, pero
`USUMLiveWriter._apply_team_swap()` no la entregaba a
`_party_payload_from_box()`. El PK7 entrante heredaba el marcador correcto y
conservaba sus EV antiguos: esa era la primera divergencia.

Alpha.125 valida el rol testigo del snapshot, aplica sus seis EV antes de
refrescar el checksum y construye la `PartyData` desde ese mismo PK7. Stored,
estadísticas finales, rol, movimientos, PC y PartyCount continúan dentro de la
transacción ya demostrada, con readback y rollback existentes. Las regresiones
cubren tanto añadir a un hueco libre como sustituir una casilla ocupada. La
validación física en UltraSol/Azahar del 24-08-2026 confirmó que la entrada desde
PC aplicó correctamente los EV y estadísticas finales del rol.

## USUM alpha.127 — selector visible y arrastre a casilla PC exacta

La reproducción visual mostró dos divergencias independientes. En el selector
de sustitución, el botón final pertenecía al cuerpo fijo de la ficha y quedaba
recortado al crecer stats/IV/EV bajo la altura reducida por los avisos. Ahora las
acciones son un pie reservado del inspector. La captura sintética
`diagnostics/manual/alpha127_faint_replacement_footer_preview.png`, generada a
1920×1080 con el modo de baja activo, muestra el botón completo.

En Equipo→PC, cada objetivo de arrastre ya declaraba `box` y `slot`, pero
`_team_pc_drop()` los sustituía por `None`; por ello el writer ejecutaba
correctamente su ruta de «primer hueco libre». Alpha.127 conserva las coordenadas
solo para el gesto explícito de USUM. El writer vuelve a leer la matriz live,
exige que la casilla exacta exista y esté vacía, y después conserva las mismas
precondiciones, readback y rollback del traslado demostrado. `ENVIAR AL PC` sin
arrastre sigue eligiendo el primer hueco libre. La regresión escribe un testigo
en Caja 3/posición 4 y comprueba que Caja 1/posición 1 permanece vacía; otra
prueba demuestra que un destino ocupado no modifica party ni PC. Validación
física completada en alpha.128.

## USUM alpha.128 — salud flotante y destino PC validados físicamente

La traza de batalla de control demostró que el reader no publicó seis ceros: en
ninguna muestra hubo dos HP mostrados simultáneamente a cero y el último snapshot
conservó los seis HP de party coherentes. La primera divergencia estaba después
del reader: la barra flotante consumía los HP provisionales de la party proyectada
en vez del snapshot de salud validado. Ahora resuelve cada miembro por identidad
fuerte única y solo acepta un rango `0 <= HP <= HP máximo` coherente.

El resto rojo de una baja era independiente: `CTkProgressBar` dibujaba el extremo
redondeado aun con progreso cero. Los miembros vacíos o a cero usan ahora un
carril neutro. La barra también se retira al mapear una ventana principal ya
explícitamente visible, cerrando la carrera de foco observada al maximizar.

La validación visual a 1920×1080 confirma que el selector no presenta el aviso rojo
superior redundante, mantiene tarjetas completas y muestra enteramente `ELEGIR
COMO SUSTITUTO`. La barra flotante de control muestra una casilla debilitada/vacía
sin píxel rojo residual.

La validación física en UltraSol/Azahar del 24-08-2026 arrastró Porygon desde el
equipo hasta Caja 1/posición 8. La matriz visible lo mostró exactamente allí y el
historial confirmó `team_to_pc`, `box: 1`, `box_slot: 8`, `output: RAM`. La
operación inversa lo devolvió al rol Support desde la misma casilla y el historial
confirmó `pc_to_team` con caja/slot 1/8. El estado usado para la comprobación quedó
restaurado.

El usuario confirmó además físicamente que una baja deja la posición flotante
neutra —sin resto rojo— y que la barra flotante desaparece al maximizar RoleRun.

## USUM alpha.129 — arrastre de Pokémon entre cajas PC

La primera divergencia estaba en la UI: las flechas de caja eran botones de clic,
no destinos de arrastre. La segunda estaba en el contrato común de drop, que
rechazaba expresamente todo PC→PC aunque el backend USUM ya hubiese demostrado la
matriz BoxPokemon completa. Mantener un Pokémon sobre una flecha cambia ahora una
sola caja tras 420 ms y conserva la captura del ratón aunque se reconstruya la
cuadrícula. Al abandonar la flecha puede avanzarse otra caja; al soltar sobre una
casilla vacía se declara origen y destino exactos.

El writer USUM copia los 0xE8 bytes cifrados exactos del PK7 stored al destino y
escribe en origen el PK7 vacío cifrado válido. Exige matriz 32×30 estable
host==guest, identidad de origen, destino vacío, límites, preflight inmediato,
dos verificaciones completas y rollback verificado de ambos huecos. No toca party,
otros backends ni reconstruye campos Pokémon. La validación física en Azahar queda
pendiente.

## USUM alpha.126 — EV del rol al sustituir una muerte

La inspección del siguiente punto de entrada PC→Equipo localizó una ruta que no
atravesaba alpha.125: `_prepare_faint_replacement()` heredaba el rol del miembro
debilitado, pero dejaba en el snapshot los EV antiguos del Pokémon de caja; a su
vez, `_apply_faint_replacement()` reconstruía `PartyData` sin consumir EV
preparados. Esa era la primera divergencia y ocurría antes de publicar el nuevo
equipo.

Alpha.126 prepara los EV automáticos del rol heredado y los aplica al mismo PK7
con el que se reconstruyen las estadísticas finales. Para Líbero solo conserva
una pareja demostrada por dos EV a 252 en el miembro saliente; si no existe esa
evidencia, no inventa una selección. La regresión de writer verifica rol, seis
EV, estadísticas runtime, origen PC vacío válido y Pokémon debilitado exacto en
el Cementerio. La validación física en UltraSol/Azahar queda pendiente.

## USUM alpha.124 — estadísticas finales reconciliadas y validadas físicamente

La prueba directa sobre la partida abierta localizó una segunda divergencia:
`assign_role()` salía antes de `_apply_role_assignment()` cuando Líbero ya tenía
la misma pareja de EV. Por tanto, la capacidad transaccional de alpha.123 era
correcta, pero la UI no llamaba al writer en el caso exacto necesario para
reparar el estado dejado por alpha.122.

Alpha.124 mantiene ese retorno temprano para el resto de backends, pero USUM
atraviesa la reconciliación siempre que existe una distribución EV explícita.
La regresión de UI demuestra esa llamada. La validación física en UltraSol con
Azahar del 24-08-2026 observó a Kangaskhan nivel 50 con EV PS/Ataque 252/252 y
estadísticas antiguas 172/140; después de aceptar de nuevo esos mismos EV, el
readback y la pantalla de RoleRun mostraron 203 PS y 170 Ataque. Los EV se
mantuvieron 252/252 y los PS actuales quedaron 203/203 al partir de salud
completa. La evidencia visual se conserva en
`diagnostics/ui/alpha123-live-before.png` y
`diagnostics/ui/alpha123-live-after.png`.

## USUM alpha.123 — writer de estadísticas finales; UI aún omitía la llamada

La prueba física de alpha.122 confirmó que seleccionar PS y Ataque para Líbero
escribía 252/252 en los EV, pero demostró que las estadísticas finales no
cambiaban. La primera divergencia estaba dentro de `USUMLiveWriter`: modificaba
el PK7 stored, mientras que la party Gen 7 mantiene sus estadísticas calculadas
en una `PartyData` dispersa separada (`slot + 0x158`).

Alpha.123 recalculaba ese bloque desde Personal efectivo, nivel, naturaleza, IV,
hiperentrenamiento y los EV deseados. Stored y PartyData comparten ahora
precondiciones, readback y rollback. También permite volver a seleccionar la
misma pareja de Líbero para reparar una party que alpha.122 hubiera dejado con
EV nuevos y stats antiguos. La prueba posterior demostró que la UI descartaba
esa petición antes del writer; alpha.124 cierra y valida esa última frontera.

## USUM alpha.122 — EV escritos; estadísticas finales incompletas

La siguiente diferencia demostrada respecto a BDSP estaba en la frontera de
edición de rol: USUM escribía el marcador PK7, pero la UI solo generaba
`old_evs/new_evs` para `bdsp` y el writer USUM ignoraba esos campos. Alpha.122
habilita la distribución EV para cambios de rol y entradas desde el PC. El
writer usa el campo PK7 ya demostrado en `0x1E:0x24`, exige coincidencia exacta
de los EV anteriores, valida 252/510, actualiza checksum y confirma por
readback identidad, rol, EV y movimientos antes de aceptar la operación. La
prueba física confirmó la distribución EV, pero no las estadísticas finales:
esa limitación queda corregida y pendiente de validar en alpha.123.

## USUM alpha.121 — fichas, PC, curación y barra validados físicamente

- En UltraSol ejecutado por Azahar se validó una ficha de Equipo y una ficha de
  PC con naturaleza, estadísticas calculadas, estadísticas base, IV y EV. La
  ficha PC de control mostró, además, habilidad y los cuatro movimientos.
- La primera divergencia de las fichas PC estaba antes de la UI: el primer
  snapshot podía dejar activa la caché del guardado y el worker PC podía
  ejecutarse antes de cargar el Personal de la ROM. La matriz PK7 viva y el
  Personal efectivo se exigen ahora antes de enriquecer la ficha.
- Se validó físicamente la curación completa sobre un Eevee con 11/19 PS. El
  writer terminó el readback y RoleRun publicó 19/19 sin quedar bloqueado en
  «Curando el equipo».
- La barra flotante USUM mostró los seis miembros y sus barras de PS, además de
  los controles CURAR y MENÚ. El menú se abrió y cerró correctamente y el logo
  devolvió a la ventana principal manteniendo vivo y responsivo el proceso.
- La validación corresponde a la partida y proceso Azahar abiertos el
  24-08-2026. No traslada por analogía ninguna dirección o writer a otro backend.

## Regla de actualización

Actualizar este documento cuando cambie una capacidad, se ejecute una baseline
completa, se demuestre una nueva dirección/estructura o termine una validación
física. No marcar una función realtime como cerrada solo porque pasen tests.
## USUM alpha.130 — arrastre PC físicamente accesible

- Causa raíz demostrada: el arrastre se enlazaba a un frame estable y llamaba
  a `grab_set`; Tk retargeteaba los movimientos/liberación a esa superficie en
  lugar de conservar el widget situado bajo el puntero. Por ello el destino se
  resolvía como la casilla ocupada de origen y las flechas no recibían hover.
- La continuación del gesto usa ahora el bindtag del `Toplevel`, que sobrevive
  al redibujado de una caja sin alterar el destino físico del cursor.
- Validado físicamente en USUM con Azahar 263745c el 2026-08-24: movimiento
  exacto dentro de caja, navegación sostenida caja 1→2, escritura en la casilla
  elegida y recorrido inverso hasta restaurar Eevee en caja 1/casilla 1.

## B2/W2 alpha.6 — evidencia de party, PC y estado de combate

- La captura real de Negro 2 España en melonDS 1.1 demostró que Lillipup y
  Patrat desaparecían en la frontera de decodificación: la permutación de
  bloques PK5 estaba invertida para PID no autoinversos. La corrección reconoce
  los seis miembros presentes en RAM; queda pendiente confirmación visual de UI.
- La captura controlada con party 6/6 y Sewaddle recién enviado al PC demostró
  la matriz en `0x022059A4`: 24 cajas, 30 slots de 136 bytes y stride `0x1000`.
  Dos lecturas completas coincidieron y dieron 3 ocupados y 717 vacíos PK5
  válidos. El reader está implementado; el writer sigue cerrado.
- La traza de parálisis demostró `0x0225B1C4` como byte de presentación:
  `0` antes, `1` con PAR visible y `0` fuera del combate. Alpha.6 lo publica
  desde ese carril.
- Validación física completada por el usuario el 26-08-2026 en Negro 2
  España/melonDS 1.1: RoleRun mostró los seis miembros (incluidos Lillipup y
  Patrat), la barra flotante completa, Azurill/Lillipup/Sewaddle en Caja 1 y
  PAR durante el combate en el momento correcto.

## B2/W2 alpha.9 — movimiento PC→PC validado

- El 27-08-2026 la prueba transaccional movió Lillipup de Caja 1/slot 2 a
  Caja 1/slot 4 en Negro 2 España/melonDS 1.1. El usuario confirmó el resultado
  visual y una lectura independiente verificó origen vacío, identidad completa
  en destino y la matriz restante coherente (3 ocupados, 717 vacíos).
- La capacidad se habilita en producción solo para origen ocupado y destino
  vacío, con precondición de identidad, readback integral y rollback. No
  demuestra ni habilita Equipo↔PC ni intercambios entre dos slots ocupados.
- Validación adicional desde la interfaz de alpha.9: el usuario movió el
  Pokémon dentro del PC y confirmó que RoleRun y el juego reflejaron el destino
  correcto. PC→Equipo continuó cerrado, conforme a la compuerta prevista.

## B2/W2 alpha.10 — intercambio Equipo↔PC 1:1 validado

- La captura controlada desde el PC del juego demostró stored PK5 idénticos en
  ambos sentidos y la regeneración del anexo party según el contrato oficial
  de PKHeX. La restauración devolvió todas las identidades originales.
- La prueba de escritura construyó el anexo con estado limpio, nivel, PS y stats
  recalculadas. El usuario confirmó visualmente Lillipup en Equipo/1 y Tepig en
  Caja 1/slot 2; la relectura independiente confirmó nivel 6, 21/21 PS,
  stats 21/12/11/8/12/12 y 3 ocupados + 717 vacíos coherentes.
- Se habilita solo el intercambio 1:1 con entrante sin objeto. Los cambios de
  tamaño de party y objetos/correo requieren pruebas separadas.
- El usuario validó después desde la interfaz de RoleRun los tres recorridos
  cubiertos: Equipo→PC dentro del swap 1:1, PC→PC a vacío y PC→Equipo 1:1.

## UI alpha.11 — carga inicial en ventana normal

- La barrera inicial ya no se maximiza ni se mantiene por encima del resto del
  escritorio. Conserva el tamaño normal de RoleRun y permite cambiar de ventana
  mientras termina la lectura. La frontera de publicación de la shell no cambia.

## UI alpha.12 — carga inicial centrada

- La ventana normal de RoleRun y su barrera inicial 1360×860 se sitúan en el
  centro de la pantalla principal de Windows. No se recuperan maximización,
  `topmost` ni captura de foco.

## B2/W2 alpha.13 — compactación y tamaño 1–6

- La captura real demostró `6→5`: al depositar el tercer miembro, los tres
  posteriores se desplazan una posición, el contador baja a 5 y el depositado
  conserva su stored PK5 en Caja 1/slot 4. La retirada hace `5→6` y lo añade
  al final; las seis identidades se conservan.
- Una segunda captura del span completo demostró que el slot liberado es
  exactamente el PK5 party vacío cifrado con semilla cero, no memoria aleatoria.
- Alpha.13 implementa count-last, compactación, append, readback y rollback.
  La validación física desde la interfaz sigue pendiente.
