# AGENTS.md — RoleRun Manager

## Ámbito y objetivo

Estas instrucciones se aplican a todo el repositorio. RoleRun Manager manipula
partidas y memoria viva de emuladores; un falso positivo puede corromper una
partida, registrar una muerte inexistente o escribir en una región RAM ajena.
La prioridad es, en este orden: integridad de los datos del usuario,
corrección demostrable, capacidad de diagnóstico y velocidad de entrega.

La versión base del repositorio se creó como `v0.2.2-alpha.58`. Antes de asumir
que sigue siendo la versión actual, comprobar `app/config.py`, `CHANGELOG.md` y
el historial Git.

Todo desarrollo debe realizarse directamente en este repositorio y en su árbol
de trabajo actual. No implementar sobre una copia exportada, un ZIP, una carpeta
paralela o una versión reconstruida que pueda divergir del código que se va a
entregar. Las copias temporales solo pueden usarse como fixtures o salidas de
prueba y nunca como fuente de la implementación.

## Regla fundamental: ninguna implementación por suposición

Nunca basar una implementación en una dirección RAM, estructura, tamaño,
endianness, relación entre juegos, comportamiento del emulador o premisa que
no esté demostrada por al menos una fuente técnica verificable.

Se considera evidencia válida, según la afirmación que se quiera demostrar:

- código que pertenezca al flujo ejecutado realmente;
- documentación técnica identificada y compatible con la edición, revisión y
  backend concretos;
- logs o capturas reproducibles con contexto suficiente;
- pruebas que reproduzcan el comportamiento real y sus invariantes;
- lectura observada durante una partida real, preferiblemente en varios estados;
- comparación exacta entre la representación invitada y la anfitriona cuando
  se investigue memoria del proceso.

No se considera demostración:

- que una dirección funcione en otro juego, región, actualización o emulador;
- que dos estructuras «parezcan iguales»;
- que el dato buscado aparezca una vez en un escaneo;
- que una escritura no produzca un error visible inmediato;
- que un offset esté cerca de otro conocido;
- un comentario, README histórico o entrada antigua del roadmap sin contraste
  con el código y la ejecución actuales;
- una prueba que solo confirme el mismo supuesto codificado por la implementación.

Toda hipótesis debe formularse de forma falsable. Si aún no puede demostrarse,
la salida correcta es instrumentar, registrar y diagnosticar; no escribir RAM
ni activar la capacidad para usuarios.

## Regla de parada y vuelta a la causa raíz

Si dos o más parches consecutivos desplazan, enmascaran o transforman el mismo
fallo sin eliminarlo, detener el parcheo incremental. No aplicar un tercer
parche hasta completar una revisión de extremo a extremo.

La revisión debe seguir y registrar cada frontera relevante:

1. estado real de la partida;
2. proceso, edición, actualización y backend conectados;
3. transporte Azahar RPC, Citra GDB u otro;
4. bytes crudos y estabilidad de las lecturas;
5. decodificación, cifrado, tamaño, stride y mapeo de slots;
6. validadores y resolución del bloque;
7. adaptador y `RealTimeSnapshot`;
8. eventos producidos por el Core;
9. estado y temporización de la UI;
10. persistencia de la run, historial, OBS y efectos secundarios.

Hay que localizar la primera frontera donde el valor observado diverge del
esperado. El siguiente cambio debe atacar esa causa y acompañarse de una
regresión que falle antes del arreglo.

## Protocolo de interacción con el usuario

El usuario no tiene que proponer archivos, funciones, offsets, arquitecturas ni
soluciones técnicas. Su aportación normal consiste en describir qué estaba
haciendo, qué esperaba, qué ocurrió, qué funcionalidad busca y aportar las
capturas, logs o archivos que existan. Es responsabilidad del agente traducir
esa información a una investigación técnica rigurosa.

1. No esperar que el usuario proponga soluciones técnicas.
2. No interpretar una sugerencia técnica del usuario como una premisa correcta
   solo porque la mencione. Debe demostrarse con la misma evidencia exigida a
   cualquier otra hipótesis.
3. Cuando el usuario reporte un bug, reconstruir primero el flujo relevante de
   extremo a extremo y localizar la primera divergencia real.
