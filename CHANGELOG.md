> Este archivo conserva el historial de versiones. Para el estado funcional,
> baseline y bugs abiertos actuales, consultar `docs/CURRENT_STATE.md`.

# v0.3.0-alpha.5 — mover Pokémon dentro del PC en Perla Reluciente

Arrastrar de un hueco del PC a otro decía «DESTINO NO HABILITADO». Ya no.

## No es una escritura nueva

Un movimiento dentro del PC son **exactamente las dos escrituras** que el writer
de tamaño ya realiza sobre esta misma matriz de 1.200 slots:

| | |
|---|---|
| `party-to-box` | mete un PB8 completo (344 bytes) en un hueco de caja |
| `box-to-party` | deja el vacío canónico en el hueco que se libera |

Aquí se aplican a **dos huecos de caja** en vez de a uno de caja y uno de party.
La estructura, el tamaño del registro y el vacío canónico son los ya demostrados
físicamente. No se ha inventado nada; se compone lo que ya estaba probado.

## Lo que sigue bloqueado

El **intercambio** entre dos huecos ocupados. Eso no son estas dos escrituras
—necesita un tercer hueco o un contrato distinto— y no está demostrado. El
destino tiene que estar vacío, y si no lo está se rechaza sin escribir un byte.

## Las precondiciones

Las mismas que el resto de writers vivos, más una que no es obvia: **la party no
se toca, así que su captura sirve de testigo**. Si cambia durante la operación,
algo más estaba escribiendo y se aborta.

Además: doble captura de cajas comparada, el origen tiene que seguir conteniendo
**ese** Pokémon —la caja pudo cambiar dentro del juego entre elegir y soltar—,
nada de esto ocurre en combate, y al terminar se verifica que ningún otro hueco
de las 1.200 posiciones cambió. Con rollback verificado si algo falla a medias.

## Nota de estructura

Este writer repite el bloque de transacción de los otros tres en vez de
compartirlo. Extraerlo tocaría tres caminos de escritura viva ya demostrados, y
eso es un trabajo aparte con su propio riesgo: aquí se ha seguido la forma de la
casa —un writer autocontenido por operación—.

1954 passed, 1 skipped.

# v0.3.0-alpha.4 — el corte de dos segundos en la música

El usuario oye que la música del juego se para **dos segundos** al cargar RoleRun
y otra vez al volver a la ventana principal desde la barra flotante.

## De dónde sale

De la medición, mirando **en qué hilo** corre cada cosa:

| operación | veces | mediana | peor | hilo |
|---|---|---|---|---|
| `realtime.read_pc` | 430 | 123 ms | 1422 ms | worker |
| `realtime.capture_monitor` | 1733 | 3 ms | 1317 ms | worker |
| **`ui.render_page`** | 15 | **610 ms** | **2576 ms** | **tk** |

Todo el trabajo pesado de memoria va en hilos aparte. **Lo único que corre en el
hilo de Tk es repintar la página**, y son 30.255 llamadas a Tcl seguidas: un
núcleo a tope justo cuando el emulador también lo necesita.

Esos 2576 ms son exactamente los «dos segundos» que se oyen.

## Lo que se arregla

Volver a la ventana principal desde la barra repintaba **siempre**. Pero mientras
se está en la barra la ventana solo está *retirada*, no destruida: si nadie marcó
la página como sucia y se vuelve a la misma, el árbol que hay ya es el bueno.

Ahora se reutiliza, con tres condiciones y una red de seguridad.

La condición delicada era «¿es la misma página?». Deducirlo de `active_page` sería
adivinar: la barra flotante y su menú cambian de página por su cuenta, así que ese
valor no habla del árbol que quedó en la ventana retirada. Ahora `render_page`
**apunta para qué página construyó el body** y se comprueba, no se deduce.

La red de seguridad: si alguna ruta olvidó marcar la página como sucia, tras
mostrar la ventana se hace un refresco en sitio —37 ms medidos frente a 610— que
pone los datos de ahora sin reconstruir nada. Y si algo no cuadra, esa ruta se
niega sola.

## Lo que no es nuestro

El usuario también reporta que **con RoleRun a pantalla completa el juego se para
del todo, y se reanuda al hacer clic en el emulador**. Eso no es un corte: es
Ryujinx pausando la emulación al perder el foco, y se quita en sus opciones. Es
además lo que explica las pausas «sin foco» que salían en el trazado del reloj.

1943 passed, 1 skipped.

# v0.3.0-alpha.3 — sin sonidos

Los efectos sintetizados sonaban a Windows, que es justo lo que el usuario no
quería. Un adorno que molesta es peor que no tenerlo, así que quedan apagados.

Apagado no es un maquillaje: no se abre ningún hilo, no se sintetiza nada y no
se toca el disco. La carpeta `Documentos\RoleRun Manager\Sonidos` se puede
borrar; no se vuelve a crear.

La maquinaria se queda —está probada y aislada— porque el día que haya sonidos
propios solo hay que traerlos: `Sonidos` usa el WAV que encuentre en la carpeta
antes que el suyo. Una prueba comprueba que el programa se entrega mudo, para
que no vuelva a encenderse solo.

El vuelo del Pokémon entre el equipo y el PC se queda: eso no se objetó.

## Y de paso, el congelado tiene explicación

Investigando esto salió la pieza que faltaba. El usuario reportó que Windows **no
podía abrir el mezclador de volumen**, y que **al cerrar Ryujinx el mezclador se
abrió al instante**.

Eso señala a Ryujinx teniendo atascado el audio de Windows, y encaja con todo lo
medido hasta ahora:

- **es intermitente** —depende de cuándo se atasque el audio—;
- **el reloj del juego seguía avanzando** durante un congelado: el hilo de CPU
  sigue vivo y el que se queda esperando es el de audio;
- la memoria del juego seguía siendo legible y coherente;
- **reiniciar Ryujinx era lo único que lo arreglaba**.

También explica por qué dos hipótesis sobre la escritura de MT no llevaban a
ningún sitio: la mochila queda como el juego la deja y `_set_move` escribe lo
mismo que `CoreParam.SetWaza`. La escritura no era el problema; coincidió.

Lo accionable está en Ryujinx, no aquí: **Options → Settings → Audio → Audio
Backend**, y cambiar el que esté puesto por otro (SDL2 / OpenAL / SoundIO).

Los efectos de RoleRun reproducían con `winsound.PlaySound` **en un hilo por
sonido**, así que apagarlos también quita a RoleRun de esa disputa.

1937 passed, 1 skipped.

# v0.3.0-alpha.2 — el primer drafteo enciende los botones

Con la pestaña de Drafteos abierta y cero drafteos, sumar uno dejaba una pantalla
rota: aparecía un panel «Elige el rol del drafteo» flotando en mitad de la
página, y debajo las seis tarjetas seguían diciendo **EN PREPARACIÓN**.

Era código heredado. Esa rama destruía un paso que ya no existe y llamaba a
`_render_role_step`, el renderizador del **diseño antiguo por pasos**, que dibuja
dentro del body actual: encima del flujo visual que ya estaba ahí.

## Por qué hay que repintar y no basta con refrescar

Cada tarjeta decide al construirse si su botón está encendido:

```python
eligible = role != "SIN ROL" and self.draft_count > 0
```

Así que cruzar el cero cambia lo que hay que construir, no solo cómo se ve.
Refrescar los botones dejaba seis tarjetas apagadas con drafteos disponibles.

Ahora se repinta la página, **en las dos direcciones**: gastar el último drafteo
también vuelve a apagarlas. Y de 3 a 4 no se repinta nada, porque ahí no cambia
la forma.

`_render_role_step` queda sin llamantes. Una prueba recorre `app/` y falla si
alguien vuelve a invocarlo: cualquier llamada nueva reviviría exactamente este
fallo.

1936 passed, 1 skipped.

# v0.3.0-alpha.1 — empieza la 0.3: que se vea y que se oiga

La 0.2.6 se fue en velocidad y en pruebas. La 0.3 empieza por lo contrario: que
mover un Pokémon **se vea moverse** y que la interfaz responda con algo más que
un cambio de píxeles.

## El Pokémon vuela

Mover uno entre el equipo y el PC cambiaba en seco: desaparecía de un sitio y
aparecía en otro. Sin nada que seguir con la vista, hay que reconstruir
mentalmente qué ha pasado.

Ahora el sprite recorre el camino en **300 ms**, con arranque suave, frenada al
llegar y un arco que crece con la distancia —entre paneles se nota, entre dos
casillas vecinas apenas—. Vuela sobre la ventana y no dentro de los paneles,
porque tienen scroll y recortarían el recorrido.

Esos 300 ms no se suman a la espera: **la tapan**. La parte inmediata del
movimiento son 90 ms y la escritura al juego unos 400, así que el vuelo ocurre
mientras se escribe.

Se anima la **posición y nunca el aspecto**: mover un widget es barato, pero
reconfigurar colores cuesta 0,8–1,4 ms medidos y a sesenta fotogramas por
segundo eso no cabe. Y todo vuelo se puede parar: un sprite huérfano se quedaría
pegado en mitad de la pantalla.

## Suena

Seis efectos —roce, selección, confirmación, error, y dos para el drafteo— que
**se sintetizan solos** la primera vez en `Documentos\RoleRun Manager\Sonidos`.
No hacen falta archivos ni licencias, y suenan desde el primer arranque.

Y son sustituibles: **si dejas ahí un WAV con el mismo nombre, se usa el tuyo**.
Los generados no se vuelven a escribir si el archivo ya existe.

Dos frenos que no son opcionales:

- **el ratón**: una caja del PC son treinta casillas y se recorren en menos de un
  segundo. Sin un mínimo de 60 ms entre sonidos, eso es una ametralladora.
- **los avisos**: un solo movimiento pasa por «confirmado» **tres veces** —al
  preparar, al escribir y al releer el PC—. Sin freno serían tres campanitas por
  arrastre.

Suenan en un hilo aparte: `winsound` bloquea al llamante, y el llamante sería el
hilo de Tk. Un tirón en cada paso del ratón por la caja del PC se notaría justo
donde más.

Nada de esto puede estorbar: un sonido que no se puede reproducir se traga en
silencio, y un vuelo que no se puede hacer no impide el movimiento.

1931 passed, 1 skipped.

# v0.2.6-alpha.117 — mirar la pila, no quién tiene el foco

Dos fallos de la versión anterior, y el segundo era de fondo.

## RoleRun desaparecía del todo

En modo flotante la ventana principal está retirada, así que esconder la barra
dejaba a RoleRun **sin ninguna ventana y sin icono en la barra de tareas**.

Ahora, al esconderla, la ventana principal se minimiza: sigue estando ahí para
volver a ella. Al destaparse el juego, vuelve a retirarse y solo se ve la barra,
como debe ser.

Y esa minimización no puede reabrir la barra por el camino de siempre —minimizar
a mano equivale a entrar en la barra—, porque la pondría justo encima de lo que
está tapando el juego.

## Preguntaba por la ventana equivocada

La comprobación miraba **la ventana con foco**. Con un navegador puesto delante
del juego, pinchar en la otra pantalla dejaba activa una ventana que no solapa
nada… y la barra reaparecía **encima del navegador**, tapando el juego igual.

El estorbo sigue donde estaba aunque pierda el foco. Así que ahora se recorre la
**pila de ventanas** por encima del juego —`GetWindow` con `GW_HWNDPREV`— y se
mira cuánto lo tapan las que están visibles, no minimizadas y con superficie,
saltándose las del propio juego y las de RoleRun, que están encima por diseño.

Se devuelve la mayor tapadura y no la suma: dos ventanas encima pueden solaparse
entre sí, y sumar contaría dos veces la misma zona.

1913 passed, 1 skipped.

# v0.2.6-alpha.116 — guardar un fallo sin parar el directo

Dos cosas para poder jugar en directo sin ir reportando sobre la marcha.

## Un botón para guardar el fallo

Contar un fallo al terminar el directo pierde justo lo que hace falta: la hora
exacta, qué había en pantalla y qué estaba leyendo o escribiendo RoleRun en ese
momento.

**F8** —de fábrica, sin configurar nada— deja una carpeta con todo eso. No
pregunta nada ni saca al usuario de lo que estaba haciendo:

| | |
|---|---|
| `pantalla.png` | lo que se veía |
| `contexto.json` | versión, juego, página, equipo con PS y movimientos, cambios pendientes |
| `bdsp_trace.jsonl` | la cola de la traza del juego en vivo |
| `tiempos.jsonl` | la cola de la medición de tiempos |
| `nota.txt` | para escribir después, si apetece |

Se acumulan en `Documentos\RoleRun Manager\Bugs`, y al terminar se entregan
todas juntas.

El atajo global es lo más orgánico mientras se juega: el emulador está delante y
no hay que cambiar de ventana. El menú flotante lleva además un **GUARDAR
FALLO** para cuando el fallo sea de RoleRun; ese cierra el menú primero, para que
la captura recoja lo que había debajo y no el propio panel.

**Nada de esto puede tumbar la partida.** Si una parte del informe falla —la
captura, un registro, leer el equipo— se anota dentro del propio informe y las
demás se guardan igual. Un informe incompleto sirve; perder lo que estabas
haciendo por intentar guardarlo, no.

## La barra flotante solo se retira si tapan el juego

Cambiar de ventana no basta: con dos monitores, mirar el navegador en el segundo
deja el juego a la vista y la barra sigue haciendo falta.

La decisión se toma con la **geometría**, no con el foco. Las coordenadas de
ventana son del escritorio completo, así que dos ventanas maximizadas en
pantallas distintas no se solapan nunca. Si la ventana activa cubre **un cuarto
o más** del juego, la barra se retira y RoleRun se queda como estaba; al volver
al juego, vuelve sola.

Ese umbral deja pasar una calculadora en una esquina (0,019) y no un navegador
encima (0,781), ambos medidos.

Se distingue de haberla cerrado a mano: volver a la ventana principal la retira a
propósito y entonces no vuelve sola. Y el sondeo sigue vivo mientras está
escondida, porque en modo flotante la ventana principal está retirada y nada más
la traería de vuelta.

1911 passed, 1 skipped.

# v0.2.6-alpha.115 — el latido no vale sin saber quién tiene la ventana

Con el reloj ya puesto, el usuario enseñó otra MT y **no se congeló**. La traza
registró esto alrededor de la escritura:

```
16:41:09.5   reloj 10:52:21
16:41:12.0   ESCRITURA        reloj 10:52:21
16:41:16.0   reloj 10:52:21     ← 6,5 s sin avanzar
16:41:16.8   reloj 10:52:22     ← se reanuda
```

Parecía un hallazgo. No lo era: mirando la sesión entera, el reloj llevaba
parado **24,5 segundos**, desde las 16:40:52 —antes incluso de que RoleRun leyera
las MT— y se reanudó al volver el usuario al juego.

**El reloj también se para cuando el emulador pierde el foco.** Como latido, eso
lo inutiliza: no distingue un juego colgado de alguien mirando otra ventana, que
es exactamente la pregunta.

## El discriminador

Cada captura anota ahora también **qué proceso tiene la ventana activa**. Con las
dos señales el tramo deja de ser ambiguo:

| reloj | foco | qué es |
|---|---|---|
| parado | del juego | **colgado** |
| parado | de otra ventana | normal: el emulador está en pausa |
| parado | no se sabe | no se puede decir, y decirlo **es** la respuesta |

Esa tercera fila es deliberada. Las trazas anteriores a esta versión no anotaban
el foco, y darlas por pausas normales sería inventarse el resultado.

`app/ventana_activa.py` solo le pregunta a Windows por la ventana de primer
plano y de qué proceso es: no abre ningún handle ni lee memoria.

## Cómo se usa

`ver_congelados_bdsp.bat` lee la traza y dice si hubo algún tramo parado **con el
juego delante**, cuánto duró y en qué segundo se quedó el reloj, además de listar
las escrituras con su reloj, su foco y qué se escribió.

## Lo que sabemos del congelado

Es **intermitente**: la misma operación, sin haber cambiado nada de la escritura,
unas veces cuelga el juego y otras no. Eso descarta un dato mal formado —eso
fallaría siempre— y apunta a una carrera con el hilo del juego.

1888 passed, 1 skipped.

# v0.2.6-alpha.114 — un latido, para que el congelado se pueda datar

El problema de fondo al investigar el congelado no era la falta de hipótesis:
era que **la traza no podía ver un juego parado**. Tras la escritura de la MT
siguió leyendo con normalidad 68 segundos, porque un juego congelado se ve
exactamente igual desde fuera —proceso vivo, memoria legible— y con el personaje
quieto ni los PS ni el equipo cambian.

## Lo que se encontró leyendo

`buscar_latido_bdsp.bat` lee tres veces `PlayerWork._saveData` con pausas y
señala qué avanza solo. Con el personaje quieto en el mapa, de 16.384 bytes
**cambió uno**. Ese:

| | | |
|---|---|---|
| `SaveData+0x118` | u16 | horas (`0x000A` = 10) |
| `SaveData+0x11A` | u8 | minutos (`0x28` → `0x29` al pasar de 59 s) |
| `SaveData+0x11B` | u8 | segundos: 39, 41, 43 … 59, **0**, 2, 4 |

Es el reloj del juego. Da la vuelta en 59, sube el minuto al hacerlo, y **solo
avanza si el juego está corriendo de verdad**.

## Dónde queda

En **cada captura** y en **cada escritura**. Si el reloj se repite entre dos
capturas, el juego está parado, y la traza dirá el segundo exacto. Si se para
justo en la escritura, la escritura es la culpable; si sigue un rato y se para
después, hay que buscar en lo que el juego hizo luego.

La lectura nunca propaga: es una señal de diagnóstico y no puede tumbar una
captura real. Un `None` en la traza significa «no se pudo leer», que ya es
información.

## Las dos hipótesis caídas hasta ahora

- **La mochila.** RoleRun solo escribe la cantidad, así que al gastar la última
  MT el registro queda con cantidad 0 conservando su orden. La partida ya tiene
  **siete** registros así: los hace el juego.
- **Los PP.** `_set_move` escribe el movimiento, PP Ups a 0 y los PP al valor
  base, que es exactamente lo que hace `CoreParam.SetWaza`.

1880 passed, 1 skipped.

# v0.2.6-alpha.113 — el juego se congela al enseñar una MT: qué se descartó

El usuario enseña una MT desde RoleRun y **el juego se queda congelado**, hay que
reiniciar Ryujinx. Aquí no se arregla nada todavía: se descarta una hipótesis
midiendo y se deja el rastro para la próxima.

## Lo que dice la traza

La escritura se verificó a las 16:20:51 y tocó dos sitios: el core PB8 del
Pokémon (328 bytes) y **un registro de 12 bytes de la mochila**. Después RoleRun
siguió leyendo el juego **con normalidad durante 68 segundos** —90 capturas
seguidas, sin un solo fallo— hasta que el usuario reinició Ryujinx.

Eso no exonera a la escritura: un juego congelado se ve exactamente así desde
fuera. Su proceso sigue vivo y su memoria sigue siendo legible.

## La hipótesis que parecía buena, y era falsa

Curar y cambiar roles escriben el core PB8 y nunca han congelado el juego. Lo
único nuevo al enseñar una MT es la mochila. Y un registro de `saveItem` es:

```
0..3   cantidad (int32)
4      vanish_new    5  favorito    6  mostrar movimiento
7..9   relleno (tiene que ser 0)
10..11 orden en la mochila (uint16)
```

RoleRun **solo escribe la cantidad**. Al gastar la última MT, el registro queda
con cantidad 0 conservando su orden — parecía un estado que el juego nunca crea.

**Medido con `mirar_mochila_bdsp.bat`, que solo lee: la partida ya tiene siete
registros así.** El juego los produce él solo. La hipótesis se cae.

## Lo que queda

`mirar_mochila_bdsp.bat` se queda como herramienta: lee la mochila viva y enseña
cada registro tal cual está en memoria, sin escribir nada.

Y la traza de escritura deja de decir solo «applied_count: 1»: ahora anota **qué
se pidió escribir** —tipo de cambio, Pokémon, hueco de movimiento, número de MT,
objeto y cantidad previa—. Saber que se aplicó «un cambio» no permite volver
sobre una escritura que congeló el juego.

1875 passed, 1 skipped.

# v0.2.6-alpha.112 — la casilla se destruía y luego reventaba

`build_fixed_team_slots` devuelve una **tupla**. El repintado por casillas hacía
`self.team_slots[index] = team_slots[index]`, que en una tupla lanza
`TypeError`… justo **después** de haber olvidado y destruido la tarjeta anterior.

Resultado en la máquina del usuario: al sacar un Pokémon del equipo, su casilla
**desaparecía** junto con su destino de soltar. Arrastrar otro desde el PC hasta
ese hueco no encontraba dónde soltarlo. La reconstrucción que venía detrás lo
arreglaba, y de ahí el «al probar varias veces, al final una sí que me ha
dejado».

En la medición salía tres veces como «no se pudo repintar una casilla», porque
un `except Exception` se la tragaba sin decir cuál.

## Tres arreglos

1. La vista guarda sus casillas en una **lista**, que es lo que un repintado por
   casillas necesita.
2. **El destrozo no puede preceder al fallo.** La casilla nueva se apunta antes
   de destruir la vieja, para que un error a mitad no deje un hueco.
3. La excepción deja de ser muda: se anota con su tipo y su mensaje.

## Y las pruebas pasan tuplas

Usaban listas. Por eso pasaban con el código roto. Ahora `_equipo()` devuelve una
tupla, igual que el programa: con el código anterior, **seis** de las doce
pruebas de casillas fallan.

## Lo que no es un fallo

Mover un Pokémon de una posición del PC a otra en Perla Reluciente dice «DESTINO
NO HABILITADO», y está bien: RoleRun no tiene una escritura PC→PC demostrada
para ese juego y **no escribe lo que no ha demostrado**. Los intentos anotados
como `pc -> pc` en la medición eran eso, no arrastres fallidos.

1875 passed, 1 skipped.

# v0.2.6-alpha.111 — otra cascada, y el arrastre deja rastro

La medición del usuario tras el repintado por casillas:

```
actualizadas en sitio ......... 24
reconstruidas ................. 14

    7 x  otra forma de equipo
    5 x  arrancando
    1 x  vista a medio componer
```

Antes eran **0 en sitio y 30 reconstrucciones**. Y la parte que se nota al
soltar —lo que ocurre con la interfaz congelada— pasó de **1017 ms a 90**.

## «Vista a medio componer» era otra cascada

Igual que la anterior, y del mismo tipo. `is_fully_composed` exige que la
geometría **haya dejado de moverse**, y la escalera de composición tarda un par
de fotogramas. El refresco siguiente llegaba a los 4 ms de terminar la
reconstrucción, se encontraba la vista «a medio componer» y reconstruía otra vez.

Esa exigencia es de la **barrera de arranque** —allí importa que nada se siga
recolocando antes de publicar la primera página—, no de cambiar unos datos.
Ahora el refresco en sitio usa una comprobación más ligera: los cuatro paneles
existen, están mapeados y tienen tamaño.

## Siete motivos sin nombre

«Otra forma de equipo» tapaba tres pasos distintos. `refrescar_en_sitio` pasa a
devolver **cuál** falló —«no se pudo repintar una casilla», «una tarjeta no se
pudo actualizar», «fallo al refrescar el PC o la ficha», «otro numero de
casillas», «modo banner»— en vez de un `False`. Reconstruir cuesta hasta 987 ms:
un motivo sin nombre es medio segundo que no se puede atribuir a nada.

## El arrastre deja rastro

El usuario dice que a veces no le deja arrastrar del PC al equipo. En la
medición **sí funcionó** (`box-to-party`, SOLTAR #2) y en una simulación con Tk
también, así que no hay nada que adivinar: ahora se anota cuándo un arrastre no
llega a empezar y por qué, cuándo se pierde sin destino, y la razón exacta por la
que un destino queda «no habilitado».

1873 passed, 1 skipped.

# v0.2.6-alpha.110 — repintar la casilla, no la página

Tras cortar la cascada, el arrastre bajó de 4,5 s a 3,4. Las tres
reconstrucciones que quedaban tenían **la misma raíz**, y son dos cosas:

## 1. El PC no tiene una sola caja porque se esté releyendo

Escribir en el juego invalida el PC en caché —a propósito: lo que había ya no es
de fiar—. Pero la página se dibujaba entonces con **una** caja en vez de
dieciocho, y al volver la lectura cambiaba de forma otra vez. Dos
reconstrucciones por eso: «sin datos del PC» y «otro numero de cajas».

Cuántas cajas tiene el PC y de qué tamaño es del **juego**, no de la lectura.
Ahora se recuerda, así que la navegación de cajas no se encoge y se estira, y la
forma queda estable.

La negativa existía además porque es el repintado completo quien **programa** la
lectura de las cajas: atajar ahí dejaría el PC sin cargarse nunca. Esa cola pasa
a una función que llaman los dos caminos, así que ya no puede divergir.

## 2. Cambiar de equipo repinta la casilla, no la página

`refrescar_en_sitio` solo sabía cambiar datos: en cuanto la forma del equipo era
otra devolvía `False`. Y sacar un Pokémon del equipo **siempre** cambia la forma.

Ahora se rehacen solo las casillas cuya terna —rol, estado, ocupante— haya
cambiado. Medido con Tk de verdad:

| | |
|---|---|
| reconstruir la página | 456–987 ms |
| **sacar un miembro del equipo** | **35 ms** |
| volver a meterlo | 77 ms |
| un refresco que no cambia nada | 16 ms |

## Lo delicado no era la ganancia

Una casilla repintada tiene que soltar **todo** lo que la identidad anterior dejó
registrado —marco, barra de PS, widgets de la tarjeta, destino de soltar, botón
de rol, marca de preparación—, porque esos registros los recorren después el
arrastre, los estilos de selección y la barrera de arranque. Un registro que
sobreviva a su widget apunta a un árbol muerto.

Y la evidencia de PS pasa de lista a diccionario por casilla: en una lista,
repintar una casilla suelta **añadía** una fila en vez de sustituirla, y la firma
acababa con siete. Hay una prueba que repinta ocho veces y exige que sigan siendo
seis.

Siete pruebas nuevas sobre la vista real bajo Tk comprueban que no quede ningún
marco huérfano ni ningún destino de soltar apuntando a un widget destruido.

1870 passed, 1 skipped.

# v0.2.6-alpha.109 — un resumen, una sesión

El JSONL de tiempos es uno por día y se abre en modo añadir, así que un día de
trabajo mezcla todas las sesiones en el mismo archivo. El resumen las sumaba:
la primera medición dio 30 reconstrucciones y la siguiente 40, cuando la sesión
nueva había hecho **10**.

Con las cifras sumadas no hay forma de saber si un arreglo funcionó, que es
justo para lo que se mide.

RoleRun deja ahora una marca `sesion.inicio` al abrirse, y `ver_lentitud.bat`
corta ahí. Las mediciones anteriores a la marca se cortan por el silencio largo
que deja cerrar el programa y volver a abrirlo.

1860 passed, 1 skipped.

# v0.2.6-alpha.108 — una reconstrucción obligaba a la siguiente

Con los motivos completos, el arrastre queda explicado entero. Del equipo al PC,
en BDSP:

| desde que sueltas | | |
|---|---|---|
| 0 ms | sueltas | |
| 33 ms | reconstruye — «sin datos del PC» | 983 ms |
| 1464 ms | **el juego confirma** | **419 ms** |
| 1718 ms | reconstruye — «sin datos del PC» | 1078 ms |
| 2804 ms | reconstruye — «vista no publicada» | 836 ms |
| 3644 ms | reconstruye — «vista no publicada» | 826 ms |
| 4471 ms | fin | |

**4,5 segundos, de los que 3,7 son cuatro reconstrucciones.** Escribir en el
juego son 419 ms.

## La cascada

Las dos últimas —1,66 s— eran culpa mía y de nadie más.

`_presented_team_pc_view` lo pone `retire_old_body`, que va con `after(70, …)`
porque destruir el body anterior en el mismo callback deja un parpadeo. Yo exigí
esa marca para poder actualizar en sitio. Resultado: **durante 70 ms después de
cada reconstrucción, la vista recién construida «no está publicada»**, así que el
siguiente refresco reconstruía también… y abría otra ventana de 70 ms. En la
medición los refrescos llegan a los **8 ms**.

Cada reconstrucción se obligaba a sí misma a tener una detrás.

Lo que de verdad hay que comprobar es que la vista esté en pantalla, y de eso ya
se encarga `is_fully_composed`: exige que el marco y los tres paneles existan,
estén mapeados y tengan tamaño. La marca de `retire_old_body` es la frontera que
necesita la **barrera de arranque** —excluida aquí por el motivo «arrancando»—,
no esta.

## Lo que queda, y por qué no se toca todavía

Las dos primeras reconstrucciones **sí** están justificadas: el equipo pasa de
seis miembros a cinco y de cinco a cuatro, y el camino en sitio solo sabe cambiar
datos, no composición.

Y «sin datos del PC» seguirá refusando aunque la forma coincida, porque es
`_render_team_pc_unified_page` quien programa la lectura de las cajas: atajar ahí
dejaría el PC sin cargarse nunca. Queda anotado en el código.

1857 passed, 1 skipped.

# v0.2.6-alpha.107 — 30 reconstrucciones, 8 motivos

La medición trajo el número que faltaba y, de paso, un fallo mío de método:

```
actualizadas en sitio ......... 3
reconstruidas ................. 30   (mediana 721 ms, total 26,5 s)

    5 x  arrancando
    2 x  sin datos del PC
    1 x  vista no publicada
```

**Ocho motivos para treinta reconstrucciones.** Las otras veintidós se negaron en
las cinco condiciones que estaban escritas en línea dentro del `if`, y Python
cortocircuita el `and`: nunca llegaban a la función que anota. Veintidós
reconstrucciones —unos quince segundos— sin poder atribuirlas a nada.

Las cinco pasan a la misma función que las nueve interiores: un solo sitio
decide y un solo sitio anota. Y una prueba lee el código fuente y falla si alguna
vuelve a escribirse en línea, porque el error no se ve —el programa funciona
igual, solo deja de explicarse—.

## El reparto de esa sesión

| operación | veces | mediana | total |
|---|---|---|---|
| `ui.smooth_render_page` | 30 | 1005 ms | **27,0 s** |
| `ui.render_page` | 30 | 721 ms | 26,5 s |
| `ui.team_pc.construir_vista` | 28 | 711 ms | 22,7 s |
| `ui.finish_team_pc_load` | 8 | 1016 ms | 7,1 s |
| `ui.finalize_live_changes` | 5 | 1209 ms | 6,1 s |
| `realtime.apply_changes` | 5 | 351 ms | 1,2 s |
| `ui.save_live_changes` | 5 | 25 ms | 0,1 s |

Escribir en el juego —las dos últimas filas— es **1,3 segundos de los 27**.

Y `ui.smooth_render_page` cuesta 284 ms más que el `render_page` que envuelve:
es el doble buffer, que resuelve la geometría del árbol nuevo y restaura el
scroll con varios `update_idletasks` sobre 642 widgets recién creados.

1856 passed, 1 skipped.

# v0.2.6-alpha.106 — los 4-5 segundos son 21 reconstrucciones

Ya está medido en la máquina del usuario, con BDSP. Soltando un Pokémon del
equipo al PC:

| desde que se suelta | qué pasa |
|---|---|
| **+846 ms** | reconstrucción entera, **dentro del propio `drop`** y por tanto con la interfaz congelada |
| +1124 ms | la escritura se envía (`save_live_changes`: 26 ms) |
| +1552 ms | el emulador confirma (`realtime.apply_changes`: **428 ms**) |
| **+2716 ms** | segunda reconstrucción entera, en `finalize_live_changes` |
| **+3640 ms** | tercera reconstrucción entera, en `finish_team_pc_load` |

**La escritura al juego no es el problema: son 428 ms.** El resto lo pone la
interfaz rehaciéndose tres veces, a 626–937 ms cada vez.

En toda la sesión —cuatro arrastres— hubo **21 reconstrucciones que suman 18,7
segundos**, contra 3 refrescos en sitio.

## Por qué una reconstrucción cuesta casi un segundo

Perfilada la construcción de la vista con Tk real, por cada una:

- **30.255 llamadas a Tcl**;
- **268 ms** dentro de `__draw_rounded_rect_with_border_font_shapes`, que es
  customtkinter dibujando esquinas redondeadas;
- 145 ms moviendo coordenadas de canvas.

No hay micro-optimización que arregle eso: el coste **es** el número de widgets.
La única salida es dejar de reconstruir.

## Lo que se añade aquí

El camino rápido ya existe y cuesta 37 ms, pero se negó en las 21. No dejaba
dicho por qué. Ahora **cada negativa anota su motivo** —«sin datos del PC»,
«otro numero de cajas», «otra forma de equipo», «arrancando»…— y
`ver_lentitud.bat` los cuenta.

Es la diferencia entre arreglarlo y adivinar: cada motivo que aparezca en esa
lista son segundos de espera con nombre y sitio.

## El .bat estaba roto

`ver_lentitud.bat` se generó con `printf`, y el `` de `toolser_lentitud.py`
se convirtió en un tabulador vertical: quedó `toolser_lentitud.py`. El usuario lo
ejecutó y no salió nada.

Como todos los diagnósticos se le entregan como `.bat` de doble clic, un `.bat`
roto cuesta el viaje entero. `test_bats_apuntan_a_algo.py` comprueba ahora que
ningún `.bat` lleve caracteres de control y que todo script que invoque exista.

1854 passed, 1 skipped.

# v0.2.6-alpha.105 — partir los 2585 ms de un repintado

La sesión de BDSP del usuario, sin llegar a arrastrar nada, ya dejó un hallazgo
grande:

| operación | veces | cada una |
|---|---|---|
| **`ui.render_page`** | 2 | **2585 ms** |
| `realtime.capture_full` | 1 | 1193 ms |
| `ui.smooth_render_page` | 4 | peor 820 ms |
| `engine.run` | 5 | 188 ms |

Construir la vista entera con Tk, medido aparte en este mismo equipo, son 660 ms.
Faltaban casi dos segundos por explicar, y no se van a adivinar: `render_page`
queda partido en fases con nombre —menú lateral, estado superior, navegación
contextual y cuerpo— y el cuerpo de Equipo y PC en cinco más: party proyectada,
casillas fijas, datos del PC, miembros de la caja y construcción de la vista.

El reparto por página sale de `render_page` a `_render_page_body` para poder
cronometrarlo solo a él.

## El resumidor mezclaba peras con manzanas

`ui.poll_gamepad` aparecía como la operación más cara de la sesión, 3832 ms.
No lo es: corre a 60 Hz y se anota **resumido por ventana de un segundo**, así
que su `ms` es el total de la ventana, no el de una llamada. Son 0,48 ms por
llamada, 59 por segundo.

Ahora las de alta frecuencia van en su propia tabla, con coste por llamada,
llamadas por segundo y el peor pico. Ahí sí se ve algo: un pico de **116 ms** en
el sondeo del mando.

1849 passed, 1 skipped.

# v0.2.6-alpha.104 — BDSP colgado en «Preparando Equipo y PC…»

Lo rompí yo en la alpha.100. El trazado de la barrera de arranque lo dijo exacto,
sin necesidad de suponer nada:

```
esperado    [67,67] [66,66] [58,58] [58,58] [70,70] [74,74]
renderizado [74,74] [67,67] [66,66] [58,58] [58,58] [70,70]
```

No era un dato viejo. Era la **misma lista rotada una posición**.

## Qué pasaba

`rendered_team_health_signature` ordena por la posición física del Pokémon,
porque las tarjetas se presentan por rol y el reader publica por posición. Esa
firma es la evidencia que la barrera de arranque compara contra la party
proyectada antes de publicar la primera página.

`update_team_health` reescribía los PS **conservando la posición de cuando se
construyó la tarjeta**. Era correcto mientras solo refrescaba barras de una vista
recién hecha. Desde que la tarjeta se actualiza entera sin reconstruirse, esa
posición se queda obsoleta en cuanto el equipo llega reordenado: cada tarjeta
enseña lo suyo, pero la firma sale permutada.

Y la barrera de arranque no publica por timeout **a propósito** —«el fallo no se
disfraza como una UI utilizable»—, así que se quedaba esperando para siempre.

## Los tres arreglos

1. **La tarjeta apunta la posición de ahora** junto a los PS de ahora.
2. **La ruta de PS en vivo, también.** Estaba el mismo fallo latente desde antes:
   comprueba las identidades **como conjunto**, así que los mismos seis
   reordenados pasan el filtro y llegan a actualizar barras. Hasta ahora nadie lo
   había disparado.
3. **El camino rápido no entra mientras la barrera de arranque espera.** Esa
   comprobación verifica evidencia de lo que la vista materializó; ahí hay que
   reconstruir, que es lo que sabe validar. Un arranque colgado para siempre es
   mucho peor que 300 ms.

De paso: si los PS no se pueden poner, la tarjeta ya no dice que sí. Es lo único
que no pinta por sí misma, y devolver «hecho» dejaba en pantalla los PS del
Pokémon anterior.

## Pruebas

`test_firma_de_ps_sigue_al_equipo.py` reconstruye las dos filas del trazado con
sus cifras: con la posición de ahora sale la lista correcta, y sin ella sale la
rotación exacta que colgó el arranque. Esa segunda prueba existe para que la
primera tenga dientes.

1848 passed, 1 skipped.

# v0.2.6-alpha.103 — el mismo hallazgo, en los otros 29 sitios

En Equipo y PC, comparar antes de escribir bajó un refresco de 376 ms a 37, y
el hover de una tarjeta de 135 ms a nada. El patrón que lo causaba —«repinta
todos los elementos para mover un único resalte»— no era exclusivo de esa
vista: buscándolo por AST aparecen **29 sitios más**, y casi todos cuelgan de
una tecla o del ratón.

## Qué se movía

| dónde | cuándo se dispara |
|---|---|
| menú lateral y menú flotante | cada flecha |
| botones de navegación | cada repintado de página |
| rejilla de MT, compatibilidad del equipo, resalte de MT | cada cambio de selección |
| rol, Pokémon y movimiento de Drafteos | cada elección |
| selectores de rol, de estadísticas y de baja | cada clic |
| contadores de cabecera y avisos de atajos | cada actualización |

## Lo que cuesta mover un resalte

Medido con customtkinter en el equipo del usuario, moviendo el resalte una
posición dentro de una rejilla:

| elementos | repintar todo | comparar antes |
|---|---|---|
| 8 | 13,05 ms | **3,17 ms** |
| 30 | 46,64 ms | **3,16 ms** |
| 100 | 153,93 ms | **3,34 ms** |

Lo importante de esa tabla no es el factor: es que la columna de la derecha **no
crece**. Se escriben los dos elementos que cambian, y da igual que la rejilla
tenga ocho o cien.

## Por qué una función y no un parche global

Sería más corto sustituir `CTkBaseClass.configure` de una vez. No se hizo a
propósito: un cambio silencioso dentro de la biblioteca haría que algún widget
dejara de repintarse en un caso que no conocemos —cambio de tema, geometría,
imagen recreada— y el síntoma sería «no se ve el cambio», que es peor que ir
lento. `app/ui_components/repintado.py` es explícito y se ve en cada sitio.

## La guardia

`test_solo_se_escribe_lo_que_cambia.py` recorre `app/` entera por AST y falla si
vuelve a aparecer un `configure` con opciones de color dentro de un bucle. El
patrón vuelve solo, porque al escribirlo lo natural es repintarlo todo.

1841 passed, 1 skipped.

# v0.2.6-alpha.102 — medir los 4-5 segundos antes de tocarlos

Con el repintado ya en 37 ms, mover un Pokémon del equipo al PC sigue tardando
4-5 segundos. Eso no es repintado, así que **no** se toca nada hasta saber dónde
están esos segundos, y el único sitio donde se puede saber es en la máquina del
usuario con su juego.

`app/perf.py` ya existía y sigue apagado salvo con `ROLERUN_PERF=1`. Lo que
faltaba eran las marcas del camino de soltar:

- el instante exacto en que se suelta, con origen y destino;
- qué operación se decidió (`party-to-box`, `move-box-slot`, …);
- cuánto tarda la parte síncrona;
- **cada vez que la escritura viva se reprograma**, y por qué —hay un bucle de
  220 ms que espera a que termine otra escritura, una sincronización, el
  monitor o la carga de MT—;
- cuánto tarda la escritura y cuánto su cierre;
- cada cambio del rótulo de estado, que es donde el usuario para el reloj;
- si un repintado tomó el camino rápido o reconstruyó.

## Cómo se usa

1. `medir_lentitud.bat` — abre RoleRun midiendo. Hacer justo lo que va lento.
2. Cerrar RoleRun.
3. `ver_lentitud.bat` — imprime la línea de tiempo de **cada** vez que se soltó
   un Pokémon, con los milisegundos desde el instante de soltar, y el reparto
   por operación de toda la sesión.

Ninguno de los dos cambia nada de la Run: solo miden y leen.

## Por qué el resumidor tiene pruebas

Se ejecuta **una sola vez**, después de una sesión entera midiendo. Si revienta
ahí se pierde esa sesión y hay que volver a pedir que se reproduzca lo lento.
Las dos formas concretas de romperse están fijadas: la consola de un `.bat` es
cp1252 —un carácter fuera de esa tabla no sale mal, corta la salida entera— y el
JSONL puede acabar con una línea a medias, porque lo vuelca un hilo demonio cada
segundo y cerrar el programa puede cortarla.

1840 passed, 1 skipped.

# v0.2.6-alpha.101 — escribir cuesta, comparar no

La versión anterior dio por hecho que lo caro era **crear** widgets. Medido de
punta a punta sobre la vista real, con los seis miembros y una caja entera
cambiando de datos, resultó ser menos de la mitad de la historia:

| | antes | ahora |
|---|---|---|
| destruir y reconstruir la vista | 660 ms | — |
| refrescar en sitio | 376 ms | **37 ms** |

Los 376 ms se repartían así: 86 las seis tarjetas, **183 la rejilla del PC** y
**135 los estilos de selección**. Y la rejilla del PC ya reutilizaba sus
casillas, así que ahí no se estaba creando nada.

## Dónde estaba

En `configure`. Medido con customtkinter en el equipo del usuario:

| operación | coste |
|---|---|
| `configure` de un CTkFrame con 4 colores | 1,445 ms |
| `configure` de un CTkButton con 5 opciones | 0,844 ms |
| `configure(text=…)` a secas | 0,047 ms |
| leer esas mismas opciones con `cget` | **0,001 ms** |

Cualquier opción de color obliga a customtkinter a repintar el canvas entero,
**cambie o no el valor**. Y en un refresco normal casi nada ha cambiado.

Ahora hay un `_configurar_si_cambia` que compara primero y solo envía las claves
distintas. Comparar sale mil veces más barato que escribir, así que el peor caso
—que haya cambiado todo— cuesta lo mismo que antes, y el caso normal, nada.

## El peor caso medido no era un repintado

Era pasar el ratón. `_apply_selection_styles` reconfigura las seis tarjetas del
equipo y las treinta casillas del PC para mover un único borde, y está enganchado
al `<Leave>` de cada tarjeta. **135 ms cada vez que el cursor sale de una
tarjeta.** Con la comparación delante, solo se repintan las dos casillas que de
verdad cambian de borde.

Es, con diferencia, lo que más se va a notar: no hacía falta ni pulsar nada.

## Alcance

El ayudante se usa en los cuatro sitios que se repiten muchas veces por
operación: las tarjetas del equipo, los PS, las casillas del PC y los estilos de
selección. Lo que se pinta una sola vez sigue como estaba.

Queda la ficha del inspector, que se rehace entera —15 ms— y ahora es la pieza
más grande de los 37 que cuesta un refresco.

## Pruebas

`tests/test_solo_se_escribe_lo_que_cambia.py` fija las dos mitades: que lo igual
no se escriba y que lo distinto sí, porque quedarse corto dejaría un dato viejo
en pantalla. La prueba de la rejilla del PC pasa de exigir cinco reconfiguraciones
a exigir **cero** cuando el aspecto no cambia, y una cuando sí.

1833 passed, 1 skipped.

# v0.2.6-alpha.100 — las tarjetas del equipo se actualizan, no se rehacen

Medido con customtkinter en el equipo del usuario, para una tarjeta del equipo:

| operación | una | las seis |
|---|---|---|
| construirla | 34,71 ms | **208 ms** |
| destruirla | 16,11 ms | 97 ms |
| **reconfigurarla entera** | **4,69 ms** | **28 ms** |

Hasta ahora cualquier refresco interno de *Equipo y PC* pasaba por
`_smooth_render_page`, que construye un body entero y llama a `render_page()`,
que vacía la superficie y la rehace. Los 305 ms de destruir y reconstruir el
equipo se pagaban enteros por cosas tan pequeñas como que terminara de bajarse
un sprite.

Ahora, cuando la página es la misma y solo han cambiado los datos, se cambian
los datos.

## Qué se actualiza

Todo lo que la tarjeta enseña: sprite, mote y nivel, la barra y el texto de PS,
las seis estadísticas con el color de su naturaleza, habilidad, objeto y los
cuatro movimientos con su marcado —alto, fondo, borde y color de texto—. Y
después la rejilla del PC, el rótulo de la caja y la ficha, que es exactamente
lo que ya refrescaba cambiar de caja.

## Qué frena el camino rápido

La vista se construye con unos botones, unos límites y un modo concretos que
este camino **no** rehace. En cuanto alguno cambiaría, se devuelve el control al
render normal:

- otra forma de equipo: otro rol, otro ocupante o otro estado en cualquiera de
  las seis casillas —de ahí dependen el icono del rol, el rótulo y el marco
  dorado de preparación—;
- aparece o desaparece **CURAR EQUIPO** o **FIJAR ROLES**;
- cambian las cajas o los huecos del PC, o todavía no hay datos del PC;
- la ventana se estrecha por debajo de 1160 y entra el modo compacto;
- modo de sustitución por debilitado, o modo banner;
- la vista aún no está compuesta, o no es la que Windows está enseñando;
- alguien pidió volver arriba o enfocar a un miembro: eso lo hace el render que
  mueve el scroll.

Un freno de más solo cuesta tiempo. Uno de menos deja la pantalla mintiendo.

## El dato viejo invisible

Lo delicado de actualizar en sitio no es que se olvide un `configure` —eso se
ve—, sino que quede una referencia vieja donde nadie mira. Las tarjetas
llevaban el Pokémon **metido en el cierre** del clic y del arrastre, y en el
diccionario del destino de soltar. Actualizada la tarjeta sin tocar eso, soltar
sobre ella habría movido al Pokémon anterior.

El Pokémon deja de vivir en el cierre y pasa a `_team_card_pokemon`, que se
consulta en el momento —el mismo arreglo que ya llevaba la rejilla del PC al
empezar a reutilizar sus casillas—. Y se reapunta **al final**, solo si toda la
parte visible ha ido bien: enseñar a uno y arrastrar a otro sería peor que no
acelerar nada.

De paso, un arrastre sin Pokémon ya no empieza. Los huecos vacíos del PC también
tienen el arrastre enganchado desde que sus botones se reutilizan entre cajas.

## Pruebas

`tests/test_team_card_update.py` actualiza una tarjeta con un Pokémon distinto
en todo y exige que **todos** los textos registrados cambien, además de leer el
código fuente para que ninguna clave que la tarjeta registra se quede sin tocar.
`tests/test_team_pc_refresh_in_place.py` cubre los frenos uno a uno y comprueba
que el camino rápido vuelve antes del doble buffer y no se salta lo que
`render_page()` hace fuera de él.

1826 passed, 1 skipped.

# v0.2.6-alpha.99 — la rueda donde no estaba, y fuera los plazos fijos

Cinco arreglos sobre el mismo síntoma, todos localizados leyendo el camino
completo de repintado.

## «Muchas veces está repintando algo y no aparece»

Era literal. De los **61 repintados** que pasan por `_smooth_render_page`, **uno
solo** recibía la superficie de navegación con rueda. Los otros sesenta recibían
`_create_page_transition_overlay`, que es una foto congelada y **muda**: aparecía,
pero sin nada moviéndose, y una imagen quieta trescientos milisegundos se lee
como que el programa se ha colgado.

Ahora esa superficie arranca la misma rueda. Y se para antes de destruirla, que
si no el worker pintaría sobre un HWND inválido.

*Hipótesis descartada por medición:* se sospechaba que poner `-alpha` convertía
la ventana en *layered* y la rueda nunca llegaba a pantalla. Comprobado con
`GetWindowLongW`: con alpha a 1.0 el exstyle pasa de `0x80` a `0x00`, sin
`WS_EX_LAYERED`. No era eso.

## «Se ve incompleta durante unos segundos»

`UnifiedTeamPCView` recolocaba con una escalera de reloj —`for delay in (0, 80,
180)`—: la página seguía moviéndose 180 ms después de estar pintada. Y como la
barrera tenía que taparlo, no se podía acortar.

Ahora los pases se encadenan a un fotograma y **paran en cuanto el alto medido
se repite**: dos o tres pases de unos pocos milisegundos en el caso normal, con
tope de ocho por si la geometría nunca se para. `is_fully_composed` pasa a
mirar esa condición en vez de contar tres pases de reloj.

## Los plazos fijos, que no dependían de nada

| | antes | ahora |
|--|-------|-------|
| devolver el control a Tk | 34 ms | 16 (un fotograma) |
| espera antes del fundido | 120 ms | 48 (tres) |
| fundido | 150 ms | 80 |
| **total por navegación** | **304 ms** | **144 ms** |
| barrera de un refresco interno | 140 ms | 32 |
| deslizamiento del menú lateral | 260 ms | 140 |

El menú no era solo animación: al elegir destino desde ahí, la navegación **no
arranca** hasta que el drawer termina de cerrarse. Y se animaba con un callback
cada 4 ms —unos 65— compitiendo con la construcción en el mismo hilo; ahora uno
cada 12.

## OBS se sincronizaba una vez por sprite

`_sync_obs_state` estaba **dentro** del bucle que vacía la cola de sprites. No es
ajustar un widget: escribe `state.json`, `slot.css`, `slot.js`, seis HTML de rol,
`paladin.html` e `INSTRUCCIONES_OBS.txt` por carpeta, y puede haber dos. Abrir una
Run con seis especies sin descargar disparaba eso **seis veces**, en el hilo de
Tk, justo mientras construía la página. Ahora una por lote, con prueba.

## Dos pantallas de carga que se quedaban colgadas

- La lectura viva del PC abandonada por cambio de sesión salía sin soltar
  `_team_pc_pc_loading`. Como `_start_team_pc_load` se niega a empezar con esa
  bandera puesta, **las cajas no volvían a cargarse en toda la sesión**: ventana
  opaca con rueda encima de un programa que por dentro ya no hacía nada.
- Un repintado que llegaba durante otro salía sin retirar la barrera que traía.

Suite completa: **1809**.

# v0.2.6-alpha.98 — la rejilla del PC reutiliza sus casillas

Primer paso contra las pantallas de carga: **no rehacer lo que ya está hecho**.

## Lo que cuesta construir, medido

Con customtkinter en el equipo del usuario:

| | |
|--|--|
| `CTkLabel` | 0,52 ms |
| `CTkFrame` | 1,35 ms |
| `CTkButton` | 1,69 ms |
| una tarjeta de equipo (19 etiquetas, 7 marcos, 1 botón) | **34,7 ms** |
| las seis del equipo | **208 ms** |
| destruirlas además | +97 ms |
| **reconfigurar una tarjeta entera** | **4,7 ms** |

Y una sospecha descartada: crear una `CTkFont` cuesta **0,008 ms**. Reutilizar
fuentes ahorraría 4 ms en trescientas etiquetas, así que no es por ahí.

## Cambiar de caja del PC

`_render_pc_grid` destruía sus treinta botones y los volvía a crear. Ahora los
reutiliza y solo los reconfigura:

    antes: destruir + crear ....... 37,4 ms
    ahora: reconfigurar ...........  5,9 ms

Lo delicado no era la ganancia sino el arrastre. `_bind_drag_tree` engancha con
`add="+"`, así que volver a enganchar un botón reutilizado apilaría manejadores:
a la sexta caja, un clic dispararía seis arrastres. Por eso el Pokémon de cada
hueco vive ahora en `_pc_slot_pokemon` y no en el cierre del manejador, y los
enganches se ponen **una sola vez**, al crear el botón. Hay una prueba que lo
vigila contando manejadores.

Un resultado de búsqueda o un aviso ocupan la misma rejilla con otra forma, así
que ahí sí se rehace: lo decide `_vaciar_rejilla_pc` con el modo.

## El diagnóstico de fondo

`render_page` hace `self._clear(self.body)`: destruye la página entera y la
reconstruye. Se dispara desde **63 sitios**. La pantalla de carga no infla el
tiempo —el diseño ya usa doble búfer— pero tapa una espera real de unos 300 ms.
Reutilizando widgets esa espera baja a decenas de milisegundos, y a esa velocidad
la pantalla de carga sobra, que es lo que el usuario quiere.

Suite completa: **1807**.

# v0.2.6-alpha.97 — cuarta fuera de la lista, y el sprite se redimensiona una vez

## Cuarta generación se oculta

Diamante/Perla, Platino y HeartGold/SoulSilver salen de la selección de juegos.
Leer funciona entero —equipo, cajas, dinero, medallas, MT, a 18 ms— pero
escribir no se puede garantizar: una escritura de 236 bytes no es atómica para
el juego emulado, y si mira el registro a medio escribir lo marca como «Huevo
malo» sin vuelta atrás.

Se **ocultan**, no se borran: el código está entero y probado, y sus etiquetas
siguen ahí para que una Run antigua conserve su nombre. Es un `frozenset` de tres
claves, así que volver a ofrecerlas es quitar una línea.

## El sprite se redimensiona una vez, no una por tarjeta

Medido con los sprites del proyecto, que son **PNG de 512×512**:

| | |
|--|--|
| `copy()` + `thumbnail` LANCZOS a 118 px | **3,77 ms por sprite** |
| devolver uno ya hecho | **0,00 ms** |

`sprite_pil_cache` guardaba el PNG decodificado, pero cada tarjeta hacía después
su propia copia y su propio LANCZOS:

- una caja del PC son treinta tarjetas → **113 ms** por repintado,
- el equipo son seis → **23 ms**,
- Equipo y PC enseña las dos cosas → **136 ms** cada vez,
- y la página se repinta **entera** cada vez que termina de bajar un sprite.

Ahora hay una caché por `(especie, tamaño)` que devuelve el `CTkImage` ya hecho
—se pueden compartir entre widgets—, y un sprite que llega tarde invalida lo que
hubiera redimensionado de esa especie, que sería la silueta de ausencia.

## Para seguir midiendo

`medir_lentitud.bat` abre RoleRun con la instrumentación encendida
(`ROLERUN_PERF=1`, que ya existía y nunca se había usado). Deja un JSONL por día
con una línea por operación, y con eso se sabe qué tarda de verdad en vez de
suponerlo.

Suite completa: **1802**.

# v0.2.6-alpha.96 — cinco de seis, y la marca que nadie miraba

**Corrección de alpha.95: lo de «mezcla de dos escrituras» era falso.** Salió de
una lectura suelta, que se parte. Con mayoría de 60 lecturas por hueco, la
partida tras FIJAR ROLES estaba así:

| hueco | | EV escritos |
|-------|--|-------------|
| 1 TOTODILE | correcto | (252, 252, 0, 0, 0, 0) |
| 2 HOOTHOOT | correcto | (0, 252, 0, 0, 0, 252) |
| 3 RATTATA | correcto | (0, 0, 0, 252, 0, 252) |
| **4 WOOPER** | **roto** | `sanity=0x0004` |
| 5 GASTLY | correcto | (252, 0, 0, 0, 252, 0) |
| 6 SPINARAK | correcto | (0, 0, 252, 0, 252, 0) |

**FIJAR ROLES funcionó en cinco de seis.** El sexto lleva algo en los dos bytes
de 0x04 que los otros cinco no llevan, y que tampoco llevan los veinticuatro
casos generados por PKHeX: todos ellos, 0x0000.

## Lo que se hace con eso

No se sabe qué significa cada valor de ese campo, así que **no se rechaza nada
por su contenido**. Se vigila como **cambio**: si no vale lo mismo antes y
después de escribir, el juego ha tocado esa ficha por su cuenta y se deshace.

La referencia se toma **una sola vez**, no en cada intento. Se comprobó con el
doble de pruebas que tomarla de nuevo dejaba entrar la marca como referencia
buena en el intento siguiente, y la protección no servía de nada.

Esto no cierra el problema —una escritura de 236 bytes no es atómica para el
juego emulado, y lo que pase después del readback no lo ve nadie— pero sí cubre
el caso que se midió: que el juego marque la ficha mientras se escribe.

## Corregido también

La nota de `unshuffle_pk4` decía que `sanity=4` marcaba el estado en claro. Era
falsa y llevaba media sesión ahí. El Hoothoot del que salió esa idea era casi con
seguridad un «Huevo malo» ya estropeado, y el ayudante de pruebas `_en_claro`
forzaba ese 4 a mano por la misma razón: ahora deja la cabecera como está.

La escritura de cuarta sigue apagada.

Suite completa: **1797**.

# v0.2.6-alpha.95 — la prueba: el juego reescribe encima de lo escrito

Cuarto «Huevo malo», esta vez al pulsar FIJAR ROLES. Y por fin se capturó el
registro dañado **con la partida todavía rota**, que es lo que faltaba.

## Lo que dice la captura

El registro del hueco 1, leído **en claro**, da **especie 158 = TOTODILE**, que
es la correcta. Pero su mote es basura. Especie y mote viven en **bloques
distintos** de los cuatro que componen el cuerpo.

Es decir: unos bloques son los que escribió RoleRun y otros no. El registro es
una **mezcla de dos escrituras**.

Y el registro de escrituras vivas dice que la operación terminó **sin error, con
los seis aplicados y verificados por readback**. O sea que la mezcla se produjo
*después* de que RoleRun releyera y confirmara: **el juego vuelve a escribir esos
registros encima**, desde otro sitio.

El hueco 4 quedó peor: cuadra su propio checksum y aun así no da una especie
válida con **ninguna de las 24 permutaciones** de bloques, así que su cuerpo es
basura coherente, no un barajado equivocado.

## Qué se hace

`MELONDS_GEN4_ESCRIBE = False`. Escribir en cuarta con el juego corriendo no es
seguro mientras no se sepa desde dónde reescribe el juego esos registros, y eso
todavía no se sabe.

Leer sigue intacto, y la grabadora `grabar_escritura_heartgold.bat` ahora filtra
el parpadeo cifrado/en claro y enseña **solo los cambios de contenido**, que es
lo que hace falta para ver quién escribe después de RoleRun. Antes eran miles de
líneas ilegibles.

Suite completa: **1796**.

# v0.2.6-alpha.94 — el mismo criterio en los otros tres caminos

**La curación funciona, confirmado por el usuario.** Y el fallo que la tenía
parada seguía intacto en todo lo demás: enseñar MT, Equipo↔PC y bolsa/dinero
comparaban los bytes del equipo antes de escribir. Los tres se habrían negado
igual, con el mismo 28 % por intento.

Ahora ninguno compara bytes del equipo. Lo que se exige es lo que no parpadea:

- el bloque **demostrado vivo** y en la **misma dirección**;
- la identidad de cada hueco;
- y el readback **por contenido**, con el parser de producción.

**El PC y la mochila se siguen comparando byte a byte**, porque ahí sí valen: 1
único contenido en 12 lecturas seguidas de cada uno.

Queda una prueba estructural que lo vigila —`test_ningun_camino_compara_los_bytes_del_equipo`—
para que esto no vuelva por la puerta de atrás, más una funcional de Equipo↔PC
con una ficha parpadeando.

Suite completa: **1796**.

# v0.2.6-alpha.93 — la curación no compara bytes que parpadean

La versión anterior seguía negándose: «La ficha que se iba a escribir cambió
entre la lectura y la escritura». **Medido sobre la partida real**, 25 pares de
lecturas seguidas del equipo:

| lo que se comparaba | falla |
|---------------------|-------|
| los bytes de las seis fichas | **7 de 25** |
| los bytes de alguna ficha tocada | **7 de 25** |
| el contenido ya interpretado | **0 de 25** |

Un 28 % de fallo por pulsación, y desde alpha.89 esa comprobación estaba fuera
del bucle de reintentos —para que un rollback no escribiera con la dirección
vieja—, así que había **una sola oportunidad por pulsación**. Eso es exactamente
lo que el usuario veía.

## El arreglo

La ventana entre leer y escribir no se cierra comparando mejor: se cierra **no
teniéndola**. La transacción lee, muta **esa misma lectura** y escribe. Lo que
sale es siempre un registro derivado del estado que se acaba de ver, así que ya
no hay nada que volver a confirmar.

Lo que se sigue exigiendo, que es lo que protege de verdad:

- que el bloque esté **demostrado vivo**;
- que **no se haya movido** entre leer y escribir —escribir con la dirección
  vieja es lo que dejó tres «Huevo malo»—;
- que la identidad de cada hueco sea la que la petición declara;
- y un readback con el parser de producción, **por contenido**: `esperados`
  cubre los seis huecos con todo lo que se puede cambiar —PS, PP, EV, marcas,
  identidad—, así que es más fuerte que comparar los bytes de uno solo.

Las pruebas del parpadeo se invierten en consecuencia: que una ficha alterne
entre cifrada y en claro —la que se toca o cualquier otra— ya no impide escribir,
y hay una que cura las seis con todas parpadeando.

Suite completa: **1794**.

# v0.2.6-alpha.92 — HeartGold cura, y a la primera

**Cura sin romper nada.** Registro de la partida del usuario:

    12:15:57  curación  error: null  aplicados: 6

Y confirma la causa que se identificó en alpha.88: los tres «Huevo malo» venían
de **mutar una lectura partida**. Desde que una lectura solo vale si el mismo
contenido sale tres veces, lo que se escribe es coherente y el juego lo acepta.

## El falso negativo que quedaba

La primera pulsación, treinta segundos antes, se había negado:

    12:15:26  curación  error: «El equipo cambió entre la lectura y la
                        escritura; no se ha tocado nada»  aplicados: 0

No era un fallo —no se escribió ni un byte, que es lo correcto— pero obligaba a
pulsar dos veces. La grabación a 0,5 ms explica por qué: **cada ficha alterna
entre cifrada y en claro por su cuenta**, muchas veces por segundo. El mismo
Pokémon con el mismo checksum sale una vez cifrado y a la siguiente en claro, y
los dos contenidos son igual de válidos.

Exigir los bytes de las seis fichas hacía que la escritura se negara por el
parpadeo de una que ni se toca.

Ahora la comprobación previa exige:

- el mismo proceso, la misma reserva y **la misma dirección de bloque**;
- los mismos Pokémon en los seis huecos;
- y los mismos bytes **solo en las fichas que se van a escribir**.

De los demás huecos no sale ni un byte, así que comparar sus bytes no protegía
de nada. Si parpadea la ficha que sí se va a escribir, ahí no se cede: se niega
y no se toca nada.

Suite completa: **1793**.

# v0.2.6-alpha.91 — grabar el momento de la escritura

Se acabó lo que se puede demostrar leyendo antes y leyendo después. Todo sale
bien y la partida se rompe igual, así que el fallo pasa **entre medias**.

## Lo descartado en esta vuelta

- **La ventana de reposo no lo explica.** Medido a 0,5 ms durante 6 s: cada
  ficha sale de reposo unas 12 veces por segundo, pero un hueco normal está
  fuera de reposo solo el **2 %** del tiempo. Acertar dentro tres veces seguidas
  sería una entre cien mil, y las tres corrupciones fueron deterministas.
- **La caché del ARM9 tampoco.** El JIT de melonDS del usuario ya estaba
  apagado —`[JIT] Enable = false`— y su configuración no tiene ninguna opción de
  emulación de caché.
- **La dirección de escritura es correcta**, verificada seis de seis en seis
  pasadas: coincide con dónde está de verdad cada registro, buscado por su PID
  por toda la reserva.
- **El orden de bloques es correcto**: `reshuffle_pk4` es el inverso exacto de
  `unshuffle_pk4`, y la ida y vuelta sale byte a byte idéntica sobre el `.sav` y
  sobre los registros de la RAM.

De paso, un hallazgo lateral: el líder del equipo tiene una **cuarta copia** en
RAM —Totodile en 0x022A1E68— que los demás no tienen. Es el Pokémon que sigue al
jugador por el mapa. Habrá que actualizarla también cuando esto funcione.

## La herramienta

`grabar_escritura_heartgold.bat`. Muestrea las seis fichas a unas 2000 veces por
segundo y apunta cada cambio de contenido con su hora, su checksum, el orden de
sus bloques y si la marca de huevo está puesta, mientras el jugador pulsa CURAR
en RoleRun. Deja la grabación en crudo en `Logs/grabacion_escritura_hgss.bin`.

Un contenido **coherente** se apunta aunque dure una sola muestra: si algo se
come la escritura en menos de un milisegundo, esa muestra es la prueba. Lo que
no cuadra el checksum tiene que salir dos veces seguidas, para que el diario no
se llene de lecturas partidas.

La escritura de cuarta se enciende otra vez, a petición del usuario y solo para
poder grabar el fallo.

Suite completa: **1791**.

# v0.2.6-alpha.90 — herramienta para ver cuándo la ficha está en reposo

`cuando_se_puede_escribir_heartgold.bat`. Muestrea el bloque de equipo a 0,5 ms
y clasifica cada ficha en **reposo** (cifrada y legible), **en claro** (legible
sin cifrar) o **partida** (pillada a medias), en tres fases: quieto, andando y
con el menú Pokémon abierto. No escribe ni un byte.

Sirve para comprobar la hipótesis de alpha.89: que el juego descifra la ficha en
su sitio y la vuelve a cifrar, y que escribir dentro de esa ventana deja el
checksum sin cuadrar —un «Huevo malo»—.

## Lo que ya se ve en un ensayo de 2 segundos

4029 muestras, partida quieta:

| hueco | reposo | en claro | partida | ventana mala |
|-------|--------|----------|---------|--------------|
| 1 | 3951 | 30 | 48 | 0,5 ms |
| 2 | 2533 | 198 | 1298 | **hasta 14 ms** |
| 3 | 3949 | 32 | 48 | 0,5 ms |
| 4 | 3967 | 24 | 38 | 0,5 ms |
| 5 | 3948 | 31 | 50 | 0,5 ms |
| 6 | 3962 | 20 | 47 | 0,5 ms |

**Las ventanas existen**: la ficha sale de reposo decenas de veces por segundo.
Y el hueco 2 está fuera de reposo el 37 % del tiempo, **por posición y no por
Pokémon** —el que está ahí ahora no es el que estaba antes—.

Lo prometedor: las rachas de reposo duran entre 25 y 120 ms y una escritura tarda
menos de 1 ms. Si la hipótesis se confirma, esperar a una racha de reposo y
escribir dentro cabe de sobra.

La escritura de cuarta sigue apagada.

Suite completa: **1791**.

# v0.2.6-alpha.89 — la escritura de cuarta se apaga hasta demostrar el mecanismo

Tercer «Huevo malo» en la partida del usuario al pulsar CURAR. Lo que se sabe
con certeza, y lo que no.

## Lo que descarta este intento

El huevo salió en **Totodile, hueco 3**: el único Pokémon que la curación tenía
que tocar —estaba a 18/42 y los otros cinco al máximo—. Hueco correcto, Pokémon
correcto, dirección correcta. Y el codificador está probado: los seis registros
de la partida real se deshacen y se rehacen **byte a byte idénticos**.

Así que no es el formato, ni el hueco, ni la copia equivocada del bloque.

## La hipótesis que queda

La misma competencia con el hilo del emulador que parte las **lecturas** —medido
en alpha.88: hasta un 33 % de lecturas partidas en el peor hueco— parte también
las **escrituras**. Una ficha mitad nuestra y mitad del juego es exactamente un
registro incoherente, que es lo que el juego enseña como «Huevo malo».

Encaja con todo lo que ninguna hipótesis anterior explicaba: por qué la escritura
se verificaba bien y el readback cuadraba —los dos leen lo que acabamos de
escribir— y aun así el juego enseñaba un huevo al volver a mirar la ficha.

Está **sin demostrar**. Y no se demuestra sobre la partida del usuario.

## Qué se hace

`MELONDS_GEN4_ESCRIBE = False`, y no se vuelve a encender sin que el usuario lo
diga. Leer sigue funcionando, y desde alpha.88 sin lecturas partidas.

Queda la captura `huevo_malo_3.bin` con las tres copias del bloque tal y como
estaban tras el fallo.

Suite completa: **1791**.

# v0.2.6-alpha.88 — la causa raíz: `ReadProcessMemory` devuelve lecturas partidas

La prueba del usuario cerró la primera pregunta: de las copias del bloque, **la
que el juego usa es 0x0227C2DC**. Cambió dos Pokémon de sitio dentro del juego y
solo esa copia lo siguió; la otra ni se inmutó. Y buscando el equipo por toda la
RAM aparece **tres veces, siempre cifrado**: no hay ninguna copia en claro, así
que el juego lee de ahí. Una de las tres, 0x02376864, está caducada —tiene a
Totodile a Nv14 37/40—.

## Lo que fallaba de verdad

`ReadProcessMemory` compite con el hilo del emulador y devuelve registros
**pillados a medias**. Medido, 300 lecturas de cada miembro a dirección fija:

| hueco | iguales | hueco | iguales |
|-------|---------|-------|---------|
| 1 | 288/300 | 4 | 286/300 |
| 2 | 199/300 | 5 | 292/300 |
| 3 | 297/300 | 6 | 293/300 |

Y las variantes difieren siempre en **tramos contiguos que acaban en 0x87 o en
0xEB**: la frontera cuerpo/extensión y el final del registro. No es el juego
cambiando nada; es la lectura partida por la mitad.

Lo peligroso es que **la extensión de combate no tiene checksum**, así que una
lectura partida ahí pasa todas las validaciones. De ahí el Wooper publicado con
AtEsp 28801 y DefEsp 43367. Y si esa lectura sirve de base para escribir, lo que
se escribe es un registro incoherente: **eso es el «Huevo malo»**.

## El arreglo

Una lectura sola no vale. Gana **el primer contenido que salga tres veces**. El
bueno es mayoría abrumadora, así que llega a tres mucho antes que cualquier
variante partida; y si nunca se repite nada, no se publica nada.

Comprobado en la partida real: **60 lecturas seguidas, 0 fallos, un solo
equipo**, 17,9 ms de media. Antes fallaba a ratos y publicaba estadísticas
imposibles.

La escritura de cuarta vuelve a estar encendida. La detección de la copia viva
coincide con lo que demostró la prueba del usuario: 0x0227C2DC, 5 de 5.

Suite completa: **1791**.

# v0.2.6-alpha.87 — tres copias del guardado, y se escribía en la que no era

«No cura», y el mensaje era «el rollback de curación no se pudo confirmar; no
guardes». Buscando el motivo se midió mal y se llegó a una conclusión falsa —que
el juego reescribe las fichas solo— que costó un segundo «Huevo malo» en la
partida del usuario. Lo que sigue es lo que de verdad hay, medido.

## Lo que se midió

- **Conviven tres copias del bloque del guardado**: 0x0227C2DC, 0x02376864 y
  0x02399884, las tres con los mismos seis Pokémon.
- **Una copia sola es estable**: 200 lecturas seguidas a dirección fija dieron
  **un único contenido**, siempre cifrado, en los seis huecos.
- Lo que parecía «el equipo se reescribe solo» —once contenidos crudos distintos
  en veinte lecturas— era el localizador **saltando entre copias**.
- El codificador de PK4 es correcto: los seis registros de la partida real se
  deshacen y se rehacen **byte a byte idénticos**.

Como las tres copias dan el mismo equipo al interpretarlas, **comparar por
contenido no las distingue**. Por eso una escritura podía verificarse «bien» y
dejar un «Huevo malo».

## Los dos fallos reales

**1. La dirección del bloque podía moverse sin que nadie lo notara.** El bloque
cambia de sitio dentro de la misma reserva —se le vio en 0x0227C26C, 0x0227C290,
0x0227C2FC y 0x0227C2DC—. La comprobación previa miraba proceso, reserva y
bytes, pero **no la dirección del bloque**. Ahora se apunta al leer y se exige
que sea la misma al escribir.

**2. El rollback se ejecutaba aunque no se hubiera escrito nada.** Si la
comprobación previa se negaba, el `except` llamaba igual a `deshacer`, que
escribía con la dirección vieja. Eso no deshace: mete una ficha donde no va, que
es exactamente lo que el juego enseña como «Huevo malo». En las cinco
transacciones, confirmar la dirección va ahora **fuera del `try`**.

## Además

- **Se escribe solo la ficha que cambia**, no el bloque entero. Curar un Pokémon
  volcaba 1416 bytes; ahora son 236.
- **La extensión de combate se valida por las seis estadísticas**, no solo por
  nivel y PS. En la partida real un Wooper de nivel 6 y 23 PS colaba leído al
  revés y salía con AtEsp 28801 y DefEsp 43367. Leerlo mal es malo; **mutar esa
  ficha habría escrito esa basura en la partida**.

## La escritura de cuarta queda apagada

`MELONDS_GEN4_ESCRIBE = False` hasta demostrar **cuál de las tres copias lee el
juego**. El criterio de ahora —«la que cambia»— no lo demuestra, y con el
emulador pausado no cambia ninguna.

Para eso está `que_copia_lee_heartgold.bat`: pide cambiar de sitio dos Pokémon
dentro del juego y mira cuál de las copias sigue al cambio. No escribe ni un
byte.

Suite completa: **1788**.

# v0.2.6-alpha.86 — decir cuál es el Pokémon que no se puede leer

La localización de alpha.85 funciona: encuentra el bloque, demuestra cuál manda y
lo recuerda. Y aun así seguía saliendo «no se localizó la RAM DS validada».

El motivo real era otro: **el segundo miembro del equipo está dañado**. Falla su
checksum 40 de 40 veces —no es una lectura rota, es el Pokémon— y con un miembro
ilegible el equipo entero deja de poder leerse. Es el «Huevo malo» que dejó la
escritura de antes, que sigue en la partida.

El mensaje mandaba a buscar donde no había nada que buscar. Ahora, cuando el
bloque está localizado y aun así no se puede leer, se dice por su nombre:

> El miembro 2 del equipo no es un PK4: Checksum PK4 inválido.

Para eso la reserva localizada se guarda aparte de la caché de lectura, que se
olvida justo al fallar —que es cuando más falta hace—.

Suite completa: **1784**.

# v0.2.6-alpha.85 — la dirección ya no se da por sabida: se busca

HeartGold vuelve a escribir, con la causa del «Huevo malo» resuelta de raíz.

**Encontrar el bloque.** El nombre del entrenador y sus identificadores no
cambian mientras se juega, así que sirven de firma y viven al principio del
bloque. Sumando la marca `0x20060623` que cuarta pone al final del bloque
general, de los cuatro candidatos que aparecían en la RAM del usuario quedan los
dos de verdad.

**Saber cuál manda.** Los dos que quedan se parecen tanto que tienen hasta el
mismo pie. Lo que los distingue es que **el vivo se mueve**: en 30 muestras
tomadas en tres décimas de segundo, el bloque bueno cambió nueve veces y la
copia congelada ninguna. Ni siquiera hizo falta estar en combate. Es la misma
prueba de dos estados que localizó las filas de combate de Blanco.

**No escribir a ciegas.** Dos condiciones, y sin las dos no se toca nada:

1. Que el bloque esté demostrado vivo.
2. Que la dirección **siga valiendo justo antes de escribir**: se relee el
   equipo y tiene que salir byte a byte el mismo. Eso cierra la ventana por la
   que se coló el fallo —la lectura fue buena y, para cuando llegó la escritura,
   el bloque ya se había movido—.

**Y una tercera cosa que apareció por el camino.** La extensión de combate puede
ir en un estado distinto del cuerpo: se vio un Totodile con el cuerpo cifrado y
la extensión en claro, y leerla al revés lo dejaba a nivel 50 con 52226 PS. Como
no tiene checksum propio, se decide por coherencia: nivel entre 1 y 100, PS
máximos que quepan en el juego y actuales que no los pasen.

Medido después: **60 lecturas seguidas sin un fallo**, con el bloque localizado
solo, y ni un valor imposible.

Suite completa: **1782**.

# v0.2.6-alpha.84 — el bloque del guardado se mueve: escritura de cuarta cortada

Al sacar el Pokémon del PC, el juego enseñó un **«Huevo malo»**. Eso es lo que
muestra cuando un Pokémon tiene el cuerpo de uno y el checksum de otro, y lo
causó una escritura de RoleRun.

**La causa, medida.** El ancla no es estable. El equipo estuvo en `0x0227C304`
y apareció después en `0x0227C328`, treinta y seis bytes más allá: en la
posición nueva el bloque coincide al **99,64 %** con el archivo de la partida y
en la vieja al **37 %**. Además hay varias copias del bloque a la vez y no todas
están al día. Toda la arquitectura de cuarta daba por sabida esa dirección.

Leer con la dirección vieja es tolerable: el checksum caza lo que no cuadra y la
lectura falla en vez de mentir. **Escribir no lo es**, y por eso queda cortado:

- `hgss_write` niega cualquier escritura con un mensaje que dice por qué.
- HeartGold sale de los conjuntos de writer de la interfaz, así que sus botones
  de curar, MT y roles no aparecen. La lectura se queda entera.
- La ayuda del backend lo dice con todas las letras.

Se reactivará cuando la dirección se **localice en cada operación** en vez de
darse por sabida. Todo lo escrito para cuarta —roles, curación, movimientos, MT,
mochila, Equipo↔PC— sigue en su sitio y con sus pruebas; lo que falta es el
anclaje.

Suite completa: **1779**.

# v0.2.6-alpha.83 — el cambio se preparaba y nadie lo enviaba

Al sacar un Pokémon del PC, la pantalla decía «APLICANDO CAMBIO», el Pokémon
aparecía en el equipo con **«PS no disponible»**… y en el juego no estaba. El
registro de escrituras vivas no tenía ni una línea de ese intento: el cambio
nunca salió de la interfaz.

`_team_pc_execute_change` creaba los cambios, calculaba cuáles eran nuevos, los
pintaba y ponía el cartel de «APLICANDO CAMBIO» —pero **no llamaba a
`_request_oras_live_auto_apply_since`**, que es como termina cualquier otra
acción que crea cambios. Se quedaban en la cola para siempre.

No era cosa de cuarta generación: afectaba a **todos los juegos** por esa vía.

Hay dos pruebas nuevas: una comprueba que la llamada está y va después de crear
los cambios; la otra, en el flujo de X/Y, que decir «APLICANDO CAMBIO» y no
enviar nada no vuelve a pasar.

Suite completa: **1778**.

# v0.2.6-alpha.82 — un Pokémon puede estar **sin cifrar**, y ahí estaba el fallo

No era una RAM inquieta. Era esto.

Un PK4 vive en memoria **cifrado o en claro**, y el juego pasa de un estado a
otro cuando trabaja con ese Pokémon. Medido sobre la partida del usuario: de sus
cinco miembros, cuatro estaban cifrados y **el Hoothoot en claro**, con `sanity`
a 4 en vez de a 0. Leyéndolo descifrado daba la especie 2288 y un mote de
basura; leyéndolo tal cual, la especie **163** y **«HOOTHOOT»**. Su nivel y sus
PS en claro salían 5 y 25/25, exactamente los de la pantalla.

Como el lector siempre descifraba, ese miembro **nunca** pasaba su checksum
—0 de 40 lecturas— y con él caía el equipo entero. De ahí venían «no se localizó
la RAM DS validada», el PC que no abría y la operación Equipo↔PC que falló.

**El estado no se deduce del `sanity`: se demuestra con el checksum.** Si la suma
del cuerpo tal cual cuadra, está en claro; si cuadra al descifrarlo, está
cifrado; si no cuadra de ninguna forma, el bloque no vale. Es la misma prueba que
ya se usaba para todo lo demás.

Y al escribir **se devuelve en el estado en que se leyó**: cifrar un bloque que
el juego tenía en claro lo dejaría ilegible para él. Todo el registro va en el
mismo estado, extensión de combate incluida.

Medido después: 60 de 60 lecturas de equipo, PC y entrenador seguidas.

**Además: la operación Equipo↔PC del usuario sí había funcionado.** Su Spinarak
estaba en la caja 1 hueco 2 y el equipo compactado a cinco. Lo que falló fue la
verificación posterior, por este mismo motivo.

Suite completa: **1777**.

# v0.2.6-alpha.81 — Equipo ↔ PC en HeartGold

Las cinco operaciones: mover dentro del PC, depositar, retirar, intercambiar y
sustituir a un debilitado. Todas con el mismo contrato, y todas escribiendo el
equipo, el PC y el contador como una sola transacción con rollback entero.

**Dos detalles medidos sobre la partida real, no supuestos:**

- Un hueco vacío del PC **no son 136 ceros**: es un PK4 cifrado con semilla
  cero. Se comprobó sobre los **539 huecos vacíos** del PC del usuario. Escribir
  ceros haría que el readback de este mismo writer los rechazara por checksum, y
  toda retirada acabaría en rollback. Es exactamente lo que le pasó a quinta.
- **El contador se escribe el último.** Mientras el equipo nuevo no esté entero
  en memoria, el juego no debe verlo declarado. Hay una prueba que lo vigila.

Un PK4 guardado no lleva nivel ni estadísticas —las calcula el juego al
sacarlo—, así que al retirar se construyen con la misma tabla personal que usa
el resto de RoleRun: la de la ROM si la partida está randomizada.

**No se sustituye a quien no está debilitado.** La Run cuenta las bajas, y
falsear una sería peor que no poder hacerlo.

`tests/test_hgss_party_pc.py`: 13 pruebas, la mitad sobre lo que **no** debe
escribirse. Suite completa: **1728**.

# v0.2.6-alpha.80 — las MT de HeartGold, y se gastan

Cambiar un movimiento pasaba por el selector de MT, y el selector contestaba que
no estaban disponibles. Ya lo están.

**Cómo se localizó la tabla.** Las 92 MT son idénticas en toda la cuarta
generación, así que su lista salió del binario de las ROM de **Perla y Platino**
del usuario —las dos dan exactamente la misma—. Esa firma de 92 movimientos se
buscó en los 4 MiB de RAM del DS con HeartGold cargado: **aparece una sola vez**,
en `0x021000B4`.

**Y se valida sola.** La MO05 que hay ahí es **Torbellino**, no Despejar: justo
la diferencia conocida entre HeartGold y Platino. Lo encontrado no es una copia
de la referencia, es la tabla propia del juego. Las dos MT que el usuario tenía
en la mochila salieron MT51 Respiro y MT70 Destello.

El arm9 de HeartGold va comprimido, por eso hubo que buscarla en memoria en vez
de leerla del archivo como en Perla y Platino.

**En cuarta las MT se gastan.** Enseñar una no es solo escribir el movimiento:
hay que descontar el objeto, y las dos escrituras —el Pokémon y la mochila— van o
no van juntas. Si la segunda falla, se deshace también la primera. Antes de
escribir se comprueba que quede al menos una unidad.

**Y otra lista escrita a mano, menos.** Los juegos que saben leer su tabla de MT
estaban repetidos como literal en tres sitios, y a Blanco le faltó uno desde que
entró. Ahora es `LIVE_TM_GAME_KEYS`, y hay una prueba que vigila que no vuelva a
haber cuatro copias.

`app/hgss_tm_service.py`, `data/gen4_tm_table.json` y `tests/test_hgss_tm.py`
(10). Suite completa: **1715**.

# v0.2.6-alpha.79 — las tres utilidades de la cabecera, en HeartGold

Caramelos Raros ×999, Repelentes Máximos ×999 y dinero al tope. Probado contra
el juego vivo: los tres quedaron escritos y el parser de producción los volvió a
leer donde tenían que estar.

**La mochila, medida.** Los ocho bolsillos se sondearon en PKHeX tocando un
hueco de cada uno y mirando qué bytes se movían, y después se comprobaron contra
la RAM del juego: las Pociones, las Poké Balls y las dos MT del usuario
aparecieron exactamente en el bolsillo que les toca. Cada hueco son cuatro
bytes: identificador y cantidad.

**El bolsillo no se hereda de quinta.** Lo dice PKHeX: el Repelente Máximo vive
en OBJETOS y el Caramelo Raro en MEDICINAS. Meterlos en el equivocado los dejaría
invisibles dentro del juego. Y el nombre de la utilidad se contrasta con la tabla
de PKHeX antes de escribir: en BDSP una rotulada «Repelente Máximo» acabó tocando
el Repelente normal.

**El dinero son tres bytes**, y las medallas viven cinco más allá: la escritura
comprueba que no se han movido antes de dar el cambio por bueno.

Un bolsillo se mantiene compacto: poner cero borra el objeto y los de detrás
suben. Un hueco vacío por medio invalida la lectura entera, porque significa que
lo leído no es una mochila.

`data/gen4_bag_layout.json`, `tools_extract_gen4_move_pp/` y
`tests/test_hgss_bag.py` (17). Suite completa: **1705**.

# v0.2.6-alpha.78 — HeartGold ya cambia movimientos

Drafteo y borrado, con el mismo contrato transaccional. Dentro de un Pokémon se
escriben primero los movimientos nuevos y después los borrados, de atrás hacia
delante: así cada hueco significa lo mismo que cuando el usuario lo eligió.

- Al enseñar, los PP quedan al máximo y **los Más PP de ese hueco vuelven a
  cero**: se aplicaron al movimiento anterior y no se heredan.
- Al borrar, los de detrás suben. Un hueco vacío delante de uno lleno no es un
  moveset válido, y la verificación lo comprueba.
- No se enseña un movimiento que el Pokémon ya conoce: reescribirlo encima le
  borraría sus Más PP.

**Las MT quedan fuera a propósito.** En cuarta generación **se gastan al
enseñarlas**, al contrario que en quinta. Escribir el movimiento sin descontar
el objeto le regalaría la MT al jugador, y la mochila de HeartGold todavía no
está mapeada. El selector ya dice que no están disponibles.

**Y de paso, un fallo de Blanco.** El selector de MT llevaba la lista de juegos
escrita a mano y a Blanco le faltaba su entrada desde que entró: su tabla está
demostrada y su adaptador la lee, pero el selector le contestaba que las MT no
estaban disponibles. Ahora usa el conjunto, que es lo que se actualiza al añadir
un juego. Es el segundo fallo de este tipo en dos días.

Suite completa: **1686**.

# v0.2.6-alpha.77 — la curación fallaba por unos PP que nadie tenía

El registro de escrituras vivas que entró en la versión anterior lo dijo con
todas las letras a la primera:

> «No se conocen los PP base del movimiento #44; no se cura con un valor
> inventado.»

El adaptador de cuarta pedía los PP a la ROM y devolvía **cero** si no la tenía
delante, y un cero paraba la curación entera. El writer estaba bien: ejecutada a
mano contra la partida real, la curación funcionó a la primera.

Ahora hay `data/gen4_move_pp.json`, extraído del mismo PKHeX.Core que usa el
motor de guardados. **Comprobado contra la ROM real del usuario: coincide en los
467 movimientos.** Con la ROM delante sigue mandando la ROM —un randomizer puede
cambiar los PP—; sin ella se usa esta tabla, que es lo correcto en una partida
sin randomizar. Es el mismo reparto que ya tenía quinta.

Y el registro anota también si la ROM de cuarta llegó a cargarse, porque sin ella
las estadísticas base saldrían de PKHeX y una partida randomizada se vería mal.

`tools_extract_gen4_move_pp/`, y dos pruebas nuevas.
Suite completa: **1674**.

# v0.2.6-alpha.76 — un Líbero sin sus EV ya no se queda callado

El intercambio de roles **sí** pide las dos estadísticas del nuevo Líbero: se ha
comprobado en las dos direcciones —arrastrando el Asesino a la casilla del Líbero
y al revés— y en ambas pregunta por el que acaba de Líbero. Esa comprobación
queda como prueba.

Lo que faltaba es qué pasa si algún camino **no** lo pregunta. Hasta ahora, el
rol se asignaba y los EV se quedaban como estaban **sin decir nada**, porque el
reparto del Líbero es el único que no se deduce del rol: `_bdsp_role_evs`
devuelve `None` sin dos estadísticas elegidas. Un silencio así es
indistinguible de que RoleRun no funcione.

Ahora avisa, y dice qué hacer: usar CAMBIAR ROL sobre ese Pokémon para
repartirlos.

Suite completa: **1670**.

# v0.2.6-alpha.75 — la prueba de una lectura buena es el checksum, no repetirla

Alpha.74 se quedó corta. Reintentar la doble lectura no bastaba, y la medida lo
explica: **con el juego en marcha**, de 400 intentos seguidos sobre el bloque de
equipo, **304 tuvieron las dos lecturas distintas**. Con el juego parado, 300 de
300 coincidieron. Mientras se juega, ese bloque no para quieto.

Esperar a que dos lecturas coincidan es una prueba **más débil** que la que ya
trae el formato: **cada PK4 lleva su checksum de 16 bits, y son seis**. Una
lectura pillada a mitad de una escritura del juego no los pasa —comprobado: de
las lecturas que no coincidían, una parte no pasaba el checksum del primer
miembro—.

Así que ahora una lectura se acepta cuando **el contador no se ha movido
alrededor de ella y los seis PK4 pasan su checksum**, y se reintenta cuando no.
El contador sí se sigue leyendo dos veces: es un byte suelto y no tiene checksum
que lo respalde.

- La búsqueda por las 365 reservas del proceso es impaciente (3 intentos); la
  reserva ya demostrada tiene toda la paciencia (25). Y el recorrido entero se
  repite hasta tres veces antes de rendirse.
- El PC son 72 KiB sin checksum propio, así que se le exige que **dos lecturas
  digan lo mismo**: los mismos Pokémon en los mismos huecos, aunque los bytes de
  alrededor se muevan. Eso descarta publicar un estado mezclado sin depender de
  que 72 KiB se queden quietos.

Medido después: 80 de 80 lecturas de equipo, PC y entrenador seguidas, y 60 de
60 con el PC incluido, sin un solo fallo.

Suite completa: **1669**.

# v0.2.6-alpha.74 — HeartGold: curar, fijar roles y el PC fallaban por impaciencia

Con el juego en marcha, RoleRun no curaba, no fijaba roles, no aceptaba un
cambio de rol y avisaba de que no podía leer el PC. Todo era **el mismo fallo**,
y estaba en la lectura, no en la interfaz: sin lectura no hay escritura, y sin
enlace vivo la interfaz encola los cambios en vez de aplicarlos.

**La medida, antes de tocar nada.** El ancla es correcta y no se mueve: el equipo
apareció en `0x0227C304` en cinco búsquedas seguidas. Lo que pasa es que ese
bloque **no se está quieto**. De 3000 tripletes de lecturas seguidas, 129 no
coincidieron, y en 121 de ellos salieron **las tres distintas** —o sea, no es un
cambio que se asiente, es trasiego—. En parte de esas lecturas ni el checksum del
primer miembro cuadraba.

Quinta no necesitaba paciencia porque su bloque está quieto. Cuarta sí. Con la
reserva ya localizada, la captura se rechazaba **41 de 161 veces**, y la lectura
entera fallaba más de la mitad de las veces.

**Lo que se ha cambiado no afloja ni una garantía.** Se sigue exigiendo que dos
lecturas seguidas coincidan byte a byte y que cada PK4 pase su checksum; lo único
que se hace ahora es reintentar hasta ocho veces cuando las dos lecturas no
cuadran. Y solo en ese caso: un contador imposible o un checksum que no pasa
siguen siendo un «no» inmediato, porque repetirlos sobre las 365 reservas del
proceso solo costaría tiempo.

Misma paciencia para el PC —72 KiB, aún más fácil de pillar a medias— y para los
datos del entrenador.

**La escritura también.** Una escritura puede caer en uno de esos huecos, así que
la transacción se reintenta hasta tres veces, **pero solo si el rollback ha
quedado confirmado**: eso demuestra que la memoria es coherente y que falló el
intento, no la partida. Si el rollback no se confirma, no se reintenta nada.

Medido después: 150 de 150 lecturas del equipo correctas, y 60 de 60 leyendo
equipo, PC y entrenador seguidos, en 23 ms de media.

Suite completa: **1668**.

# v0.2.6-alpha.73 — HeartGold empieza a escribir: roles con sus EV y curación

`app/hgss_write.py`, con el mismo contrato transaccional de quinta y sin saltarse
un paso: relectura fresca, identidad fuerte por hueco, readback **con el parser
de producción** —no con el que escribió—, verificación semántica y rollback
completo. Si lo que se pide ya está puesto, no se escribe un solo byte.

**Separado del lector a propósito.** `hgss_live` no contiene ni una llamada de
escritura, y hay una prueba que lo vigila: así queda a la vista qué código puede
estropear una Run.

Lo que la mutación del PK4 respeta:

- **Las estadísticas se recalculan** al cambiar los EV. Dejarlas viejas
  descuadraría el PS máximo con el actual.
- **El daño recibido se conserva.** Si sube el PS máximo, sube igual el actual;
  y un Pokémon **debilitado sigue debilitado** —resucitarlo al aplicarle un rol
  sería un desastre silencioso, porque la Run cuenta las bajas—.
- **La naturaleza no se toca**, porque en cuarta sale del PID y no de un byte.
- **No se cura con unos PP inventados**: si no se conocen los PP base de un
  movimiento, se para. Jugando en randomizers pueden ser otros.

En la interfaz, HeartGold entra en las listas de writer de rol y de curación
completa. Los movimientos, el Equipo↔PC, el combate y las MT siguen fuera: no
tienen writer demostrado y la ayuda lo dice.

`tests/test_hgss_write.py` (22) y ampliación de `test_hgss_adapter.py` (26).
Suite completa: **1664**.

Pendiente de validación física: cambiar un rol y curar el equipo desde RoleRun.

# v0.2.6-alpha.72 — HeartGold, dentro de RoleRun

`app/realtime/hgss_adapter.py`, enchufado a la interfaz. Al abrir una Run de
HeartGold, RoleRun enlaza con melonDS y publica el equipo con sus PS, naturaleza,
estadísticas, IV, EV y movimientos; las 18 cajas del PC; y las medallas.

**Lo que NO hace, y por qué está separado.** Cuarta entra solo con lectura, así
que los conjuntos de la interfaz se han partido en dos:
`MELONDS_GEN5_REALTIME_GAME_KEYS` para lo que ya escribe y
`MELONDS_GEN4_REALTIME_GAME_KEYS` para lo que todavía no. Meter HeartGold en el
conjunto de quinta le habría atribuido curación, FIJAR ROLES y enseñanza de MT
que no existen. La Run se sigue guardando por el motor de archivo, que sí está
validado.

Detalles que la partida real obligó a resolver:

- **Un rol ya guardado no se borra** porque el PK4 vivo no tenga marcas. Cuarta
  todavía no las escribe; si el rol vivo mandara, abrir la Run dejaría al equipo
  entero SIN ROL.
- **El equipo publica las estadísticas que el juego escribió**; el PC las
  calcula, porque un PK4 almacenado no las trae y su nivel sale de la
  experiencia.
- **`boxed_metadata` ya no supone dónde está cada campo.** El ritmo de
  crecimiento vive en `0x13` en cuarta y en `0x15` de quinta en adelante; darlo
  por hecho habría hecho subir de nivel con la curva equivocada. Ahora el
  desplazamiento va en el descriptor de cada edición.
- **Las estadísticas del PK4 se publican en el orden de RoleRun**, no en el de
  la tabla personal. El juego las guarda con la velocidad en medio.

`tests/test_hgss_adapter.py`: 18 pruebas. Suite completa: **1634**.

# v0.2.6-alpha.71 — HeartGold se lee en vivo: equipo, PC y entrenador

`app/hgss_live.py`, con la disciplina de quinta entera: doble lectura estable,
validación antes de publicar, y **ambigüedad = error** en lugar de elegir un
equipo al azar.

Comprobado contra melonDS con la partida del usuario: los seis del equipo con
sus PS, 3856 de dinero, cero medallas y el Bellsprout de la caja 1. La relectura
con la base ya cacheada tarda **5 ms**.

Dos cosas que la partida real enseñó y que están puestas a prueba:

- **Un hueco vacío pasa el checksum.** No son 136 ceros: el juego deja un PK4
  cifrado con semilla cero, que al descifrarlo da ceros cuya suma cuadra. Por
  eso la especie se comprueba aparte; si no, el equipo saldría con un miembro
  fantasma. Se vio en el sexto hueco de su propia partida.
- **HeartGold reparte sus dieciséis medallas en dos bytes**, Johto en `0x7E` y
  Kanto en `0x83`. Sondeados por separado en PKHeX.

El PC se sondeó escribiendo en cuatro huecos concretos: 18 cajas de 30, hueco a
136 bytes del anterior y caja a `0x1000` de la anterior.

Un miembro del equipo que no cuadre invalida la lectura entera —publicar cinco
de seis daría un equipo que el jugador no tiene—, pero un hueco ilegible del PC
solo se cuenta como vacío: una caja con basura no puede dejar al jugador sin ver
el resto de sus Pokémon.

- `tests/test_hgss_live.py`: 20 pruebas, con la comprobación estructural que
  habría cazado el `self.memory` dentro de un `@staticmethod` de alpha.57.
- Suite completa: **1616**.

Todavía no está enchufado a la interfaz: falta el adaptador.

# v0.2.6-alpha.70 — HeartGold: el ancla, y la regla del espejo también en cuarta

El equipo de HeartGold vive en `0x0227C304`. No se supuso: se buscaron en la RAM
de melonDS los **PID concretos** del equipo que declara la partida guardada y se
conservaron los sitios donde varios caen separados 236 bytes, que es lo que mide
un PK4 de combate. Cada candidato se confirmó leyéndolo con el parser de
producción.

**La regla del espejo se cumple en cuarta.** Restando el desplazamiento del
equipo cae el principio del bloque, y de ahí en adelante el **98,65 %** de
128 KiB coincide byte a byte con el archivo de la partida; lo que no coincide es
justo lo que el jugador había avanzado desde el último guardado. Con esa sola
dirección salen contador, dinero, medallas y PC, y se comprobaron en vivo: el
dinero que llevaba encima, su equipo de seis y el Bellsprout de la caja 1.

**Había cinco copias y elegir mal habría salido caro.** Dos coinciden con el
archivo al 100 % —y por eso no valen: son los búferes del cartucho, congelados
en el último guardado—. Otra tenía el equipo al día pero no llega al 18 % de
espejo: es una estructura de trabajo aparte. Solo `0x0227C304` cumple las dos
cosas.

Los desplazamientos del guardado se sondearon en PKHeX cambiando cada campo y
mirando qué bytes se movían: dinero en `0x78` y de **tres bytes**, medallas en
`0x7E`, contador en `0x94`, equipo en `0x98`, PC en `0xF700`.

- `app/gen4_memory.py`, `tools_hgss_anchor_capture.py`, `tools_hgss_read_check.py`.
- `buscar_ancla_heartgold.bat` y `comprobar_heartgold.bat`, los dos de solo lectura.
- `tests/test_gen4_memory.py`: 14 pruebas. Suite completa: **1596**.

Pendiente de validación física: que lo que enseña `comprobar_heartgold.bat`
coincida con la pantalla.

# v0.2.6-alpha.69 — cuarta generación: la ROM y el formato PK4, demostrados

Primer ladrillo de HeartGold/SoulSilver. Nada de esto adivina: cada dato se
contrastó contra un oráculo independiente.

**Los datos de juego** (`app/gen4_rom_service.py`). Cuarta guarda la tabla
personal en registros de 44 bytes y la de movimientos en 16, con **los campos en
otro orden que quinta y la categoría invertida** (0=físico, 1=especial,
2=estado). Además conserva el tipo «???» en el índice 9, así que de Fuego en
adelante todo va desplazado uno; se traduce al leer.

- HeartGold coincide con la copia de PKHeX en **las 501 especies** en
  estadísticas base, ritmo de crecimiento y habilidad 1. Lo que difiere está
  explicado y comprobado sin excepciones.
- De los 467 movimientos, los 170 de categoría «estado» tienen potencia cero y
  los 297 restantes potencia mayor que cero. Sin una sola excepción.
- Descriptores para los tres juegos: las tres ROM del usuario se leen.

**El formato PK4** (`app/pk4.py`). Mismo cifrado que quinta, pero el registro de
combate mide 236 bytes, **la naturaleza no se guarda** —sale del PID— y los
nombres no son UTF-16: usan la tabla de caracteres de cuarta, volcada de PKHeX
código a código en `data/gen4_charmap.json`.

- 24 Pokémon generados por PKHeX, uno por cada disposición de bloque: todos los
  campos coinciden.
- Y sobre la partida real: los cinco del equipo se leen enteros, y sus seis
  estadísticas recalculadas con la tabla personal salen **exactamente** las que
  el juego dejó escritas.
- El equipo vive en `0x94` (contador) y `0x98`, separados 236 bytes. Medido
  recorriendo el guardado entero, no supuesto.

`tests/test_pk4.py` (128) y `tests/test_gen4_rom_service.py` (30).
Suite completa: **1582**.

# v0.2.6-alpha.68 — FIJAR ROLES, en los diez juegos

Botón en la cabecera de EQUIPO que asigna de una vez el rol de su casilla a
todos los que no tengan. Sin ramas por juego: encola los mismos
`PendingRoleChange` que el editor uno a uno.

- La casilla manda; quien ya tiene rol propio no se toca.
- Al Líbero se le preguntan sus dos estadísticas antes de tocar nada, y si se
  cancela no se fija ninguno.
- El botón solo aparece si hay algo que fijar. Una sola reconstrucción al final.
- `tests/test_fijar_roles.py`: 21 pruebas. Suite completa: 1424.

# v0.2.6-alpha.67 — el paso entre filas era 0x224, no 0x228

Alpha.65 restó el **inicio** de una fila menos el **campo de PS** de otra, que va
cuatro bytes más allá. Con el paso mal, la fila del segundo miembro salía
desplazada, la validación la rechazaba y RoleRun caía al bloque de equipo, que
en quinta no se actualiza en combate: por eso el equipo salía intacto.

La validación por miembro hizo su trabajo — falló hacia el lado seguro.
`0x224` sale dos veces por caminos independientes. Suite completa: 1403.

# v0.2.6-alpha.66 — el combate de Blanco, conectado y por equipo entero

Con el paso medido, Blanco lee **las seis filas**, una por miembro, y publica los
PS vivos del equipo entero durante el combate. Cada fila se valida contra su
propio miembro; una fila mala descarta ese Pokémon, no el combate.

Negro 2 no cambia: su paso no está medido y sigue leyendo una sola fila.

`tests/test_bw_memory.py`: 31 pruebas. Suite completa: 1400.

# v0.2.6-alpha.65 — el combate de Blanco, resuelto y con estructura

Lógica `0x0226E794` (1115 ms) y presentación `0x0226D898` (4544 ms). Los 3429 ms
de diferencia son casi los 3362 ms de Negro 2: el mismo retardo de animación,
medido en dos juegos y con dos métodos distintos.

Y reveló la estructura: **dos tablas de filas, una por miembro del equipo**, con
paso `0x228`. Se guarda la del primero más el paso. Negro 2 no lo hereda: allí
no se ha medido.

Blanco ya no tiene nada por inventar. Suite completa: 1400.

# v0.2.6-alpha.64 — el combate de Blanco, por dos estados

La búsqueda por firma falló dos veces por suponer que Blanco coloca los campos
como Negro 2: la última encontró las copias viejas de un Purrloin debilitado y
no la del Serperior que estaba luchando.

Se cambia a **dos estados**, que no supone nada del formato: las posiciones que
contenían los PS viejos y ahora contienen los nuevos. Es el método con el que se
demostraron la mochila y el dinero. Un tercer paso las ordena por tiempo.

Suite completa: 1398.

# v0.2.6-alpha.63 — la segunda fila de Blanco era del rival

`0x0226D670` sí es del Pokémon del jugador (24 → 9 PS). `0x0226E348` tenía un
Pansear a nivel 3342: coincidió una vez por azar.

Con una sola fila no se sabe si es la de presentación o la lógica, y elegir mal
cantaría una baja antes de verla. La herramienta nueva busca **todas** las filas
del Pokémon que lucha y las vigila a la vez, sin suponer distancias.

Suite completa: 1398.

# v0.2.6-alpha.62 — Blanco no tenía MT porque preguntaba al juego equivocado

`_get_b2w2_tm_profile` pedía el perfil siempre al adaptador de Negro 2, escrito
a mano. Con Blanco abierto leía la dirección equivocada. Lo mismo en el lector
de PC del selector y en los PP de la tarjeta de drafteo: tres referencias por
nombre fijo que la generalización de alpha.58 no alcanzó.

El test nuevo comprueba las dos rutas, no solo que responda alguien.
Suite completa: 1398.

# v0.2.6-alpha.61 — la tabla de MT de Blanco, y el combate a medias

**MT: `0x0209EA88`.** De 381 tramos con la forma correcta, uno solo coincide
101 de 101 con la referencia de PKHeX.

**Combate: localizado, no ordenado.** Dos filas exactas, pero con la vida llena
las dos dicen lo mismo y no se sabe cuál manda en pantalla. Elegir mal
adelantaría el KO a la animación, así que siguen apagadas.
`cual_es_cual_combate_blanco.bat` las separa por tiempo.

Suite completa: 1397.

# v0.2.6-alpha.60 — Blanco VALIDADO: lectura y escritura

Confirmado sobre la partida real: equipo, cajas PC, intercambios Equipo↔PC y el
botón de dinero. Los dos últimos son **escrituras**, así que el contrato
transaccional queda validado en Blanco con sus propias direcciones.

Quedan las dos cosas que no salen del cálculo, con su herramienta cada una:
`buscar_mts_blanco.bat` y `buscar_combate_blanco.bat`. Esta última busca por
firma de cuatro campos contra el equipo, en vez de rastrear a ciegas.

Suite completa: 1393.

# v0.2.6-alpha.59 — el PC vuelve a leerse

El equipo de Blanco se lee perfecto, así que el ancla queda validada. El PC no,
y el fallo era de alpha.57: al sustituir las direcciones, una cayó dentro de un
`@staticmethod` que no tiene `self`. Rompía el PC de **los dos** juegos.

Ninguna prueba se enteró porque los dobles sustituyen `read_pc` entero y nunca
llegan a ese método. Ahora hay dos: una estructural que cubre la clase de error
y otra que ejercita la lectura de verdad. Suite completa: 1393.

# v0.2.6-alpha.58 — Blanco, conectado

Adaptador vivo de Blanco, registrado junto al de Negro 2 y compartiendo lector,
writer y contrato. Lo único propio es el descriptor de direcciones.

- `key`, `game_key` y `display_name` pasan a ser por instancia.
- Cada juego consulta **su** tabla personal: 668 especies frente a 709.
- `MELONDS_REALTIME_GAME_KEYS` sustituye a los `== "b2w2"` de la interfaz.
- Blanco declara equipo, PC, mochila, dinero y medallas; y declara **no** tener
  carril de combate ni tabla de MT, en vez de prometerlos.
- `tests/test_bw_memory.py`: 20 pruebas. Suite completa: 1385.

# v0.2.6-alpha.57 — el lector de quinta, genérico

El lector recibe el descriptor del juego: 26 direcciones incrustadas pasan a
`self.memory.*`, y las constantes del módulo quedan como alias derivados. Sin
argumentos sigue dando Negro 2.

Lo que un juego no tiene demostrado —la tabla de MT y el carril de batalla en
Blanco— se niega con su motivo, y antes de abrir el proceso.

- `tests/test_bw_memory.py`: 14 pruebas. Suite completa: 1385.

# v0.2.6-alpha.56 — el ancla de Blanco

**`0x02234974`**, con dos confirmaciones independientes: cuatro PK5 seguidos
separados 220 bytes (el equipo declarado) y, en la dirección que predice la
resta, el dinero exacto que el usuario había apuntado (1624).

De ahí salen contador, PC, mochila, dinero y medallas sin más capturas.

- `app/gen5_memory.py`: un descriptor por juego, solo el ancla se mide.
- Corregido: la herramienta leía el contador cuatro bytes antes de donde está.
- `tests/test_bw_memory.py`: 9 pruebas. Suite completa: 1380.

# v0.2.6-alpha.55 — el bloque vivo es un espejo del guardado

Partiendo solo del dinero de Negro 2 y del desplazamiento que PKHeX declara,
el contador del equipo y sus seis Pokémon aparecen en el guardado real en las
posiciones predichas. Cada juego nuevo necesita **un ancla, no seis**.

No autoriza heredar direcciones: Blanco guarda el dinero en `0x21200` y Negro 2
en `0x21100`. Misma regla, distintos números.

- `tools_bw_anchor_capture.py` + `buscar_ancla_blanco.bat`.
- `tests/test_gen5_save_mirror.py`. Suite completa: 1371.

# v0.2.6-alpha.54 — Blanco: la base común de ROM de DS

Primer paso del segundo juego de DS, hecho sin pedir nada al usuario: sus cinco
ROM están en el disco.

- La tabla de **movimientos** es idéntica byte a byte entre Blanco y Negro 2.
  La **personal no**: 668 especies de `0x3C` frente a 709 de `0x4C`.
- `app/nds_rom.py` (FNT/FAT/NARC, común a los cinco juegos) y
  `app/gen5_rom_service.py` con un descriptor por juego. `b2w2_rom_service`
  desaparece.
- `boxed_metadata` gana la familia `bw`.
- Falta lo que no se puede deducir: las direcciones de RAM de Blanco.
- `tests/test_gen5_rom_service.py`: 37 pruebas. Suite completa: 1367.

# v0.2.6-alpha.53 — medallas VALIDADAS FÍSICAMENTE

El contador marca 1 tras la Medalla Base y los botones manuales ya no aparecen.
Cierra alpha.50, 51 y 52.

Con esto B2/W2 tiene implementado todo lo que la Run necesita. Lo único sin
validar físicamente es el drafteo y el borrado de movimientos (alpha.46-48).
Siguiente frente: los otros cuatro juegos de DS.

# v0.2.6-alpha.52 — la dirección de medallas, confirmada contra el juego

Con una medalla conseguida, `0x022266A8` vale **0x01**: lo que predijo la
deducción de PKHeX antes de mirar la RAM. Dos caminos independientes, el mismo
byte. El segundo candidato del volcado (`dinero−32`) es una coincidencia
esperable con una sola medalla; la siguiente lo separará.

- `tests/test_b2w2_badges.py`: 29 pruebas, ancladas a la captura real.
- Suite completa: 1357.

# v0.2.6-alpha.51 — la medalla ya llega al contador

Alpha.50 leía las medallas y las tiraba: la rama de B2/W2 del monitor nunca
llamaba a `_process_oras_badge_value`. Reportado al conseguir la Medalla Base.

- Se procesa antes de cualquier return por herencia de rol o cambio de equipo,
  con una prueba que fija ese orden.
- B2/W2 entra en `AUTOMATIC_BADGE_GAME_KEYS`: desaparecen los botones de sumar
  y restar medallas, porque el valor lo gobierna el juego.
- `comprobar_medallas_b2w2.bat` confirma la dirección con una sola lectura.
- `tests/test_b2w2_badges.py`: 27 pruebas. Suite completa: 1355.

# v0.2.6-alpha.50 — medallas en tiempo real, y el dinero corregido

**`0x022266A8`**, deducida sin pedir captura: PKHeX dice que las medallas caen
cuatro bytes detrás del dinero, ya demostrado. Misma vecindad que ORAS. La
equivalencia guardado↔RAM la confirma el propio guardado del usuario, que pone
4524 donde su traza de dinero empezó en 4524.

- Quinta guarda un bit por medalla, no el número: se cuentan.
- Sin lectura fiable se publica `None`, no un cero.
- **El dinero ocupa tres bytes, no cuatro**: RoleRun escribía uno de más que no
  le pertenece. En el guardado del usuario valía cero, así que la validación de
  alpha.39 no se vio afectada.
- `tests/test_b2w2_badges.py`: 25 pruebas. Suite completa: 1355.

# v0.2.6-alpha.49 — el marco cortado, esta vez medido

Alpha.48 lo intentó a ojo y lo empeoró. Reconstruida la tarjeta real y medida:
la tarjeta deja **92 píxeles útiles** y el contenido pedía **95**. Tk recortaba
tres, justo el borde inferior de la fila de ataques. La celda aislada se dibuja
perfecta: no era un problema de dibujo sino de sitio.

- El bloque de estadísticas pasa de 70 a 64 píxeles, que le sobraban.
- Se retiran los márgenes que alpha.48 añadió: eran los tres píxeles de más.
- Medido después: 86 necesarios sobre 92 útiles. Suite completa: 1330.

# v0.2.6-alpha.48 — el Support resoluble, y el marco cortado

- Una celda dorada lleva ya los mismos SUSTITUIR y ELIMINAR que una roja.
  `delete_move` solo miraba las incompatibilidades, y un ataque que sobra en un
  Support no lo es: el límite de dos es de conjunto.
- **Marco cortado en todos los juegos**: las celdas de movimiento tenían altura
  fija y el borde de abajo quedaba fuera. En la tarjeta ganan dos píxeles; en la
  ficha, una celda con botones se ajusta a su contenido.
- `tests/test_b2w2_move_presentation.py`: 17 pruebas. Suite completa: 1329.

# v0.2.6-alpha.47 — dos fallos de la interfaz, reportados con captura

- **Tarjetas de drafteo vacías**: potencia, precisión y PP ya salen de la ROM
  cargada, y la descripción del catálogo español. Sin ROM, guion en vez del
  número de otra generación.
- **Support sin marcar**: la vista compacta de Equipo y PC no conocía el exceso
  de ataques de daño. Ahora pinta en dorado los candidatos y ofrece elegir
  cuáles quitar, como hacía la tarjeta antigua.
- Los roles de Pokémon en el PC quedan **descartados** por decisión del usuario.
- `tests/test_b2w2_move_presentation.py`: 13 pruebas. Suite completa: 1325.

# v0.2.6-alpha.46 — el drafteo en B2/W2

**alpha.42-45 VALIDADAS FÍSICAMENTE** (27-08-2026): enseñar una MT funciona, la
MT no se gasta, y leer los datos de la ROM no cambió nada de lo que ya iba.

Nuevo: cambiar un movimiento a mano ya escribe en Negro 2.

- Comparte writer con la enseñanza de MT: la escritura en el PK5 es idéntica.
- Borrar un movimiento compacta los huecos, como `_remove_move_slots` en ORAS.
  Lo necesita un Support al perder los ataques de daño que le sobran.
- Dar uno y quitar otro al mismo Pokémon va en una sola transacción.
- No se deja a un Pokémon sin ningún movimiento.
- `tests/test_b2w2_draft_writer.py`: 23 pruebas. Suite completa: 1312.

# v0.2.6-alpha.45 — la ROM se lee sin congelar la interfaz

Alpha.44 leía la ROM entera para consultar unos kilobytes: 512 MiB en el hilo
de Tk la primera vez. Ahora se leen solo cabecera, FNT, FAT y los dos
contenedores —**2 ms**—, con una prueba que impide la regresión.

# v0.2.6-alpha.44 — B2/W2 lee los datos de juego de su ROM

Cierra el hueco frente a randomizers como los juegos terminados: ORAS y X/Y
leen su ROM, Perla Reluciente su masterdata, y ahora B2/W2 su `.nds`.

**El riesgo que elimina:** con tablas estáticas, aplicar un rol en una partida
randomizada recalculaba las estadísticas con las bases del juego original y las
**escribía en la partida**.

- `app/b2w2_rom_service.py`: FNT/FAT del NDS, NARC, personal (`a/0/1/6`) y
  movimientos (`a/0/2/1`).
- Se descubre sola: melonDS guarda la partida junto a la ROM con el mismo nombre.
- `boxed_metadata.set_personal_override()` sustituye la copia de PKHeX en un
  único sitio; se olvida al cambiar de Run.
- PP de curar/enseñar y categoría para filtrar por rol salen de la ROM.
- Formato demostrado: personal idéntico a PKHeX salvo habilidades normalizadas;
  tipo y PP 559/559; potencia y precisión corrigen valores que la tabla de sexta
  tenía mal para quinta.
- `tests/test_b2w2_rom_service.py`: 28 pruebas. Suite completa: 1288.

# v0.2.6-alpha.43 — la pantalla de MT, por rol y por partida

- El filtro por rol ya funcionaba y es el **mismo de los demás juegos**. Ahora
  queda verificado con `DraftEngine` real: Mago sin físicos, Asesino sin
  especiales, y Support con dos ataques solo recibe MT de estado.
- La compatibilidad por especie se sigue ignorando a propósito: manda el rol.
- **Randomizada, se ofrece y se escribe el movimiento de esta partida.** La
  MT26 vanilla es Terremoto y a un Mago no se le ofrece; randomizada a especial,
  sí, y al revés. El `PendingTMTeach` lleva el movimiento vivo hasta el writer.
- `B2W2TMSource` expone `.name`: la procedencia ya no se degrada en pantalla.
- `tests/test_b2w2_tm_roles.py`: 20 pruebas. Suite completa: 1260.

# v0.2.6-alpha.42 — enseñar MT en B2/W2

La pantalla MT y el selector individual ya funcionan en Negro 2/Blanco 2.

- **No se gasta la MT**: en quinta son reutilizables y el writer no toca la
  mochila. Misma regla que ORAS y X/Y.
- `pk5_party_with_move()` deja los PP al máximo y los Más PP del hueco a cero
  (se aplicaron al movimiento anterior y no se heredan).
- Un movimiento ya conocido se rechaza, **incluso en su propio hueco**:
  reescribirlo encima borraría los Más PP del jugador a cambio de nada.
- Enseñar no toca PS, estado ni estadísticas.
- `write_party_moves()` con el contrato transaccional completo; el adaptador
  localiza al Pokémon por identidad fuerte, no por el índice de party.
- La interfaz no pide ROM: lee la tabla viva. Sin melonDS enlazado, no lee nada.
- `tests/test_b2w2_tm_teach.py`: 33 pruebas. Suite completa: 1240.
- Pendiente de validación física.

# v0.2.6-alpha.41 — la tabla de MT, demostrada y leída en vivo

**`0x02090C54`**, demostrada con la captura del usuario del 27-08-2026.

- Un **solo** tramo en 4 MiB con la forma de una tabla de MT, y coincide **101
  de 101** con la referencia de PKHeX. Forma y contenido señalan el mismo sitio.
- La captura corrigió un supuesto: el juego guarda la lista en **orden de
  objeto** (MT01–92, MO01–06, MT93–95), no de número de MT. La comparación dio
  92/101 por eso; eran los mismos movimientos en otro orden.
- `read_tm_table()` lee en vivo con doble lectura y valida la forma entera;
  `read_tm_profile()` publica el perfil. Nada sale de una tabla de disco, que es
  lo que exige jugar en randomizers.
- Se publican las 95 MT; las 6 MO se leen pero no entran (la interfaz rotula
  todo como `MT<número>`, y en quinta un movimiento de MO no se olvida en juego).
- `tests/test_b2w2_tm_table.py` reescrito: 31 pruebas, cuatro de ellas ancladas
  al archivo de la captura real. Suite completa: 1207.

# v0.2.6-alpha.40 — la tabla de MT, replanteada para randomizers

**Corrige un supuesto equivocado de alpha.39.** Alpha.39 extrajo la tabla
MT → movimiento de PKHeX dando por hecho que en quinta generación es fija. No lo
es para este proyecto: RoleRun está pensado para jugarse en **randomizers**, y un
randomizer cambia qué movimiento enseña cada MT.

- La tabla que manda es la que el juego tiene cargada en memoria, y se lee en
  vivo como el equipo y la mochila.
- `data/b2w2_tm_table.json` pasa a ser **referencia**, no fuente: sirve para
  localizar y validar el tramo de RAM correcto. En una partida sin randomizar
  tiene que coincidir movimiento a movimiento.
- Qué objeto es cada MT sí es fijo: MT01 = 328, MT21 = 348 en cualquier B2/W2.
- `tools_b2w2_tm_table_capture.py` + `buscar_mts_b2w2.bat`: 101 movimientos
  seguidos, todos entre 1 y 559 y todos distintos. Peor caso 6,4 s sobre 4 MiB.
- La compatibilidad por especie se sigue ignorando a propósito: en RoleRun quién
  puede aprender una MT lo decide el **rol**.
- `tests/test_b2w2_tm_table_search.py`: 10 pruebas nuevas.
- **alpha.39 queda validado físicamente**: los tres botones de la cabecera
  funcionan en Negro 2 (confirmado por el usuario el 27-08-2026).

# v0.2.6-alpha.39 — las utilidades de la cabecera, escribiendo en Negro 2

Los tres botones que hay junto a la vida (Caramelos Raros ×999, Repelentes
Máximos ×999 y dinero al máximo) ya funcionan en B2/W2. Hasta ahora estaban
ahí pero no escribían nada en este juego.

- **Mochila.** `set_bag_quantity` coloca el objeto respetando el compactado que
  el juego espera: si ya lo tienes, solo cambia la cantidad y no mueve nada; si
  no, lo añade justo detrás del último. El bolsillo sale del reparto extraído
  de `SAV5B2W2.Inventory`, no de una suposición: Caramelo Raro (#50) vive en
  Medicinas y Repelente Máximo (#77) en Objetos.
- **Dinero.** `MONEY_ADDRESS = 0x022266A4`, demostrado en la traza de dos
  estados del 27-08-2026: de **dos** candidatos iniciales, fue el único que
  pasó de 4524 a 4224 al gastar dinero dentro del juego. El tope se fija en
  999 999, que es el único valor que la utilidad escribe; un límite mayor no
  está demostrado en B2/W2 y no se admite.
- Ambos writers usan el contrato transaccional del resto de B2/W2: relectura
  fresca, construcción validada con el parser de producción, readback,
  verificación semántica y rollback completo. Si ya tenías esa cantidad, **no
  se escribe un solo byte**.
- El adaptador contrasta el rótulo de cada utilidad con la tabla de PKHeX antes
  de escribir. Es exactamente lo que falló en BDSP alpha.85, donde un botón
  rotulado «Repelente Máximo» modificó el Repelente normal.
- Sin melonDS sincronizado, la utilidad avisa y **no deja nada pendiente**:
  B2/W2 solo tiene writer vivo, y una cola que nunca se vacía congelaría el
  monitor (la clase de fallo que cerró alpha.27).
- Decisión de alcance del usuario: **no** se añade un visor de mochila. El
  inventario se registra para saber qué MT tienes y poder enseñarlas desde
  RoleRun, que es el siguiente paso.
- `tests/test_b2w2_bag_writer.py`: 37 pruebas nuevas. Suite completa: 1166.
- Falta la validación física de los tres botones y el perfil de MT de B2/W2.

# v0.2.6-alpha.38 — la mochila de B2/W2, por el contrato común

El lector quedó **validado físicamente**: lo que RoleRun lee coincide con la
mochila del juego, bolsillo por bolsillo.

- El adaptador implementa `read_tm_inventory`, que es el contrato por el que el
  resto de RoleRun —la interfaz y el selector de MT— pide el inventario a
  cualquier backend. B2/W2 deja así de ser una excepción.
- El testigo del guardado sigue siendo **solo diagnóstico**: en cuanto el jugador
  coge o gasta un objeto ambos difieren, y manda siempre la muestra de RAM.
- Baseline completa: **1129 passed**.

Falta mostrarlo en la interfaz y, más adelante, el writer.

# v0.2.6-alpha.37 — lector de la mochila de B2/W2

Con la estructura ya demostrada, el lector.

- `read_bag()` con la misma disciplina que el resto de lecturas B2/W2: **doble
  lectura** que debe coincidir byte a byte, y el cerrojo que serializa el lector.
- `parse_bag()` valida **antes de publicar**: cada bolsillo tiene que estar
  compactado —sus objetos al principio y ceros detrás—, cada identificador tiene
  que ser legal **en ese bolsillo concreto** según la lista de PKHeX, las
  cantidades entre 1 y 999, y ningún objeto repetido. Cualquier fallo rechaza la
  mochila entera en vez de publicar medio inventario inventado.
- El reparto de huecos por bolsillo se **deriva** de la distancia hasta el
  siguiente, que es exactamente lo que se midió en la RAM: 310, 83, 109, 48 y 64.
  Todos son mayores que su lista de objetos legales, como debe ser.
- Comprobado que la mochila **real** del usuario pasa el validador entera y que
  sus ocho objetos son legales en su bolsillo. Si la lista de PKHeX no hubiera
  cubierto alguno, el lector lo habría rechazado.
- Comprobado también que la mochila termina antes del contador de party, que está
  en una dirección ya demostrada: no se solapan.
- Nueva herramienta `comprobar_mochila_b2w2.bat`, que usa **el lector de
  producción** y no una copia simplificada, para contrastar contra el juego.
- Baseline completa: **1127 passed**.

Todavía no se muestra en la interfaz ni se abre ninguna escritura.

# v0.2.6-alpha.36 — la estructura completa de la mochila, demostrada

El mapa de la RAM del usuario y la estructura que PKHeX declara para el guardado
**coinciden byte a byte en tres fronteras independientes**. No es una analogía:
es un ajuste verificado tres veces contra datos reales.

| Frontera entre bolsillos | Medido en la RAM | `SAV5B2W2` de PKHeX |
|---|---|---|
| Items → Objetos clave | 1240 | 1240 |
| … → MT/MO | 1572 | 1572 |
| … → Medicinas | 2008 | 2008 |

- **Mochila en `0x0221D9A4`**, con los bolsillos en Items +0, Objetos clave
  +1240, MT/MO +1572, Medicinas +2008 y Bayas +2200. Cada hueco son dos enteros
  de 16 bits: identificador y cantidad.
- El contenido encontrado confirma cada bolsillo por separado: Videomisor, Bloc
  de Amigos y Mapa en objetos clave; MT21 en el de MT; Poción y Antiparalizador
  en medicinas. Ninguno de esos objetos se buscó.
- La traza comprobó además que el contador de party sigue cuadrando en su
  dirección ya demostrada, lo que confirma que se está leyendo el bloque espejo
  del guardado y no una copia temporal.
- Nuevo `data/b2w2_bag_layout.json` con el desplazamiento de cada bolsillo y su
  **lista de objetos legales**, extraído de la misma PKHeX.Core que usa el motor,
  con la herramienta reproducible `tools_extract_gen5_bag_layout/`.
- Esa lista de objetos legales es lo que permitirá validar cada hueco al leer, en
  lugar de aceptar cualquier número.
- El dinero sigue en `0x022266A4`, confirmado con dos estados.

Falta el reader y su validación. Ninguna capacidad se abre todavía.

# v0.2.6-alpha.35 — la mochila y el dinero, localizados

El método de dos estados funcionó a la primera y dejó **una sola dirección** en
cada caso, no un puñado de candidatos.

- **Bolsillo de medicinas en `0x0221E17C`.** De cinco posiciones que contenían
  «Poción ×2», solo esa pasó a contener «Poción ×3» al usar una. Las otras cuatro
  eran coincidencias.
- **Dinero en `0x022266A4`.** De dos posiciones con 4524, solo esa pasó a 4224
  tras la compra.
- **Corroboración que no se buscaba:** la casilla contigua al ancla contiene
  Antiparalizador ×2, un objeto por el que la herramienta no preguntaba. Que
  aparezca justo ahí, con formato válido, es evidencia independiente de que se
  trata de un bolsillo real. Todo lo anterior y posterior está a cero, como
  corresponde a un bolsillo compactado.
- La estructura queda confirmada: pares de dos enteros de 16 bits,
  identificador y cantidad, alineados a 4 bytes.
- El ancla cae 0x230 bytes antes del contador de party, que ya estaba demostrado.
  Es decir, la mochila vive en el mismo bloque espejo del guardado.

Nueva herramienta `tools_b2w2_bag_map_capture.py` con su lanzador
`mapear_mochila_b2w2.bat`, para el paso que falta: **dónde empieza y acaba cada
bolsillo**. Vuelca la zona alrededor del ancla decodificada y agrupa las tiras de
objetos válidos consecutivos. Comprueba además que el contador de party sigue
cuadrando, lo que demuestra que el bloque leído es el espejo del guardado y no
una copia temporal. No pide nada al usuario dentro del juego.

Ninguna de estas direcciones pasa a producción todavía: falta el mapa y una
confirmación tras reiniciar el juego.

# v0.2.6-alpha.34 — la mochila se busca con dos estados, no con un número

La primera traza lo dejó claro: buscar solo el par (identificador, cantidad)
devolvió **40 posiciones** para «Poké Ball ×3», y al decodificarlas resultaron ser
un patrón repetitivo de valores pequeños que coincidía por azar. Un número
suelto, por específico que parezca, aparece muchas veces en 4 MiB.

También quedó claro que la heurística de «varios objetos juntos» no sirve aquí:
en quinta generación **cada bolsillo va por separado**, así que Poké Ball y
Poción no tienen por qué estar cerca.

- La herramienta pasa al método que pide el propio documento de paridad: **dos
  estados**. Se guardan las posiciones que contienen la cantidad vieja, el
  jugador usa o compra algo, y se conservan solo las que **en esa misma posición**
  pasan a contener la cantidad nueva. Un patrón casual no sobrevive a ese filtro.
- Lo mismo para el dinero, comparando antes y después de una compra o venta.
- De cada dirección confirmada se vuelca además el bolsillo decodificado
  alrededor, con nombres de objeto, para poder verificar que es una mochila de
  verdad y no otra coincidencia.
- Corregidos los dos lanzadores `.bat`, que se estaban escribiendo con los saltos
  de línea duplicados.

# v0.2.6-alpha.33 — búsqueda de la mochila y el dinero

El ciclo de combate y bajas de B2/W2 queda **validado físicamente al completo**:
daño en tiempo real, KO en el momento, descuento de vida, selector, sustitución y
recuperación al curar.

Todo lo que le queda a B2/W2 —mochila, MT, utilidades y medallas— depende de
direcciones de RAM que **no están demostradas**. No se implementa nada sobre una
dirección inventada, así que el paso siguiente es obtener la evidencia.

- Nueva herramienta `tools_b2w2_bag_capture.py`, de **solo lectura**, con su
  lanzador de doble clic `buscar_mochila_b2w2.bat`.
- El método no es un escaneo a ciegas. En quinta generación cada hueco de la
  mochila son dos enteros de 16 bits seguidos: identificador y cantidad. El
  usuario dice cuántas unidades tiene de dos o tres objetos concretos y se busca
  **ese par exacto**, quedándose solo con las zonas donde aparecen varios objetos
  juntos: una coincidencia mucho más difícil de fabricar por azar que un número
  suelto.
- Los identificadores salen de la misma tabla de PKHeX que ya usa RoleRun, no de
  una lista escrita a mano.
- Se lee dos veces con una pausa: lo que no sobrevive a ambas lecturas era un
  buffer transitorio.
- El dinero se busca aparte, como entero de 32 bits alineado.
- Nada de lo que salga de aquí es una dirección de producción mientras no se
  confirme con un segundo estado.

# v0.2.6-alpha.32 — los PS y la baja, ya en tiempo real

La traza física del usuario resolvió el diagnóstico. Tres hallazgos, todos
medidos, ninguno supuesto:

1. **El bloque de party de Gen 5 no refleja el daño durante el combate.** A los
   27 s la copia de presentación mostraba a Patrat con 3/16 PS y la party seguía
   diciendo 16/16; a los 39 s la presentación decía 0 y la party seguía en 16/16.
   La party solo se actualizó a los 47 s, al terminar el combate. Esa era la
   fuente a la que RoleRun estaba cayendo.
2. **La segunda fila de batalla estaba obsoleta todo el combate**: describía a
   otro miembro del equipo, sin moverse, y con un nivel imposible (516). Como
   `parse_battle_copies` exigía que ambas filas coincidieran en identidad,
   rechazaba la lectura entera y descartaba la única fuente que sí tenía el dato.
3. **El byte de estado se mantuvo en 0** todo el combate, incluso con el Pokémon
   ya debilitado. La sospecha de que un estado no demostrado rompía la lane
   —anticipada por la auditoría— queda **descartada**.

El arreglo: la copia de presentación es la autoridad y la segunda fila solo
**corrobora**. Su desacuerdo ya no anula la lectura.

- **No se relaja ninguna comprobación que proteja.** La presentación sigue
  teniendo que identificar de forma única a un miembro del equipo, los PS
  imposibles se siguen rechazando, y un estado no demostrado también.
- Con las dos filas de acuerdo, el comportamiento validado físicamente en
  alpha.5 no cambia: la HUD muestra la presentación y no adelanta el KO a la
  animación.
- Sin copia de presentación no se publica nada: no se usa la otra fila como
  sustituta para no arriesgarse a adelantar daño.
- Las pruebas usan **los bytes reales de la traza**, no valores inventados.
- Baseline completa: **1112 passed**.

Limitación conocida, ahora demostrada: durante el combate solo se conoce el PS
del Pokémon **activo**. El resto procede del bloque de party, que Gen 5 no
actualiza hasta el final.

# v0.2.6-alpha.31 — diagnóstico de la baja durante el combate

La sustitución quedó **validada físicamente**. Queda un único fallo abierto en el
ciclo de bajas: ni los PS ni la baja se actualizan mientras dura el combate; todo
aparece al terminarlo.

No se implementa nada a ciegas. Hay dos explicaciones posibles y **ninguna está
demostrada**, así que se instrumenta:

1. Que el **bloque de party** de Gen 5 no refleje el daño hasta que acaba el
   combate. RoleRun lee la party para detectar bajas, así que si el juego no la
   toca antes, la baja no puede verse antes.
2. Que la **lane de presentación** rechace la lectura justo al morir. El byte de
   estado de `0x0225B1C4` solo tiene demostrados los valores 0 y 1, y
   `parse_battle_copies` rechaza cualquier otro; un rechazo deja la lane sin
   confirmar y RoleRun cae al bloque de party. La auditoría del 27-08-2026 ya
   anticipó este riesgo sin poder medirlo.

- Nueva herramienta `tools_b2w2_battle_faint_capture.py`, de **solo lectura**.
  Muestrea a la vez los PS de la party y las dos filas de batalla con su byte de
  estado, y ejecuta **el parser de producción** sobre cada muestra anotando si
  acepta o rechaza y por qué. El diagnóstico dice lo que RoleRun ve de verdad, no
  lo que supondríamos que ve.
- Solo registra los cambios, no las 1.800 muestras, para que el archivo sea
  legible.
- Se registran las validaciones físicas del usuario: casilla correcta liberada,
  selector, recuperación al curar y sustitución completa.

# v0.2.6-alpha.30 — dos hilos dejan de romperse los tipos entre ellos

Al aplicar una sustitución saltaba un error que no tenía nada que ver con la
sustitución:

    argument 2: TypeError: expected LP_PROCESSENTRY32W instance
    instead of pointer to PROCESSENTRY32W

Son **dos clases distintas con el mismo nombre**. Dos causas sumadas:

- `PROCESSENTRY32W` estaba declarada **dentro** de la función que enumera
  procesos, así que cada llamada creaba una clase nueva y volvía a fijar
  `argtypes`. Con el monitor, el sondeo del PC y una escritura solapándose en
  hilos distintos, uno pisaba los tipos del otro en mitad de la llamada.
- `ctypes.windll.kernel32` es un singleton de todo el proceso, y su caché de
  funciones también. **Cuatro módulos** de RoleRun declaran su propia
  `PROCESSENTRY32W` y fijan `argtypes` sobre ese mismo objeto compartido.

Se corrigen las dos: una única estructura de módulo y una **instancia privada**
de kernel32 para B2/W2, con todos los tipos fijados una sola vez al importar.
Los cinco puntos del lector que reconfiguraban el kernel32 compartido en cada
llamada pasan a usarla.

- Además se **serializa el lector** con un cerrojo reentrante. Es el riesgo de
  concurrencia que la auditoría del 27-08-2026 marcó como ALTO —«`RealTimeCore`
  no serializa `read_pc`/`capture_*`/`apply_changes`»— y este fallo es su primera
  manifestación demostrada. Reentrante porque los writers releen party y PC
  dentro de su propia transacción.
- Baseline completa: **1100 passed**.

**Pendiente todavía:** que la vida se descuente en el momento del KO y no al
terminar el combate. Confirmado por el usuario que sigue ocurriendo; no se
declara cerrado.

# v0.2.6-alpha.29 — la baja de B2/W2 deja de quedarse en un limbo

Alpha.28 detectaba la baja pero no permitía salir de ella. Reportado con detalle:
no aparecía la opción de sustituir, curar al debilitado no lo devolvía, reiniciar
juego y programa tampoco, y el hueco vacío se desplazaba al rol equivocado.

Dos causas con una raíz común: la rama B2/W2 del monitor **no llamaba a dos
funciones que los otros cinco backends sí llaman**.

- Sin `_process_oras_battle_state` no se marca nunca `battle_ended`. El selector
  de sustituto lo exige, así que no se abría. Y
  `clear_stale_detected_faint_for_alive_party` exige `battle_ended` **o**
  `prompt_shown`, así que curar al debilitado tampoco lo devolvía. Como la baja se
  persiste en la Run, reiniciar no cambiaba nada. Una sola llamada ausente
  explicaba tres de los síntomas.
- Sin `_reconcile_pending_faints_against_party`, resolver la baja desde el PC del
  propio juego no se detectaba.
- B2/W2 habla de `battle`/`none`; el resto del programa, de `wild`/`trainer`/
  `none`. La traducción se hace explícita, con `None` cuando la lane no está
  confirmada, que es lo que ya hacen los demás backends.

Y una tercera, de presentación y aplicable a todos los juegos:

- La casilla de un rol **pertenece al rol**, y es la que heredará el sustituto.
  Un miembro SIN ROL podía deslizarse hasta la casilla del caído, moviendo el
  hueco visible a otro rol distinto: se veía vacío el puesto de Support cuando
  quien había caído era el Asesino. Una baja pendiente reserva ahora su casilla.
- Baseline completa: **1092 passed**.

# v0.2.6-alpha.28 — bajas y sustitución en B2/W2

El corazón de una RoleRun. Sus tres dependencias quedaron validadas por el
usuario el 27-08-2026: la lane de combate, el writer de roles y la escritura del
PC.

- **Bajas.** B2/W2 entra en el camino común de salud, que además de publicar los
  PS detecta las transiciones a cero, descuenta la vida, registra el evento y
  abre el selector de sustituto. Hasta ahora su rama del monitor ni siquiera
  llegaba a esa detección.
- En combate confirmado se usa `battle-visible`: la copia de presentación de
  B2/W2 ya converge con la animación, así que el KO se registra en cuanto la
  barra visible llega a cero, sin el retraso extra que ORAS necesita.
- **Sustitución.** Nuevo `replace_fainted_party_pc()`. Intervienen **tres**
  posiciones y no dos: el sustituto sale de su casilla, el debilitado se deposita
  en el Cementerio y la casilla de origen queda vacía. Por eso no se puede
  reutilizar `swap_party_pc`.
- El orden de escritura no es casual: primero se copia al debilitado al
  Cementerio, después entra el sustituto en la party y solo al final se vacía la
  casilla de origen. En ningún punto intermedio hay un Pokémon con cero copias;
  como mucho un duplicado transitorio, que sí es recuperable. Hay una regresión
  que lo comprueba escritura a escritura.
- La casilla liberada queda como la deja el juego: un PK5 semilla-0, nunca ceros.
- El sustituto hereda el rol de la casilla que deja libre el debilitado, que es
  la regla nuclear de RoleRun.
- Se exige que el Cementerio esté vacío, que origen y Cementerio sean casillas
  distintas, y las dos identidades fuertes; cualquier fallo hace rollback de las
  tres posiciones.
- Baseline completa: **1082 passed**. Validación física pendiente.

# v0.2.6-alpha.27 — un cambio sin writer ya no puede congelar el seguimiento

Este fallo ha aparecido dos veces con síntomas muy distintos y siempre por la
misma causa, así que se cierra la clase entera en lugar de caso a caso.

- `_oras_live_reconciliation_can_read` exigía la cola de cambios
  **completamente vacía**. Esperar a un cambio que el adaptador vivo no sabe
  aplicar es esperar para siempre: la partida deja de actualizarse y el usuario
  no tiene forma de saber por qué.
- Ocurrió con la curación en alpha.16 y con los roles en alpha.23. La segunda vez
  se manifestó como tres fallos aparentemente distintos —«los roles no
  funcionan», «los EV siguen a cero», «la vida no se refleja»— que resultaron ser
  uno solo.
- Ahora **solo bloquean la lectura los cambios que de verdad tienen writer**. Un
  cambio sin writer sigue en la cola, para poder guardarlo por archivo, pero no
  secuestra el seguimiento en vivo.
- Comprobado además que el selector de MT ya rechaza B2/W2 con un aviso claro y
  sin encolar nada; el drafteo sí puede crear cambios de movimientos, y esos son
  precisamente los que esta red de seguridad desactiva como bloqueo.
- Se registran las validaciones físicas del usuario: rol + EV (alpha.24/25) y
  curación (alpha.26), ambas en Negro 2 España/melonDS 1.1.
- Se elimina una fila duplicada del documento de paridad que seguía declarando el
  writer de roles como cerrado.
- Baseline completa: **1071 passed**.

# v0.2.6-alpha.26 — curación de B2/W2

El botón CURAR vuelve a B2/W2, esta vez con writer propio. Se cerró en alpha.16
precisamente porque no lo tenía: encolaba seis curaciones que nadie escribía y
bloqueaba el monitor en vivo.

- Curar es lo que hace un Centro Pokémon: **PS al máximo, estado alterado a cero
  y PP de los cuatro movimientos al tope**, contando los Más PP aplicados.
- El PP base **no** se toma de la tabla de sexta generación que ya existía en el
  proyecto. Varios movimientos cambiaron de PP entre generaciones y darlos por
  equivalentes sería una analogía no demostrada, justo lo que el proyecto
  prohíbe. Se extrae de la misma PKHeX.Core que usa el motor de guardados con
  `MoveInfo.GetPPTable(EntityContext.Gen5)`.
- Nuevo `data/b2w2_move_pp.json` (559 movimientos, exactamente los de quinta) y
  la herramienta reproducible `tools_extract_gen5_move_pp/` que lo genera.
- Si un PP no se puede demostrar, **no se cura**: antes que inventar un valor
  sobre la partida del usuario, la operación se detiene.
- `write_party_heal()` sigue el contrato transaccional habitual: relectura
  fresca, identidad fuerte por slot, readback con el parser de producción,
  verificación semántica de PS, estado y PP, y rollback completo.
- Curar a quien ya está curado **no escribe ni un byte**.
- Los cuatro tests que fijaban la curación como cerrada se corrigen de forma
  explícita; la regla que protegían —una capacidad solo pasa la compuerta cuando
  tiene writer— sigue vigente y ahora la ejercen los movimientos, que siguen sin
  writer en B2/W2.
- Baseline completa: **1061 passed**. Validación física pendiente.

# v0.2.6-alpha.25 — la ficha de B2/W2 deja de estar vacía y los EV se reparten

Dos fallos del mismo reporte, ambos de la misma familia que el anterior: algo que
compara demasiado poco.

- **La ficha en «—».** `diff_live_party` compara composición, orden, roles,
  movimientos y nivel, e **ignora a propósito** estadísticas, IV, EV y
  naturaleza. La rama B2/W2 solo publicaba la captura viva cuando ese diff
  detectaba algo, así que en cuanto algo reponía `current_game` desde el guardado
  —recargar tras guardar dentro del juego, o abrir la Run— esos datos se perdían
  para siempre. Asignar un rol cambiaba el rol, el diff se activaba, y por eso
  «al elegir el rol ya aparecen los stats».
- Ahora se republica también cuando la captura viva trae datos que la vista no
  tiene. Es una comprobación en un solo sentido y por identidad fuerte, así que
  se cumple una vez y deja de cumplirse: no republica en bucle.
- **Los EV no se repartían.** El cálculo del reparto de EV de un rol estaba
  condicionado a `{"bdsp", "oras", "xy", "sm", "usum"}` escrito como literal en
  **siete sitios distintos**, y B2/W2 no estaba en ninguno. Se sustituye por la
  constante `ROLE_EV_WRITER_GAME_KEYS`, que ya incluye B2/W2 porque desde
  alpha.24 tiene writer.
- Los tres usos restantes de ese literal son de MT/ROM, otra capacidad distinta,
  y se dejan intactos a propósito.
- Recordatorio del contrato: en **Líbero** la ausencia de reparto automático es
  deliberada; RoleRun pide antes las dos características al jugador.
- Baseline completa: **1040 passed**.

# v0.2.6-alpha.24 — writer de roles de B2/W2

Asignar un rol en Negro 2 no hacía absolutamente nada: los seis seguían en
"SIN ROL" y los EV a cero. Y como el cambio se quedaba atascado en la cola, y
`_oras_live_reconciliation_can_read` exige la cola vacía, **congelaba además el
monitor en vivo**. De ahí que la vida tampoco se actualizara.

No existía writer de roles para B2/W2. Ahora sí.

- Nuevo `pk5_party_with_role()`: descifra el PK5, lo desbaraja, escribe las seis
  marcas y los EV, **recalcula las estadísticas** con la tabla personal de la
  edición, recompone el checksum, vuelve a barajar y cifra.
- Cambiar EV sin recalcular dejaría las estadísticas antiguas y un PS máximo que
  no cuadra con el actual. El daño recibido se conserva: si sube el máximo, sube
  igual el actual. Un debilitado sigue debilitado.
- Nuevo `write_party_roles()` con el mismo contrato que los demás writers B2/W2:
  relectura fresca antes de escribir, identidad fuerte por slot, readback con el
  parser de producción, verificación semántica de marcas y EV, y rollback
  completo ante cualquier divergencia. No toca el contador ni el orden.
- El adaptador traduce `PendingRoleChange` a la escritura concreta usando la
  **misma** identidad que `RunProjectService.pokemon_identity_key`; con otra, un
  cambio de rol no encontraría nunca a su Pokémon.
- `SIN ROL` borra las seis marcas, que es el contrato que ya usaba la lectura.
- Se abren las dos compuertas de la interfaz. La curación de B2/W2 **sigue
  cerrada**: abrir roles no puede abrir de rebote lo que no tiene writer.
- Baseline completa: **1027 passed**. Validación física pendiente.

# v0.2.6-alpha.23 — la vida se actualiza también DURANTE el combate

La captura del usuario lo dejó claro: con Mareep debilitado (0/22) y Azurill a
4/20, RoleRun pintaba a los seis miembros al máximo durante todo el combate y
solo se corregía al salir.

- **Causa raíz.** `BattleState` vale `"unknown"` por defecto y la lane de
  presentación de B2/W2 lo deja así ante **cualquier** excepción: dos copias
  describiendo miembros distintos durante un cambio, animación a medias, o un
  estado runtime todavía no demostrado. Con ese valor no se publicaba ninguna
  salud, de modo que un fallo que afecta al Pokémon **activo** congelaba a los
  seis.
- Esa lane gobierna solo los PS del activo: los otros cinco ya salen del bloque
  de party incluso en un combate confirmado, y ahí no hay nada que destripar.
  Ahora, con la lane sin validar, se publica el bloque de party.
- Dejar un debilitado pintado a vida llena durante todo el combate es peor que
  adelantar unos segundos el daño de un único Pokémon.
- **No se relaja la regla validada en alpha.5**: con el combate confirmado sigue
  mandando la copia de presentación, que no adelanta el daño a la animación.
  Tampoco se afirma que haya combate cuando no se sabe: no se toca
  `_oras_battle_probe_last_state`.
- Baseline completa: **999 passed**.

# v0.2.6-alpha.22 — el parpadeo de la barra flotante y los PS de B2/W2

Dos fallos reportados por el usuario, **con una única causa raíz**: la rama
B2/W2 del monitor hacía justo lo contrario de lo necesario.

- **El parpadeo, por fin.** Cuando nada había cambiado, esa rama llamaba en cada
  ciclo —cada 950 ms— a `_sync_live_layout(refresh_floating=True)`, que fuerza
  una reconstrucción **completa** de la barra flotante: destruye todos sus
  widgets y relee dos PNG del disco. Ese era el parpadeo de una vez por segundo
  que llevaba muchas versiones. Ahora, cuando no hay novedad, no se toca la
  barra.
- **Los PS de B2/W2.** Era el único backend que no publicaba la salud viva por
  el camino común. Como `diff_live_party` ignora los PS a propósito —su trabajo
  es la composición del equipo, no la vida—, un cambio de vida dejaba
  `difference.changed` en falso y no llegaba nunca a `current_game`. La ventana
  principal no podía enseñarlo.
- Se extrae `_publish_live_health()`, la parte de `_process_oras_health_snapshot`
  que **no** decide bajas, y B2/W2 la usa. Su maquinaria de KO sigue cerrada
  porque todavía no tiene writer de sustitución seguro.
- Solo se publica salud demostrada: en combate la copia de presentación, fuera
  de combate el bloque de party. Con la lane de batalla en un estado no
  confirmado no se publica nada, que es justo para lo que existe esa copia.
- **La barra flotante también se actualiza en su sitio.** Un cambio de PS ya no
  la reconstruye: se mueve la barra y ya está. Cede a la reconstrucción cuando
  cambia un contador, el ocupante de un rol, su visibilidad, el sprite, cuando
  aparece o desaparece un estado o cuando la vida cruza por cero, porque al 0 %
  la casilla no tiene barra sino un carril neutro.
- La firma de la barra pasa a ser `(contadores, roles)` en vez de una tupla
  plana, para poder distinguir «solo cambiaron los PS» de «cambió la
  composición».
- Baseline completa: **996 passed**.

# v0.2.6-alpha.21 — los PS en vivo dejan de reconstruir la página

Primera pieza de la Fase 3, la de velocidad percibida, y la primera medida sobre
la vista real bajo Tk en Windows.

- **Medición que faltaba.** La auditoría estimó ~0,6 s por reconstrucción en
  Linux y lo dejó como hipótesis para Windows. Construyendo la vista de verdad:
  **642 widgets Tk y 845 ms** de hilo bloqueado (666 ms de construcción, 157 de
  `update_idletasks`, 23 de `update`). Una confirmación de cambio dispara 3-4
  reconstrucciones: **2,5-3,4 segundos** de congelación.
- Durante un combate el monitor lee cada 250-450 ms y **cada cambio de PS
  reconstruía la página entera** solo para mover unas barras.
- `UnifiedTeamPCView` gana `update_team_health()` y `rendered_team_identities()`.
  Actualizar las seis barras cuesta **8,2 ms**: **×103** más rápido.
- La presentación de PS —fracción, color y texto— pasa a calcularse en un único
  sitio, `_health_presentation`, que usan por igual el render completo y la
  actualización incremental. Si cada uno calculara lo suyo, una barra actualizada
  en vivo podría acabar mostrando un color distinto al del render normal.
- Es una ruta de **aceleración, no de decisión**: cede al render completo si la
  composición del equipo cambió (baja, sustitución, entrada desde el PC), si la
  vista no es la publicada, si una tarjeta ya está destruida o ante cualquier
  error. No cambia nunca lo que se muestra.
- La evidencia que consulta la barrera inicial se actualiza junto a los widgets:
  de lo contrario diría que se muestra un PS que ya no es el que se ve.
- Primeras pruebas del proyecto que **construyen la ventana Tk real**, como
  recomendaba la auditoría; se omiten solas si no hay entorno gráfico.
- Baseline completa: **981 passed**.

# v0.2.6-alpha.20 — la base de melonDS se resuelve una vez, no en cada lectura

- Hasta ahora, **cada** `read_party()` y **cada** `read_pc()` de B2/W2 recorrían
  entero el espacio de direcciones de melonDS con `VirtualQueryEx` y sondeaban
  con lecturas de memoria cada `AllocationBase` distinta. Se pagaba en cada ciclo
  del monitor, otra vez en cada escritura y, desde alpha.19, también en cada
  sondeo del PC vivo.
- La base demostrada se cachea y se reutiliza. **No es un atajo que se salte
  comprobaciones**: cada lectura vuelve a ejecutar la misma doble lectura estable
  de `count`+party, el mismo rango del contador y el mismo checksum de cada PK5.
  Lo único que se omite es *buscar dónde está* esa base.
- La detección de lecturas ambiguas solo existe en el recorrido completo, así que
  se redescubre siempre que cambia el conjunto de procesos melonDS (abrir o
  cerrar una segunda instancia) y, por seguridad, cada 60 s aunque nada cambie.
- Si la revalidación de la base falla —por ejemplo tras un state-load que remapee
  la memoria— se vuelve a descubrir en silencio en vez de dar error. Si melonDS
  desaparece, la base se olvida.
- Con el sondeo del PC cada ~2,5 s, los recorridos completos pasan de uno por
  lectura a como mucho uno por minuto.
- **No se toca** la doble lectura interna de `resize_party_pc`: es la captura
  fresca inmediatamente anterior a escribir y forma parte del contrato del
  writer. Eliminar esa relectura ahorraría tiempo a costa de seguridad.
- Es además la primera pieza pensada para reutilizarse en los otros juegos NDS:
  resolver la base del emulador es común; las direcciones y el formato del bloque
  no lo son.
- Baseline completa: **961 passed**.

# v0.2.6-alpha.19 — RoleRun vuelve a mirar el PC del juego

Fallo físico reportado el 27-08-2026 en Negro 2/melonDS: un Azurill movido al
slot 7 del PC desde RoleRun y movido después al slot 2 **dentro del juego**
seguía apareciendo en el 7 dentro de RoleRun; al retirarlo al equipo desde esa
vista desfasada apareció duplicado.

- **Causa raíz demostrada.** `_bdsp_pc_poll_is_active` exigía
  `active_page == "pc"`, pero desde que Equipo y PC se unificaron en una sola
  pantalla **ninguna ruta de navegación produce ese valor**: la barra principal
  solo ofrece `("team", "♟ EQUIPO Y PC")` y `_render_context_navigation` oculta
  los controles secundarios justamente para `{"team", "pc"}`. El sondeo
  permanente del PC vivo quedó inalcanzable para B2/W2 y BDSP, así que RoleRun
  leía el PC del juego al cargar y **no volvía a mirarlo nunca**.
- Lo mismo ocurría al entrar y salir de la vista: el refresco de entrada y la
  cancelación del sondeo comprobaban solo `"pc"`.
- Los tres puntos pasan a usar `TEAM_PC_PAGES = {"team", "pc"}`, declarado una
  sola vez. El resto del archivo ya comprobaba `in {"team", "pc"}` en diez
  sitios: estos se habían quedado atrás en la unificación.
- Con el predicado corregido, el sondeo vuelve a rearmarse tras cada
  reconciliación, que es lo que restaura el seguimiento continuo del PC.
- Tres regresiones existentes afirmaban que `"team"` debía detener el sondeo.
  Esa expectativa era el defecto y se corrige de forma explícita, no relajando
  la comprobación.
- **No demostrado todavía:** el mecanismo exacto de la duplicación. Su
  precondición —RoleRun operando sobre un PC que nunca refrescaba— queda
  cerrada. Ninguna partida estuvo en riesgo: el writer valida identidad y
  coordenadas contra la RAM y hace rollback antes de escribir.
- Baseline completa: **953 passed**.

# v0.2.6-alpha.18 — el bucle de mando deja de robar CPU a la interfaz

- Mientras no hubiera un mando resuelto, el bucle de mando buscaba Ryujinx en
  **cada tick de 16 ms**, y esa búsqueda enumera la tabla completa de procesos
  de Windows. Sin Ryujinx abierto —todos los juegos salvo BDSP— eso costaba
  2,36 ms por intento: **142 ms de CPU por segundo, el 14 % de un núcleo**,
  robados al hilo que dibuja la interfaz desde el splash y durante toda la
  sesión.
- La búsqueda pasa a intentarse como mucho cada 2 s. Conectar Ryujinx a mitad de
  sesión se sigue detectando; solo tarda unos segundos, imperceptible.
- No se restringe la búsqueda a BDSP: no está demostrado que el mando no se use
  en otros juegos con Ryujinx instalado, y el intervalo ya elimina el coste.
- Medición hecha con la instrumentación de alpha.15 en esta máquina.
- Baseline completa: **940 passed**.

# v0.2.6-alpha.17 — monitor que no se queda huérfano y sprites que no bloquean

- **R1 corregido.** Si el usuario guardaba dentro del juego mientras una lectura
  del monitor estaba en vuelo, el watcher invalidaba el token, se encontraba el
  cerrojo puesto y no armaba nada; el worker viejo terminaba, soltaba el cerrojo
  y descartaba su resultado sin reprogramar. La sesión quedaba viva y sin nadie
  leyendo hasta el siguiente guardado. Ahora el worker obsoleto rearma el
  monitor si la sesión sigue activa. Se corrige ahí, y no soltando el cerrojo
  antes, porque eso permitiría capturas solapadas sobre readers sin lock.
- **Error ≠ dato.** `_oras_live_snapshot_matches_disk` devolvía `False` tanto si
  la comparación con `main` demostraba una diferencia como si el motor fallaba
  al leer. Ahora devuelve `None` cuando no se pudo comprobar, deja rastro del
  error y RoleRun ya no adopta como buena una huella que nunca verificó:
  conserva la expectativa anterior y reintenta en el siguiente ciclo.
- **Sprites que ya no bloquean el arranque.** Sin Internet y sin la imagen en
  disco, el worker terminaba en silencio; como la barrera inicial espera a todos
  los sprites de la party, RoleRun podía quedarse en la pantalla de carga
  indefinidamente. Ahora se publica una silueta dibujada localmente, con aviso
  no bloqueante, y la partida se abre igual.
- La descarga de sprites pasa a tener límite de tiempo (8 s); `urlretrieve` no
  admitía ninguno y una red no enrutada podía colgar el hilo para siempre.
- Se deduplican las peticiones: seis tarjetas de la misma especie abrían seis
  hilos compitiendo por el mismo archivo temporal.
- Al recargar la partida se reintentan solo las imágenes que quedaron ausentes.
- Baseline completa: **935 passed**.

# v0.2.6-alpha.16 — retirada B2/W2 y botón CURAR coherente

- **B1 corregido.** Retirar del PC al equipo (`box-to-party`) era imposible: el
  writer dejaba 136 ceros en el slot PC liberado y su propia relectura los
  rechazaba por checksum, así que toda retirada acababa en rollback. El juego no
  deja ceros, deja un PK5 almacenado cifrado con semilla 0. Lo demuestran la
  captura física `b2w2_party_resize_latest.json` —tras retirar desde el juego, el
  parser de producción leyó `pc_empty: 717` sin error— y la cola de party ya
  validada en alpha.13, que empieza exactamente por esos mismos 136 bytes.
- Nueva función `empty_pk5_stored()` como única fuente de esa representación;
  `empty_pk5_party()` se construye sobre ella y conserva sus bytes exactos
  (mismo SHA-256 `0a62191d…a2856`).
- **B2 corregido.** B2/W2 mostraba el botón CURAR sin tener writer de curación.
  Encolaba seis `PendingPartyHeal` que la compuerta B2/W2 no acepta y que
  `_discard_b2w2_ghost_team_changes` no retiraba; como el monitor exige la cola
  vacía para leer, la partida viva dejaba de actualizarse hasta descartarlos a
  mano. El botón se retira hasta que exista su writer validado.
- La regresión de B2 se escribió como invariante para los seis backends: el
  botón CURAR y la compuerta de auto-aplicación deben coincidir siempre.
- Nuevo simulador de RAM de melonDS en las pruebas: ejercita el ciclo completo
  del writer —escritura, relectura con el parser de producción y rollback— de
  forma determinista y sin proceso real. No sustituye a la validación física.
- Corregida la fila de paridad que afirmaba tener pruebas del tamaño 1–6 sin
  que existiera ninguna.
- Baseline completa: **918 passed**. Validación física de la retirada PC→Equipo
  en Negro 2/melonDS: **pendiente**.

# v0.2.6-alpha.15 — instrumentación de rendimiento medible

- Nuevo módulo `app/perf.py` y modo diagnóstico `ROLERUN_PERF=1`. Apagado —el
  caso normal— su coste es cero: el decorador devuelve la función original sin
  envolverla. Encendido escribe `Logs/perf_<fecha>.jsonl` con una línea por
  operación, incluyendo el hilo en que corrió.
- Puntos medidos: invocaciones del motor .NET por comando, capturas/`read_pc`/
  escrituras del Core realtime por backend, walk de regiones y lecturas de
  B2/W2, render completo y transición de navegación, bucle de mando (agregado
  por ventana de un segundo), cadena de confirmación de cambios, recarga tras
  guardado del juego, sincronización OBS e historial de la run.
- La escritura del registro ocurre en un hilo propio, nunca en el hilo medido,
  para no medir la propia instrumentación en NTFS con antivirus.
- No cambia comportamiento: se conservan retorno, excepciones y firma, y
  `inspect.getsource` sigue viendo el cuerpo original de los métodos medidos.
- Primeras cifras reales en Windows: **~72 ms de suelo por invocación del motor
  .NET** sin abrir siquiera un save, y 2,5–8,1 ms por `append_history`.
- Documentación en `docs/PERF_INSTRUMENTATION.md`. Regresiones en
  `tests/test_perf_instrumentation.py`. Baseline completa: **906 passed**.

# v0.2.6-alpha.14 — depósito B2/W2 y ventana principal maximizada

- Corregida la primera divergencia del depósito Equipo→PC: la cuadrícula se
  componía con la matriz viva de melonDS, pero la acción volvía al PC del save
  y podía elegir una casilla ocupada en RAM. B2/W2 conserva ahora el destino
  vivo exacto y el writer mantiene su relectura inmediata antes del commit.
- Tras validar y componer la partida, la interfaz principal se abre maximizada
  como ventana normal de Windows (`zoomed`), sin usar fullscreen/F11. El
  cargador inicial permanece centrado y permite cambiar de aplicación.
- Añadidas regresiones para el destino B2/W2 y la transición visual.

# v0.2.6-alpha.13 — tamaño de equipo B2/W2 1–6

- La captura 6→5→6 demostró que depositar compacta todos los slots posteriores,
  retirar añade al final y el contador de `0x0221E3A8` es la autoridad.
- El slot físico liberado coincide byte por byte con un PK5 party vacío cifrado
  con semilla cero (`SHA-256 0a62191d…a2856`), no con 220 ceros.
- Depósito y retirada escriben primero PC/party y el contador al final. Verifican
  count, orden, identidad, destino/origen PC y aplican rollback completo.
- Se impide depositar el último miembro y se mantiene la restricción temporal
  de retirar solo Pokémon sin objeto hasta demostrar correo/objetos party.
- Implementación y regresiones completas; validación física desde RoleRun pendiente.

# v0.2.6-alpha.12 — ventana inicial centrada

- La geometría normal 1360×860 se calcula respecto a la pantalla de Windows y
  arranca centrada. La barrera de carga hereda esa misma posición.
- Se conserva el comportamiento de alpha.11: sin pantalla completa, `topmost`
  ni bloqueo para cambiar a otras aplicaciones.
- Preparada una captura de solo lectura para demostrar contador y compactación
  en transiciones de party 6→5→6 antes de abrir cambios de tamaño B2/W2.

# v0.2.6-alpha.11 — carga inicial no invasiva

- La pantalla de carga inicial conserva la geometría normal de RoleRun: ya no
  se maximiza ni fuerza la raíz a pantalla completa durante la composición.
- La barrera deja de usar `topmost`, por lo que Alt+Tab y el cambio a otras
  ventanas permanecen disponibles mientras conecta emulador, equipo y PC.
- Se conserva la barrera de composición: la interfaz definitiva solo aparece
  después de validar layout, sprites, matriz PC y primer snapshot live.
- Validación física B2/W2: Equipo→PC, PC→PC y PC→Equipo 1:1 funcionan desde
  RoleRun en Negro 2 España/melonDS 1.1.

# v0.2.6-alpha.10 — intercambio Equipo↔PC 1:1 B2/W2

- Una captura antes/intercambio/restauración demostró que los 136 bytes stored
  pasan intactos entre PC y party, mientras el anexo de 84 bytes se reconstruye.
- El contrato se trazó a `PK5.ResetPartyStats`: estado limpio, nivel efectivo,
  PS completos y stats recalculadas; correo y bytes residuales parten vacíos.
- La prueba física escribió Lillipup en Equipo/1 con nivel 6, 21/21 PS y stats
  21/12/11/8/12/12, y Tepig en Caja 1/slot 2. El readback independiente confirmó
  las identidades y los 720 slots.
- Producción habilita solo swap 1:1 con equipo lleno y entrante sin objeto,
  precondiciones inmediatamente anteriores, readback y rollback completos.
  Depósito/retirada que cambien el tamaño siguen cerrados.

# v0.2.6-alpha.9 — writer PC→PC B2/W2

- La prueba física movió Lillipup de Caja 1/slot 2 a slot 4 en Negro 2
  España/melonDS 1.1. El readback independiente confirmó origen vacío, misma
  identidad en destino y 3 ocupados + 717 vacíos válidos.
- El writer de producción exige origen ocupado, destino vacío, identidad fuerte
  estable inmediatamente antes de escribir y doble lectura completa.
- Escribe destino antes que origen, verifica los 24×0x1000 bytes y hace rollback
  confirmado de ambos PK5 si falla cualquier comprobación.
- Equipo↔PC continúa cerrado: convertir stored PK5 (136 bytes) a party PK5
  (220 bytes) requiere una prueba estructural y transaccional independiente.
- El usuario validó además el movimiento PC→PC desde la propia interfaz de
  alpha.9; el cambio se reflejó correctamente dentro del juego.

# v0.2.6-alpha.8 — ficha de equipo y proyecciones seguras B2/W2

- La party B2/W2 publica ahora sus estadísticas base desde el mismo Personal
  oficial ya utilizado por las fichas del PC.
- B2/W2 deja de crear cambios Equipo↔PC locales que no puede escribir: la
  conexión retira las proyecciones antiguas y vuelve a mostrar la RAM real, sin
  duplicar al miembro saliente.
- El rechazo de PC→PC aclara que el reader está disponible pero el writer sigue
  pendiente; no deja cambios fantasma.
- Añadida una prueba transaccional independiente PC→PC con precondiciones,
  readback de los 720 slots y rollback. No se habilita en producción hasta su
  validación física.

# v0.2.6-alpha.7 — seguimiento externo del PC B2/W2

- Equipo↔PC se reconcilia desde cada transición estable de la party y PC↔PC
  se sondea ahora mientras la pantalla PC está visible, reutilizando la matriz
  24×30 y su doble lectura integral; no se realiza ningún escaneo ni escritura.
- El sondeo no solapa workers, solo repinta cuando cambia la proyección y se
  cancela al abandonar PC, ocultar RoleRun o perder la sesión live.
- Añadida una regresión específica del ciclo B2/W2; validación física pendiente.

# v0.2.6-alpha.6 — party completa, lectura PC y estado de combate B2/W2

- Corregida la desordenación PK5: se aplicaba la permutación inversa y solo
  parecía funcionar con PID de disposición autoinversa. Lillipup y Patrat se
  rechazaban pese a tener checksum correcto; ahora se publican los seis slots.
- Incorporada la matriz PC demostrada de Negro 2 España/melonDS 1.1: 24 cajas,
  30 PK5 stored de 136 bytes por caja y stride `0x1000`, con doble lectura y
  validación de los 720 slots. Las escrituras continúan cerradas.
- El estado de batalla usa el byte de presentación `0x0225B1C4`, observado
  como `0→1→0` al aplicar PAR y salir del combate. Así puede mostrarse durante
  el combate sin esperar a la party nominal ni adelantar el evento visual.
- Añadidas regresiones para PID no autoinverso, matriz PC completa, vacíos
  corruptos, publicación de ficha PC y estado PAR del carril de batalla.
- Validación física completada en Negro 2 España/melonDS 1.1: seis miembros
  visibles, barra completa, Caja 1 correcta y PAR publicado durante combate.

# v0.2.6-alpha.5 — daño sin spoiler y parálisis B2/W2

- La HUD deja de publicar el PS lógico adelantado: espera la convergencia de la
  copia asociada a la presentación del juego, sin aplicar temporizadores fijos.
- El valor runtime `1`, demostrado físicamente como parálisis, se traduce al
  estado común PAR. Estados no observados no reciben una etiqueta inventada.
- Añadidas regresiones para el mirror retrasado y la conversión de parálisis.
- Validación física completada: el daño ya no se adelanta visualmente y la
  parálisis aparece como `PAR` en Negro 2/melonDS.

# v0.2.6-alpha.4 — PS inmediatos de combate B2/W2

- Una traza temporal demostró que `0x0225B5FC` publica el KO 3,36 segundos
  antes que `0x0225B1B4`; se usan respectivamente como fuente inmediata y
  testigo de convergencia.
- El reader exige doble lectura e identidad única contra la party. Un fallo del
  lane de batalla no invalida el equipo normal.
- La barra puede actualizar PS cada 250 ms durante combate. KO automático sigue
  cerrado hasta disponer de PC/reemplazo seguro para B2/W2.
- Verificación dirigida: **26 passed**.

# v0.2.6-alpha.3 — barra B2/W2 y evidencia inicial de combate

- La barra flotante muestra ahora también miembros SIN ROL en las casillas
  libres, igual que la vista principal, sin convertir la posición visual en rol.
- Mientras B2/W2 sea read-only, la ausencia de marca PK5 no borra un rol ya
  persistido en la Run; una única marca viva sí continúa siendo autoridad.
- La captura física de combate encontró dos copias coherentes de Tepig con PS
  `24→21` y desaparición poscombate. Siguen en investigación y KO permanece
  cerrado hasta distinguir autoridad y mirror.
- El usuario confirmó físicamente que Tepig vuelve a aparecer en la barra
  flotante de Negro 2/melonDS, incluso sin una marca PK5 escrita.
- Verificación dirigida: **23 passed**.

# v0.2.6-alpha.2 — ficha PK5 completa y matriz de paridad B2/W2

- El reader de party publica estado, naturaleza, stats, IV, EV, PP, PP Up,
  huevo y marcas desde el mismo PK5 estable ya validado.
- Los offsets se trazan a `PKHeX.Core.PK5` y se contrastaron con la party real
  abierta en melonDS 1.1.
- Los roles se derivan de las seis marcas vivas respetando el layout de la Run.
- `docs/B2W2_REALTIME_PARITY.md` registra todos los carriles de 3DS/BDSP y sus
  dependencias. B2/W2 continúa estrictamente en solo lectura.
- Verificación dirigida: **10 passed**. El usuario confirmó visualmente IV,
  EV, habilidad, objeto y movimientos; PP se lee pero la UI no lo presenta.

# v0.2.6-alpha.1 — party B2/W2 de solo lectura en melonDS

- Inicia la serie 0.2.6 con Pokémon Negro 2/Blanco 2. El primer alcance es
  equipo PK5, identidad, nivel, movimientos y PS desde Pokémon Negro 2
  (España) en melonDS 1.1.
- La muestra física demostró la party nominal en `0x0221E3AC` y su contador en
  `0x0221E3A8`. Una segunda dirección usada por el intento antiguo quedó
  refutada: ya no contenía PK5 y hacía rechazar la lectura válida.
- El reader exige un único mapeo anfitrión y relee dos veces `count + party`.
  Todos los PK5 deben superar checksum, especie, nivel y coherencia de PS.
- El adapter exige además una identidad PID/TID/SID común con el guardado
  activo. La lectura real produjo Tepig, nivel 5 y 22/22 PS.
- La UI termina conexión y monitor antes de cualquier writer. PC, roles,
  curación, MT, inventario, batalla, bajas y progreso quedan bloqueados.
- Verificación: 10 regresiones B2/W2 dirigidas y **876 passed** en la suite
  completa.
- Validación física completada en Pokémon Negro 2/melonDS 1.1: conexión,
  equipo, PS y actualización en vivo funcionan correctamente desde RoleRun.

# v0.2.5-alpha.9 — lectura inmediata del drafteo de Líbero

- Reordenada la presentación del drafteo de Líbero: las tres categorías
  auxiliares sorteadas ocupan la fila superior y los resultados fijos de daño
  físico y especial quedan centrados en la fila inferior. La generación y sus
  restricciones no cambian.
- Confirmados físicamente por el usuario en ORAS/Azahar el dinero infinito, la
  composición completa de cinco opciones de Support y el drafteo propio de
  Líbero.
- La enseñanza de MT ya implementada continúa siendo la única validación física
  pendiente para cerrar el alcance ORAS actual.

# v0.2.5-alpha.8 — dinero ORAS validado y drafteos de cinco opciones

- Corregida la segunda divergencia del dinero infinito en ORAS: la dirección
  nominal del bloque Misc podía contener ceros estructuralmente plausibles y
  se aceptaba solo porque dinero y PB estaban dentro de rango. El resolver
  exige ahora que el bloque Misc nominal coincida con el testigo completo del
  guardado; si no coincide, localiza y valida de forma independiente la copia
  viva correcta.
- La escritura real terminó con readback de `9.999.999 ₽` en
  `0x08C6DDD0`. Se mantienen las precondiciones, la copia anterior y el
  rollback verificado. Falta únicamente confirmar el valor desde la interfaz
  del juego.
- Los drafteos de cinco categorías se distribuyen en dos filas, tres arriba y
  dos centradas debajo. La comprobación visual a 1920×1080 muestra las cinco
  tarjetas completas, incluidos sus botones, sin desplazamiento vertical.
- Líbero deja de reutilizar manualmente el pool de otro rol: genera siempre un
  movimiento de daño físico, uno de daño especial y tres categorías auxiliares
  distintas elegidas entre los roles disponibles para el juego activo. No se
  repiten categorías ni se introducen movimientos de generaciones posteriores.

# v0.2.5-alpha.7 — dinero y metadatos completos de MT en ORAS

- Corregida la primera divergencia del dinero infinito: el dinero pertenece al
  bloque Misc del guardado, pero el writer lo resolvía aplicándole el
  desplazamiento descubierto para las bolsas del inventario. Ahora localiza y
  valida el bloque Misc de forma independiente mediante su testigo completo.
- La escritura exige precondiciones de sesión y testigo, conserva los bytes
  anteriores, hace readback del valor y ejecuta rollback verificado si diverge.
  No se ha reutilizado ninguna dirección ni desplazamiento de otro backend.
- Añadida la tabla de movimientos fijada a Omega Rubí/Zafiro Alfa. La UI usa
  ahora potencia, precisión, PP y descripción de la revisión ORAS, sin heredar
  datos de X/Y ni de generaciones posteriores.
- La comprobación visible en RoleRun mostró únicamente las MT presentes en la
  mochila viva: MT39 Truco Fuerza y MT54 Pistola Agua; Pistola Agua aparece con
  potencia 40, precisión 100 y 25 PP. Falta confirmar visualmente en el juego
  que el dinero queda en 999.999 ₽.

# v0.2.5-alpha.6 — MT de ORAS vinculadas solo a la mochila viva

- Corregida la primera divergencia del selector de MT de ORAS: cuando fallaba
  la lectura de la mochila viva, la UI recuperaba silenciosamente el inventario
  del último guardado. Eso podía ofrecer una MT que ya no estuviera en la
  sesión actual, aunque el writer y el mensaje de error exigían RAM validada.
- El inventario del guardado se conserva únicamente como testigo para localizar
  y validar la mochila; si la lectura RAM falla, el selector no se habilita ni
  muestra datos obsoletos.
- La escritura ya existente mantiene las MT de ORAS como reutilizables y exige
  precondiciones, readback y rollback. Las regresiones focalizadas de UI,
  inventario y writer completan `14 passed`.
- El usuario confirmó físicamente en ORAS/Azahar los metadatos completos de
  equipo y PC entregados en `alpha.5`.
- La enseñanza física de una MT en ORAS/Azahar queda pendiente antes de cerrar
  esta capacidad.

# v0.2.5-alpha.5 — metadatos completos de equipo y PC en ORAS

- Corregida la primera divergencia de las fichas ORAS: el perfil Personal de la
  ROM se cargaba correctamente, pero la sincronización inicial lo invalidaba
  justo después de capturar el equipo y antes de publicar o refrescar las
  fichas. Por ello el equipo perdía las stats base y el PC no podía reconstruir
  naturaleza, stats finales, IV ni EV.
- La sincronización inicial, el refresco externo del PC y la resincronización
  manual preparan ahora el perfil ORAS antes de capturar los datos y lo
  conservan durante la publicación. La finalización inicial refresca también
  las cajas ORAS, igual que ya hacía con X/Y.
- Se añadieron regresiones del ciclo de vida del perfil. La comprobación local
  visible confirmó en Dwebble de PC naturaleza Ingenua, stats finales, stats
  base, IV y EV. No se modificaron roles, EV, offsets ni otros backends.

# v0.2.5-alpha.4 — EV completos en intercambios Equipo↔PC de ORAS

- Corregida la primera divergencia del intercambio: la UI calculaba y enviaba
  los EV correspondientes al rol heredado, pero `ORASLiveWriter` solo aplicaba
  el marcador y reconstruía las estadísticas con los EV antiguos del Pokémon
  guardado en el PC.
- El writer aplica ahora los seis EV recibidos, valida límites y total, vuelve
  a calcular la extensión de party y mantiene el readback byte a byte y el
  rollback ya existentes para el intercambio completo.
- La regresión intercambia un Zigzagoon de PC por el primer miembro, demuestra
  252 EV en At. Esp. y Velocidad en el PK6 y comprueba las estadísticas finales
  reconstruidas. No se añade ninguna dirección RAM ni se toca otro backend.
- El cambio de rol Houndoom↔Quagsire de `alpha.3` quedó validado físicamente por
  el usuario en ORAS/Azahar, incluidos EV y estadísticas resultantes.

# v0.2.5-alpha.3 — Personal ORAS fijado en cambios de rol

- Corregido el rechazo falso «la ROM activa no contiene datos Personal» al
  intercambiar roles que recalculan EV y estadísticas. La ROM configurada sí
  contiene la entrada exacta de Quagsire (especie 195, forma 0); la divergencia
  estaba en que la UI solo precargaba Personal para operaciones estructurales
  Equipo↔PC, no para `PendingRoleChange` con EV.
- La transacción carga ahora el perfil de la ROM exacta antes de cualquier
  escritura de rol que necesite recalcular estadísticas y fija ese perfil al
  writer durante toda la operación, sin depender de una caché mutable de UI.
- No se añade ni modifica ninguna dirección RAM. Las regresiones cubren el
  disparador de precarga, los cambios sin EV y la conservación del perfil.

# v0.2.5-alpha.2 — roles, EV y estadísticas vivas de ORAS

- Corregida la primera divergencia del flujo de roles ORAS: la UI excluía este
  backend al construir los EV automáticos y el writer solo cambiaba el marcador
  del rol, aunque ORAS ya exponía la extensión viva necesaria para recalcular
  las estadísticas.
- Los roles fijos escriben ahora su distribución completa de EV y Líbero abre
  el selector de dos estadísticas. La misma ruta se aplica a cambios manuales,
  sustituciones y entradas desde el PC.
- La operación valida identidad, rol, EV anteriores, nivel, datos Personal y
  estadísticas runtime antes de escribir. Conserva los PS perdidos, recalcula
  PS máximos y las cinco estadísticas, hace readback de PK6 y extensión viva y
  restaura ambas regiones si cualquier comprobación falla.
- La curación completa de `v0.2.5-alpha.1` quedó validada físicamente por el
  usuario en ORAS/Azahar.
- Las regresiones cubren aplicación y recálculo, rechazo de EV obsoletos y
  rollback ante fallo de readback. La asignación de rol permanece pendiente de
  validación física en ORAS/Azahar.

# v0.2.5-alpha.1 — curación completa de ORAS

- ORAS incorpora la operación de curación completa ya demostrada para la
  estructura PK6: restaura PS, problemas de estado y PP de los seis miembros.
- El writer exige captura estable, identidad inequívoca de cada objetivo y
  testigos inmediatos antes de escribir; después verifica por readback los
  bytes almacenados y las estadísticas runtime.
- Cualquier divergencia activa rollback de todos los slots afectados y exige
  una segunda lectura que demuestre la restauración exacta.
- No se añade ninguna dirección RAM: se reutilizan únicamente el bloque, stride
  y offsets ORAS ya validados por el reader y el writer existentes.
- Regresiones automatizadas cubren el éxito y la restauración completa ante un
  readback corrupto. Queda pendiente la validación física en ORAS/Azahar.

# v0.2.4-alpha.14 — vacío PK6 válido en el PC de X/Y

- La captura física demostró que vaciar una casilla PC con `0xE8` ceros deja un
  Huevo corrupto visible. Caja 1:11 contenía exactamente esos ceros, mientras
  los slots vacíos válidos 6–10 y 12 compartían una plantilla PK6 cifrada no
  nula e idéntica.
- `PC→Equipo` y `PC→PC` dejan de escribir ceros. Antes de la transacción el
  writer relee la matriz completa dos veces y exige una representación vacía
  no nula, semánticamente vacía, repetida y única. Sin esa evidencia aborta.
- Readback y rollback comparan ahora esa plantilla exacta. La regresión exige
  que el origen quede vacío sin convertirse en cero y conserva los rechazos y
  restauraciones ante cualquier divergencia.
- Validación física completada en Pokémon X/Azahar 263745c: el movimiento
  PC→PC dejó el origen vacío sin Huevo y conservó el destino correcto.
- En la misma sesión se validaron físicamente Caramelo Raro ×999, Repelente
  Máximo ×999 y dinero máximo; las tres utilidades se reflejaron correctamente
  dentro de Pokémon X.
- Validado además el carril de PS X/Y en combate y tras salir de él, junto con
  la curación completa desde RoleRun.
- Validación física del flujo simple de baja en Pokémon X/Azahar 263745c: la
  transición a 0 PS descontó una única vida, el selector apareció al terminar
  el combate y el sustituto elegido se incorporó correctamente.
- Una segunda prueba física con dos KO dentro del mismo combate descontó
  exactamente dos vidas y encadenó correctamente ambos selectores y sus
  sustituciones.
- La party observada seguía compacta (`count=4`, slots 1–4 ocupados); los huecos
  de la pantalla de equipo son la disposición visual nativa de Pokémon X.

# v0.2.4-alpha.13 — testigos PC vivos al depositar en X/Y

- La prueba física de alpha.12 confirmó que Budew quedó correctamente en el
  slot de memoria 5, con contador 5 y slot 6 vacío. La disposición del menú de
  Pokémon X deja visualmente libre la casilla inferior izquierda con cinco
  miembros; no es un hueco interno ni requiere reordenar RAM.
- Demostrada la causa del rechazo al devolver Budew: la cuadrícula mostraba los
  cuatro ocupantes de la matriz viva, pero `_pc_box_witnesses` consultaba solo
  los ocupantes del último `main`, que estaba vacío. La operación llegaba al
  writer sin testigos y este abortaba correctamente antes de escribir.
- Los testigos se obtienen ahora de la misma proyección viva que renderiza la
  caja. Se mantienen la exclusión del destino, la identidad estable y todos los
  validadores y mecanismos de rollback del writer X/Y.

# v0.2.4-alpha.12 — compuerta completa Equipo↔PC de X/Y

- Demostrada la primera divergencia común de las operaciones que no llegaban a
  ejecutarse: la UI automática admitía los cinco tipos X/Y, pero la validación
  inmediatamente anterior al Core omitía `party-to-box` y `box-to-party`; el
  botón de cambios pendientes conservaba una lista todavía más antigua.
- Las dos compuertas aceptan ahora exactamente las cinco operaciones que
  `XYLiveWriter` ya valida: movimiento PC→PC, depósito, retirada, intercambio
  1↔1 y sustitución por baja. ORAS y los demás backends no se modifican.
- Añadida una regresión de frontera UI→Core que exige que ninguna de esas
  operaciones sea reclasificada como no compatible. La validación física del
  ciclo completo en Pokémon X/Azahar permanece pendiente.

# v0.2.4-alpha.11 — commit Equipo↔PC sobre la FCRAM autoritativa de X/Y

- La prueba física de alpha.10 desmintió que el despacho al writer bastara:
  Azahar aceptaba la escritura y el readback por RPC, pero Pokémon X seguía
  consumiendo una copia anfitriona que conservaba a Budew dentro del equipo.
  La primera divergencia restante estaba, por tanto, en la autoridad usada
  para confirmar la transacción y no en el arrastre ni en la proyección UI.
- La sesión real permitió localizar una única matriz anfitriona coherente: sus
  seis slots de party, contador y matriz PC completa coinciden simultáneamente
  con las estructuras invitadas ya demostradas. El writer resuelve esa copia
  por identidad estructural en cada operación y deriva un único desplazamiento
  común; no incorpora una dirección anfitriona fija ni un escaneo amplio.
- Equipo→PC y PC→Equipo escriben ahora la unidad transaccional completa en esa
  FCRAM autoritativa. Se verifican antes y después la party completa, el
  contador, la casilla PC exacta y los slots no implicados; una segunda lectura
  estable debe coincidir también por RPC. Cualquier divergencia restaura y
  verifica los tres bloques originales.
- Añadida una regresión que exige utilizar la autoridad anfitriona; habría
  fallado con el writer de alpha.10 aunque su readback RPC fuera positivo.
  La validación física de este cambio queda pendiente de una única prueba
  Equipo→PC en Pokémon X/Azahar.

# v0.2.4-alpha.10 — operaciones Equipo↔PC conectadas al writer X/Y

- Demostrada la primera divergencia del traslado que solo aparecía en RoleRun:
  la UI creaba correctamente `party-to-box` y `box-to-party`, pero la compuerta
  que despacha operaciones al writer vivo de X/Y omitía precisamente esos dos
  tipos. Por ello se proyectaba el cambio sin escribir RAM; el posterior
  PC→PC partía de un origen inexistente en el juego y los testigos del writer
  lo rechazaban correctamente.
- La compuerta X/Y incluye ahora las dos operaciones que su writer transaccional
  ya implementaba. No se han relajado validadores ni testigos: cada cambio sigue
  exigiendo identidad, party, contador y caja estables, además de readback y
  rollback. ORAS y los demás backends no se han modificado.
- Añadida una regresión que exige que ambos cambios de tamaño lleguen al
  coordinador vivo. Las 50 pruebas relacionadas con X/Y pasan y la suite
  completa queda en `836 passed`.
- Registrada la validación física en X/Y del nuevo pool de Prisma basado en
  problemas de estado. El ciclo Equipo↔PC iniciado desde RoleRun queda pendiente
  de una única validación física en esta versión.

# v0.2.4-alpha.9 — destinos PC exactos en X/Y y Prisma de estados

- Localizada la primera divergencia de los tres fallos PC de X/Y en la UI,
  antes del writer RAM: el destino elegido al arrastrar Equipo→PC se descartaba,
  PC→PC reunía testigos por rol en vez de por caja y un guard heredado de Gen 6
  bloqueaba PC→Equipo cuando había una casilla libre. El writer X/Y ya admitía
  las tres operaciones con coordenadas, precondiciones, readback y rollback.
- La UI conserva ahora la caja y casilla exactas al depositar, obtiene testigos
  ocupados de la misma caja al mover o retirar y permite a X/Y ampliar la party.
  ORAS continúa cerrado: no se le ha atribuido ninguna capacidad no demostrada.
- Prisma deja de compartir la categoría de Protección de Tanque. Su cuarta
  categoría pasa a ser Problemas de Estado y admite movimientos que provocan
  directamente un problema de estado mayor. El pool se filtra con el catálogo
  real cargado por cada juego, por lo que no ofrece movimientos de generaciones
  posteriores; Protección deja de ser válida para Prisma.
- Añadidas regresiones para destino vacío exacto, testigos de caja, retirada a
  rol libre y filtrado generacional del nuevo pool de Prisma. La operación RAM
  X/Y y el drafteo Prisma quedan pendientes de validación física en Pokémon X.
  Suite completa: `834 passed`.

# v0.2.4-alpha.8 — cambios de tamaño Equipo↔PC en X/Y

- Demostrado físicamente en Pokémon X/Azahar que el contador de miembros de
  la party se encuentra en `0x08CE1C74`, ocupa cuatro bytes little-endian y
  cambia de 6 a 5 al depositar un Pokémon desde el propio juego. La party
  comienza en `0x08CE1CE8`, compacta los miembros posteriores hacia la
  izquierda y sustituye el último slot anterior por el PK6 vacío cifrado
  canónico. Las palabras anteriores al contador se conservan como solo lectura:
  no forman parte de la escritura.
- Implementadas exclusivamente para X/Y las transacciones Equipo→PC y
  PC→Equipo con casilla exacta. El writer exige party y contador estables,
  identidad inequívoca, destino vacío u origen ocupado y testigos de la misma
  caja. Cada bloque tiene readback inmediato y el contador se escribe siempre
  al final como punto de confirmación de la operación.
- Tras la escritura se verifican el orden completo de la party, la casilla PC,
  el contador y los miembros no implicados. Ante cualquier discrepancia se
  restauran todos los bytes originales y se comprueba el rollback, dejando el
  contador para el final también durante la recuperación.
- La UI solo habilita estas rutas para X/Y; ORAS continúa cerrado hasta disponer
  de evidencia propia. Las regresiones cubren depósito con compactación,
  retirada, destino exacto, orden del commit, rechazo sin testigos y rollback
  íntegro. La operación completa queda pendiente de validación física iniciada
  desde RoleRun. Suite completa: `831 passed`.

# v0.2.4-alpha.7 — MT globales completas y seguras en X/Y

- Demostrada la primera divergencia de la pestaña MT de X/Y: la UI solo tenía
  metadatos completos para BDSP y Gen 7; X/Y caía junto con ORAS en un fallback
  que conservaba únicamente los PP. No era seguro reutilizar Gen 7: por
  ejemplo, Placaje (`move_id=33`) tiene potencia 50 en X/Y y 40 en Gen 7.
- Añadida una tabla X/Y fijada explícitamente a la generación 6 y al grupo de
  versiones `x-y`, con 621 movimientos, IDs oficiales, potencia, precisión,
  PP y descripción española. La rama X/Y de la UI consume exclusivamente esta
  fuente; ORAS y los demás backends no se han modificado.
- La transacción heredada de Gen 6 queda cubierta por regresiones específicas
  de X/Y: una MT reutilizable modifica solo el PK6 de la party, conserva la
  mochila, hace readback semántico de movimientos y PP y restaura exactamente
  los bytes originales si la comprobación falla.
- Comprobación visual real en Pokémon X/Azahar: la pestaña global muestra MT83
  Acoso como `Pot. 20 · Prec. 100 · PP 20`. El usuario confirmó físicamente el
  25-08-2026 que enseñar una MT cambia el movimiento en el juego y que la misma
  MT continúa disponible después, como corresponde a X/Y. Suite completa:
  `826 passed`.

# v0.2.4-alpha.6 — publicación inicial del PC vivo de X/Y

- Demostrada una segunda divergencia tras corregir la base de la matriz: el
  lector vivo devolvía exactamente Budew, Ledyba y Skitty, pero la composición
  inicial de X/Y solo solicitaba reconciliar el PC si también cambiaba la
  party. Con una party estable, la UI conservaba el PC vacío procedente del
  guardado aunque la lectura RAM ya fuera válida.
- La sincronización inicial validada de X/Y solicita ahora una única
  reconciliación del PC vivo independientemente de que cambie la party. El
  cambio queda limitado a X/Y y no modifica readers ni writers de otros juegos.
- Añadida una regresión que publica una party sin cambios y exige aun así el
  refresco del PC. Comprobación visual real en Pokémon X/Azahar: Caja 1 muestra
  los tres ocupantes en las posiciones 1–3. Suite completa: `821 passed`.

# v0.2.4-alpha.5 — cajas X/Y visibles sin anchors del guardado

- Demostrada en la sesión real de Pokémon X/Azahar la primera divergencia del
  PC vacío: la matriz viva comenzaba en `0x08C861B8`, dieciséis bytes antes de
  la candidata nominal `0x08C861C8`. Sin Pokémon posicionados en el `main`, el
  lector aceptaba la candidata nominal sin validarla; el primer PK6 fallaba y
  la UI sustituía el fallo por el `main` guardado, cuyo PC estaba vacío.
- El lector calibra ahora exclusivamente dentro del rango local ya acotado y
  solo acepta una única matriz que contenga al menos dos PK6 completos con
  checksum y especie válidos. Una coincidencia aislada o varias matrices
  compatibles se rechazan; no se ha añadido ningún escaneo amplio ni fallback
  de escritura.
- El readback directo de la sesión encontró exactamente Budew, Ledyba y Skitty
  en Caja 1, posiciones 1–3, en la base `0x08C861B8`.
- Añadidas regresiones para apertura sin anchors, invalidación de una caché
  nominal obsoleta y rechazo de matrices ambiguas. Suite completa:
  `820 passed`. La confirmación visual quedó completada en alpha.6.

# v0.2.4-alpha.4 — movimiento exacto dentro del PC de X/Y

- Habilitado exclusivamente el movimiento PC→PC de X/Y entre una casilla
  ocupada y una casilla vacía concretas. La implementación usa la matriz viva
  X/Y ya demostrada de 31 cajas × 30 posiciones y el PK6 almacenado de `0xE8`
  bytes; no incorpora direcciones ni estructuras nuevas.
- La transacción verifica proceso, party estable, identidad del Pokémon origen,
  destino vacío y testigos de la matriz inmediatamente antes de escribir.
  Escribe primero el destino, confirma su readback, vacía después el origen y
  vuelve a verificar ambas casillas y su significado; ante cualquier fallo
  restaura y comprueba los dos bloques originales.
- Las operaciones que cambian el tamaño de la party X/Y siguen cerradas porque
  la sesión actual no demuestra aún el campo de conteo ni su transacción.
- Registrada la validación física del cambio de rol fijo de alpha.3 en
  Pokémon X/Azahar. La entrada PC→Líbero y el movimiento PC→PC exacto quedan
  pendientes de validación física.
- Añadidas regresiones de éxito, destino ocupado, identidad stale, rollback y
  coordenadas exactas preparadas por la UI. Suite completa: `817 passed`.

# v0.2.4-alpha.3 — roles, EV y estadísticas vivas en X/Y

- Demostrada la primera divergencia del cambio de rol X/Y: la UI excluía este
  backend al preparar los EV y el writer heredado solo actualizaba el marcador
  del PK6 almacenado, sin recalcular la región `PartyData` que contiene las
  estadísticas finales vivas.
- El writer X/Y aplica ahora marcador, EV y estadísticas como una sola
  transacción sobre las dos regiones físicas ya demostradas. Exige identidad y
  EV anteriores, conserva estado y daño, hace readback exacto y revierte ambos
  bloques si cualquier comprobación falla.
- La entrada desde el PC del propio juego hereda también en X/Y los EV del rol;
  si el destino es Líbero, la escritura queda detenida hasta elegir dos stats.
- Registrada la validación física de la curación completa X/Y en Pokémon
  X/Azahar. La validación física del nuevo flujo de roles queda pendiente.
- Añadidas regresiones de recalculo, muestra stale, rollback de ambas regiones
  y asignación automática desde PC. Suite completa: `811 passed`.

# v0.2.4-alpha.2 — curación visible y sustitución descartable en X/Y

- Corregida la compuerta de composición que ocultaba en X/Y `CURAR EQUIPO` y
  las acciones flotantes `CURAR`/`MENÚ` aunque el writer transaccional ya estaba
  disponible. Las dos superficies consumen ahora una única capacidad común.
- Las bajas pendientes ofrecen `NO SUSTITUIR`: la decisión conserva la muerte,
  la vida descontada y el historial del Cementerio, pero elimina de forma
  persistente la obligación de elegir reemplazo y deja libre el rol.
- Corregida la espera inicial con bajas pendientes: la compuerta de composición
  valida la misma party proyectada que renderiza la UI, en vez de exigir también
  los miembros ya excluidos por sus bajas.
- Añadidas regresiones de exposición de curación X/Y y de archivo de una baja
  sin modificar contadores. Suite completa: `806 passed`.

# v0.2.4-alpha.1 — inicio de la serie X/Y y curación completa

- Corregida la familia de versiones: `v0.2.1` identifica BDSP, `v0.2.2` USUM,
  `v0.2.3` Sol/Luna, `v0.2.4` X/Y y la futura `v0.2.5` ORAS. Las entradas
  antiguas se conservan como historial y no se reescriben retroactivamente.
- El parser Gen 6 publica naturaleza, IV, EV, estado y los seis stats finales
  que el reader X/Y ya capturaba de la party viva.
- X/Y admite curación completa transaccional: restaura PS, estado y PP sobre
  los dos bloques físicos demostrados (`PK6` almacenado y `PartyData` runtime),
  con precondiciones inmediatas, readback semántico y rollback verificado.
- No se escribe el snapshot sintético `0x104` como un bloque contiguo: el writer
  separa explícitamente `0xE8` bytes almacenados y `0x16` bytes runtime para no
  invadir el hueco existente entre ambas regiones en X/Y.
- Añadidas regresiones de curación efectiva, exposición del estado y rollback
  ante corrupción del readback. La validación física de la curación en
  Pokémon X/Azahar queda pendiente.

# v0.2.2-alpha.148 — selector EV del sustituto Líbero en BDSP

- Corregida la omisión del flujo de sustitución por muerte de BDSP: cuando el
  debilitado era Líbero, el sustituto espera ahora una elección nueva de dos
  estadísticas antes de preparar el cambio.
- El snapshot de sustitución conserva los seis EV deseados para que el flujo
  BDSP ya existente los aplique, recalcule las estadísticas finales y verifique
  el readback después de completar el reemplazo.
- Sol/Luna y UltraSol/UltraLuna mantienen el mismo comportamiento ya validado;
  ORAS y XY no se modifican porque no disponen de este writer realtime demostrado.

# v0.2.2-alpha.147 — paridad segura de continuidad en USUM

- Registrada la validación física del arranque Sol/Luna de Alpha.146.
- `USUMLiveReader` recibe las identidades persistidas de la Run y admite dos
  sustituciones gestionadas solo con ambos entrantes demostrados y cuatro
  testigos conservados. La regresión mantiene el rechazo sin esa evidencia.
- La auditoría confirma que BDSP, XY y ORAS no consumen esta barrera de
  continuidad, por lo que no se les ha propagado el cambio.

# v0.2.2-alpha.146 — arranque SM tras dos sustituciones gestionadas

- Demostrada la causa del bloqueo de la pantalla inicial: la party viva conservaba
  cuatro identidades fuertes, pero contenía dos sustitutos ya persistidos por
  RoleRun; el resolver solo admitía una sustitución gestionada por arranque.
- La continuidad inicial acepta ahora exclusivamente dos sustituciones, con los
  otros cuatro miembros conservados y ambas identidades entrantes presentes en
  la Run. No se amplía la aceptación a parties estructurales arbitrarias.
- Añadida una regresión que rechaza la misma muestra sin esos testigos y la acepta
  únicamente tras aportar las dos identidades persistidas.
- Validado contra la sesión física actual de Azahar: `snapshot=true`, dirección
  `874077712` y prueba `multiple-managed-replacements`; la barrera se retiró y
  apareció el selector EV pendiente.

# v0.2.2-alpha.145 — selector EV para el sustituto de un Líbero debilitado

- Corregida la divergencia específica de Líbero en las sustituciones tras una
  baja de Sol/Luna y UltraSol/UltraLuna: el flujo reutilizaba silenciosamente
  los dos stats maximizados del Pokémon muerto y no abría el selector.
- La sustitución queda ahora pendiente y no prepara ni escribe ningún cambio
  hasta elegir dos stats nuevos para el Pokémon entrante.
- Los roles fijos conservan la asignación automática ya validada y Líbero usa
  el mismo selector protegido frente a refrescos de la barra flotante.
- Añadida una regresión que demuestra que la elección nueva sustituye, en vez
  de copiar, el reparto del Líbero debilitado.

# v0.2.2-alpha.144 — EV heredados en sustituciones por baja de Sol/Luna

- Corregida la primera divergencia del flujo de sustitución tras una baja en
  Sol/Luna: la UI preparaba el reparto EV heredado únicamente para USUM y el
  writer SM reconstruía el Pokémon entrante sin consumir ese reparto.
- Sol/Luna prepara ahora los EV del rol del debilitado en el mismo snapshot
  transaccional y el writer los aplica antes de cifrar el PK7 de equipo.
- Se conservan las precondiciones de identidad y rol, readback completo de
  equipo y PC y rollback de ambos bloques ante cualquier divergencia.
- Añadidas regresiones de extremo a extremo para la preparación desde la UI y
  para el resultado final del reemplazo SM con EV heredados.

# v0.2.2-alpha.143 — selector EV persistente durante refrescos flotantes

- Demostrada y corregida la carrera que cerraba por sí sola el selector EV de
  Líbero: el refresco periódico de la barra destruía todos sus widgets hijos,
  incluida la ventana modal recién abierta.
- El render conserva ahora explícitamente las ventanas modales flotantes y el
  selector mantiene como propietaria la barra visible, sin reasignarse al root
  principal retirado.
- Añadida una regresión que fuerza el mismo refresco y comprueba que reconstruye
  el contenido normal sin destruir el selector abierto.

# v0.2.2-alpha.142 — selector EV al incorporar un Líbero desde el PC del juego

- Corregida la primera divergencia del flujo automático PC del juego→Equipo:
  la inferencia común heredaba el rol Líbero y llegaba directamente al writer
  sin disponer de los dos stats elegidos por el jugador.
- En BDSP, Sol/Luna y UltraSol/UltraLuna la operación queda ahora diferida, sin
  escribir RAM, hasta que el usuario elige exactamente dos stats. El selector
  aparece sobre el emulador si RoleRun está en modo flotante y en la aplicación
  si está en primer plano.
- Los demás roles llevan su reparto EV normalizado dentro de la misma
  transacción automática. Se conservan las precondiciones, readback y rollback
  de cada backend.
- Añadidas regresiones para impedir una escritura Líbero prematura y para
  verificar la normalización automática de un rol fijo.

# v0.2.2-alpha.141 — selector de Líbero flotante y datos MT Gen 7

- Corregida la primera divergencia del arrastre hacia Líbero desde la barra:
  el selector de EV se creaba dentro del root principal retirado y solo se
  volvía visible al restaurar RoleRun. En modo flotante se aloja ahora en una
  ventana real, centrada y superior al emulador; la escritura sigue esperando
  la elección de dos stats y conserva su readback y rollback existentes.
- Las tarjetas de movimientos de Sol/Luna y UltraSol/UltraLuna cargan potencia,
  precisión, PP y descripción española versionados para Gen 7. La tabla local
  procede de los CSV públicos de PokeAPI y revierte los cambios introducidos
  después del version-group de Sol/Luna, en vez de reutilizar valores modernos.
- Añadidas regresiones para la superficie visible del selector flotante y para
  valores que distinguen Gen 7 de generaciones anteriores.

# v0.2.2-alpha.140 — SUSTITUIR y pestaña MT en Sol/Luna

- Corregida la primera divergencia de la mochila viva de Sol/Luna: RoleRun
  derivaba su dirección desde BoxPokemon usando la separación del archivo de
  guardado, relación que no existe en RAM. La dirección derivada devolvía
  `0xDE0` bytes a cero en la sesión real.
- La candidata Items propia de Sun/Moon (`0x330D5934`, documentada por
  PKMN-NTR para SN/MN) solo se acepta tras doble lectura estable, ancla de party
  de la sesión y concordancia byte a byte entre memoria host y guest.
- SUSTITUIR y la pestaña MT compartida pueden cargar ahora únicamente las MT
  presentes en la mochila viva. En Sol/Luna siguen siendo reutilizables y la
  enseñanza conserva precondiciones, readback semántico y rollback.
- Añadida una regresión que demuestra la mochila publicada aun con un `main`
  desfasado y que habría fallado con la antigua dirección derivada del PC.


# v0.2.2-alpha.139 — PC vivo coherente y vacío PK7 seguro en Sol/Luna

- Corregida la primera divergencia que creaba huevos corruptos al incorporar
  un Pokémon del PC al equipo: el writer escribía `0xE8` ceros crudos en el
  origen. Ahora escribe el PK7 vacío cifrado canónico y exige readback exacto.
- Sol/Luna publica ahora la matriz completa del PC leída de RAM viva, igual que
  los backends con matriz demostrada, en vez de conservar una proyección de
  save obsoleta que podía mostrar un Pikipek donde el juego ya tenía Decidueye.
- La barrera inicial no descubre Equipo y PC hasta que coinciden el equipo live,
  la matriz PC live, los PS, sprites y la composición final de la vista.
- Añadidas regresiones del vacío cifrado y de la barrera PC live de Sol/Luna.

# v0.2.2-alpha.138 — reanudación estable de Sol/Luna

- Corregida la carga interminable al reabrir Sol/Luna después de sustituir un
  miembro del equipo y reordenarlo. El reader perdía al reiniciar su testigo en
  memoria y rechazaba para siempre una party válida aunque la identidad exacta
  del Pokémon entrante ya estuviera persistida en la run.
- La calibración acepta ahora esa transición únicamente cuando cinco
  identidades coinciden y la sexta identidad exacta pertenece al equipo
  gestionado persistido. Una identidad distinta sigue siendo rechazada.
- La barrera inicial permanece hasta que la party viva, sus PS, los sprites y
  el último refresco visual estén completos, evitando publicar tarjetas
  parciales tras retirar el cargador.
- La sesión real de Pokémon Sol/Azahar reabrió correctamente con la resolución
  `single-managed-replacement-and-reorder`; se verificó visualmente el primer
  frame publicado y la selección inmediata del Pikipek de PC.

# v0.2.2-alpha.137 — EV de rol al entrar desde el PC en Sol/Luna

- Corregida la primera divergencia del traslado PC→Equipo de Sol/Luna: la UI
  preparaba los seis EV del rol heredado, pero el writer descartaba ese dato al
  construir el PartyData entrante y lo dejaba para una segunda transacción.
- El traslado aplica ahora marcador, EV, checksum y estadísticas finales dentro
  de la misma transacción atómica que mueve el Pokémon. Mantiene precondiciones,
  readback host/guest, validación semántica y rollback conjunto de party y PC.
- Un snapshot EV incompleto o cuyo rol no coincide se rechaza antes de escribir.
- Añadidas regresiones de sustitución 1↔1, entrada con hueco libre y rechazo sin
  escrituras. Suite completa: `782 passed`.
- Validación física en Pokémon Sol/Azahar: un Pikipek de Caja 1 entró en la
  segunda casilla como Asesino con EV Ataque/Velocidad `252/252`, los restantes
  a cero y estadísticas finales recalculadas.

# v0.2.2-alpha.136 — entrenamiento por rol en Sol/Luna

- Sol/Luna aplica ahora los EV asociados al rol desde la misma UI compartida
  por BDSP y USUM: los cinco roles fijos maximizan sus dos estadísticas y
  Líbero conserva la elección explícita de dos atributos.
- El writer SM valida los EV anteriores, el Personal efectivo de la ROM, IV,
  nivel, naturaleza, hiperentrenamiento y PartyData antes de escribir. Después
  recalcula PS y las cinco estadísticas, preserva el daño sufrido, renueva el
  checksum y exige readback host/guest y semántico.
- El rollback restaura y verifica tanto el PK7 almacenado como PartyData si
  falla cualquier comprobación. No se incorporan direcciones ni offsets nuevos.
- Añadidas regresiones para la compuerta UI SM y para EV, estadísticas, checksum
  y conservación del daño.
- Validación física en Pokémon Sol/Azahar: un Pikipek de nivel 4 pasó de EV
  Ataque/Velocidad `1/0` a `252/252`; el readback mostró Ataque `11→14`,
  Velocidad `9→10`, los demás EV a cero y PS conservados en `17/17`.

# v0.2.2-alpha.135 — curación SM con prueba autocontenida del destino

- Corregido el rechazo seguro de `CURAR EQUIPO` en la primera escritura de una
  sesión de Sol/Luna cuando Azahar expone varias copias anfitrionas de la party.
- El writer demuestra ahora la matriz PC completa ya validada por el backend SM
  y deriva de ella la única copia de party que comparte el mismo backing FCRAM,
  en lugar de exigir que una operación PC anterior hubiese dejado esa prueba en
  caché.
- Se mantienen las precondiciones, doble readback host/guest, comprobación
  semántica y rollback verificado de PS, estado y PP.
- Añadida una regresión para la curación como primera escritura con buffers de
  party duplicados y validación física de PS en Pokémon Sol/Azahar.

# v0.2.2-alpha.134 — curación completa en Sol/Luna

- Sol/Luna incorpora curación completa en tiempo real: restaura PS, problemas
  de estado y PP de todos los miembros del equipo.
- El writer usa la separación sparse ya demostrada de SM entre stored PK7 y
  PartyData, con precondiciones de identidad, readback host/guest, verificación
  semántica final y rollback verificado de ambos campos.
- La acción queda disponible tanto en Equipo y PC como en la barra flotante.
- Añadidas regresiones de proyección HP/estado/PP y de las compuertas UI SM.

# v0.2.2-alpha.133 — apertura íntegra y datos completos en Sol/Luna

- Sol/Luna mantiene ahora la barrera de carga inicial hasta que Azahar ha
  publicado una party live autoritativa y los seis miembros declaran pares
  PS/PS máximos coherentes. Ya no se expone durante la conexión la composición
  provisional del save con barras rojas o datos incompletos.
- La party SM publica naturaleza, IV, EV, estadísticas finales y problemas de
  estado desde los campos PK7 ya demostrados. El adaptador completa las stats
  base desde el perfil ROM efectivo de la edición activa, sin trasladar
  offsets ni writers de USUM.
- Añadida una regresión que impide retirar la barrera de Sol/Luna ante un fallo
  inicial de transporte.
- Verificación visual en Pokémon Sol/Azahar: el cargador cubre íntegramente la
  conexión y solo desaparece cuando los seis PS están resueltos; la ficha de
  Decidueye mostró naturaleza, stats finales/base, IV, EV, habilidad, objeto y
  cuatro movimientos coherentes.

# v0.2.2-alpha.132 — incompatibilidades visibles en Equipo

- La tarjeta principal de cada miembro usa ahora el mismo mapa de
  incompatibilidades por slot que la ficha lateral; fondo, texto y borde rojo
  identifican el movimiento que no cumple su rol.
- La ficha mantiene las acciones `SUSTITUIR` y `ELIMINAR` ya conectadas a los
  writers existentes. Los Pokémon almacenados en PC no reciben restricciones
  de un rol de equipo que no ocupan.
- Añadida regresión de la frontera compartida entre tarjeta e inspector.
- Verificado visualmente en la run USUM/Azahar que `Cuchilla Solar` de un
  Carnivine/Mago se marca en rojo en ambas superficies y ofrece las dos acciones.
- Validación física completada: `ELIMINAR` retiró `Cuchilla Solar` tanto de
  RoleRun como del moveset leído de la partida real en USUM/Azahar.

# v0.2.2-alpha.131 — MT reutilizables en Gen 6 y Gen 7

- Corregida la proyección común de inventario que reservaba/restaba una unidad
  para cualquier `PendingTMTeach`, aunque los writers de ORAS, X/Y, SM y USUM
  ya modificaban exclusivamente el moveset y no consumían la máquina.
- `PendingTMTeach` conserva ahora explícitamente si la operación consume objeto:
  solo BDSP descuenta una unidad; ORAS, X/Y, SM y USUM mantienen la MT disponible.
- El historial, la revisión, el inventario pendiente y el refresco posterior al
  readback usan el mismo contrato, evitando consumos visuales ficticios.
- Añadidas regresiones separadas para MT reutilizable 3DS y MT consumible BDSP.
- Validación física en USUM/Azahar: una MT con cantidad `x1` se enseñó y siguió
  figurando como `x1` tanto en el juego como en RoleRun.

# v0.2.2-alpha.130 — arrastre PC accesible y verificado

- Corregida la primera divergencia del gesto PC→PC: la continuación del
  arrastre ya no usa un `grab_set` que retargeteaba el puntero a la superficie
  de origen. Los eventos continúan mediante el bindtag estable de la ventana y
  conservan el widget y las coordenadas físicas situados bajo el cursor.
- Las casillas vacías vuelven a recibir el drop real y las flechas `<`/`>`
  reciben el hover sostenido necesario para navegar entre cajas sin soltar el
  Pokémon.
- Añadida regresión que prohíbe volver a capturar/retargetear el puntero y
  verifica el alta y retirada simétrica de los eventos en la ventana.
- Validación física en USUM/Azahar: Eevee se movió caja 1 casilla 1 → caja 1
  casilla 2 → caja 2 casilla 1 y se restauró mediante la flecha inversa a caja
  1 casilla 1. Se conservaron capturas en `diagnostics/manual/alpha130_*.png`.

# v0.2.2-alpha.129 — arrastre entre cajas PC en USUM

- Mantener un Pokémon del PC sobre las flechas cambia de caja sin perder el
  arrastre; cada permanencia avanza una sola caja y exige abandonar la flecha
  antes de repetir, evitando recorrer cajas accidentalmente.
- Soltarlo sobre un hueco vacío mueve el PK7 cifrado exacto entre las dos
  posiciones de la matriz USUM ya demostrada. Origen, destino, identidad,
  límites, host y guest se verifican antes y después de escribir.
- Si cualquier readback falla, se restauran y verifican ambos huecos. Los swaps
  entre dos casillas ocupadas permanecen bloqueados y no se toca ningún otro
  backend.
- Se registra la validación física de alpha.128: baja flotante neutra y retirada
  correcta de la barra al maximizar RoleRun.

# v0.2.2-alpha.128 — salud flotante validada y sustitución USUM sin solapes

- La entrada en combate podía publicar temporalmente HP provisionales en la
  party proyectada aunque el carril de salud validado conservase los seis HP
  correctos. La barra flotante toma ahora HP y estado del único miembro con
  identidad fuerte coincidente en el snapshot validado; no convierte esa muestra
  provisional en seis barras rojas.
- Una casilla vacía o un miembro con cero PS ya no instancia una barra de progreso:
  usa un carril neutro, evitando el píxel rojo que el extremo redondeado dibujaba
  incluso con progreso cero.
- Restaurar o maximizar la ventana principal retira siempre la barra flotante
  cuando la raíz ya es visible, aun durante la breve carrera de foco de Windows.
- Se elimina el aviso rojo superior duplicado de sustitución. La barra de estado
  inferior sigue siendo la autoridad y la ficha conserva visible la acción
  `ELEGIR COMO SUSTITUTO`.
- El destino exacto del arrastre Equipo→PC se conserva para cualquier runtime
  Gen 7 compatible. La prueba física en UltraSol/Azahar envió Porygon a Caja 1,
  posición 8, confirmó el mismo destino por readback e historial y después lo
  devolvió al equipo desde esa misma casilla.
- Regresiones cubren la autoridad del snapshot de salud, el cero real, la
  restauración de ventana principal, la ausencia del aviso superior y la
  conservación de caja/casilla en runtimes Gen 7.

# v0.2.2-alpha.127 — sustitución visible y destino PC exacto en USUM

- La acción `ELEGIR COMO SUSTITUTO` estaba dentro del cuerpo de una ficha fija:
  stats, IV, EV y movimientos podían empujarla fuera del viewport cuando el
  aviso de muerte reducía la altura disponible. Ahora las acciones ocupan un
  pie reservado que no puede ser ocultado por el contenido de la ficha.
- El arrastre Equipo→PC ya transportaba caja y casilla exactas, pero la UI
  descartaba esos datos y el writer elegía deliberadamente el primer hueco
  libre. El arrastre USUM conserva ahora el destino y el writer lo valida contra
  la matriz PC viva inmediatamente antes de escribir.
- El botón `ENVIAR AL PC` conserva su semántica histórica de primer hueco libre.
  Un destino exacto ocupado, incompleto o fuera de rango se rechaza sin escribir;
  la transacción mantiene readback y rollback existentes.
- Regresiones nuevas cubren la frontera del gesto, el pie fijo, la escritura en
  Caja 3/slot 4 y el rechazo sin mutación de una casilla ocupada. La disposición
  se verificó visualmente a 1920×1080; falta validación física en Azahar.

# v0.2.2-alpha.126 — EV del rol en sustituciones por muerte USUM

- La ruta especial `replace-fainted` heredaba correctamente el marcador del
  Pokémon debilitado, pero conservaba los EV que el sustituto tenía en el PC.
  La primera divergencia estaba en dos fronteras exclusivas de esta operación:
  la UI no preparaba el reparto y el writer no lo entregaba al constructor de
  `PartyData`.
- El selector prepara ahora el reparto automático del rol heredado. En Líbero
  conserva las dos estadísticas a 252 demostradas por el miembro saliente; si
  esa pareja no existe, no inventa una configuración.
- El writer aplica rol, EV, movimientos y estadísticas finales dentro de la
  misma transacción que vacía el origen PC y mueve al debilitado al Cementerio.
  Conserva las precondiciones, readback doble y rollback ya demostrados.
- Las regresiones verifican la preparación UI y la transacción RAM completa.
  Falta la validación física en UltraSol/Azahar.

# v0.2.2-alpha.125 — EV automáticos al entrar desde PC en USUM

- La UI ya preparaba la distribución EV del rol al añadir o intercambiar un
  Pokémon del PC, pero `USUMLiveWriter` descartaba ese campo al reconstruir su
  `PartyData`. La primera divergencia estaba en esa frontera del writer.
- Las rutas PC→Equipo e intercambio Equipo↔PC incorporan ahora los seis EV a
  la misma transacción que rol, movimientos, PK7 stored y estadísticas finales.
- El writer rechaza un snapshot incompleto o cuyo rol no coincida con la casilla
  de destino; las operaciones históricas sin snapshot conservan el PK7 original.
- Dos regresiones completas verifican añadir e intercambiar con readback de EV,
  rol, identidad y estadísticas runtime. Validación física en UltraSol/Azahar:
  la entrada desde PC aplicó correctamente el reparto y las estadísticas del rol.

# v0.2.2-alpha.124 — reconciliación efectiva de estadísticas USUM

- La prueba física de alpha.123 demostró una segunda divergencia, anterior al
  writer: al volver a aceptar el mismo rol Líbero con los mismos EV, la UI
  terminaba el flujo anticipadamente y nunca enviaba la reconciliación a
  `USUMLiveWriter`.
- En USUM, aceptar una distribución EV explícita atraviesa ahora el writer
  aunque rol y EV coincidan. Los demás backends conservan el retorno temprano.
- Validación física en UltraSol/Azahar: Kangaskhan, nivel 50, tenía EV 252 en PS
  y Ataque pero estadísticas antiguas de 172 PS y 140 Ataque. Tras la
  reconciliación quedó en 203 PS y 170 Ataque, manteniendo EV 252/252 y con
  readback de la party viva.
- Se añadió una regresión de la frontera UI que demuestra que repetir la misma
  pareja de Líbero en USUM llega al writer en vez de descartarse.

# v0.2.2-alpha.123 — EV y estadísticas finales USUM transaccionales

- La validación física de alpha.122 demostró que los seis EV PK7 cambiaban,
  pero los valores finales permanecían iguales. La primera divergencia estaba
  en el writer: solo actualizaba el bloque stored `0x1E:0x24` y omitía la
  `PartyData` calculada que Gen 7 conserva separada en la party viva.
- El cambio de EV recalcula ahora PS, Ataque, Defensa, Velocidad, Ataque
  Especial y Defensa Especial con Personal efectivo, nivel, naturaleza, IV e
  hiperentrenamiento del mismo PK7. Conserva los PS perdidos y un Pokémon
  debilitado continúa a cero PS.
- Stored PK7 y estadísticas dispersas se tratan como una sola transacción:
  precondición sobre ambos bloques, escritura mínima, readback de transporte y
  guest, comprobación semántica y rollback verificado de los dos si falla
  cualquier frontera.
- El writer admitía volver a elegir la misma pareja de Líbero para reconciliar
  las estadísticas, pero la UI no llegaba a invocarlo; alpha.124 corrige esa
  frontera sin reescribir esta historia.
- Las regresiones cubren fórmula/orden Gen 7, conservación de daño, reparación
  del estado alpha.122, escritura dispersa y rollback al fallar la segunda
  mitad de la transacción. El writer quedó validado físicamente en alpha.124.

# v0.2.2-alpha.122 — roles USUM aplican su distribución EV

- Los cambios de rol de USUM preparan ahora la misma distribución automática
  validada en BDSP: Asesino (Ataque/Velocidad), Mago (Ataque Especial/Velocidad),
  Tanque (PS/Defensa), Prisma (PS/Defensa Especial), Support
  (Defensa/Defensa Especial) y dos estadísticas elegidas para Líbero.
- El writer PK7 comprueba los seis EV anteriores inmediatamente antes de
  escribir, traduce entre el orden visible y el orden binario Gen 7, limita
  cada valor a 252 y el total a 510, recalcula checksum y exige readback de
  rol, EV, movimientos e identidad. Un fallo activa el rollback PK7 existente.
- Una entrada USUM desde el PC conserva la regla de heredar/ocupar rol y agenda
  después una transacción EV independiente contra la identidad confirmada.
- Regresiones nuevas cubren orden PK7, precondición concurrente y preparación
  de EV al incorporar desde el PC. La validación física confirmó los EV, pero
  reveló que las estadísticas finales no se recalculaban; alpha.123 corrige
  esa frontera sin reescribir esta historia.

# v0.2.2-alpha.121 — cierre físico de fichas, PC, curación y barra USUM

- La primera publicación realtime de USUM exige ahora que la matriz PC viva
  sustituya la caché procedente del guardado aunque el monitor ya se hubiera
  marcado activo. Así la ficha recibe el PK7 completo en lugar de una entrada
  parcial sin naturaleza, estadísticas, IV ni EV.
- La carga PC prepara primero el Personal efectivo de la ROM abierta en Azahar.
  Las estadísticas calculadas de los Pokémon almacenados dejan de depender del
  orden accidental entre la carga del perfil y el worker de cajas.
- La conversión de stats base USUM usa `personal_for(species, form)` y traduce
  expresamente el orden binario Gen 7 al orden visible de RoleRun.
- La curación completa y las acciones CURAR/MENÚ de la barra flotante quedan
  habilitadas para USUM por la misma frontera transaccional ya demostrada del
  writer Gen 7; el retorno mediante el logo conserva vivo el proceso principal.
- Validación física en UltraSol/Azahar: ficha PC completa, curación de 11/19 a
  19/19 con readback, barra con seis HP, CURAR y MENÚ, apertura/cierre del menú
  y retorno mediante logo sin excepción ni terminación del proceso.

# v0.2.2-alpha.120 — primera paridad USUM: entrenamiento y curación completa

- USUM publica ahora naturaleza, estadísticas calculadas, estadísticas base,
  IV y EV en Equipo, PC, ficha y Drafteos. La traducción respeta la diferencia
  demostrada entre el orden binario Gen 7 y el orden visible de RoleRun.
- Los Pokémon de caja solo reciben stats calculados cuando la ROM efectiva de
  Azahar aporta su Personal; esto conserva correctamente randomizers y mods y
  evita reconstruir valores desde una tabla vanilla supuesta.
- La curación completa queda disponible también en USUM. La transacción restaura
  PS, estado y PP, valida identidad y party estable, escribe PK7 y PartyData,
  realiza readback host+guest y revierte ambos campos si falla una comprobación.
- Se añadieron regresiones específicas de naturaleza/orden, PC enriquecido y
  curación sin alterar IV, EV, identidad ni movimientos.

# v0.2.2-alpha.119 — controles exclusivos con RoleRun en primer plano

- La rama principal de navegación consumía teclado y mando dentro de RoleRun,
  pero no activaba la compuerta que ya protegía el menú flotante. Como Ryujinx
  acepta SDL2 fuera de foco, el mismo botón podía navegar RoleRun y actuar en
  Pokémon Perla Reluciente.
- Mientras una ventana de RoleRun posee ahora el primer plano en una sesión
  BDSP, el proceso exacto de Ryujinx queda retenido una sola vez. La retención
  se libera al volver al juego, al abandonar RoleRun o al cerrar la aplicación.
- La compuerta se cierra antes de muestrear o despachar el mando, por lo que el
  primer flanco tampoco puede atravesar la frontera. La protección cubre por
  igual flechas, aceptar y atrás de teclado y mando.
- La prueba física contra el Ryujinx abierto observó `0` incremento de tiempo
  de CPU durante 600 ms retenido y una reanudación correcta. Se añadieron
  regresiones de adquisición idempotente, liberación al perder foco y orden de
  cierre anterior al muestreo SDL.

# v0.2.2-alpha.118 — primer frame BDSP completamente compuesto

- Las capturas sincronizadas de alpha.117 demostraron que los datos live ya
  eran correctos, pero la barrera se retiraba tras validar un árbol construido
  con la raíz retirada. Al maximizar el HWND, Windows iniciaba un segundo relayout
  y llegaba a publicar frames blancos, vacíos o con tarjetas parciales.
- El inicio separa ahora dos fronteras: primero valida cajas y PS live; después
  mapea la raíz transparente, recompone Equipo/PC en la geometría maximizada
  real y exige cuatro muestras consecutivas de geometría y salud estables.
- El cargador inicial es una superficie independiente maximizada y no cambia
  de tamaño durante el relayout. Solo se retira después de publicar la raíz ya
  asentada, evitando exponer el compositor intermedio.
- Dos arranques nuevos fueron capturados cada 150 ms. En ambos, el último frame
  del loader da paso directamente a la vista completa con los seis PS live:
  `diagnostics/ui/alpha118-startup-physical-19/` y
  `diagnostics/ui/alpha118-startup-physical-20/`.

# v0.2.2-alpha.117 — apertura BDSP cerrada hasta los PS live

- El vídeo físico de la primera apertura demostró que RoleRun retiraba la
  barrera al fallar el primer intento de conexión con Ryujinx. La shell mostraba
  entonces durante unos trece segundos los PS provisionales del guardado antes
  de que un reintento publicara la party live.
- En BDSP, un fallo inicial mantiene ahora el loader animado y reintenta la
  conexión. La pantalla solo se publica cuando el snapshot live es autoritativo,
  todos los miembros declaran `0 <= HP <= Max HP` con `Max HP > 0` y la vista
  final de Equipo/PC ha completado sus tres pasadas de composición.
- Terminar una captura que ha desviado el flujo a una migración o escritura no
  se confunde ya con haber publicado sus datos. Se conserva el loader hasta el
  readback y la publicación posteriores.
- Regresiones añadidas para el error inicial de transporte, los placeholders
  `0/0` y un debilitado válido `0/Max HP`.

# v0.2.2-alpha.116 — un tap, un movimiento y datos live en Drafteos

- La validación física de alpha.115 demostró que iniciar la repetición del mando
  tras 200 ms convertía una pulsación normal en varias órdenes. El flanco físico
  sigue siendo inmediato, pero la repetición solo comienza tras 450 ms de
  mantenimiento deliberado y continúa cada 70 ms.
- La reconciliación BDSP ya no descarta un snapshot live cuando conserva la
  misma identidad, rol y movimientos que el estado persistido pero aporta por
  primera vez naturaleza, estadísticas, estadísticas base, IV o EV. Ese dato de
  presentación se publica sin generar cambios pendientes ni escrituras.
- Regresiones añadidas para una pulsación de 300 ms, el mantenimiento deliberado
  y la diferencia entre un equipo persistido sin entrenamiento y su snapshot
  live enriquecido.

# v0.2.2-alpha.115 — drawer exclusivo y navegación fluida

- La prueba física de alpha.114 separó dos comportamientos: la autoridad única
  corrigió los saltos, pero limitar el D-pad al flanco inicial eliminó también
  su repetición controlada. Se restaura el contrato demostrado de 200 ms de
  espera y repetición cada 52 ms, ahora dirigido únicamente a la vista visible.
- Con el drawer abierto, Izquierda y Derecha se consumen sin cerrar el menú ni
  devolver foco al contenido. Arriba/Abajo siguen recorriendo exclusivamente
  sus entradas y Atrás es la única dirección que lo cierra.
- Drafteos vuelve a utilizar el marco dorado común. El borde fijo del Pokémon
  Líbero se elimina porque duplicaba visualmente el selector; rol e icono ya lo
  identifican sin ambigüedad.
- Regresiones añadidas para el plano vertical del drawer, la repetición del
  mando con propietario único y la ausencia de una falsa selección en Líbero.
- Verificación visual a 1920×1080 en
  `diagnostics/ui/alpha115-draft-shared-focus.png` y
  `diagnostics/ui/alpha115-sidebar-exclusive-focus.png`. Verificación completa:
  **719 tests superados** en 24,20 s con `python -m pytest -q`.

# v0.2.2-alpha.114 — paridad real entre teclado y mando

- La prueba física de alpha.113 demostró que el mando seguía resolviendo su
  destino mediante la pestaña base, mientras el teclado usaba la autoridad de
  navegación visible. En el selector integrado de MT esto enviaba el D-pad a
  Equipo/PC oculto: el movimiento no aparecía en «qué movimiento olvidará» y
  la selección inferior acumulaba desplazamientos.
- Teclado y mando consultan ahora exactamente el mismo propietario publicado
  por el controlador. El flujo MT recibe dirección, aceptar y atrás mientras
  está abierto y devuelve la autoridad a la página base al cerrarse.
- La vista principal consume únicamente el flanco físico del D-pad. La
  repetición sintética queda separada del tap, evitando que una pulsación corta
  atraviese varias casillas.
- El foco de Drafteos usa un marco marfil de cinco píxeles, visible también
  sobre botones dorados como `ELEGIR`.
- Regresiones añadidas para el despacho del mando a un flujo modal, el uso del
  flanco físico y el contraste del foco de Drafteos.
- Verificación visual a 1920×1080 en
  `diagnostics/ui/alpha114-draft-focus-selected.png`; el botón dorado enfocado
  conserva un marco marfil inequívoco. Verificación completa: **718 tests
  superados** en 24,92 s con `python -m pytest -q`.

# v0.2.2-alpha.113 — autoridad única de navegación

- Demostrada la causa común de los saltos de varias casillas y de la ausencia
  de selector en los pasos de MT: varias vistas conservaban simultáneamente
  bindings sobre el mismo `Toplevel`. Una sola pulsación podía atravesar la
  vista anterior, la página situada bajo el modal y la superficie visible.
- El controlador publica ahora una única autoridad de navegación. Las vistas
  ocultas o conservadas como buffer dejan pasar el evento sin mutar su estado;
  únicamente la vista visible mueve exactamente una casilla.
- El flujo integrado de MT toma la autoridad al abrirse y la devuelve a
  Equipo/PC o a la pestaña MT al cerrarse. Sus pasos de elegir MT y elegir
  movimiento muestran y conservan su propio selector espacial.
- El menú lateral recibe foco exclusivo: al seleccionar `>` desaparece el
  selector del contenido, el drawer admite Arriba/Abajo, Aceptar y Atrás, y al
  cerrarse restaura el cursor de la página sin crear una segunda selección.
- Regresiones añadidas para impedir que una vista oculta consuma la misma
  flecha y para verificar que el drawer avanza una sola entrada.
- Verificación completa: **715 tests superados** en 24,30 s con
  `python -m pytest -q`.

# v0.2.2-alpha.112 — navegación continua y stats base

- Atrás en los pasos 2 y 3 de Drafteos vuelve al paso 1 sin consumir el
  drafteo. En Equipo/PC y MT, Atrás abandona el nivel de acciones o destino,
  pero conserva el cursor sobre el Pokémon o la MT de origen.
- El extremo izquierdo de Equipo/PC, MT y Drafteos conecta con el selector del
  menú lateral contraído. Aceptar sobre `>` abre el menú sin recurrir al ratón.
- La ficha del Pokémon muestra ahora stat final, stat base, IV y EV en el mismo
  bloque. Los stats base BDSP proceden de la tabla Personal validada de la ROM
  activa y se publican también en los snapshots realtime de equipo y PC.
- La causa de las entradas perdidas era la reconstrucción síncrona de toda la
  ficha en cada flecha. El cursor se actualiza inmediatamente y la ficha agrupa
  la ráfaga durante 18 ms para pintar solo el destino final. El mando incorpora
  repetición controlada tras 200 ms y cada 52 ms mientras se mantiene el D-pad.
- El foco ya no usa el contorno azul de Tk/Windows: las tarjetas y acciones
  seleccionadas emplean un marco dorado ancho y un fondo cálido coherente con
  RoleRun.
- Verificación visual sobre la aplicación conectada a Ryujinx: cinco pulsaciones
  `Abajo` separadas 10 ms alcanzaron el sexto Pokémon sin perder entradas; las
  fichas mostraron los seis stats base procedentes de `PersonalTable`.
- Verificación completa: **713 tests superados** en 24,58 s con
  `python -m pytest -q`.

# v0.2.2-alpha.111 — atajos exclusivos del emulador

- Todos los atajos Win32, incluidas letras, combinaciones, teclas F y teclado
  numérico, se registran únicamente mientras un emulador compatible está
  realmente en primer plano. RoleRun y el resto de aplicaciones reciben sus
  teclas con normalidad.
- La ejecución de la acción repite la comprobación de foco. Así, un mensaje de
  teclado que ya estuviera encolado tampoco puede modificar contadores, abrir
  el menú o escribir RAM después de abandonar el juego.
- Prueba Win32 sobre la aplicación real y la configuración activa: `D` y
  `NUM 7` quedaron libres en RoleRun, reservadas en Ryujinx y libres de nuevo
  al volver a RoleRun.
- El usuario confirmó que los stats de Pokémon almacenados en el PC ya aparecen
  correctamente en alpha.110.
- Verificación completa: **705 tests superados** en 24,56 s con
  `python -m pytest -q`.

# v0.2.2-alpha.110 — cierre real de stats PC y atajos de letra acotados al foco

- La causa raíz final de los guiones en fichas PC estaba en el ciclo de inicio:
  la matriz del guardado se cargaba antes de activar realtime y el refresco vivo
  solo se rearmaba para la antigua página `pc`, no para la vista unificada
  `team`. La sincronización inicial BDSP dispara ahora directamente la lectura
  completa y su publicación redibuja ambas vistas consumidoras.
- Verificación sobre la aplicación real conectada a Ryujinx: la traza registró
  11 slots ocupados y una proyección nueva; la ficha de Ornita mostró naturaleza
  Huraña, stats `44/31/21/19/18/30`, IV `23/13/29/17/8/8` y EV a cero.
- Las letras simples vuelven a ser asignables. El registro Win32 de una tecla de
  escritura se activa únicamente mientras RoleRun o un emulador compatible tiene
  el foco y se libera cada 100 ms al cambiar a otra aplicación.
- Prueba Win32 real del ciclo de `D`: disponible fuera, reservada dentro y
  disponible de nuevo al salir (`True/False/True`), sin errores de registro.
- Verificación completa: **705 tests superados** en 24,89 s con
  `python -m pytest -q`.

# v0.2.2-alpha.109 — publicación PC completa y atajos que no secuestran texto

- Demostrada la primera divergencia de las fichas PC: el reader BDSP sí
  devolvía para Ornita naturaleza, stats, IV y EV desde el PB8 vivo, pero la
  reconciliación de la UI comparaba únicamente identidad y posición. Cuando
  ambas coincidían ejecutaba `continue` y conservaba el objeto incompleto del
  guardado. BDSP materializa ahora toda la matriz viva validada y repinta solo
  cuando cambia algún dato visible.
- La lectura física de control sobre caja 1/slot 8 produjo naturaleza Huraña,
  stats `44/31/21/19/18/30`, IV `23/13/29/17/8/8` y EV a cero. Una regresión
  atraviesa reader simulado, reconciliación, caché y proyección final de ficha.
- Las teclas de escritura ya no pueden registrarse solas como atajos globales.
  Win32 `RegisterHotKey` las consume antes de entregarlas a la aplicación con
  foco; por eso la asignación física de `D` impedía escribir esa letra. Letras,
  números de la fila superior, Espacio y Enter exigen ahora un modificador;
  F1–F12, teclado numérico y navegación siguen admitiendo asignación simple.
- Retirada de la Run activa la asignación peligrosa `floating_menu = d`.
- El usuario confirmó físicamente que los contadores de la barra flotante ya
  responden desde la primera interacción.
- Verificación visual a 1920×1080 en ventana normal y overlay:
  `diagnostics/ui/alpha109-pc-live-metadata.png` y
  `diagnostics/ui/alpha109-overlay-pc-live-metadata.png`.
- Verificación completa: **705 tests superados** en 24,12 s con
  `python -m pytest -q`.

# v0.2.2-alpha.108 — metadatos PC autónomos y controles coherentes

- Corregida la causa por la que un Pokémon exclusivamente almacenado en PC
  seguía sin stats: el PB8 publica ahora su EXP y el adaptador deriva el nivel
  mediante `SheetPersonal.expType` de la misma ROM activa antes de calcular las
  seis estadísticas. La lectura física actual de Ornita produjo nivel 15,
  naturaleza, IV/EV y seis stats no nulos sin usar un ancla del equipo.
- La barra flotante repinta sus contadores inmediatamente después de confirmar
  el ajuste persistente, fuera del callback del botón; ya no parece bloqueada
  hasta abrir la ventana principal.
- Separada la X global de la flecha derecha de la ficha en el overlay.
- La asignación de teclado captura directamente pulsaciones breves y declara
  expresamente que acepta teclas simples.
- Configuración muestra columnas diferenciadas de teclado y mando. La columna
  de mando permanece cerrada: Ryujinx usa SDL2 con input fuera de foco y el
  equipo no dispone de captura HID exclusiva, por lo que habilitar solo la
  detección duplicaría las pulsaciones en el juego.
- Regresiones añadidas para PC sin ancla, EXP preservada, repintado inmediato y
  separación de controles del overlay.

# v0.2.2-alpha.107 — navegación completa y datos PC BDSP

- Corregida la pérdida de naturaleza, IV y EV al reconstruir cada PB8 de caja;
  los stats se calculan únicamente cuando existen nivel testigo y PersonalTable
  validada para esa identidad.
- Z sobre una MT termina la fase izquierda y mueve el selector al primer Pokémon
  compatible; una segunda Z ejecuta la elección visible.
- Elegir y regenerar cada resultado de drafteo son ahora destinos independientes.
- Bolsa muestra confirmación inmediata dentro del propio overlay para cada
  utilidad enviada al writer BDSP.
- Añadido un engranaje navegable que abre Configuración.
- La captura de mando no se habilita todavía: Ryujinx usa SDL2 con input fuera de
  foco activado y no existe un filtro HID instalado, por lo que leer el mando en
  RoleRun duplicaría la misma pulsación en el juego.
- Verificación visual en `diagnostics/ui/alpha107_overlay_home.png` y
  `diagnostics/ui/alpha107_overlay_bag_feedback.png`.
- Verificación completa: **699 tests superados** en 24,30 s con
  `python -m pytest -q`.

# v0.2.2-alpha.106 — navegación jerárquica sin modificar Ryujinx

- Eliminado el envío de F5 y toda llamada `ShowWindow` del menú inmersivo: abrir
  RoleRun ya no restaura, maximiza, pausa ni cambia la geometría del emulador.
- El overlay toma foco y grab de teclado mientras está visible, de modo que las
  flechas se consumen en RoleRun y no mueven al personaje.
- Flechas y Z se enrutan explícitamente a Equipo/PC, MT o Drafteos, sin depender
  de bindings superpuestos de cada vista.
- X vuelve primero al selector de cuatro secciones; solo otra X desde ese
  selector cierra el overlay y restaura inmediatamente la barra flotante.
- La X de ratón respeta la misma jerarquía, incluida Bolsa.
- Regresiones añadidas para ausencia de pausa/cambio de ventana, navegación de
  la vista activa y retorno jerárquico.
- Verificación visual iterativa en
  `diagnostics/ui/alpha106_overlay_team.png` y
  `diagnostics/ui/alpha106_overlay_back_to_menu.png`.
- Verificación completa: **696 tests superados** en 22,81 s con
  `python -m pytest -q`.

# v0.2.2-alpha.105 — superficies inmersivas independientes

- Corregida la causa del recorte extremo de Equipo/PC y Drafteos: ya no se
  reconstruyen dentro del canvas histórico de la ventana principal. Cada vista
  se compone en un viewport independiente, medido dentro de la superficie que
  cubre Ryujinx.
- MT compacta sus seis fichas y presenta los cuatro movimientos en una matriz
  2×2; la página completa cabe en el overlay 1920×1080 sin scroll general.
- El selector ON/OFF deja de combinar `textvariable` y `text`; el botón visible
  tiene ahora una única autoridad de texto y se repinta en la misma interacción.
- La pausa reemplaza `PostMessage` —que no altera el estado de teclado leído por
  SDL— por dos eventos SendInput F5 después de verificar Title ID, configuración
  y foreground exactos de Ryujinx.
- El menú central y Bolsa permiten navegación con flechas, Z para aceptar y X
  para volver/cerrar. Las vistas funcionales conservan su navegación espacial.
- Verificación visual iterativa en `diagnostics/ui/alpha105_overlay_team_final.png`,
  `diagnostics/ui/alpha105_overlay_tms_final.png` y
  `diagnostics/ui/alpha105_overlay_drafts_final.png`.
- Verificación completa: **694 tests superados** en 22,07 s con
  `python -m pytest -q`.

# v0.2.2-alpha.104 — presentación física y menú de juego

- La compuerta de presentación BDSP cubre ahora cualquier descenso de PS, no
  solo el KO: conserva el último valor publicado hasta observar para el mismo
  PokeID el objetivo con `IsAnimation=true` y después `false` en la barra real.
- El selector ON/OFF usa una variable visual persistente y fuerza su repintado
  antes de retirar la ventana principal.
- La cabecera utiliza los iconos originales de Caramelo Raro y Repelente Máximo.
- La vista global de MT coloca el buscador sobre la lista izquierda y compacta
  las seis fichas para que entren completas a 1920×1080.
- El menú flotante pasa a ser una superficie central sobre Ryujinx, con fondo
  translúcido y las entradas Equipo y PC, MT, Drafteos y Bolsa. Las tres vistas
  funcionales se abren sin barra lateral, cabecera ni pie; Bolsa permite ejecutar
  las tres utilidades ya verificadas.
- La pausa solo se activa si el `Config.json` de la instalación declara F5 y si
  se identifica la ventana Perla Reluciente `010018E011D92000`; el cierre deshace
  exactamente el toggle y también protege el cierre completo de RoleRun.
- Regresión añadida para daño positivo adelantado. Revisión visual en
  `diagnostics/ui/alpha104_tm.png` y
  `diagnostics/ui/alpha104_overlay_menu_final.png`.
- Verificación completa: **691 tests superados** en 22,42 s con
  `python -m pytest -q`.

# v0.2.2-alpha.103 — salud viva y controles de juego

- Corregida la primera divergencia de las barras de PS: el carril validado de
  salud se fusiona ahora por identidad fuerte con la party publicada y la
  captura posterior no puede restaurar el HP antiguo de `PlayerWork`.
- La barra flotante muestra una barra de PS por rol y el estado persistente
  PB8 con los valores exactos de `PKHeX.Core.StatusCondition`.
- El antiguo `+` ambiguo es ahora `♥ CURAR`; debajo aparece `☰ MENÚ`, que abre
  accesos flotantes a `Equipo y PC`, `MT` y `Drafteos`.
- `BARRA FLOTANTE · ON` abre la barra de inmediato. Curar y abrir el menú pueden
  configurarse como atajos y se rechazan si ni RoleRun ni Ryujinx están en
  primer plano.
- Restaurados en la cabecera común los accesos a Caramelos Raros x999,
  Repelentes Máximos x999 y dinero máximo.
- Visualización iterativa verificada en
  `diagnostics/ui/alpha103_floating_bar_final.png`,
  `diagnostics/ui/alpha103_floating_menu.png` y
  `diagnostics/ui/alpha103_header.png`.
- Verificación completa: **690 passed** en 23,51 s con `python -m pytest -q`.

# v0.2.2-alpha.102 — cierre funcional BDSP

- Añadida curación completa e inmediata de la party BDSP desde `Equipo y PC` y
  la barra flotante: restaura PS, estado y PP máximos demostrados por
  `personal_masterdatas`. La transacción identifica cada PB8, hace doble
  lectura, readback host/guest y rollback verificado.
- Arrastrar entre las seis casillas de Equipo intercambia roles, no posiciones
  físicas. Aplica también EV, stats derivados y PS coherentes mediante el writer
  de rol ya validado; el receptor de Líbero exige elegir sus dos stats.
- La ficha vuelve a señalar movimientos incompatibles en rojo y ofrece las
  rutas existentes de `SUSTITUIR` y `ELIMINAR`, sin crear otro writer.
- Un Pokémon que entra desde el PC recibe automáticamente los EV del rol que
  hereda. Líbero pregunta sus dos stats antes de preparar el cambio.
- `BARRA FLOTANTE` pasa a ser una preferencia persistente ON/OFF. En OFF no se
  abre automáticamente al enfocar el emulador; en ON conserva el comportamiento
  anterior.
- Las MO no reciben un bypass genérico: BDSP ya las ejecuta desde el Pokétch sin
  ocupar moveset. Los juegos antiguos requerirán prueba independiente de su
  comprobación de campo antes de modificar su motor.
- Revisión visual real del fixture a 1920×1080 en
  `diagnostics/ui/alpha102-bdsp-heal-move-issues.png` y
  `diagnostics/ui/alpha102-bdsp-invalid-moves.png`.

Pendiente la validación física breve en BDSP/Ryujinx de las nuevas escrituras y
controles. Verificación automatizada: **671 passed** en 22,69 s con
`py -3.14 -m pytest -q`.

# v0.2.2-alpha.101 — EV por rol en BDSP

- `PersonalTable` aporta los seis stats base de la especie/forma desde el mismo
  `personal_masterdatas` activo que ya gobierna MT y compatibilidades.
- El reader runtime conserva naturaleza efectiva, IV, EV y stats calculados al
  publicar cada `PokemonParam`; antes los extraía del PB8 y los descartaba en la
  reconstrucción final.
- Cambiar de rol en BDSP prepara una distribución de 504 EV: Asesino
  Ataque/Velocidad; Mago At. Esp./Velocidad; Tanque PS/Defensa; Prisma
  PS/Def. Esp.; Support Defensa/Def. Esp. Los otros cuatro stats quedan a cero.
- Líbero exige elegir exactamente dos de los seis stats en el editor de rol.
- Rol, EV, stats calculados y PS forman una sola transacción. El writer verifica
  identidad, rol y EV anteriores, reproduce los stats vivos desde
  Personal/IV/EV/nivel/naturaleza, escribe core+calc, hace readback host/guest y
  rollback conjunto. Conserva el daño existente y nunca cura ni revive como
  efecto lateral de cambiar EV.
- Revisión visual iterativa del editor a 1920×1080 en
  `diagnostics/design_evolution/alpha101_role_evs_1920x1080.png`.

Verificación automatizada: **667 passed** en 22,98 s con
`py -3.14 -m pytest -q`. Pendiente una única validación física controlada en
BDSP/Ryujinx antes de declarar cerrada la capacidad realtime.

Validación física completada: Líbero selecciona y aplica correctamente sus dos
estadísticas y los roles fijos asignan automáticamente su pareja 252/252,
dejando a cero los otros cuatro stats. La capacidad queda cerrada en
BDSP/Ryujinx.

# Cambios posteriores a alpha.100 — carga inicial y cierre de MT atómicos

## Pestaña global de MT

- `MT` pasa a ser un destino principal y muestra exclusivamente las MT cuya
  cantidad positiva ha sido confirmada en la mochila viva.
- Buscar por número o movimiento filtra el catálogo. Al seleccionar una MT, los
  seis miembros se evalúan mediante `_tm_flow_candidates()`: los resultados
  incompatibles con su rol quedan grises y no se pueden aceptar.
- Elegir un Pokémon entra directamente en el selector existente de movimiento a
  olvidar. Confirmación, consumo, escritura realtime y readback siguen usando el
  mismo contrato ya validado; la vista global no contiene un segundo writer.
- Hover, flechas, `Z` y `X` recorren catálogo y equipo. La previsualización no
  destruye widgets, no altera el scroll y distingue `YA LO CONOCE` de una
  incompatibilidad de rol.
- La vista global permanece completa durante la escritura. Solo después del
  readback se actualizan cantidad, moveset y compatibilidad, sin publicar el
  estado intermedio `Comprobando la mochila` ni reconstruir la página.
- El paso de movimiento a olvidar usa cuatro tarjetas compactas centradas, sin
  las franjas vacías producidas por estirarlas hasta todo el viewport.
- Revisión visual iterativa a 1920×1080: catálogo, seis tarjetas y operación
  inferior ocupan el viewport completo sin scroll general ni barreras residuales.

Verificación: **662 passed** en 23,85 s con `py -3.14 -m pytest -q`.
La escritura, el aprendizaje, el descenso exacto de cantidad y la interacción
final —catálogo poseído, hover sin flicker, scroll estable, `YA LO CONOCE`,
selector centrado y regreso sin cargador intermedio— fueron validados
físicamente en BDSP/Ryujinx el 23 de agosto de 2026.

- La partida ya no construye primero una vista provisional de una caja: equipo,
  cajas y movimientos válidos se leen en el worker inicial y la caché PC queda
  instalada antes de crear `Equipo y PC`.
- El cargador inicial no depende de un retraso fijo. Permanece hasta que la vista
  final confirma tres pasadas de geometría, el número real de cajas y la
  finalización del primer intento realtime.
- Al cerrar MT se conserva primero el flujo completo como fondo y después se
  descubre la vista `Equipo y PC` que seguía intacta debajo. Ya no se reconstruye
  esa página ni se superponen dos barreras de carga.
- La navegación de la ficha verifica de forma funcional que `Z` transfiere el
  foco y derecha pasa de `CAMBIAR ROL` a `ENSEÑAR MT`.

La versión sigue siendo `v0.2.2-alpha.100` hasta completar la validación física.
No se modifica RAM, readers, writers ni persistencia.
Verificación: **655 passed** en 23,53 s con `python -m pytest -q`.

Validación física posterior: el flujo de MT funciona correctamente. La carga
inicial aún publica durante unos tres segundos una vista parcialmente compuesta;
no se declara corregida y se detiene el parcheo incremental de ese defecto.

# v0.2.2-alpha.100 — publicación visual verificada

- La carga PC no se retira al solicitar un render: espera tres observaciones
  consecutivas de la vista final, con el número real de cajas y geometría válida.
- Apertura conserva la pantalla autónoma; MT usa el frame estable oscurecido de
  origen, igual que la navegación entre pestañas.
- Dentro de la ficha, izquierda/derecha recorre todas sus acciones. `Z` entra
  desde cualquier Pokémon y vuelve a aceptar la acción enfocada.

No se modifica RAM, readers, writers ni persistencia.
Verificación: **649 passed** en 22,37 s con `python -m pytest -q`.

# v0.2.2-alpha.99 — carga autónoma y navegación explícita

- Las operaciones ya no congelan capturas de widgets CTk. Apertura, PC y MT
  muestran una pantalla opaca autónoma con spinner independiente hasta que el
  destino está completamente construido.
- Equipo recorre sus seis posiciones en orden estricto; deja de interpolarse
  sobre las diez filas del PC, causa de los saltos de Mago y Prisma.
- `Z` sobre cualquier Pokémon lleva el selector a la primera acción de su ficha;
  una segunda pulsación la ejecuta.
- `X` elimina la selección en Equipo/PC, Drafteos y MT. Se retira `B`.

No se modifica RAM, readers, writers ni persistencia.
Verificación: **648 passed** en 22,78 s con `python -m pytest -q`.

# v0.2.2-alpha.98 — barreras persistentes y navegación sin reentrada

- La limpieza welcome→shell preserva expresamente el Toplevel de carga; la
  primera lectura PC ya no puede exponer ni capturar una shell parcial.
- Cerrar MT destruye el flujo y todos sus bindings antes de reconstruir
  Equipo/PC. Una flecha vuelve a producir exactamente un movimiento.
- El botón del inspector PC forma parte del recorrido de flechas y se acepta con
  `Z`; `B` sigue eliminando la selección.
- Entrada y salida de MT quedan cubiertas por la barrera independiente.
- La barra inferior aumenta su tipografía y revela gradualmente cada mensaje.

No se modifica RAM, readers, writers ni persistencia.
Verificación: **647 passed** en 22,58 s con `python -m pytest -q`.

# v0.2.2-alpha.97 — readback BDSP y superficies de actividad estables

- BDSP conectado deja de proyectar cambios Equipo↔PC antes del resultado
  verificado del writer. Ya no combina un equipo futuro con una caja anterior.
- La barrera de apertura permanece hasta terminar la primera lectura PC.
- El arrastre usa una ventana nativa independiente y no repinta el canvas.
- El mensaje de actividad tiene una superficie fija que se repinta antes de la
  siguiente operación bloqueante.

No se añaden direcciones RAM ni se altera ningún writer.
Verificación: **643 passed** en 22,86 s con `python -m pytest -q`.

# v0.2.2-alpha.96 — sistema único de espera independiente

## Cargas y operaciones

- La apertura de una partida, la lectura de cajas, las operaciones PC↔Equipo,
  las escrituras realtime y la consulta de inventario comparten ahora una
  superficie independiente del árbol que se está reconstruyendo.
- El fondo queda congelado y oscurecido de forma uniforme. El indicador circular
  usa el worker gráfico independiente y continúa girando aunque Tkinter esté
  ocupado construyendo widgets.
- La carga de cajas mantiene su barrera hasta terminar el render completo de
  Equipo/PC; el loader ya no puede desaparecer antes y exponer tarjetas parciales.
- La navegación conserva deliberadamente el frame de origen oscurecido hasta
  publicar la pestaña nueva completa.

No se modifica lógica realtime, RAM, persistencia, readers ni writers.
Verificación: **639 passed** en 22,95 s con `py -3.14 -m pytest -q`;
preview con bloqueo real de 1,7 s y grabación de control a 60 fps.

# v0.2.2-alpha.95 — transición inmutable con actividad visible

## Navegación

- La navegación iniciada desde el menú reutiliza la captura limpia tomada antes
  de oscurecer el contenido. Ya no recaptura una superficie que DWM pudiera
  estar iluminando por zonas al retirar el menú.
- El drawer cerrado se desmapea del gestor de geometría: su tirador `<` deja de
  conservar una superficie residual junto al control colapsado `>`.
- Un indicador circular gira desde un worker gráfico independiente mientras el
  hilo principal construye la página. Por ello continúa moviéndose incluso
  durante el tramo síncrono en que Tkinter no puede atender callbacks `after`.
- La captura transferida se invalida también si se elige la página ya visible,
  evitando reutilizar un frame antiguo en una navegación posterior.

No se modifica lógica realtime, persistencia, readers ni writers.
Verificación: **638 passed** en 22,71 s con `py -3.14 -m pytest -q`;
grabación de control a 60 fps y contacto ampliado del spinner a 20 fps.

# v0.2.2-alpha.94 — navegación compuesta sin reconstrucción visible

## Cambio de pantalla

- La pestaña ya visible no vuelve a renderizarse al seleccionarla desde el menú:
  el lateral se cierra y el árbol actual permanece intacto.
- Una navegación real congela el último frame completo en una superficie DWM
  independiente. La vista de destino se construye y compone debajo; el fundido
  comienza únicamente después de varios frames estables.
- La superficie anterior y la nueva se mantienen como buffers reales durante el
  intercambio. Nunca se publica un canvas, tarjeta o panel parcialmente creado.

## Menú lateral

- El lateral expandido deja de redimensionar su árbol en cada tick: se mantiene
  precalculado a ancho fijo y solo cambia su coordenada horizontal.
- La temporización ya no suma otros 16 ms al coste de repintado de Tk. La traza
  a 1920×1080 pasa de saltos observados de unos 31 ms a actualizaciones
  mayoritariamente de 4–5 ms durante el tramo visible.

No se modifica lógica realtime, persistencia, compatibilidad, readers ni
writers. Verificación: **637 passed** en 22,95 s con
`py -3.14 -m pytest -q`; revisión fotograma a fotograma de una grabación de
control a 1920×1080/30 fps y capturas asentadas con escala 100 % y 125 %.

# v0.2.2-alpha.93 — densidad final y navegación sin reentrada

## Equipo y ficha

- Las cuatro casillas de movimientos forman una sola fila compacta en cada
  tarjeta de Equipo; ya no quedan dos ataques fuera del alto visible.
- El tooltip de rol se ancla al centro superior de su propio botón, con
  independencia de la posición de la tarjeta o del scroll.
- Cada stat de la ficha contiene directamente su valor, IV y EV. Se elimina la
  segunda matriz de entrenamiento y habilidad/objeto suben al espacio liberado.

## Menú lateral y Drafteos

- La capa oscura usa exactamente el rectángulo visible del contenido y conserva
  sus dimensiones también con escalado de Windows; el lateral interpola de 76 a
  285 px durante 210 ms sin relayout de la página.
- Elegir una pestaña espera al cierre real del lateral. La barrera de cambio ya
  no reentra en el bucle de eventos durante el render: se elimina la causa que
  podía dejar una captura oscura superpuesta o reconstruir dos veces la vista.
- La primera pantalla de Drafteos no muestra un cierre sin función. En pasos
  posteriores aparece únicamente una flecha que vuelve a elegir Pokémon.

No se modifica lógica realtime, persistencia, compatibilidad, readers ni
writers. Verificación: **635 passed** en 23,37 s con
`py -3.14 -m pytest -q`; revisión visual fotograma a fotograma a 1920×1080 y
con escala 125 %.

# v0.2.2-alpha.92 — tarjetas completas y transiciones estables

## Equipo y ficha

- Las tarjetas muestran únicamente mote y nivel, reducen la barra de PS a un
  tercio útil y colocan los seis stats en una matriz 2×3. Habilidad, objeto y
  los cuatro movimientos permanecen visibles en las seis filas a 1900×1040.
- El botón de ayuda adopta las seis siluetas de rol aportadas por el usuario,
  recoloreadas en dorado a partir de su canal alfa. El nombre del rol aparece
  como tooltip y el botón conserva la guía existente.
- Toda la tarjeta abre la ficha, excepto el control de rol con acción propia.
  La ficha centra habilidad, objeto y movimientos, elimina la numeración y
  separa IV/EV en seis recuadros legibles.

## Ventana y navegación

- Minimizar la ventana principal cambia a la barra flotante; sin una Run apta,
  la ventana vuelve maximizada. RoleRun mantiene así solo sus dos modos
  deliberados de presentación.
- El menú lateral se abre y cierra mediante una interpolación de 210 ms. El
  tirador ocupa un carril propio, toda la barra colapsada responde al hover y
  Configuración deja de quedar tapada.
- Los cambios de página mantienen la superficie anterior hasta que la nueva
  ha construido y medido todos sus widgets. Se corrige la primera divergencia
  del parpadeo: Drafteos destruía su contenido antes del intercambio visual.
- Drafteos replica la matriz 2×3 de stats, amplía sus movimientos y presenta la
  silueta de rol debajo del nombre.

No se modifica lógica realtime, persistencia, compatibilidad, readers ni
writers. Verificación: **631 passed** en 23,10 s con
`py -3.14 -m pytest -q -p no:cacheprovider`; revisión visual sintética a
1900×1040 de Equipo/PC, ficha, Drafteos y menú lateral.

# v0.2.2-alpha.91 — equipo protagonista y navegación completa

## Interfaz y navegación

- La barra lateral queda reducida al icono de RoleRun y un tirador central. Al
  abrirla, el contenido permanece reconocible pero oscurecido; pulsar fuera,
  volver a pulsar el tirador o elegir una página la cierra.
- Las flechas mueven un selector espacial en Equipo/PC, Drafteos y MT; `Z`
  acepta y `B` elimina la selección. Tras eliminarla, la siguiente flecha parte
  de la primera opción disponible.
- La cabecera usa los símbolos históricos para vidas, curaciones, medallas y
  drafteos. Medallas no expone botones manuales; los otros contadores conservan
  sus controles directos.

## Equipo, PC y respuesta

- Equipo gana anchura y sus seis fichas muestran mote, especie, nivel, rol,
  PS live con barra, stats coloreados por naturaleza, habilidad, objeto y los
  cuatro movimientos sin salir del panel.
- PC se estrecha a tres columnas y mantiene las treinta posiciones mediante un
  scroll local. La ficha de un miembro del equipo ofrece únicamente `CAMBIAR
  ROL` y `ENSEÑAR MT`; las operaciones de PC viven en el contexto del PC.
- El indicador centrado animado cubre también la aplicación y verificación de
  writers realtime. Las mochilas ORAS y X/Y se leen en background con las
  mismas reglas anteriores; ORAS conserva explícitamente su fallback al último
  guardado y X/Y sigue rechazándolo.

No se añade ninguna dirección RAM, writer, regla de rol ni capacidad realtime.
La pestaña global de MT y la transacción de EV por rol siguen pendientes.

- Verificación: **625 passed** en 22,22 s con
  `py -3.14 -m pytest -q -p no:cacheprovider`. Se revisaron capturas sintéticas
  a 1900×1040 de Equipo/PC, menú lateral, Drafteos y MT.

# v0.2.2-alpha.90 — composición completa a pantalla completa

## Cabecera común

- El bloque desplegable de contadores se sustituye por cuatro controles
  independientes siempre visibles: vidas, curaciones, medallas y drafteos.
  Cada contador manual expone `−`, valor y `+` desde cualquier página.
- Los contadores gobernados por el juego conservan una única fuente de verdad:
  sus botones aparecen deshabilitados y el valor sigue actualizándose en vivo.

## Equipo, PC y Drafteos

- Equipo termina visualmente junto a la fila 21–25 del PC. Las seis fichas se
  muestran completas, con identidad, PS, naturaleza, habilidad y objeto.
- La caja PC vuelve a una matriz fija 5×6: sus 30 casillas y sprites compactos
  caben a 1900×1040 sin rueda ni barra de desplazamiento.
- Las seis opciones de Drafteos muestran sprite grande, naturaleza, objeto,
  stats, IV, EV y movimientos; los seis botones `ELEGIR` permanecen visibles.
- El alto de Equipo/PC y Drafteos sigue el viewport real de la superficie
  principal, incluso después de un redimensionado.

No se modifica ninguna regla, backend, dirección RAM, detección realtime ni
writer. La pestaña global de MT y la transacción de EV por rol siguen siendo
fases funcionales separadas y pendientes.

- Verificación: **620 passed** en 23,29 s con
  `py -3.14 -m pytest -q -p no:cacheprovider`. Se revisaron capturas sintéticas
  a 1900×1040 de Equipo/PC y de los tres pasos de Drafteos.

# v0.2.2-alpha.89 — jerarquía visual y respuesta de la interfaz

## Equipo y PC

- Las seis tarjetas del equipo se reparten ahora en seis filas equivalentes y
  ocupan toda la altura del panel. Incorporan rol, identidad, especie, nivel,
  PS, naturaleza, habilidad y objeto sin desplazar ninguna línea sobre el borde.
- El contenido de cada tarjeta vive dentro de un margen propio. El borde azul
  de selección queda continuo y ya no puede ser tapado por el texto inferior.
- La matriz del PC es la única superficie desplazable de Equipo/PC. Sus treinta
  posiciones conservan un tamaño legible y la ficha permanece fija.

## Drafteos, navegación y carga

- Las seis opciones de Pokémon usan sprites de 112 px y una composición
  jerárquica con nombre, especie, nivel, rol, naturaleza, objeto, movimientos y
  acción explícita.
- La transición ya no altera la opacidad de la ventana. Solo se desvanecen los
  widgets del flujo, sobre un shell que permanece estable.
- `CONSULTAR MOVIMIENTOS` desde un drafteo conserva el estado y muestra
  `← VOLVER AL DRAFTEO` como ruta inequívoca de retorno.
- La carga inicial, las cajas PC y la mochila de MT muestran un indicador
  animado centrado durante sus trabajos en segundo plano.

No se modifica ningún backend, regla, offset ni writer. La transacción de EV y
la pestaña global de MT siguen registradas como las dos fases funcionales
pendientes; no es necesario que el usuario vuelva a recordarlas.

- Verificación: **620 passed** en 22,92 s con
  `py -3.14 -m pytest -q -p no:cacheprovider`. Capturas sintéticas revisadas a
  1900×1040 para Equipo/PC y Drafteos.

# v0.2.2-alpha.88 — densidad 16:9 y datos completos de Pokémon BDSP

## Interfaz

- Vidas, curaciones, medallas y drafteos ocupan ahora el centro común de la
  cabecera y abren el panel de Estado de la Run. En anchuras compactas el bloque
  se oculta para preservar las acciones y el resumen equivalente sigue en la
  barra lateral.
- Equipo/PC mide el cuerpo real disponible: a 1080p muestra las seis tarjetas,
  las 30 casillas y la ficha completa sin rueda. Las tarjetas usan dos líneas,
  sprites contenidos y un botón `?` circular; desaparece la tercera línea
  redundante que podía quedar recortada como un punto.
- La ficha agrupa naturaleza, los seis stats, IV y EV, habilidad, objeto,
  movimientos y acciones. El stat favorecido por la naturaleza efectiva se
  muestra en rojo y el perjudicado en azul. Ventanas pequeñas conservan un
  scroll local y distribuyen los stats en dos filas legibles.
- Drafteos muestra seis tarjetas compactas 3×2 con nivel, rol, naturaleza,
  objeto y movimientos; elimina `LISTO`, reduce los candidatos y aplica una
  transición breve. Líbero elige primero su pool. Las opciones nuevas y los
  movimientos a sustituir muestran metadatos y descripción cuando existe.

## Datos demostrados, sin nuevas escrituras

- El reader PB8 BDSP publica `Nature` 0x20, `StatNature` 0x21, EV 0x26–0x2B,
  IV32 0x8C y los seis stats calculados 0x14A–0x154 en un orden canónico de UI.
  Son campos del mismo PB8 ya cifrado y validado por checksum; no se añade una
  dirección RAM ni una ruta de escritura.
- `WazaTable` aporta ahora potencia y `hitPer` además de clase y PP. El bundle
  hermano `Message/<idioma>` aporta las 826 descripciones no vacías de
  `ss_wazainfo`; la instalación activa expone `english` y la UI lo identifica
  como `EN` en lugar de presentarlo como texto español.
- La asignación automática de EV por rol no se habilita todavía: falta demostrar
  y cerrar la escritura conjunta de EV, recálculo de stats/HP, precondiciones,
  readback y rollback. La futura pestaña global de MT se mantiene también como
  fase separada; el selector transaccional actual no cambia.
- Verificación: **614 passed** en 22,66 s con
  `py -3.14 -m pytest -q -p no:cacheprovider`. Capturas sintéticas revisadas a
  1900×1010, 1360×768 y 1100×720; no se accedió a la RAM real durante los tests.

# v0.2.2-alpha.87 — Design Evolution sobre la interfaz original

## Evolución visual y navegación

- Esta versión parte de una copia verificada de alpha.86 y conserva la identidad
  visual original. El proyecto rechazado `RoleRun Manager Redesign Prototype`
  no se utilizó como base ni como fuente de implementación.
- La navegación principal queda en `Equipo y PC`, `Drafteos`, `Configuración`
  y `Ayuda`. Dashboard deja de ser destino; Historial pasa a Configuración y
  Consulta de movimientos a Ayuda. La Run activa abre un panel integrado.
- El antiguo Modo Libre desaparece. Runs antiguas con
  `role_rules_active=false` se normalizan sin tocar save, roles, movimientos ni
  contadores.
- Una barra inferior permanente diferencia preparación, aplicación,
  verificación, confirmación, restauración, advertencia y error. Nunca presenta
  una proyección como confirmación del juego.

## Equipo, PC, MT y drafteos

- Equipo y PC comparten una vista `Equipo | Caja | Ficha`, con seis casillas
  canónicas, búsqueda, navegación por caja, inspector, flechas y alternativa
  de botones al drag and drop. Las operaciones continúan llamando a los modelos,
  writers y verificaciones existentes.
- PC→PC y reordenación física Equipo→Equipo permanecen deshabilitados porque
  los writers actuales no demuestran esas operaciones; la UI las identifica
  como destinos inválidos en vez de simularlas.
- La enseñanza de MT es un flujo integrado de tres pasos y permite elegir el
  slot sustituido incluso con cuatro movimientos. La compatibilidad se calcula
  por slot y el límite completo de Support se conserva.
- Drafteos muestra los seis Pokémon, exige pool para Líbero y consume el derecho
  únicamente al elegir el movimiento sustituido, igual que el flujo funcional
  anterior.

## Una sola ventana, bajas y configuración

- Ayuda, guía del formato, editor de roles, conflictos, Support, revisión de
  equipo, selectores Equipo↔PC, revisión de cambios, historial, diagnóstico y
  captura de atajos usan superficies integradas. Solo permanecen como
  `CTkToplevel` la barra flotante y el fantasma técnico temporal de drag.
- La sustitución por baja reutiliza la vista Equipo y PC. Cerrar el panel no
  elimina la baja ni devuelve la vida; la barra inferior mantiene una acción
  persistente para reabrirlo. El `PendingTeamChange("replace-fainted")`, Caja 4,
  testigos, writer, readback, rollback y resolución persistente no se cambiaron.
- Configuración se organiza por secciones y usa un helper único para abrir o
  seleccionar guardado, ROM, datos, Runs, OBS, diagnósticos y backups. Una ruta
  ausente se comunica en la barra sin lanzar una excepción.

## Verificación

- Capturas revisadas en 1100×720, 1360×768 y 1440×900, incluida escala 125 %.
- Regresiones dirigidas de navegación, migración, estado de operaciones,
  Equipo/PC, MT, drafteos, baja integrada, ventana única y rutas.
- Suite completa: **608 passed** en 22,48 s con
  `py -3.14 -m pytest -q -p no:cacheprovider`.
- No se modificaron readers, adapters, direcciones RAM, writers, detección de
  KO, contadores automáticos ni estructuras de save durante esta evolución.

# v0.2.2-alpha.86 — identidad e inserción de Repelente Máximo BDSP

## Causa raíz demostrada

- La prueba física de alpha.85 mostró `Repelente ×999`, no Repelente Máximo.
  El writer, readback y refresco funcionaron; la primera divergencia estaba en
  `BDSP_UTILITY_ITEM_IDS`, que enviaba la acción semántica `max-repel` al
  registro `79`.
- El catálogo español de PKHeX indexa `77 = Repelente Máximo` y
  `79 = Repelente`. OpenDPR coincide: `GOORUDOSUPUREE=77` y
  `MUSIYOKESUPUREE=79`. Alpha.85 había traducido erróneamente el segundo nombre
  interno sin contrastarlo con el catálogo indexado.
- La relectura física posterior confirmó exactamente el efecto: `SaveItem[79]`
  tenía 999, mientras `SaveItem[77]` seguía completamente vacío. Evidencia:
  `diagnostics/manual/bdsp_alpha85_max_repel_identity_FAIL_alpha86_ROOT_CAUSE_20260823.json`.

## Corrección y seguridad

- `max-repel` apunta ahora exclusivamente al ID BDSP `77`; el registro `79`
  queda intacto como Repelente normal.
- Como el Repelente Máximo no existe aún en esta partida, alpha.86 implementa
  el alta real del `SaveItem`: conserva flags/padding y asigna el siguiente
  `SortNumber` del bolsillo General. El algoritmo está demostrado por
  `ItemInfo.count` de OpenDPR y `MyItem8b.GetNextSortIndex` de PKHeX; no se
  inventa un orden global ni se mezcla con otros bolsillos.
- Se mantienen doble captura, precondición guest/host, escritura del único
  registro de 12 bytes, readback completo de mochila/party/MYSTATUS y rollback.
- Las regresiones comprueban el catálogo español por índice, reproducen el
  caso físico `77` ausente + `79` presente, exigen `max+1` incluso si un objeto
  con cantidad cero conserva orden y verifican que el Repelente normal no se
  modifica.
- Verificación: **130 passed** en el bloque BDSP dirigido y **581 passed** en
  22,05 s con `py -3.14 -m pytest -q`.
- Validación física posterior en SP 1.3.0 / Ryujinx: el botón corregido creó
  Repelente Máximo ×999 correctamente. Caramelo Raro, Repelente Máximo y dinero
  quedan cerrados físicamente para el perfil demostrado.

# v0.2.2-alpha.85 — utilidades BDSP transaccionales

## Evidencia y primera divergencia

- La UI bloqueaba explícitamente todo `PendingInventoryChange` de BDSP antes de
  alcanzar el adapter. El reader ya había demostrado el array vivo completo de
  3.000 `SaveItem`; no faltaba un fallback ni una segunda mochila.
- Alpha.85 identificó Caramelo Raro como `50`, pero interpretó erróneamente el
  registro `79` como Repelente Máximo. La prueba física posterior demostró que
  era Repelente normal; el ID correcto es `77` y la corrección se conserva en
  alpha.86. Los registros físicos observados tenían cantidades 892/26 y
  `SortNumber` 1/9, pero esas cifras no demostraban por sí solas la identidad
  localizada del segundo objeto.
- OpenDPR demuestra `SaveData.playerData.mystatus` y el orden
  `name, id, gold`; PKHeX fija el máximo BDSP en 999.999 ₽. Una inspección
  HostMapped acotada al único `PlayerWork` situó `MYSTATUS` en `+0xE0` y dinero
  en `+0xEC`. Nombre, ID32, dinero, edición y medallas coincidieron con
  el save; la estructura fue estable en doble lectura y el ID apareció una sola
  vez en el objeto. Evidencia:
  `diagnostics/manual/bdsp_alpha85_money_and_utility_layout_PROOF_20260822.json`.

## Implementación y seguridad

- `BDSPMoneyReader` valida referencia, nombre IL2CPP, ID32, límite monetario,
  sexo, medallas y edición antes de publicar el valor.
- `BDSPLiveWriter` acepta lotes exclusivos de utilidades fuera de combate.
  Relee dos veces party, mochila y `MYSTATUS`; compara los bloques completos
  entre guest y host; escribe únicamente los registros de 12 bytes de los dos
  IDs demostrados y/o los cuatro bytes de `gold`.
- La escritura preserva todos los flags, padding y orden de cada objeto. Si el
  objeto nunca tuvo una posición válida (`Count=0`, `SortNumber=0`), se rechaza
  sin inventar el orden de bolsillo ni escribir un byte.
- El readback exige la mochila completa, `MYSTATUS` completo, party intacta y
  significado final exacto. Cualquier fallo restaura en orden inverso y verifica
  ambos bloques.
- La UI aplica automáticamente los tres botones en Ryujinx y usa el límite BDSP
  999.999; desconectado no deja cambios de save invisibles. El cambio manual de
  rol de un Pokémon que permanece en PC queda fuera de alcance por decisión del
  usuario.
- Regresiones dirigidas: **115 passed**. Suite completa:
  **580 passed** en 21,72 s con `py -3.14 -m pytest -q`.
- Validación física posterior: Caramelo Raro y dinero funcionaron. El botón
  rotulado Repelente Máximo modificó Repelente normal, fallo corregido en
  alpha.86.

# v0.2.2-alpha.84 — sustitución por baja BDSP transaccional

## Primera divergencia y alcance demostrado

- El selector común ya construía correctamente `replace-fainted` con identidad
  saliente/entrante, slot de party, origen PC, Cementerio y rol. La primera
  divergencia BDSP estaba después del selector: las dos compuertas de UI
  descartaban esa operación y `BDSPLiveWriter.apply()` carecía de un destino
  para ella.
- No se incorpora ninguna dirección ni estructura nueva. La operación compone
  los mismos PB8 de 344 bytes y objetos core(328)+calc(16) demostrados y
  validados físicamente en alpha.81–83. A diferencia de un swap, el origen PC
  debe quedar con el vacío canónico y el debilitado debe ir a otro slot vacío
  de la Caja 4 sin alterar el tamaño ni el orden de la party.

## Implementación y seguridad

- El writer exige fuera de combate dos capturas idénticas de party y de las
  1.200 cajas, seis objetos runtime, direcciones estables, identidades exactas,
  HP=0 todavía vigente, un rol vivo único y el destino de Cementerio vacío.
- El rol se obtiene del Pokémon debilitado releído en RAM; no se confía en el
  valor preparado por la UI. Se prevalidan guest y host antes de escribir.
- La transacción vacía el origen PC, deposita los 344 bytes exactos del
  debilitado en Cementerio y sustituye core/calc del mismo slot por el PB8 del
  sustituto con el rol heredado. El contador de party no se toca.
- El readback comprueba los seis objetos, composición y conteo de party, las
  1.200 cajas, origen vacío, Cementerio exacto y rol. Cualquier fallo restaura
  en orden inverso los cuatro bloques y verifica la restauración en host y
  guest.
- Regresiones específicas cubren éxito, fallo en el cuarto write con rollback,
  rechazo de un miembro ya vivo y paso inmediato de la operación por la UI.
- Verificación: **121 passed** en el bloque BDSP y **572 passed** en 22,17 s en
  la suite completa. Validación física posterior del usuario en SP 1.3.0 /
  Ryujinx: tras un KO el selector apareció al terminar el combate, el sustituto
  entró correctamente, el debilitado quedó en la Caja 4 y la vida se descontó
  una sola vez. El caso integrado de una baja queda validado físicamente; OBS
  y la herencia visual del marcador conservan pruebas separadas. Los varios KO
  se comprobaron a continuación.
- Segunda validación física: dos Pokémon se debilitaron en el mismo combate;
  RoleRun descontó exactamente dos vidas, abrió y completó los dos selectores
  consecutivamente sin minimizar la aplicación, colocó ambos debilitados en la
  Caja 4 e incorporó ambos sustitutos. Quedan fuera de esta prueba OBS, historial
  visual y reconexión.
- Tercera comprobación física: el marcador del sustituto dentro del juego
  coincidió con el rol heredado mostrado por RoleRun. Queda demostrado el write
  y readback semántico del rol dentro de `replace-fainted`; esto no se presenta
  como validación de cualquier otro flujo manual de roles.

# v0.2.2-alpha.83 — compactación intermedia BDSP demostrada

## Causa raíz y evidencia

- Alpha.82 podía retirar el último miembro, pero bloqueaba cualquier posición
  intermedia porque todavía no estaba demostrado cómo `PokeParty` compacta sus
  seis objetos runtime. OpenDPR `5b0cb0c8...` declara `RemoveMember()` y la
  rutina privada `scootOver()`, pero ambos cuerpos están ausentes; sus nombres
  no bastan como contrato de escritura.
- Una captura completa de solo lectura observó una retirada nativa del slot 2
  con party de seis. `PokeParty`, el array, los seis `PokemonParam` y todas sus
  direcciones core/calc permanecieron estables. Los 344 bytes completos se
  copiaron exactamente 3→2, 4→3, 5→4 y 6→5; el slot 6 recibió el PB8 vacío
  canónico; el antiguo slot 2 pasó sin cambios a Caja 1:3; y el contador bajó
  6→5. Los otros 1.199 slots PC permanecieron idénticos.
- Evidencia:
  `diagnostics/manual/bdsp_sp130_party_size_transition_AUTO_20260822_224902.json`,
  SHA-256 `B65F6B7812314955CD090DB2AA6B68748402DDF17D4ADEA858D2A896254AEFCE`.

## Implementación y seguridad

- `BDSPLiveWriter` reproduce solo ese contrato: deposita el miembro seleccionado,
  desplaza literalmente cada PB8 posterior sobre el objeto fijo anterior, vacía
  el último objeto y escribe `m_memberCount` al final.
- Antes de abrir RW exige dos party y dos matrices PC completas idénticas,
  identidad/slot, correspondencia exacta entre miembros activos y almacenamiento,
  destino vacío, sesión y huella. Cada bloque tiene precondición guest y host.
- El readback exige el orden de identidades esperado, los 344 bytes exactos de
  los seis slots, el depósito exacto, el contador y la invariancia de los otros
  1.199 slots. Cualquier fallo restaura en orden inverso todos los bloques y
  verifica host e invitado.
- La UI ya permite enviar cualquier miembro BDSP activo; los demás backends no
  cambian. Nuevas regresiones cubren la compactación completa observada y un
  fallo inyectado en el último paso que restaura doce bloques.
- Verificación: **117 passed** en BDSP y **568 passed** en 21,62 s en la suite
  completa. El usuario validó después la escritura iniciada desde RoleRun en
  SP 1.3.0 / Ryujinx: la retirada intermedia, la compactación y el PC se
  reflejaron correctamente tanto en el juego como en RoleRun.

# v0.2.2-alpha.82 — tamaño de party BDSP 5↔6 demostrado y transaccional

## Causa raíz y evidencia

- El bloqueo anterior no era un error de UI: faltaba demostrar cómo representa
  BDSP un cambio de tamaño sin inferirlo del swap 1↔1 ni de los writers 3DS.
- Dos capturas físicas, estables y de solo lectura sobre SP 1.3.0 / Ryujinx
  demuestran las dos direcciones nativas del caso de cola. En 6→5, Pidgeotto
  salió del slot 6, ese mismo objeto fijo recibió el vacío PB8 canónico, Caja
  1:3 recibió exactamente sus 344 bytes y `m_memberCount` pasó de 6 a 5. En
  5→6 ocurrió la transformación inversa sobre las mismas direcciones. Los slots
  1–5 y los otros 1.199 slots de caja permanecieron idénticos.
- Evidencias: `bdsp_sp130_party_size_transition_AUTO_20260822_222122.json`
  (SHA-256 `718373E0D7061BECBB804EB1DC84E3CF765D830DD258BD47DA03BEB4F070F248`)
  y `bdsp_sp130_party_size_transition_AUTO_20260822_222322.json`
  (SHA-256 `C2AEF1C40D2D4A8C3F8BE94FCABC13A5B79EEC89A82F3B1D6DA5380B58BF0BFE`).

## Implementación y límites

- Los readers conservan ahora los seis objetos fijos de `PokeParty`, la
  dirección validada de `m_memberCount` y las 1.200 unidades cifradas de caja.
- El writer habilita únicamente retirar el último miembro o rellenar el
  siguiente slot. Rechaza miembros intermedios: la compactación no está
  demostrada y no se ha supuesto.
- La transacción hace doble captura completa, precondiciones guest/host, escribe
  el contador en último lugar, verifica readback y semántica, comprueba todos
  los miembros y slots de caja no implicados y restaura los cuatro bloques ante
  cualquier fallo. La entrada desde PC recibe el primer rol RoleRun libre.
- Cuatro regresiones cubren depósito, incorporación, rollback al fallar el
  contador y rechazo del miembro no final. La UI no deja proyectar operaciones
  no soportadas. También se restauró el orden de rechazo histórico de X/Y tras
  detectar que una consulta común prematura afectaba a su fixture.
- Verificación: **116 passed** en el bloque BDSP dirigido y **567 passed** en
  21,00 s en la suite completa. El writer alpha.82 queda pendiente de validación
  física; las capturas anteriores demuestran el contrato nativo, no una escritura
  iniciada por RoleRun.
- Validación física posterior del 2026-08-22: el usuario confirmó que el ciclo
  completo iniciado desde RoleRun funciona correctamente en SP 1.3.0 / Ryujinx:
  sexto miembro → PC y recuperación PC → sexto miembro. Quedan cerradas ambas
  direcciones de cola; no se extrapola esta validación a retirar un miembro
  intermedio.

# v0.2.2-alpha.81 — el swap Equipo↔PC BDSP alcanza el writer

## Causa raíz demostrada

- La prueba física de alpha.80 mostró Pidgeotto en el selector, de modo que la
  ocupación live de Caja 1:1 y el punto de entrada del modal ya eran correctos.
  Sin embargo, tras confirmar, Ryujinx mantuvo Slowpoke en la party.
- La traza contiene `pc-selector-live-start`, `pc-read` y
  `pc-selector-live-ready`, pero ningún evento de escritura. El fallo estaba por
  tanto entre la confirmación UI y el inicio del writer, no en RAM ni en el
  lector de cajas.
- `_prepare_pc_team_change()` creaba un `PendingTeamChange(operation="swap-party-box")`
  y solicitaba aplicación inmediata. La compuerta
  `_request_oras_live_auto_apply()` para BDSP solo admitía cambios de rol,
  movimiento y MT, y ejecutaba `continue` sin encolar el swap. Esto contradecía
  tanto `_oras_live_unsupported_changes()` como `BDSPLiveWriter`, que ya aceptan
  exclusivamente el intercambio 1↔1 demostrado.

## Corrección y regresión

- La compuerta BDSP admite ahora solo `PendingTeamChange` con operación
  `swap-party-box`. `party-to-box`, `box-to-party` y cualquier cambio de tamaño
  continúan cerrados.
- La regresión causal comprueba que un swap 1↔1 entra en el conjunto inmediato
  y programa el flush. Antes del arreglo falló con el conjunto vacío; después
  pasa junto con las pruebas del writer, readback y rollback.
- Verificación: **64 passed** en el bloque BDSP dirigido y **559 passed** en
  21,44 s en la suite completa.
- Validación física del 2026-08-22: el usuario confirmó que el intercambio se
  refleja correctamente dentro de Perla Reluciente 1.3.0 en Ryujinx. Esto cierra
  el swap 1↔1; no valida cambios de tamaño de party.

# v0.2.2-alpha.80 — ruta real de CAMBIAR CON PC conectada a RAM

## Primera divergencia demostrada

- Alpha.79 corrigió `open_pc_selector()`, pero la segunda prueba física mostró
  el mismo Slowpoke stale. La captura identifica otro modal: título `Cambiar
  Pokémon del equipo por uno del PC` y cabecera `POKÉMON QUE SALE DEL EQUIPO`.
- El botón de la tarjeta Equipo no llama `open_pc_selector()`: llama
  `_open_team_to_pc_swap_picker()`. Ese punto de entrada mantenía su propia
  lectura `self._read_pc_data(force=True)` y forzaba precisamente el save stale.
  La traza alpha.79 contiene `ui-initial-sync`, pero ningún
  `pc-selector-live-start`, `pc-selector-live-ready` ni write; por tanto la
  corrección anterior no participó en la reproducción.

## Corrección y regresión

- `_open_team_to_pc_swap_picker()` difiere ahora su modal mediante el mismo
  cargador de matriz viva y recibe el `SavePCData` materializado por RAM. No
  existe ninguna llamada al lector de save para decidir ocupación antes de abrir.
- La carga registra inicio, matriz lista con número de ocupados o error. Esto
  permite demostrar en la siguiente prueba qué ruta ejecutó la UI sin interpretar
  manualmente logs.
- Nueva regresión sobre el punto de entrada exacto del botón `CAMBIAR CON PC`:
  exige que solicite la matriz viva y hace fallar el test si intenta
  `_read_pc_data(force=True)`. **63 passed** en el bloque BDSP dirigido y
  **558 passed** en 21,62 s en la suite completa.

# v0.2.2-alpha.79 — selector PC BDSP gobernado por RAM viva

## Causa raíz demostrada

- En la reproducción física, PlayerWork publicó Slowpoke en la party y la
  matriz PC viva publicó Pidgeotto en Caja 1, slot 1. El `SaveData.bin`, sin
  guardar desde las operaciones posteriores, conservaba exactamente el estado
  opuesto: Pidgeotto en party y Slowpoke en Caja 1, slot 1.
- El selector contextual de `CAMBIAR CON PC` llamaba `_read_pc_data()` y abría
  inmediatamente la ventana con la ocupación del save. A diferencia de la página
  CAJAS PC y del selector de bajas, no esperaba una captura completa de RAM.
  Esta es la primera divergencia: reader/adapter vivos eran correctos; la UI los
  omitía antes de construir el selector. No llegó a ejecutarse el writer.

## Corrección

- Los selectores contextuales de los backends con matriz PC completa cargan
  ahora las cajas fuera del hilo Tk, materializan las 40×30 posiciones desde
  `read_pc()` y solo después abren la ventana. El save y capturas anteriores
  aportan únicamente nombres/nivel mediante identidad fuerte.
- Si la lectura RAM falla, el selector no se abre y RoleRun explica que se negó
  a mostrar la copia obsoleta. La matriz viva confirmada sustituye la caché y
  elimina overrides calculados contra el save anterior.
- Regresiones: una Caja 1:1 con Slowpoke en save y Pidgeotto en RAM debe mostrar
  Pidgeotto; el selector BDSP debe diferirse y no llamar primero al lector del
  archivo. **62 passed** en el bloque BDSP dirigido y **557 passed** en 21,55 s
  en la suite completa.

# v0.2.2-alpha.78 — intercambio Equipo ↔ PC BDSP 1↔1

- OpenDPR `5b0cb0c8...` fija `PokemonParam.DATASIZE=344`, el contrato
  `SerializedPokemonFull` y `PokemonParam.CopyFrom()` mediante serialización
  completa. Coincide con las estructuras físicas ya demostradas: cada slot de
  caja contiene un PB8 de 344 bytes y cada miembro de party conserva esos mismos
  bytes como core de 328 + calc de 16.
- `BDSPLiveWriter` admite exclusivamente `swap-party-box`: captura dos veces la
  party y las 40×30 cajas, exige coordenadas e identidades fuertes exactas y
  aplica el rol heredado al entrante antes de cifrarlo.
- La escritura es una transacción de tres regiones (party core, party calc y
  PB8 completo de caja), con precondición guest/host, readback byte a byte,
  verificación semántica de ambas identidades y del rol, y rollback verificado
  de las tres regiones.
- Añadir o retirar Pokémon continúa bloqueado: requiere demostrar por separado
  contador, compactación y representación vacía. Tampoco se crea una operación
  diferida si Ryujinx no está conectado.
- Regresiones nuevas: intercambio de los 344 bytes con HP/nivel/rol y rollback
  ante fallo en la tercera escritura. **60 passed** en el bloque BDSP dirigido
  y **555 passed** en 21,15 s en la suite completa. Pendiente de validación física.

# v0.2.2-alpha.77 — medallas BDSP desde SystemFlags vivos

- OpenDPR `5b0cb0c8...` demuestra que `FlagWork.BadgeCount()` suma exactamente
  `PlayerWork.SaveData.systemFlags[124..131]`; PKHeX 26.07.07 confirma la misma
  representación en `FlagWork8b`, sin trasladar offsets ni reglas desde 3DS.
- La lectura física SP 1.3.0 resolvió un `bool[1000]` estable, íntegramente
  booleano, con valores `[1,1,0,0,0,0,0,0]`. El total 2 coincide con los mismos
  flags del save y con `MYSTATUS.badge=2`. Evidencia:
  `diagnostics/manual/bdsp_alpha77_badge_system_flags_PROOF_20260822.json`.
- `BDSPBadgeReader` relee raíz y bloque, exige longitud 1000 y rechaza raíces,
  tamaños, valores o muestras inestables. No escribe RAM ni usa el save como
  fallback.
- `BDSPRealTimeAdapter` publica `badges=0..8`, procedencia live explícita y un
  diagnóstico separado. Si este carril falla, conserva la party válida.
- La primera divergencia de integración estaba en la rama UI específica BDSP:
  retornaba antes del compromiso común de medallas. Ahora procesa el valor
  absoluto antes de cualquier salida por batalla, herencia de rol o cambio de
  party. El contador manual queda deshabilitado para evitar dos autoridades.
- Regresiones dirigidas reader/Adapter/UI/Core: **107 passed**. Suite completa:
  **552 passed** en 21,06 s con `py -3.14 -m pytest -q`.
- Validación física del 2026-08-22: al abrir alpha.77, RoleRun sincronizó
  correctamente las dos medallas existentes (0→2). Esta prueba cubre reader,
  UI y Run en el arranque; queda pendiente obtener la siguiente medalla y
  comprobar el incremento 2→3 y OBS.

# v0.2.2-alpha.76 — herencia PC BDSP y ausencia válida de BattleProc

## Causas raíz demostradas

- La captura física alpha.75 conservada en
  `diagnostics/manual/bdsp_alpha75_pc_seventh_and_tm_battleproc_FAIL_20260822_210614.jsonl`
  contiene 439 snapshots y todos publican exactamente seis miembros. La
  transición de especies es `303,359,391,353,339,17` →
  `303,359,391,353,339,79`, también con seis slots. La séptima tarjeta no nacía
  en PlayerWork, el adapter ni el reconciliador PC: el branch UI de BDSP
  publicaba al entrante con su marcador anterior antes de heredar el rol del
  saliente; el maquetador representaba el conflicto de rol como tarjeta extra.
- Los 439 snapshots de esa sesión clasificaban batalla como desconocida con
  `BattleProc contiene un TypeInfo inválido`. Una lectura directa doble y
  estable sobre la misma sesión física, fuera de combate, devolvió
  `main+0x4E71D00 = 00 00 00 00 00 00 00 00`. Alpha.75 trataba la ausencia
  IL2CPP normal (`nullptr`) como puntero corrupto y abortaba el writer de MT
  antes de abrir el handle RW.

## Corrección segura

- BDSP calcula la herencia de rol contra las capturas completas `before/after`
  y escribe/verifica el marcador del entrante antes de publicar la nueva party.
  Mientras el writer esté ocupado o necesite reintentar, RoleRun conserva la
  última party confirmada, también al arrancar con el intercambio ya hecho. El
  grid común coloca conflictos/SIN ROL dentro de las seis celdas físicas, nunca
  en una séptima posición. La reconciliación PC conserva ambos estados como
  anclas y su barrera de solapamiento sigue rechazando capturas de instantes
  incompatibles.
- `BDSPBattleReader` interpreta únicamente un TypeInfo exactamente cero y
  estable como `BattleProc` no cargado. Cualquier valor no nulo fuera del rango
  guest, campos estáticos inválidos, flags inestables o una batalla activa
  continúan bloqueando la escritura. No se cambia ninguna dirección ni se añade
  fallback de HP.

## Verificación

- Regresiones específicas: TypeInfo nulo ausente, TypeInfo no nulo inválido,
  MT permitida fuera de combate sin debilitar el bloqueo RW, y herencia de rol
  antes de publicar tanto en monitor como en arranque y tanto si el writer
  arranca como si debe reintentar; conflicto de seis miembros sin séptima celda.
- Suite BDSP reader/writer/UI: **65 passed**. Suite completa: **542 passed** en
  21,12 s con `py -3.14 -m pytest -q`.
- Validación física comunicada por el usuario el 2026-08-22 tras ejecutar la
  prueba combinada indicada: enseñanza de MT fuera de combate y cambio 1↔1
  dentro del PC del juego funcionan correctamente; no reaparece la séptima
  posición y la herencia de rol queda aplicada.

# v0.2.2-alpha.75 — enseñanza de MT BDSP en tiempo real

## Causa y evidencia

- BDSP seguía mostrando `GUARDAR CAMBIOS` porque sus acciones de movimientos
  solo preparaban una modificación del save, aunque el reader ya demostraba la
  party runtime y el array vivo de mochila. La UI no tenía un writer BDSP al
  que entregar el lote.
- OpenDPR `5b0cb0c8...` demuestra que `PokemonParam` trabaja directamente con
  un core almacenado de 328 bytes y 16 bytes calculados, que
  `CoreParam.SetWaza` escribe ID, reinicia PP Ups y toma `basePP` de
  `WazaTable`, y que `PlayerWork.SaveData.saveItem` contiene registros
  `SaveItem` de 12 bytes cuya cantidad es el primer `int32`.
- Las cadenas, punteros, longitudes, PB8 y los 3.000 `SaveItem` usados por el
  writer son exactamente los readers SP 1.3.0 ya demostrados físicamente; no se
  incorpora ninguna dirección nueva ni se comparte estructura con 3DS.

## Implementación segura

- `BDSPLiveWriter` admite roles y movimientos de la party y trata una MT como
  una sola transacción PB8 + `SaveItem`: doble snapshot, identidad fuerte,
  ausencia de batalla, coincidencia de movimiento/cantidad, huella de sesión y
  bytes host/guest son precondiciones obligatorias.
- El writer recalcula checksum/cifrado PB8, establece los PP base de la ROM
  activa, consume exactamente una unidad y preserva flags, padding y orden del
  registro. Después verifica bytes host, bytes guest y significado mediante una
  lectura fresca. Cualquier fallo restaura y verifica todas las unidades ya
  intentadas.
- BDSP adopta el modelo de UI inmediato: desaparecen `DESCARTAR` y
  `GUARDAR CAMBIOS`; enseñar, sustituir o eliminar un movimiento y cambiar un
  rol solicitan el writer automáticamente. Equipo↔PC, roles de caja, progreso y
  utilidades generales permanecen bloqueados hasta tener su writer propio; no
  existe fallback silencioso al save.

## Verificación

- Regresiones específicas: cifrado roundtrip, enseñanza/PP/consumo atómico,
  conservación del resto de `SaveItem`, rechazo de cantidad stale, rollback
  inyectado tras fallar el segundo write y selección automática desde la UI.
- Suite completa: **533 passed** en 21,12 s con `py -3.14 -m pytest -q`.
- Pendiente de validación física: una enseñanza real en Perla Reluciente 1.3.0
  sobre Ryujinx, comprobando movimiento, PP y cantidad dentro del juego.

# v0.2.2-alpha.74 — acciones de movimientos y marcadores BDSP

## Causas raíz demostradas

- `SUSTITUIR` quedaba deshabilitado porque alpha.73 trasladó correctamente la
  lectura live de mochila fuera del render, pero `has_tm_replacement()` solo
  reconocía a Gen 7 como backend de carga diferida. Para BDSP, el `None`
  deliberado de `_tm_replacement_context()` se interpretaba como cero candidatos.
- `ELIMINAR ATAQUE` sí creaba un `PendingChange`, compactaba el moveset y
  repintaba la tarjeta. El siguiente snapshot BDSP sustituía `current_game` por
  la party física todavía sin guardar y eliminaba esa previsualización, por lo
  que la acción parecía no existir.
- La Run física `SP-Timper` conserva `role_marker_layout=1`. La lectura RAM
  demostró el layout histórico: Tanque en el segundo bit, Mago en el cuarto,
  Support en el quinto y Prisma en el sexto. La UI podía mostrar los nombres
  semánticos correctos, pero los bits no seguían aún el orden canónico solicitado.
- La regla de herencia de una sustitución 1↔1 solo se forzaba al final dentro de
  la rama live de Gen 7. Los flujos de save podían aceptar el rol previo del
  Pokémon de caja a pesar de que el comentario y el contrato declaraban que la
  plaza saliente era la autoridad.

## Corrección segura

- BDSP mantiene `SUSTITUIR` disponible mientras la conexión live esté validada;
  la mochila real continúa leyéndose en background únicamente después del clic.
- Cada snapshot BDSP fresco reaplica solo las ediciones `PendingChange` a su
  copia visual. No escribe RAM ni finge que el cambio ya esté confirmado.
- Toda sustitución preparada por RoleRun hereda sin diálogo el rol saliente y el
  SaveEngine escribe esa marca junto con el swap. Los cambios hechos dentro del
  PC del juego siguen en solo lectura: no se añade un writer RAM BDSP.
- Las Runs BDSP antiguas preparan los seis cambios físicos como un lote de save.
  Antes de reemplazar el archivo activo se relee la salida y se comprueba cada
  marcador con `layout=2`; solo después se persiste `role_marker_layout=2`.
  Backup, copia anterior, reemplazo atómico y rollback siguen a cargo de
  `SaveService`.
- Una prueba real del binario empaquetado sobre una salida temporal movió
  Shuppet/Support del quinto al sexto bit y el readback con layout 2 devolvió
  `Support`. No se modificó la partida activa durante esa prueba.

## Verificación

- Regresiones específicas: botón diferido BDSP, borrado preservado tras refresh,
  herencia frente a override y migración/readback del layout físico.
- Suite completa: **523 passed** en 20,96 s con `py -3.14 -m pytest -q`.
- No se modifica ningún reader, offset ni writer RAM.
- Validación física posterior en Perla Reluciente 1.3.0/Ryujinx: el usuario
  abrió `SUSTITUIR`, consumió una MT dentro del juego sin depender de un nuevo
  guardado y, al reabrir el selector, RoleRun mostró correctamente una unidad
  menos. Quedan pendientes únicamente las escrituras de movimientos/marcadores
  iniciadas desde RoleRun y su reinicio/readback dentro del juego.

# v0.2.2-alpha.73 — mochila/MT BDSP en RAM viva

## Estructura demostrada

- PKHeX-Plugins `c8e23a43...` fija para Perla Reluciente 1.3.0 la cadena de
  `PlayerWork.SaveData.saveItem`; OpenDPR `5b0cb0c8...` demuestra el layout
  `SaveItem`, sus campos y el tamaño de 3.000 registros; PKHeX `26.07.07`
  confirma que el ID de objeto es el índice del registro y sus reglas de
  cantidad/orden.
- En el Ryujinx físico, la cadena resolvió un array IL2CPP de exactamente 3.000
  entradas × 12 bytes. Dos lecturas completas fueron idénticas, SHA-256
  `30F879B5FF490058D4E84F9A937E6522E7CFDF75F2E4ECB5D57E330F3A73B77F`.
- Los 51 IDs presentes coincidieron con el save. La única diferencia de cantidad
  fue Antiparalizador (#22): el guardado conservaba 10 y la RAM viva 9, demostrando que
  el bloque activo distingue consumo posterior al último guardado. Las siete MT
  poseídas coincidieron exactamente en ID y cantidad.
- Evidencia compacta:
  `diagnostics/manual/bdsp_sp130_inventory_live_save_PROOF_20260822.json`.

## Integración segura

- `BDSPInventoryReader` vuelve a resolver la raíz en cada lectura, exige longitud
  3.000, doble lectura estable, cantidades 0–999, flags booleanos, padding,
  orden válido y relación cantidad/orden antes de publicar objetos.
- `BDSPRealTimeAdapter.read_tm_inventory()` devuelve siempre la RAM viva. El
  inventario del save solo se registra como testigo diagnóstico; una diferencia
  nunca activa fallback ni invalida una muestra live correcta.
- El selector de MT realiza la lectura en un worker, no durante el render de
  tarjetas ni en el hilo Tk. También descuenta las MT ya preparadas y todavía
  pendientes para impedir seleccionar dos veces una unidad.
- La tabla MT→movimiento continúa procediendo del `personal_masterdatas` efectivo
  de esta Run. BDSP sigue declarando `writes_enabled=false`: enseñar una MT desde
  RoleRun permanece como cambio de save pendiente hasta `GUARDAR CAMBIOS`.
- No se modifica ningún offset ni backend 3DS y no se habilita escritura RAM.

## Verificación

- Reader/Adapter/UI BDSP: **57 passed**; bloque afectado más consumidores Gen7:
  **112 passed**.
- Suite completa: **519 passed** en 21,12 s con `py -3.14 -m pytest -q`.
- Pendiente de validación física: abrir el selector, contrastar cantidades y
  consumir una MT dentro del juego para comprobar la transición sin guardar.

# v0.2.2-alpha.72 — seguimiento PC↔PC BDSP visible

## Frontera demostrada

- El flujo alpha.71 actualiza las cajas al cambiar la composición de party y al
  abrir CAJAS PC. Un movimiento entre dos cajas no produce `PARTY_CHANGED`; por
  tanto no existe ningún evento que vuelva a solicitar la matriz mientras la
  pestaña permanece abierta.
- No hace falta una dirección nueva: `BDSPBoxReader` ya demuestra y lee la matriz
  completa 40×30 con doble lectura y checksum.

## Implementación segura

- Solo BDSP programa una lectura cada 2,5 segundos mientras la página CAJAS PC
  está visible, la conexión live sigue activa y la ventana principal no está
  minimizada/retirada ni sustituida por la barra flotante.
- Cada tick nace después de terminar el anterior. Si ya hay una conciliación en
  curso, espera; nunca acumula workers ni lecturas sobre Ryujinx.
- Salir de la pestaña, cambiar de Run o limpiar la sesión cancela el timer. Un
  error detiene el bucle para no castigar el emulador ni repetir avisos.
- La UI compara la proyección completa contra la anterior y solo se repinta si
  cambiaron posiciones o datos. La traza añade `pc-poll` y el campo `changed`.
- BDSP continúa en solo lectura; no se modifican readers, direcciones, writers ni
  otros backends.

## Verificación

- Una regresión mueve una identidad fuerte de caja 1/slot 1 a caja 2/slot 2 y
  exige vacío/origen, destino, nivel conservado y un solo repintado. Una segunda
  captura idéntica debe producir `changed=false` y cero repintados adicionales.
- Otra regresión demuestra activación solo en la página PC, reintento sin solape y
  cancelación al abandonar la vista.
- Batería BDSP: **62 passed** en 0,86 s. Consumidores PC comunes dirigidos:
  **36 passed** en 1,00 s.
- Suite completa: **510 passed** en 20,94 s con `py -3.14 -m pytest -q`.
- Validado físicamente por el usuario en Perla Reluciente 1.3.0 sobre Ryujinx
  1.3.3 con GDB desactivado. Con la party estable en seis miembros, Aipom
  (`species 190`) pasó de caja 1/slot 2 a caja 2/slot 2.
- La traza registra una sola conciliación `changed=true`, con un override y un
  vacío, seguida por siete lecturas `changed=false`. Esto confirma tanto la
  detección PC↔PC como la ausencia de repintados continuos en reposo.
- Control:
  `diagnostics/manual/bdsp_alpha72_pc_to_pc_poll_SUCCESS_20260822_191534.jsonl`,
  SHA-256
  `1A399AA247275C9A33085327628076D0FD8B64BEBE2107E81370223198101FDD`.

# v0.2.2-alpha.71 — conciliación inmediata de depósitos BDSP

## Causa raíz demostrada

- La traza física alpha.70 registra correctamente las dos transiciones de party:
  `6→5` en la secuencia 63 y `5→4` en la 160. La matriz PC también lee los
  dos depósitos: 11→12→13 ocupados, con Shuppet en caja 1/slot 1 y Monferno
  en caja 1/slot 12.
- Sin embargo, las conciliaciones PC posteriores recibieron `before/after=5/5`
  y `4/4`. No fueron provocadas por la transición: ocurrieron al volver a entrar
  en la pestaña CAJAS PC, cuando la party anterior ya se había perdido.
- La primera divergencia estaba en la rama BDSP de
  `_finish_oras_live_reconciliation`: publicaba la party nueva y retornaba sin
  programar la conciliación PC que sí ejecutan los otros backends ante
  `party_changed`. La vista quedaba stale hasta navegar y el refresco tardío no
  podía usar al saliente como ancla de nivel; por contrato seguro, el PB8 de
  caja se mostraba entonces con nivel desconocido `0`.
- Evidencia fuente:
  `diagnostics/manual/bdsp_alpha70_pc_refresh_level_FAIL_20260822.jsonl`,
  SHA-256
  `ABA76FE8028E969A6AA6B9E4854AE86265AAF805BE5B58DC88786DB82235E33B`.

## Corrección

- Solo la rama BDSP conserva ahora el estado anterior y el nuevo al detectar un
  cambio de composición, publica primero la party actual y programa después la
  lectura PC con ambos lados de la transición.
- El reconciliador puede así usar la identidad fuerte del miembro saliente para
  conservar su nivel y repintar la caja al terminar la lectura, sin depender de
  cambiar de pestaña.
- La traza incorpora `pc-reconcile-scheduled` con tipo de refresco, conteos de
  entrada/salida y tamaños antes/después. No registra identidades crudas.
- No se cambia el parser PB8, no se inventa un nivel desde experiencia y no se
  habilita ninguna escritura BDSP.

## Verificación

- La regresión causal exige que un depósito entregue al reconciliador la party
  `2→1`, conserve el nivel 12 del saliente y programe la lectura después de
  publicar la party nueva.
- Pruebas BDSP completas: **60 passed** en 0,75 s; el subconjunto UI/adapter
  relacionado dio **27 passed** en 0,86 s.
- Suite completa: **508 passed** en 21,04 s con `py -3.14 -m pytest -q`.
- Validado físicamente por el usuario en Perla Reluciente 1.3.0 sobre Ryujinx
  1.3.3 con GDB desactivado. Los depósitos aparecieron sin cambiar de pestaña y
  las recuperaciones volvieron al equipo correctamente. La traza registra seis
  transiciones directas de composición (`4→3`, `3→4`, `4→5`, `5→4`, `4→5`
  y `5→6`), todas seguidas por `pc-read` y `pc-reconcile-applied` con los
  conteos antes/después correctos.
- Control:
  `diagnostics/manual/bdsp_alpha71_pc_roundtrip_SUCCESS_20260822_190522.jsonl`,
  SHA-256
  `7662BD363815B8EF273008AB4CC69E48500549175F11AECB76E0FAA60AF4AC71`.
- El alcance validado es exclusivamente juego→RoleRun de solo lectura; los
  movimientos iniciados desde RoleRun continúan cerrados.

# v0.2.2-alpha.70 — PC BDSP de solo lectura integrado

## Base demostrada

- No se añade ninguna dirección RAM. Se utiliza la cadena SP 1.3.0 de
  `BDSPBoxReader`, ya validada físicamente como 40 cajas × 30 slots y
  contrastada con los 11 PB8 ocupados del save por posición, especie, PID,
  TID, SID y checksum.
- El parser de caja conserva ahora forma, apodo, objeto, habilidad,
  movimientos/PP, huevo y marcas de rol. El nivel no se inventa: como no forma
  parte del PB8 almacenado, solo se conserva desde una ancla de identidad fuerte
  única.

## Integración

- `BDSPRealTimeAdapter.read_pc()` valida obligatoriamente la geometría 40×30,
  lee toda la matriz con doble lectura/checksum y publica posiciones e
  identidades fuertes al reconciliador común. Continúa declarando
  `writes_enabled=false` y no incorpora ningún writer.
- La lectura completa se serializa con el monitor BDSP para impedir que una
  captura PC de 1.200 slots se mezcle con otra captura o con un reset del
  handle Win32.
- Abrir CAJAS PC o cambiar la composición del equipo programa el trabajo fuera
  del hilo Tk. La barrera de coherencia rechaza una identidad que aparezca a la
  vez en party y PC, conserva la última vista y repite la lectura.
- La traza registra una huella SHA-256 truncada de cada identidad, nunca los
  PID/TID/SID crudos, y las fronteras `pc-reconcile-*`. Un fallo mantiene la
  vista anterior y no se presenta como PC vacío.
- Writers, PC RoleRun→juego, inventario/MT y progreso BDSP siguen cerrados.

## Verificación

- Sonda integrada sobre el Ryujinx físico: PID 4016, matriz completa con 11
  ocupados, 1,459 s y `writes_enabled=false`.
- Evidencia: `diagnostics/manual/bdsp_alpha70_pc_read_probe_PROOF_20260822.json`.
- Regresiones BDSP dirigidas: **45 passed** en 0,66 s.
- Batería PC/BDSP y consumidores comunes: **145 passed** en 12,29 s.
- Suite completa: **507 passed** en 21,09 s con `py -3.14 -m pytest -q`.
- Equipo↔PC queda pendiente de una prueba física mínima en alpha.70.

# v0.2.2-alpha.69 — KO BDSP sincronizado con la presentación visible

## Causa raíz demostrada

- La traza física alpha.68 conserva el mismo Shuppet y PokeID durante todo el
  golpe. El HP lógico de `BTL_POKEPARAM.CORE_PARAM.hp` pasó `12→0` en la
  secuencia 586 (`1787415029.213`), y RoleRun comprometió la muerte 12 ms
  después.
- La ventana jugador de `BattleViewUISystem` seguía mostrando `12/58`. No
  publicó el objetivo visible `0` con `HpBar.IsAnimation=true` hasta la
  secuencia 609 (`1787415035.380`), 6,167 s después del cero lógico, y no
  terminó la animación a `0/58` hasta la secuencia 611
  (`1787415035.903`).
- La primera divergencia estaba en `BDSPRealTimeAdapter`: convertía el HP
  lógico de resolución del turno directamente en `health_game`, aunque la lane
  visible validada del mismo PokeID demostraba que el juego aún no había
  presentado el KO.
- Evidencia fuente preservada:
  `diagnostics/manual/bdsp_alpha68_visible_hp_timing_FAIL_20260822.jsonl`,
  SHA-256
  `C9211DF2C2C341B50C30852F7670FA7381D39E857B97297C80B4BAB7F922A72F`;
  prueba causal resumida en
  `diagnostics/manual/bdsp_alpha68_visible_hp_timing_ROOT_20260822.json`.

## Corrección

- Solo el adapter BDSP retiene el último HP positivo publicado cuando el
  carril lógico llega anticipadamente a cero. El cero se publica después de
  observar, para una ventana jugador única con el mismo PokeID y HP máximo, la
  secuencia visible `0 + animación activa` seguida de `0 + animación terminada`.
- No se usa un retardo fijo ni se altera el reader lógico. Una presentación
  ausente o ambigua mantiene el dato positivo en lugar de inventar el final;
  la convergencia posterior de `PlayerWork` conserva el fallback seguro.
- Un primer snapshot que ya contiene HP 0 sigue siendo baseline y no crea una
  muerte retrospectiva. Los cambios de identidad de party limpian los testigos
  visuales anteriores.
- No se modifican backends 3DS, writers, PC, inventario ni progreso. BDSP
  continúa estrictamente en modo de solo lectura.

## Verificación

- Regresión causal: reproduce `12` visible mientras el HP lógico ya es `0` y
  exige la secuencia publicada `[12, 12, 12, 0]`; otra prueba cubre la ausencia
  segura de la lane visual.
- Batería dirigida BDSP: **41 passed** en 0,59 s.
- Suite completa: **503 passed** en 20,31 s con `py -3.14 -m pytest -q`.
- Validada físicamente por el usuario en Perla Reluciente 1.3.0 sobre Ryujinx
  1.3.3, con GDB desactivado. El cero lógico quedó retenido en 6 HP; las
  secuencias 498–499 observaron la barra animando a cero y la 500 publicó el
  cero solo tras `IsAnimation=false`. RoleRun actuó entonces una sola vez y el
  selector postcombate continuó funcionando.
- Control preservado:
  `diagnostics/manual/bdsp_alpha69_visible_ko_sync_SUCCESS_20260822.jsonl`,
  SHA-256
  `855B56E05D904B0762D946C139DF871624DCD1A607A4CD9C957A90A7A1D2C151`.
- Una segunda prueba física reordenó los dos primeros miembros desde el juego.
  La traza registra `353,391,… → 391,353,…` en las secuencias 886–893 y la
  vuelta al orden original; el usuario confirmó que identidad, icono y rol se
  mantuvieron correctamente. Control:
  `diagnostics/manual/bdsp_alpha69_party_reorder_SUCCESS_20260822.jsonl`,
  SHA-256
  `D037D876FDBB464D2D1F444A54C202647F4119DBAA12E6A09B7CB006DEAD5672`.

# v0.2.2-alpha.68 — diagnóstico del HP visible de BDSP

## Validación física de alpha.67

- El usuario confirma que, después de guardar y combatir, RoleRun restó una
  vida, retiró el icono y mostró correctamente el selector tras el combate.
- La traza demuestra cuatro recargas del watcher antes del KO sin detener el
  monitor. Hubo una sola transición `12→0` y un solo compromiso de muerte.
- La detección se adelantó visualmente: RoleRun cambió al inicio del turno,
  antes de que el KO apareciera en pantalla. Esto no invalida el reader ni el
  arreglo del watcher, pero abre una frontera de presentación distinta.
- Traza preservada con SHA-256
  `F90025A11E43FEE750B2DA399F666B56EFCFD55A7FDC4A8F7AC7FED5C8934487`.

## Instrumentación alpha.68

- El source exacto y los metadatos IL2CPP vivos demuestran que BDSP separa el
  HP lógico `BTL_POKEPARAM.CORE_PARAM.hp` de cuatro `BUIStatusWindow` de UI.
- Un barrido acotado del bloque TypeInfo encontró
  `BattleViewUISystem` en `main+0x04E70E40`. Nombre de clase, geometría de
  cuatro ventanas y offsets se validan por identidad IL2CPP antes de publicar.
- La traza registra ahora HP presentado, PokeID, pertenencia al jugador,
  `needHpApply` e `HpBar.IsAnimation`. Esta lane es solo diagnóstica: alpha.68
  no retrasa ni altera todavía el compromiso de muerte.
- Evidencia:
  `diagnostics/manual/bdsp_alpha67_visible_hp_timing_PROOF_20260822.json`.
- Regresiones dirigidas BDSP: **38 passed**.
- Suite completa: **500 passed** en 20,46 s con `py -3.14 -m pytest -q`.

# v0.2.2-alpha.67 — rearmado realtime tras recargar el save

## Reproducción física y causa raíz

- La prueba integrada de alpha.66 no registró el KO ni al terminar el combate.
  Sin embargo, una captura independiente contra el mismo Ryujinx todavía
  abierto leyó correctamente los seis miembros y al primero a `0/58`.
- La introspección de solo lectura del proceso que sufrió el fallo mostró
  `live_active=true`, pero ningún timer, captura o baseline activo:
  `monitor_after_id=null`, `last_snapshot=null` y `health_snapshot=null`.
- La primera divergencia estaba en `_reload_from_watched_save()`. El watcher
  sustituía la vista viva por el `main`, cancelaba la reconciliación y reiniciaba
  el Core; después solo rearmaba el monitor si el backend era exactamente ORAS.
  BDSP quedaba anunciado como conectado, pero no volvía a leer RAM.
- Evidencia canónica:
  `diagnostics/manual/bdsp_alpha66_save_watcher_monitor_stopped_PROOF_20260822.json`.

## Corrección y diagnóstico

- El watcher rearma ahora cualquier backend declarado expresamente en
  `REALTIME_READ_GAME_KEYS`. Los juegos sin backend realtime siguen excluidos.
- No se han cambiado direcciones, parsers, mapeo de batalla, detección de
  transiciones ni escritores. BDSP continúa siendo estrictamente de lectura.
- La traza integrada `bdsp_realtime_trace_latest.jsonl` registra snapshots y
  las fronteras UI mínimas —sin bytes crudos— para demostrar en la próxima
  prueba que el reader sigue armado tras una recarga del save.
- Regresiones dirigidas Adapter/UI/watcher y consumidores comunes:
  **42 passed**.
- Suite completa: **496 passed** en 24,65 s con `py -3.14 -m pytest -q`
  (Windows).
- La corrección queda pendiente de validación física en Perla Reluciente 1.3.0
  sobre Ryujinx 1.3.3; no se declara cerrada antes de esa prueba.

# v0.2.2-alpha.66 — party y KO BDSP en el Real-Time Core

- Identificado el entorno real: Perla Reluciente 1.3.0,
  `010018E011D92000`, mod `Output` solo `romfs` y Ryujinx
  `HostMappedUnsafe`.
- Añadido `RyujinxGDBClient` de solo lectura: descubre la configuración, obtiene
  Title ID/módulo `main`, lee memoria invitada y resuelve cadenas sin
  cachearlas. Acepta tanto el formato nuevo con Process/PID como la respuesta
  real de Ryujinx 1.3.3, que identifica `SwitchPlayer.nss` sin esa línea.
- GDB queda limitado a `RyujinxGDBDiagnosticBridge`. El transporte permanente
  `RyujinxBridge` usa ahora HostMapped con permisos Win32 exclusivamente de
  consulta/lectura, presupuesto acotado y rechazo de huellas ambiguas.
- Añadido `BDSPBoxReader` para la cadena SP 1.3.0 demostrada: doble lectura,
  40×30 slots, longitud PB8, descifrado e integridad por checksum.
- Añadido `BDSPPartyReader` para el `PlayerWork._playerParty` runtime demostrado:
  conteo 1–6, array de seis, punteros únicos, PB8/cálculos estables, checksum,
  identidad, forma, apodo, objeto, habilidad, movimientos/PP, marcas, huevo,
  nivel y HP. Los seis registros se contrastaron con `PKHeX.Core 26.7.7` y el
  save real. La copia serializada `SaveData.playerParty` queda expresamente
  rechazada como autoridad live.
- Añadido `BDSPBattleReader` para la lane del cliente jugador de `BattleProc`:
  lifecycle propio, seis filas `BTL_POKEPARAM`, HP y mapeo `PokeID` 0–5. Una
  desaparición concurrente se rechaza y nunca se publica como KO o party vacía.
- La prueba física no letal demostró la primera divergencia real: dentro de
  batalla `BTL_PARTY` publicó `58/67` mientras la party normal seguía en
  `67/67`; al huir, la party normal convergió y 608 ms después desapareció el
  objeto de batalla.
- La prueba física posterior demostró el KO `7/21→0/21`, el retraso de
  PlayerWork y la reordenación de filas al elegir sustituto. Shuppet pasó a fila
  1 conservando `party_index=1`; Skitty quedó en fila 2 con `party_index=0`.
- Añadido y registrado `BDSPRealTimeAdapter`: publica party y HP de batalla en
  Core/UI, valida el mapeo por PokeID + especie + nivel + HP máximo, mantiene el
  lane de batalla opcional y establece baseline al conectar. La UI reutiliza el
  flujo común de compromiso de muertes sin usar nunca los HP stale de
  PlayerWork durante una batalla conocida.
- BDSP permanece fuera de todas las rutas de escritura automática. No se han
  habilitado writers, PC, MT, inventario ni progreso realtime.
- Incorporado el catálogo español de especies 0..493 procedente del mismo tag
  PKHeX `26.07.07` que usa el motor distribuido.
- La cadena pública de cajas SP 1.3.0 queda demostrada en la partida real: 40
  cajas×30 objetos y coincidencia exacta de los 11 PB8 ocupados con el save en
  posición, especie, PID, TID, SID y checksum. No se extrapola a party, HP o
  escritura.
- La comparación física A/B demuestra que el GDB Stub activa el modo global de
  depuración de ARMeilleure y degrada el gameplay aunque no haya cliente. Queda
  rechazado como requisito de uso normal.
- Tras reiniciar con GDB apagado, HostMapped redescubrió una dirección de sesión
  distinta y leyó 11 PB8 ocupados y 1.189 vacíos, todos con checksum válido. El
  componente de producción verificó Title ID/revisión desde la ventana activa y
  repitió la captura en 1,543 s sin escrituras.
- Regresiones HostMapped/BDSP/GDB/Adapter/UI dirigidas: **41 passed**.
- Suite completa: **489 passed** en 20,75 s con `python -m pytest -q`
  (Windows, entorno Python aislado).

# v0.2.2-alpha.65 — USUM consume la mochila viva ya demostrada

## Validación física

- Validado por el usuario en UltraSol/Azahar el 2026-08-22: al abrir alpha.65
  con Lizastal Z ya presente, RoleRun detectó el primer Kahuna e incrementó el
  contador visible de 0 a 1.
- Quedan pendientes las validaciones sucesivas 1→2, 2→3 y 3→4; esta prueba no
  se extrapola por sí sola a los otros tres Kahunas.

## Reproducción física y primera divergencia

- Tras derrotar a Kaudan/Hala, RoleRun alpha.63 mantuvo `medallas=0`.
- Dos lecturas RPC estables de ItemsOffset `0x33011934` contienen Normastal Z
  `807` y Lizastal Z `813`; `parse_usum_zcrystal_keys()` acepta la estructura y
  `count_usum_kahuna_badges()` devuelve 1.
- El último `main` contiene solo `807` y devuelve 0. Los diagnósticos de las
  13:34 demuestran además que ItemsOffset seguía aceptado estructuralmente.
- `read_tm_inventory_for_game()` publica esa prueba en
  `_tm_guest_inventory_anchor`. `read_kahuna_badges_for_game()` consultaba acto
  seguido `_utility_block_cache["items"]`, caché host+guest distinta que la ruta
  de solo lectura no rellena. Esa es la primera divergencia: el valor live 1 se
  descartaba antes del Adapter y se sustituía por el 0 del save.

## Corregido

- El lector usa la ancla guest que acaba de demostrar, valida de nuevo el bloque
  contra el testigo y publica `Z-Crystals vivos · referencia ItemsOffset revalidada`.
- En ticks posteriores hace doble lectura estable de la misma ancla y vuelve a
  validar estructura antes de conservarla.
- Se mantiene la caché host+guest como ruta separada para utilidades que sí
  escriben. No se mezcla una prueba de lectura con autoridad de escritura.
- No se añaden offsets, no se infiere progreso por combate y no se escribe RAM.

## Evidencia y regresiones

- Evidencia canónica:
  `diagnostics/manual/usum_alpha63_hala_badge_missing_FAIL_20260822_133454_probe.json`.
- La regresión causal devolvía 0 antes del arreglo y 1 después; otra regresión
  confirma que Adapter/snapshot publican el 1 con procedencia live.
- Una sonda integrada de solo lectura sobre la RAM física actual devolvió 1 en
  dos muestras consecutivas mediante la ruta corregida.
- Regresiones de progreso, adapter y Core: **67 passed**.
- Suite completa: **448 passed** en 20,37 s con `python -m pytest -q`
  (Windows, entorno Python aislado).

# v0.2.2-alpha.64 — auditoría común 3DS y diagnóstico de Kahunas USUM

## Validación física recibida

- El usuario confirmó en UltraSol que el carril alpha.59–62 detecta dos muertes
  y que alpha.63 abre los dos selectores consecutivamente sin minimizar ni
  restaurar RoleRun. Esa validación queda registrada en `docs/CURRENT_STATE.md`.

## Causas raíz demostradas y corregidas

- La autoridad común de progreso ignoraba `badge_source`. Un `main` sin guardar
  podía sustituir temporalmente un valor live más nuevo y reducir medallas o
  Kahunas. El fallback de save puede recuperar hacia arriba, pero solo una fuente
  RAM explícitamente validada puede reducir tras una carga de state.
- Los writers de utilidades SM/USUM añadían el campo a la transacción después
  del readback. Si este fallaba, el rollback inmediato podía ser ignorado y aun
  así el mensaje afirmaba restauración. Ahora el intento se registra antes del
  write y cualquier salida verifica rollback host y guest.
- El parser de cajas USUM usaba `personal_sm`. PKHeX contiene un recurso distinto
  `personal_uu`; la diferencia se demuestra con Blacephalon #806, cuyo nivel se
  calculaba con una curva perteneciente a un registro de forma de SM. USUM usa
  ahora `pkhex_personal_uu.bin`, extraído del mismo PKHeX.Core distribuido.

## Diagnóstico y documentación

- USUM conserva `usum_kahuna_progress_trace_latest.jsonl` con transiciones del
  valor, procedencia live/fallback, proceso, Title ID y base de party. No registra
  Pokémon ni contenido de mochila.
- La ayuda realtime ya describe las capacidades actuales y no el estado antiguo
  de recuperación alpha.10.
- `docs/3DS_BACKEND_AUDIT.md` documenta qué cambios son comunes y por qué las
  bases, filas y flags específicos de USUM no se propagaron a otros juegos.

## Validación

- Regresiones causales añadidas para progreso de los cuatro backends, rollback
  de utilidades en SM/USUM, tabla Personal USUM y traza de Kahunas.
- Batería focal de UI/progreso/SM/USUM/PC Gen 7: **123 passed**.
- Suite completa: **446 passed** en 20,46 s con `python -m pytest -q`
  (Windows, entorno Python aislado).
- La detección automática de Kahunas USUM permanece pendiente de la prueba
  física mínima descrita en `README_v0.2.2-alpha.64.txt`.

# v0.2.2-alpha.63 — cola de selectores para varias bajas

## Causa raíz demostrada

- La prueba física alpha.62 conservada como
  `diagnostics/manual/usum_alpha62_two_pending_second_picker_delayed_PROOF_20260822_131803_trace.jsonl`
  registra los KO de Porygon y Registeel, su convergencia a PartyData y el
  `battle-end` por `observed-ko-converged-to-party`. Queda así validado
  físicamente el final de combate del reader alpha.62.
- `config.json` e `history.json` de la misma ejecución demuestran que ambas
  muertes fueron comprometidas y quedaron listas para sustitución. El primer
  selector se marcó a las 13:14:01; el segundo, a las 13:14:52, justo después
  de minimizar y restaurar RoleRun.
- Al cerrar el primer selector, `close_picker()` destruía la ventana pero no
  programaba el siguiente pendiente. `_on_main_map()` sí programa esa revisión,
  por lo que restaurar la ventana principal era el evento accidental que hacía
  aparecer el segundo selector. La primera divergencia está en la cola de UI,
  después de reader, snapshot, muerte y final de combate.
- Si el usuario elegía un sustituto en el primer selector, una revisión que
  coincidiera con la escritura en curso también se perdía porque
  `_maybe_open_pending_faint_picker()` retornaba sin reprogramarse.

## Corregido

- Cerrar un selector programa la revisión del siguiente KO listo sin depender
  de minimizar/restaurar la aplicación.
- Si la sustitución anterior sigue aplicándose, la cola se reintenta después;
  no abre dos modales ni solapa dos escrituras.
- Se añaden dos regresiones causales. Ambas fallaban antes del arreglo y cubren
  el cierre del primer selector y la espera por una sustitución en curso.
- No se modifican lectores RAM, detección/compromiso de muertes, RunService,
  PC, writers ni ningún backend de juego.

## Validación

- Regresiones causales: **2 passed**.
- Selector, barra, RunService y ciclo USUM alpha.59–62: **37 passed**.
- Suite completa: **428 passed** en 19,95 s con `python -m pytest -q`
  (Windows, Python 3.13.14, pytest 9.1.1, entorno aislado).
- Validación física completada en UltraSol: tras dos KO, los dos selectores se
  encadenaron correctamente sin minimizar ni restaurar RoleRun.

# v0.2.2-alpha.62 — USUM: final de combate demostrado por convergencia de party

## Causa raíz demostrada

- La ejecución física alpha.61 preservada como
  `diagnostics/manual/usum_alpha61_two_kos_picker_missing_FAIL_20260822_035426.jsonl`
  registra Porygon/slot 4 a 0 HP en la secuencia 12 y Eevee/slot 2 en la
  secuencia 46. El historial confirma ambos compromisos a las 03:53:08 y
  03:53:21, con `vidas` 6→5→4.
- A las 03:53:28 los flags pasan a `0x00040005/6`. Alpha.61 conserva las dos
  bajas con `battle_seen=true`, pero deja `battle_ended=false` y
  `battle_exit_samples=0`; el reader nunca publica `state="none"` y la UI no
  recibe autorización para abrir el selector.
- Sin reiniciar juego ni emulador, una lectura RPC posterior ya en overworld
  mantiene exactamente `0x00040005/6`, mientras PartyData validada contiene
  Porygon=0 y Eevee=0. La captura alpha.60 del estado de sustitución forzada
  conservaba ambos a 19 en PartyData aunque las filas de batalla estaban a 0.
  Por tanto el par idle representa dos estados distintos y no puede decidir el
  final por sí solo.
- La fuente pública específica, USUMCheatMenu commit
  `09c4c1b98f3cd9b88c4a537c5e22c249c72edb0e`, solo define «en batalla» como
  `0x30000158 == 0x00040001`; no documenta que `0x00040000/1` sea un terminal
  obligatorio. Alpha.60 había elevado una observación de control a contrato.

## Corregido

- `USUMLiveReader` conserva por proceso exclusivamente transiciones Displayed
  HP `>0→0` de filas ya validadas y enlazadas a identidad PK7 fuerte.
- Ante `0x00040005/6`, la batalla continúa suspendida mientras PartyData no haya
  convergido. Solo se publica `none` cuando todos los KO observados del episodio
  aparecen también a 0 en PartyData con la misma identidad.
- La traza añade `battle-idle-evidence` y un motivo explícito de `battle-end`,
  de modo que la distinción queda auditable sin direcciones ni controles
  manuales nuevos.
- No se modifica UI, RunService, LivePartyWatch, PC, writers, Sol/Luna ni otros
  backends. La compuerta existente recibe de nuevo sus dos muestras `none` y
  abre el selector por su flujo normal.

## Validación

- La regresión causal falla en alpha.61: **1 failed, 1 passed**.
- Regresión alpha.62 + ciclo/identidad alpha.60–61: **8 passed**.
- Flujo reader→RunService→selector/barra: **38 passed**.
- Batería USUM completa: **45 passed**.
- Suite completa: **426 passed** en 19,90 s con `python -m pytest -q`
  (Windows, Python 3.13.14, pytest 9.1.1, entorno aislado).
- El selector postcombate queda pendiente de validación física en UltraSol.

# v0.2.2-alpha.61 — USUM: identidad PK7 real de las filas de batalla

## Causa raíz demostrada

- La reproducción física alpha.60 preservada como
  `diagnostics/manual/usum_alpha60_restart_changed_active_FAIL_20260822_033047.jsonl`
  empieza con Eevee y Porygon a 19/19. La tabla HP está en orden
  `Porygon,Eevee,Kangaskhan,Registeel,Tsareena,Carnivine`; Max, Displayed y
  Actual no contienen información suficiente para distinguir sus dos primeras
  filas. Alpha.60 las rechazó correctamente como ambiguas, pero por ello nunca
  publicó ninguno de sus ceros a `LivePartyWatch`.
- Una lectura RPC acotada del mismo proceso demostró seis PK7 stored válidos en
  `0x3254EE60 + 0x104*N`, estructura documentada por USUMCheatMenu como
  `PARTY ON BATTLE INITIAL DATA`. Sus identidades fuertes coinciden exactamente
  con las seis filas HP y demuestran que row 1 es Porygon/party slot 4.
- La misma traza confirma que `0x00040005/6` produjo `battle-suspend`, no
  `battle-end`: el ciclo de selección forzada de alpha.60 no era la causa del
  segundo fallo.

## Corregido

- `USUMLiveReader` lee dos veces y valida por checksum el PK7 de cada fila, y
  vincula la salud mediante `(species, PID, TID, SID)` antes de publicar HP.
- La identidad ausente, corrupta o duplicada no se adivina. Las filas demostradas
  por un Max único siguen operativas sin contaminar las ambiguas.
- El resolvedor FCRAM de la base HP valida ahora el multiconjunto completo de
  Max HP. Ya no exige que el vector esté en orden de party, premisa falsada por
  las reproducciones físicas.
- La traza incorpora la identidad de fila, la identidad PK7 de party y la
  procedencia de la doble lectura. No se escribe RAM.
- No se modifican SM, UI, `LivePartyWatch`, RunService, PC, writers, movimientos
  ni progresión.

## Validación

- Las dos regresiones alpha.61 fallan sobre la lógica alpha.60: KO de Porygon con
  dos miembros a 19/19 y resolución host de un vector Max permutado.
- Regresiones de batalla alpha.57–61: **13 passed**.
- Batería USUM completa: **44 passed**.
- Suite completa: **424 passed** en 19,86 s con `python -m pytest -q`
  (Python 3.13.14, pytest 9.1.1, entorno aislado Windows).
- La corrección realtime queda pendiente de validación física en UltraSol.

# v0.2.2-alpha.60 — USUM: filas permutadas y selección forzada

## Causas raíz demostradas

- La traza física alpha.59 preservada como
  `diagnostics/manual/usum_alpha59_changed_lead_FAIL_20260822_030629.jsonl`
  mantiene la base nominal correcta, pero al elegir el slot 4 como activo la
  tabla de batalla queda ordenada `4,2,3,1,5,6`. RoleRun seguía imponiendo
  `battle row N == party slot N`; descartó las filas 1 y 4 y sustituyó el HP de
  Porygon por el PartyData retrasado. Su `Displayed/Actual=0` apareció a las
  03:02:57, pero el compromiso solo llegó por overworld a las 03:05:30.
- Esa misma ejecución demuestra un segundo fallo independiente. Durante la
  selección forzada del siguiente Pokémon, los flags pasan directamente de
  `0x00040001/3` a `0x00040005/6`. RoleRun lo trataba como fin de batalla; dos
  muestras después marcó `battle_ended` y abrió el selector propio. Los finales
  físicos de control preservados pasan por el par terminal `0x00040000/1`.

## Corregido

- `USUMLiveReader` resuelve ahora una correspondencia inyectiva party↔fila por
  el vector completo de Max HP. Cuando Max HP se repite, solo desambigua si
  Displayed y Actual coinciden ambos con el HP de PartyData; si quedan varias
  soluciones, publica únicamente las filas comunes a todas y no adivina.
- Un mapeo completo demostrado se cachea durante el tramo de combate y se
  invalida al suspender/reanudar, terminar o cambiar la geometría.
- El ciclo USUM distingue activo (`0x00040001/3`), suspendido en selección
  forzada (`0x00040005/6` después de combate observado) y terminado
  (`0x00040000/1`). La suspensión sigue publicándose como `state="battle"`, sin
  HP, para mantener cerrada la compuerta de sustitución de la UI.
- Las fases de carga con flag primario activo pero fase distinta de 3 quedan
  como estado desconocido y ya no generan falsos episodios de batalla.
- La traza incorpora `mapped_party_slot`, `battle-suspend` y `battle-resume`.
  No se han añadido direcciones, escrituras ni cambios a SM u otros backends.

## Validación

- Regresiones nuevas: permutación física `4,2,3,1,5,6` hasta
  `detect_fainted_transitions(slot=4)`, rechazo de filas duplicadas ambiguas,
  ciclo activo→suspendido→activo→terminal y falso activo en fase de carga.
- Pruebas focales reader/RunService: **15 passed**.
- Batería USUM completa: **41 passed**.
- Suite completa: **422 passed** en 20,34 s con `python -m pytest -q`
  (Python 3.13.14, pytest 9.1.1, entorno aislado Windows).
- La corrección realtime queda pendiente de validación física en UltraSol.

# v0.2.2-alpha.59 — USUM: tabla de HP resuelta por evidencia runtime

## Causa raíz
- Alpha.56–58 trataba `0x30002776 / 0x30002778 / 0x30009760` como localizador
  permanente después de validar filas sueltas. La dirección procede de un cheat
  estático, no de un puntero ni de una prueba de ciclo de vida.
- La sesión física conservada contiene dos combates correctos dentro del mismo
  proceso del juego y, tras reiniciarlo, un combate donde ambos KOs se recuperan
  juntos al salir. El fragmento `FAIL` posterior se abrió durante `TitleMenu`,
  demostrando además que `0x30000158 == 0x00040001` no identifica por sí solo
  una tabla de batalla utilizable.

## Corregido
- La base publicada se mantiene como vía rápida solo si sus filas siguen
  coincidiendo con la party PK7 del mismo tick.
- Si todas las filas nominales fallan, USUM calibra el backing FCRAM mediante la
  party exacta, exige el vector completo de Max HP con stride `0x330`, rangos
  Displayed/Actual, candidatura guest única y doble readback RPC con flags antes
  y después. Una coincidencia parcial o ambigua se rechaza.
- La dirección resuelta se revalida en cada tick y se descarta al salir del
  combate. No se ha modificado SM ni existe fallback en UI para ocultar un
  `health_game=None`.
- La traza ya no se trunca al reentrar el flag: conserva episodios, ambos flags,
  fuente/base seleccionada, prueba de resolución y una copia inmutable por sesión.

## Validación
- Regresiones específicas: resolución única hasta `detect_fainted_transitions`,
  rechazo ambiguo, journal no truncable y barrido estructural completo.
- Suite completa: **418 passed** con `python -m pytest -q`.
- El cierre físico de realtime queda pendiente de una batalla breve con alpha.59.

# v0.2.2-alpha.58 — USUM: traza diagnóstica del primer KO

## Objetivo
- No cambia el criterio de muerte de alpha.57.
- Registra una traza acotada por tick para demostrar por qué el primer Pokémon activo puede no publicar su KO mientras un sustituto posterior sí.

## Traza
- Archivo: `Logs/usum_battle_health_trace_latest.jsonl`.
- Cada muestra contiene las seis filas de batalla `Max HP / Displayed HP / Actual HP`.
- Incluye la party PK7 testigo, los slots validados/rechazados y los slots candidatos por coincidencia de Max HP.
- Permite distinguir entre: mapeo battle-row↔party-slot incorrecto, `Displayed HP` retrasado frente a `Actual HP`, o fallo de validación de un slot concreto.
- No añade escaneos FCRAM ni escrituras RAM.

## Evidencia externa
- USUMCheatMenu usa `0x30000158` como flag de combate y `0x30002776 / 0x30002778 / 0x30009760` con stride `0x330` para Max/Displayed/Actual HP del equipo del jugador.
- Su cheat de 1-Hit KO distingue explícitamente `Actual HP == 0` de `Displayed HP`, por lo que ambos campos pueden divergir durante una baja.

## Tests
- Nueva regresión: registra por separado `Actual HP=0` y `Displayed HP>0`, y conserva el vínculo de Max HP al slot de party.
- 414/414 tests.

# v0.2.2-alpha.56 — USUM: PS intra-combate validados por slot

## Causa raíz
- La sonda de batalla USUM era todo-o-nada: si un único slot no coincidía en Max HP con su PartyData live, se descartaban los PS de los seis Pokémon.
- Tras operaciones PC→Equipo o sustituciones, un slot runtime puede tardar en converger aunque los demás sigan siendo demostrables; eso hacía que VIDAS y barra solo se actualizaran al terminar el combate mediante el fallback postcombate.

## Corregido
- La validación de Max/Displayed/Actual HP se hace ahora por slot.
- Un slot solo publica HP de batalla si su Max HP coincide exactamente con la PartyData live de ese mismo slot y sus HP están dentro de rango.
- Los slots no demostrados conservan la lectura segura de party y no invalidan a los demás.
- Si ningún slot queda demostrado, se mantiene el rechazo total y el fallback postcombate.
- No se modifican Cementerio, sustituciones, PC, roles ni movimientos.

## Evidencia técnica
- USUMCheatMenu usa 0x30000158 como flag de batalla y 0x30002776 / 0x30002778 / 0x30009760 con stride 0x330 para Max/Displayed/Actual HP del equipo del jugador.

## Tests
- Regresión nueva: slot 1 validado cae a 0 mientras slot 2 tiene Max HP deliberadamente incoherente; el KO del slot 1 sigue publicándose en tiempo real.
- Regresión de seguridad: si ningún slot coincide, la sonda sigue rechazándose.
- 410/410 tests.

# v0.2.2-alpha.55 — Gen 7: sustitución por muerte sin Huevo fantasma

## Causa raíz
- El writer especial `replace-fainted` de Sol/Luna y UltraSol/UltraLuna vaciaba el hueco PC del sustituto escribiendo `0xE8` bytes a cero.
- El flujo normal `PC -> Equipo` ya usaba un `BoxPokemon` vacío cifrado válido, pero esta ruta antigua había quedado sin portar.
- En UltraSol el juego puede materializar ese falso vacío como un Huevo en la caja de origen del sustituto.

## Corregido
- `replace-fainted` usa ahora `encrypt_pk6_stored(bytes(0xE8))` para dejar el hueco origen como PK7 stored vacío válido.
- La verificación tardía exige no solo que el parser vea el hueco vacío, sino que los `0xE8` bytes guest coincidan exactamente con el vacío cifrado esperado.
- La corrección se aplica a `sm` y `usum`; no se ha modificado ORAS/X/Y.

## Tests
- Regresión nueva USUM: muerte -> sustituto desde Caja 1 -> origen queda vacío cifrado, Cementerio conserva al debilitado y rol heredado correcto.
- Regresión equivalente SM reforzada con comprobación byte a byte del vacío cifrado.
- 408/408 tests.

# v0.2.2-alpha.54 — USUM: refresco de objeto equipado + mochila MT por ItemsOffset real

## Corregido
- Juego → RoleRun: `held_item` ya no se preserva desde la captura anterior. El objeto equipado se publica desde el PK7 live, por lo que quitar/equipar un objeto dentro del juego se refleja automáticamente.
- MT USUM: eliminado el supuesto `PC -> Items` derivado de offsets del SAV.
- La mochila para MT usa como candidata RAM la referencia pública específica de USUM `ItemsOffset = 0x33011934` (`ItemsSize = 0x1000`) y solo se acepta tras doble lectura estable + prueba estructural distribuida contra el `main`.
- El selector de MT ya no cae a un escaneo FCRAM/host si la referencia publicada falla: aborta rápido y deja diagnóstico preciso.

## Seguridad
- Enseñar una MT sigue sin modificar la mochila; revalida la MT poseída justo antes de escribir el movimiento.
- Las utilidades que sí escriben inventario mantienen su prueba host+guest independiente.

## Tests
- 407/407 tests.

# v0.2.2-alpha.57 — Gen 7: baseline inicial de combate

- Gen 7 (SM/USUM): la sincronización inicial lee ya el flag/HP de batalla en vez de dejar el estado en `unknown` hasta el primer monitor.
- Corrige una carrera donde la primera muerte tras abrir RoleRun podía convertirse en baseline si ocurría antes del primer tick (~950 ms), mientras las siguientes sí funcionaban.
- Arranque fuera de combate: baseline `none` inmediato. Arranque dentro de combate: baseline de HP sin cobrar muertes retrospectivas.
- Si la sonda inicial es desconocida o se conecta dentro de combate, el primer monitor se programa a 250 ms.