4. Inspeccionar el código, Git, logs, diagnósticos y tests disponibles antes de
   pedir información adicional.
5. Si una respuesta puede obtenerse leyendo archivos locales, obtenerla
   directamente; no pedir al usuario que copie, busque o interprete esos
   archivos manualmente.
6. Hacer preguntas al usuario únicamente cuando falte una observación física
   que solo él pueda realizar dentro del juego o emulador.
7. Cuando sea necesaria una prueba física, dar instrucciones simples,
   concretas y ordenadas, sin exigir conocimientos técnicos.
8. No pedir al usuario que busque offsets, direcciones RAM, estructuras
   internas o detalles de implementación salvo que resulte absolutamente
   imposible instrumentar la observación desde RoleRun.
9. Ante un bug, proceder en este orden: describir la causa raíz demostrada;
   explicar qué evidencia la demuestra; indicar qué se va a modificar; añadir
   una regresión; ejecutar toda la suite; e indicar después una prueba física
   concreta.
10. Si la causa raíz todavía no está demostrada, decirlo explícitamente y
    preparar instrumentación o diagnóstico antes de implementar.
11. Nunca convertir expresiones del usuario como «creo que», «puede ser»,
    «igual es» o «quizás» en hechos técnicos.
12. Si dos correcciones consecutivas solo desplazan el síntoma, detener
    inmediatamente el parcheo incremental y realizar una investigación
    completa de causa raíz.
13. Cuando el usuario valide físicamente una funcionalidad, registrar ese
    hecho, su alcance y el entorno validado en `docs/CURRENT_STATE.md`.
14. Mantener el lenguaje dirigido al usuario comprensible y explicar lo
    importante sin exigirle entender detalles internos de Python, C#, PKHeX,
    RPC o memoria.
15. Terminar siempre cada entrega indicando exactamente qué debe probar el
    usuario a continuación. Si no procede una prueba funcional, indicarlo
    expresamente y señalar la siguiente comprobación concreta.
16. Regla de oro de validación local: toda operación que el agente pueda
    ejecutar y observar directamente en el ordenador disponible debe probarse
    físicamente antes de entregarla. El ciclo obligatorio es ejecutar la
    acción real en RoleRun, comprobar el resultado visible en RoleRun y en el
    juego/emulador, corregir la primera divergencia y repetir hasta obtener el
    resultado esperado. Un test automatizado o un readback del mismo writer no
    sustituyen esta comprobación cuando el efecto final puede visualizarse
    localmente. No pedir al usuario que repita una comprobación que el agente
    pueda realizar por sí mismo.

## Preparación obligatoria antes de cambiar nada

1. Leer este archivo completo.
2. Ejecutar `git status --short --branch` y preservar cualquier cambio del
   usuario. Nunca limpiar, revertir, reordenar o incluir cambios ajenos.
3. Leer las secciones relevantes de `DESIGN.md`, `CHANGELOG.md`, `ROADMAP.md`,
   `VISION.md` y `docs/`. El roadmap y los README históricos pueden estar
   desfasados: contrastarlos siempre con código y pruebas actuales.
4. Trazar el flujo real con `rg` desde la UI o evento de entrada hasta el
   backend y la persistencia. No editar solo el primer resultado encontrado.
5. Identificar los invariantes y el riesgo del cambio: solo lectura, escritura
   de save, escritura RAM, muerte/progresión automática o migración de datos.
6. Reproducir el problema o reunir la evidencia disponible antes de proponer
   la implementación.
7. Definir por adelantado cómo se verificará el resultado y cómo se recuperará
   el estado anterior si una escritura falla.

Cuando falte una evidencia que solo el usuario pueda obtener de una partida
real, preparar diagnóstico seguro y pedir esa captura. No rellenar el hueco
con una inferencia.

## Arquitectura que debe preservarse

- `main.py` solo arranca la aplicación.
- `app/ui.py` es actualmente la raíz de composición y el controlador principal.
  Evitar añadirle lógica de protocolo o estructuras RAM nuevas cuando pueda
  residir en un servicio o adaptador comprobable de forma aislada.
- `app/realtime/` es común y no debe conocer offsets específicos de un juego.
- `app/*_adapter.py` transforma el backend de un juego al contrato común.
- `app/oras_live.py`, `app/xy_live.py`, `app/sm_live.py` y `app/usum_live.py`
  contienen el conocimiento de memoria específico.
- `app/save_engine_client.py` es la frontera Python del motor de saves.
- `engine/RoleRun.SaveEngine/` realiza operaciones PKHeX y debe producir una
  salida separada, recargarla y verificarla.
- `app/save_service.py` conserva backups y reemplazo atómico.
- `app/run_service.py` es la autoridad de runs, contadores, muertes pendientes,
  cementerio e historial.
- `app/live_party_watch.py` detecta cambios de equipo y transiciones de HP; el
  compromiso persistente de una muerte no debe duplicarse allí.
- `app/role_rules.py` expresa las reglas RoleRun. La legalidad de Pokémon y
  movimientos y las restricciones de rol son capas diferentes.

La UI no debe llamar a PKHeX directamente. Los adaptadores no deben filtrar
offsets hacia el Core común. Un fallo opcional —PC, inventario, progreso o
combate— no debe invalidar silenciosamente una lectura válida del equipo.

Cuando un fallo pertenezca a un juego, edición, emulador o backend concreto,
limitar el cambio a ese backend. No tocar otros backends «por consistencia» ni
propagar el parche preventivamente. Solo se puede modificar código común cuando
el trazado de extremo a extremo demuestre que la primera divergencia real está
en ese código común; en ese caso hay que probar también todos sus consumidores.

## Protocolo para investigación de RAM

Antes de aceptar una dirección, stride, campo o copia anfitriona:

- fijar juego, región, revisión/update, Title ID cuando aplique, emulador,
  versión del emulador y tipo de backend;
- identificar proceso y mapa de memoria correctos;
- obtener varias lecturas estables y anotar cuándo cambia el dato;
- contrastar al menos dos estados controlados de la partida cuando sea posible;
- demostrar estructura completa, límites y mapeo de slots, no solo un valor;
- distinguir bytes almacenados, datos de equipo, datos de combate, mirrors,
  cachés y copias obsoletas;
- conservar logs acotados que permitan repetir el razonamiento;
- añadir validadores capaces de rechazar coincidencias accidentales;
- dejar la capacidad en solo lectura hasta demostrar también una escritura y
  su readback en un entorno controlado.

Toda dirección RAM nueva debe tener evidencia positiva, reproducible y trazada
para la combinación exacta de juego, revisión y backend. Sin esa evidencia no
se incorpora como constante, candidato, fallback ni ruta oculta de producción.

Los escaneos deben ser de solo lectura, acotados por regiones justificadas,
tener presupuesto y cooldown, y producir diagnósticos. Quedan prohibidos los
escaneos indiscriminados de FCRAM o del proceso como fallback automático.

Una dirección conocida es únicamente un candidato. `LiveBlockResolver` debe
volver a validarla. La caché debe invalidarse al cambiar proceso, juego, save,
state/load, revisión o cuando fallen los invariantes.

No trasladar offsets entre ORAS, XY, SM y USUM por simetría. En Gen 7, distinguir
de forma explícita PK7 almacenado, `PartyData`, estadísticas anexas, fila de
combate y cualquier copia anfitriona.

## Lecturas en tiempo real

- Preferir doble lectura estable cuando el backend pueda cambiar mientras se
  captura un bloque.
- Validar identidad, tamaño, checksum/cifrado, conteo, límites y coherencia
  estructural antes de publicar un snapshot.
- Un snapshot debe declarar el estado de cada lane mediante diagnósticos; no
  convertir ausencia de evidencia en un valor válido por defecto.
- Conservar el último valor válido solo junto con una señal visible de dato
  stale o fallback.
- No mezclar muestras de instantes incompatibles sin declararlo.
- La sincronización inicial de combate es un baseline, nunca una transición
  retrospectiva. Un Pokémon que ya estaba a 0 HP al conectar no constituye por
  sí solo una nueva muerte.
- Reinicios del emulador, cambios de proceso y reconexiones deben invalidar las
  referencias anteriores y exigir una nueva identificación.

## Escrituras RAM y de partidas

Toda escritura debe estar cerrada por defecto y abrirse solo cuando la
capacidad concreta esté demostrada para la combinación activa.

Las precondiciones son obligatorias. Antes de escribir:

- verificar juego, proceso/backend, revisión, origen y destino;
- releer el testigo inmediatamente antes de la operación;
- verificar identidad estable —PID/TID/SID, especie y slot cuando aplique— y no
  solo el índice visible en la UI;
- rechazar snapshots stale, lanes inválidos, candidatos ambiguos y cambios
  concurrentes;
- disponer de los bytes anteriores y de un mecanismo de recuperación probado;
- escribir la unidad atómica mínima que la estructura demostrada permita, no
  una porción arbitraria que deje checksum, cifrado o mirrors incoherentes.

Después de escribir:

- hacer readback desde la fuente real, no desde la caché;
- verificar bytes y significado semántico;
- verificar invariantes colaterales como conteo, identidad, HP, roles, objetos
  y slots vecinos;
- ejecutar rollback con los bytes anteriores y verificar la restauración si
  falla cualquier comprobación;
- emitir un diagnóstico útil sin ocultar la causa original.

Nunca hacer fallback silencioso de RAM a save en disco, ni al contrario. Nunca
reemplazar una estructura Pokémon por ceros salvo que esa representación vacía
esté demostrada para el formato exacto; en formatos cifrados debe emplearse la
representación vacía válida.

Para saves, mantener siempre el flujo: backup verificable, salida separada,
recarga y validación con PKHeX, copia visible anterior, reemplazo atómico y
relectura del archivo activo. No escribir directamente sobre la única copia.

## Reglas específicas por subsistema

### PC y equipo

- Obtener dimensiones y formato desde el motor/save o evidencia equivalente.
- Demostrar ocupación, slot actual, orden y correspondencia partido-PC.
- Los cambios de tamaño del equipo son operaciones distintas de un swap 1:1 y
  requieren prueba independiente.
- No reconstruir bytes desconocidos por semejanza. Si una estructura completa
  no está demostrada, mantener la operación deshabilitada y diagnosticar.
- Tras una operación, verificar origen vacío válido, destino, conteo y todos
  los Pokémon no implicados.

### Movimientos, MT y roles

- Usar IDs oficiales como identidad interna; los nombres localizados son UI.
- Separar: validez del juego/PKHeX, compatibilidad de especie con MT, posesión
  real de la MT y restricciones de rol de RoleRun.
- Una limitación de rol no debe presentarse como ilegalidad del juego.
- Los datos ROM de ORAS, XY, SM, USUM y BDSP deben declarar origen, revisión y
  prueba estructural. No reutilizar tablas o offsets entre títulos por intuición.
- Verificar movimiento anterior, movimiento resultante, PP y Pokémon testigo.

### Muertes

- Una muerte automática necesita identidad estable, un baseline válido y una
  transición observada de HP positivo a cero dentro del flujo correcto.
- Reconciliar HP de combate y HP del equipo sin asumir que se actualizan en el
  mismo tick.
- Registrar cada muerte exactamente una vez. Proteger reconexión, reordenación,
  reemplazo directo, carga de state y desaparición temporal del Pokémon.
- No decrementar vidas ni abrir el selector si la evidencia es ambigua. Mantener
  el caso pendiente y mostrar diagnóstico.
- Cualquier cambio en este flujo debe probar: primer KO, varios KO, conexión
  dentro/fuera de combate, fin de combate, reconexión y falso positivo.

### Progresión

- No interpretar flags, masks, endianess, índices de evento o cristales por
  analogía con otro juego.
- Separar el valor leído del contador persistido y documentar la regla de
  conversión.
- El fallback manual debe ser explícito; no debe aparentar que procede de RAM.
- No retroceder ni duplicar progreso por una lectura stale o una reconexión.

### UI, OBS y automatización

- No bloquear el hilo de Tkinter con IO, escaneos o escrituras prolongadas.
- Reflejar claramente si el dato es live, de save, fallback, stale o inválido.
- No permitir que un error de PC/inventario o progreso borre un equipo live
  válido.
- Mantener consistencia entre UI, run persistida, historial y OBS.
- Una acción irreversible o que afecte a una partida debe pedir confirmación,
  salvo que forme parte de un flujo automático expresamente diseñado y probado.

## Pruebas y verificación

Cada bug corregido debe incorporar un test de regresión que reproduzca su causa
y falle antes del arreglo. Si el fenómeno físico no puede automatizarse por
completo, añadir la regresión determinista más cercana y documentar además la
reproducción y validación física pendiente. No debilitar validadores ni cambiar
expectativas únicamente para hacer pasar una prueba.

El orden normal de verificación es:

1. pruebas unitarias del componente cambiado;
2. regresiones del juego y alpha relacionadas;
3. pruebas de la frontera superior —adaptador, Core, UI o persistencia—;
4. suite completa;
5. prueba controlada en partida real cuando el cambio dependa de RAM o timing.

La validación física en el emulador objetivo es obligatoria para cerrar una
función realtime como terminada, corregida o estable. Debe cubrir el juego,
revisión y backend afectados. Las pruebas automatizadas y los replays son
necesarios, pero no sustituyen esta validación. Si no puede realizarse, dejar la
función explícitamente pendiente de validación física y no anunciarla como
cerrada.

Las cifras anotadas en el changelog no prueban el estado actual: registrar el
comando ejecutado y su resultado real. Las pruebas no deben escribir en RAM
real ni usar una partida personal; usar fakes, fixtures, grabaciones o copias
temporales. Los fixtures con datos reales deben anonimizarse y justificar su
procedencia.

Si no puede ejecutarse una prueba necesaria, indicarlo expresamente y no
declarar verificada la capacidad correspondiente.

## Documentación y trazabilidad

Todo cambio que altere comportamiento observable debe actualizar
`CHANGELOG.md`. Actualizar `DESIGN.md`, `ROADMAP.md`, `VISION.md` o `docs/`
cuando cambien contratos, arquitectura o estado real de una capacidad.

Una dirección o estructura nueva debe quedar trazada cerca de su definición y
en una prueba o documento técnico con:

- juego/revisión/backend;
- fuente de la evidencia;
- muestras o invariantes usados para validarla;
- condiciones de rechazo;
- alcance de lectura/escritura demostrado;
- limitaciones conocidas.

No reescribir documentación histórica para que parezca que una evidencia
actual siempre se conoció. Corregir contradicciones actuales de forma explícita.

## Disciplina Git y alcance

- Mantener cambios pequeños, revisables y centrados en una causa.
- Inspeccionar el diff completo antes de terminar.
- Usar Git como mecanismo de checkpoint y rollback: antes de modificar, anotar
  el `HEAD`, comprobar el árbol y asegurar que existe un commit conocido al que
  volver. En trabajos largos o de alto riesgo, crear checkpoints coherentes
  cuando estén autorizados. Para deshacer cambios ya commiteados, preferir
  `git revert` o un commit correctivo que conserve la trazabilidad.
- No usar `git reset --hard`, `git checkout --`, `git clean` ni borrar cambios
  ajenos.
- No commitear, etiquetar, publicar ni reescribir historial salvo petición
  explícita del usuario.
- No incluir logs, backups, saves, ROMs, binarios generados, cachés ni datos
  personales.
- No generar ZIPs, paquetes de distribución ni bundles salvo petición expresa
  del usuario.
- No aprovechar una corrección para refactorizaciones no necesarias. Proponerlas
  por separado si reducen un riesgo demostrado.

## Criterio de finalización

No declarar terminado un cambio hasta poder responder con evidencia:

- cuál era la causa raíz;
- qué observación la demuestra;
- qué frontera del flujo estaba equivocada;
- por qué el cambio es el mínimo seguro;
- qué pruebas se ejecutaron y con qué resultado;
- qué no se pudo verificar;
- cómo se protege la recuperación ante fallo;
- que `git diff` contiene únicamente cambios intencionados.

Ante una duda entre «probablemente funciona» y «todavía no está demostrado»,
RoleRun Manager debe elegir diagnóstico y seguridad.
