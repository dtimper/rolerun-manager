# Auditoría del estado actual de la interfaz

Fecha de auditoría: 2026-08-23  
Versión observada: `0.2.2-alpha.86`  
Alcance: interfaz y experiencia de usuario existentes; no se ha modificado comportamiento.

## 1. Método y fuentes de evidencia

Esta auditoría se ha construido desde el flujo ejecutado, no desde los nombres de
las pantallas. Se inspeccionaron:

- `main.py`, que únicamente crea `RoleRunManager` y entra en `mainloop()`;
- `app/ui.py`, raíz de composición y controlador de la interfaz;
- modelos de cambios pendientes en `app/models.py`;
- persistencia de runs, contadores, historial, bajas y cementerio en
  `app/run_service.py`;
- contrato común y snapshots en `app/realtime/`;
- readers, writers y adaptadores de ORAS, X/Y, SM, USUM y BDSP;
- `app/save_engine_client.py`, `app/save_service.py` y el motor C# de saves;
- servicios de MT/ROM, PC, reglas, OBS, hotkeys, watcher y revisión live;
- pruebas de `tests/` y estado funcional documentado en
  `docs/CURRENT_STATE.md`, `docs/GAME_ENGINES.md`, `DESIGN.md`, `VISION.md` y
  `ROADMAP.md`;
- capturas físicas aportadas durante el desarrollo de USUM y BDSP.

Los recuentos estáticos que condicionan el rediseño son:

- `app/ui.py`: aproximadamente 16 377 líneas;
- 10 familias de juego seleccionables;
- 8 entradas en la navegación principal;
- 5 adaptadores realtime registrados: ORAS, X/Y, SM, USUM y BDSP;
- una sola instancia de `RoleRunManager` concentra servicios, estado, cachés,
  ventanas, timers y renderizado.

No se lanzó una segunda instancia conectada al emulador para obtener capturas:
podría competir con la sesión real, registrar hotkeys globales o leer/escribir el
mismo juego. Las capturas físicas ya aportadas y el código son evidencia
suficiente para esta fase.

## 2. Arquitectura visible y técnica actual

```text
main.py
  └─ RoleRunManager (CustomTkinter)
       ├─ selección de juego / run
       ├─ shell: sidebar + cabecera + body reconstruible
       ├─ páginas y Toplevels
       ├─ RunProjectService / ObsSyncService / SaveFileWatcher
       ├─ GameEngine / SaveEngineClient / SaveService
       ├─ RealTimeCore
       │    └─ adapter del juego
       │         └─ reader / writer / bridge del emulador
       └─ estado proyectado, colas, timers, reconciliación y mensajes
```

La separación de backends existe y debe conservarse. La separación dentro de la
interfaz es débil: `RoleRunManager` construye todos los backends, decide qué
capacidad está disponible, transforma estados para presentarlos, crea widgets,
lanza workers, aplica escrituras, reconcilia resultados y muestra errores.

### Fuentes de verdad que conviven

| Estado | Autoridad | Representación en UI |
|---|---|---|
| Run y contadores | `RunProjectService` | Dashboard, barra flotante, historial |
| Equipo/saves clásicos | `GameEngine` sobre save | `current_game` + cambios pendientes |
| Equipo realtime | snapshot del adaptador/Core | `current_game` publicado por la UI |
| Cambios clásicos | `RunSession.pending_changes` | proyección hasta Guardar/Descartar |
| Cambios realtime | proyección breve + readback | estado pendiente, lote revisable, toast |
| PC | save base + overrides/lectura live | caché y matriz proyectada |
| Bajas | `LivePartyWatch` + `RunProjectService` | vidas, pendiente de sustituto, historial |
| OBS | `ObsSyncService` | archivos externos y visibilidad de roles |

La futura interfaz no debe crear una nueva fuente de verdad. Necesita un modelo
de presentación que etiquete cada valor como confirmado, proyectado, pendiente,
stale o inválido.

## 3. Mapa de navegación real

### Entrada y shell

```text
Splash
  └─ Selector de juego (10 tarjetas)
       ├─ ABRIR, si hay fuente configurada
       └─ CONFIGURAR
            ├─ elegir save
            ├─ elegir ROM/archivo del juego
            └─ decidir si sustituir fuente crea una run nueva

Shell principal
  ├─ Dashboard
  ├─ Drafteos
  ├─ Equipo
  ├─ Movimientos
  ├─ Cajas PC ──> Toplevel de PC
  ├─ Historial
  ├─ Configuración
  └─ Ayuda

Cabecera global
  ├─ Revisar cambios
  ├─ Guardar / Descartar (solo motores no realtime)
  ├─ Barra flotante
  └─ estado compacto de run/sincronización/error
```

### Ventanas y flujos secundarios

- editor de rol libre;
- conflicto por rol ocupado y resolución del desplazado;
- selector Equipo → PC;
- selector PC → Equipo y, si la party está llena, segundo selector de miembro;
- editor de rol de un Pokémon del PC;
- selector de MT por Pokémon y slot;
- revisión del equipo/incompatibilidades;
- selector de movimiento de daño que Support debe retirar;
- selector automático de sustituto tras una baja;
- revisión de cambios pendientes o lotes live;
- captura de hotkey;
- informe/replay de diagnóstico;
- explicación “qué es RoleRun”;
- mensajes nativos de información, confirmación, advertencia y error.

La barra flotante es otro `Toplevel`: aparece manualmente o al minimizar/perder
foco, mantiene contadores y seis roles, registra gestos de rol y restaura la
página anterior. Tiene lógica especial para suspender y restaurar otros modales.

## 4. Inventario funcional orientado a UX

### 4.1 Inicio y estado de la run

**Ubicación:** Dashboard y cabecera; versión resumida en barra flotante.  
**Datos:** juego, entrenador/run, reglas activas, conflictos, cuatro contadores y
seis roles con Pokémon/sprite/visibilidad.  
**Acciones:** aumentar/reducir contadores manuales cuando se permite; activar
reglas; resolver conflictos; mostrar/ocultar roles; arrastrar roles; abrir barra.
**Servicios:** `RunProjectService`, reglas, proyección del equipo, `ObsSyncService`.
**Estados:** sin run, contador automático, rol vacío, conflicto, reglas inactivas,
cambios pendientes y estado live en cabecera.
**Duplicación:** equipo/roles y contadores aparecen también en Equipo, barra y
OBS. El Dashboard funciona bien como lectura rápida, pero mezcla resumen con
operaciones de configuración de reglas.

### 4.2 Equipo

**Ubicación:** página Equipo, con una tarjeta alta por Pokémon.  
**Datos:** sprite, nombre, especie, nivel, rol, habilidad, objeto y cuatro
movimientos; utilidades de run en la cabecera de la página.  
**Acciones:** cambiar rol, cambiar con PC, enviar al PC, añadir desde PC si hay
hueco, sustituir/eliminar movimientos incompatibles, enseñar en hueco vacío,
añadir Caramelos Raros, Repelentes Máximos o dinero.  
**Servicios:** proyección de `current_game`, reglas, GameEngine/SaveEngine,
adaptador/writer realtime, MT/ROM/inventario, PC y servicios de run.  
**Estados:** pendiente, incompatible en rojo, rol bloqueado, utilidad no
demostrada, lectura live en curso, escritura y error.  
**Problema probado:** las tarjetas obligan a mucho scroll; comparar los seis
miembros o relacionarlos con el PC exige cambiar de contexto.

### 4.3 PC, incorporación, retirada y sustitución

**Ubicación aparente:** “Cajas PC”; **ubicación real:** un `Toplevel` de gran
tamaño que se abre sobre una página casi vacía.  
**Datos:** caja, conteo, rejilla de Pokémon, buscador y panel de detalle.  
**Acciones:** navegar/saltar caja, buscar por especie, apodo, habilidad o
movimiento, seleccionar, cambiar rol gestionado, añadir al equipo, sustituir un
miembro o explorar. Equipo permite iniciar la operación inversa.  
**Servicios:** `GameEngine.read_boxes`, `pc_browser`, caché de PC, lector live,
overrides, writers y metadatos de cajas.  
**Estados:** lectura inicial, hidratación de sprites, caja vacía, búsqueda sin
resultado, PC lleno, party llena, matriz live incoherente, escritura pendiente,
readback, rollback/error.  
**Riesgo:** una nueva vista no puede reducir un cambio de tamaño 5↔6 a un swap
1↔1 ni confundir posición física, rol y posición visual.

### 4.4 Sustitución de Pokémon debilitados y cementerio

**Ubicación:** no hay página Cementerio. Al confirmarse una muerte, un selector
automático se abre al final del flujo seguro de combate y muestra el sustituto.
El Pokémon saliente se mueve a la caja de Cementerio definida por el backend y
el hecho queda en historial/persistencia.  
**Datos:** Pokémon debilitado, rol liberado, caja, candidatos, hueco de
cementerio y bajas pendientes.  
**Acciones:** elegir sustituto; navegar/buscar cajas.  
**Servicios:** `LivePartyWatch`, `RunProjectService`, adapter/writer, lectura PC,
picker y reconciliación.  
**Estados:** muerte pendiente, combate aún activo, carga PC, selector suprimido o
reabierto, cementerio lleno, equipo cambiado, escritura verificada/fallida.  
**Descubribilidad:** el cementerio existe como dato y caja especial, pero no como
destino de navegación. No hay vista clara de pendientes y enterrados.

### 4.5 Roles y reglas

**Ubicación:** Dashboard, Equipo, PC, drafteos, barra flotante y Ajustes/estado de
run.  
**Datos:** seis roles canónicos y marcador físico; conflictos, ocupación y
visibilidad OBS.  
**Acciones:** asignar/cambiar, transferir al Pokémon sustituto, resolver rol
ocupado, mostrar/ocultar, activar reglas, arrastrar entre slots de rol.  
**Estados:** sin rol, rol libre, ocupado, desplazado, reglas inactivas, migración
de marcadores, escritura no disponible.  
**Ambigüedad:** arrastrar un rol no reordena la party, aunque visualmente el gesto
pueda parecerlo. Debe mantenerse una separación explícita entre marcador de rol,
orden físico y pertenencia Equipo/PC.

### 4.6 Drafteos

**Ubicación:** página Drafteos.  
**Flujo:** rol → Pokémon → opciones de movimiento/reroll → slot a reemplazar →
cambio pendiente o autoaplicado.  
**Datos:** drafteos disponibles, ocupante de cada rol, movimientos candidatos y
compatibilidad.  
**Servicios:** `DraftEngine`, reglas, catálogo, GameEngine/writer.  
**Estados:** sin drafteos, rol no elegible, lista generada, Pokémon elegido,
movimiento elegido, cambio pendiente/confirmado.  
**Fortaleza:** el wizard reduce decisiones simultáneas. **Coste:** destruye pasos
posteriores al cambiar una elección y ocupa una página separada del contexto de
movimientos.

### 4.7 Movimientos, compatibilidad y MT

**Movimientos:** página de consulta por rol con buscador y listas compatible/no
compatible. No enseña directamente desde esa página.  
**Compatibilidad:** se visualiza principalmente en rojo dentro de cada tarjeta de
Equipo. Existe `_open_team_review()`, pero no se encontró una llamada desde un
control visible en el flujo actual; es capacidad interna no descubrible.  
**MT:** no tiene página propia. Se abre desde `+` o SUSTITUIR junto a un movimiento
del Pokémon. El selector valida fuente ROM, inventario, compatibilidad de especie,
reglas de rol, posesión y slot.  
**Servicios:** perfiles por juego, lectores de mochila, datos ROM, reglas,
GameEngine/adaptador/writer.  
**Estados:** fuente no disponible, inventario cargando, MT no poseída, movimiento
ya conocido, no compatible por juego o rol, slot cambiado, write/readback/error.  
**Problema:** el usuario no puede partir de una MT y ver a quién se la puede
enseñar; solo puede partir de un Pokémon y un slot.

### 4.8 Progreso y recursos

**Ubicación:** cuatro contadores en Dashboard/barra; dinero y objetos de comodidad
en Equipo; medallas/Kahunas se presentan bajo el contador genérico `medallas`.
**Automatización:** `AUTOMATIC_BADGE_GAME_KEYS` incluye ORAS, X/Y, SM y USUM;
otros juegos mantienen edición manual salvo capacidades documentadas.  
**Estados:** automático (sin +/-), manual, valor proyectado, sincronizado o no
disponible. La UI no muestra de forma sistemática la procedencia de cada valor.
**Problema:** “progreso” no existe como concepto navegable; sus piezas están
repartidas y no hay explicación contextual por juego.

### 4.9 Historial y recuperación

**Ubicación:** página Historial y ventana “Revisar cambios”.  
**Datos:** eventos cronológicos de contador, quick action, roles, inventario,
Equipo/PC y otras operaciones.  
**Acciones:** consultar; limpiar todo con confirmación; revisar/revertir lotes
live o descartar cambios clásicos. `RunProjectService` también implementa
deshacer el último evento de contador, pero no se encontró un control visible que
lo invoque.  
**Riesgo:** “Limpiar historial” es irreversible desde la UI; la página actual no
ofrece filtros ni conecta de forma clara muertes con Cementerio.

### 4.10 OBS y barra flotante

**OBS:** se configura en Configuración; genera salidas de contadores, roles,
sprites y HTML en una carpeta estable. Detecta conflictos y respeta roles ocultos.
**Barra:** muestra contadores y seis roles, permite +/- manual, visibilidad y drag
de rol, sincronización F5 y retorno a la app.  
**Estados:** abierta/cerrada, no-activa, app principal retirada, modal suspendido,
estado live y toast.  
**Riesgo:** la barra y la pantalla principal comparten estado pero tienen ciclos de
ventana/foco complejos y específicos de Windows.

### 4.11 Conexión, sincronización y diagnóstico

**Ubicación:** cabecera (estado corto) y Configuración (tarjetas detalladas).  
**Acciones:** resincronizar F5, iniciar/detener grabación, ver estado, abrir replay
y carpeta. Detener puede generar un paquete diagnóstico por una acción expresa.  
**Servicios:** `RealTimeCore`, adapters, bridges, recorder, readers y watcher.  
**Estados:** buscando proceso, conectado, capturando, aplicando, stale, lane
inválido, error y reconexión.  
**Problema:** un error importante compite con nombre de run y cambios pendientes en
una etiqueta pequeña; el diagnóstico avanzado está mezclado con ajustes comunes.

### 4.12 Configuración, ayuda y cambio de run

**Configuración:** idioma, save/fuente, datos de run, seguridad, OBS, realtime,
diagnóstico/replay y hotkeys globales.  
**Atajos:** F5; numpad para vidas/curaciones/medallas/drafteos; Alt+1…6 para
visibilidad; Ctrl+Z/Ctrl+Shift+Z para edición proyectada.  
**Cambio de run/juego:** botón persistente al pie del sidebar; si hay cambios se
solicita confirmación.  
**Ayuda:** guía visual y explicación de RoleRun.  
**Problema:** Configuración mezcla preferencias estables, fuentes de datos,
operaciones de soporte y diagnóstico técnico.

### 4.13 Funciones internas sin acceso visible demostrado

Estas funciones existen, tienen lógica y en algunos casos tests, pero no se
encontró una llamada desde un control actual:

- seis acciones rápidas semánticas en `RunProjectService.apply_quick_action()`:
  Pokémon debilitado, wipe, inicio/victoria de combate importante, curación usada
  y Revivir encontrado;
- `RoleRunManager.run_quick_action()` y su toast;
- `undo_last_counter_event()`;
- `_open_team_review()` para incompatibilidades.

No se propone exponerlas automáticamente. Primero debe decidirse si son legado,
funcionalidad incompleta o una capacidad que merece superficie de producto.

## 5. Flujos frecuentes y coste actual

Los clics son aproximados desde una run ya abierta y una página cualquiera; no
incluyen navegación opcional entre cajas ni confirmaciones de error.

| Objetivo | Ruta actual | Clics | Pérdida de contexto / fricción |
|---|---|---:|---|
| Consultar run | Dashboard | 1 | Buen resumen; estado live muy comprimido |
| Ver seis Pokémon | Equipo | 1 + scroll | No se ven los seis simultáneamente |
| Equipo → PC | Equipo → Enviar al PC → confirmar | 2–3 | Se pierde la caja de destino; operación iniciada desde una tarjeta |
| PC → hueco de Equipo | Cajas PC → Pokémon → añadir | 3 | Cambio a Toplevel; detalle y party no son simultáneos |
| PC → Equipo lleno | Cajas PC → Pokémon → añadir → miembro saliente | 4–5 | Cadena de selectores y posible ambigüedad de rol |
| Sustituir baja | selector automático → candidato | 1+ | No hay bandeja persistente de bajas pendientes |
| Cambiar rol | Equipo → cambiar rol → rol | 2–4 | Puede encadenar resolución de ocupante/desplazado |
| Consultar movimientos | Movimientos → rol/búsqueda | 2+ | Catálogo separado del Pokémon y de las MT |
| Enseñar MT | Equipo → localizar tarjeta/scroll → +/Sustituir → MT | 3–5 | Solo flujo Pokémon-primero; posibles prompts de fuente |
| Revisar incompatibilidad | Equipo → localizar rojo → acción | 2+ | La revisión global interna no es visible |
| Vidas/curaciones | Dashboard o barra → +/- | 1–2 | Falta procedencia y explicación del automatismo |
| Historial | Historial | 1 | Sin filtros; Cementerio no está agrupado |
| Cementerio | no existe ruta directa | — | Solo caja especial, bajas persistidas e historial |
| Ver conexión | cabecera o Configuración | 0–2 | Resumen insuficiente o detalle mezclado con ajustes |
| Identificar fallo | Configuración → diagnóstico → ver estado/replay | 2–4 | Terminología técnica y múltiples mensajes transitorios |
| Configurar OBS | Configuración → tarjeta OBS | 1 + scroll | Correcto funcionalmente; difícil de descubrir |
| Cambiar run/juego | botón inferior → selector → abrir | 2–4 | Protege pendientes, pero abandona por completo el contexto |

## 6. Auditoría visual y de usabilidad

### Conservar

- identidad oscura y dorada reconocible;
- sprites y símbolos de rol como información primaria;
- estado compacto de run y barra flotante durante el juego;
- confirmaciones en operaciones destructivas;
- rojo para incompatibilidad real y verde para confirmación;
- wizard de drafteo como patrón guiado;
- búsqueda flexible del PC y navegación por cajas.

### Refinar

- reducir el dorado a acento/acción primaria, no borde de casi toda superficie;
- convertir colores de rol en chips con símbolo y texto, nunca solo color;
- normalizar altura, jerarquía y semántica de botones;
- añadir texto persistente al estado disabled/pending/error;
- usar una escala tipográfica y de espaciado centralizada;
- mantener foco visible, orden de tabulación y alternativas de teclado.

### Reorganizar

- unificar Equipo y PC en un espacio maestro–detalle;
- dar presencia propia a MT y Progreso;
- unir Historial y Cementerio mediante filtros/vistas relacionadas;
- separar Emisión de Ajustes y Diagnóstico avanzado;
- sustituir cadenas de `Toplevel` por panel contextual y diálogos solo cuando la
  decisión sea realmente modal;
- separar estado live persistente de toasts y messageboxes.

### Reemplazar

- páginas contenedoras que solo abren otra ventana;
- tarjetas de equipo tan altas que impiden comparar seis miembros;
- mensajes de error únicamente transitorios;
- interpretación de estado mediante prefijos/glyphs en una cadena;
- reconstrucción visual completa como mecanismo normal de actualización.

### Problemas concretos

1. **Jerarquía:** títulos grandes, tarjetas grandes y múltiples bordes compiten;
   la acción primaria no siempre destaca sobre controles globales.
2. **Densidad:** Equipo desperdicia anchura en tarjetas de tres columnas pero
   consume varias pantallas verticales.
3. **Tarjetas dentro de tarjetas:** utilidad, Pokémon, habilidad/objeto,
   movimientos e incompatibilidades usan superficies anidadas.
4. **Consistencia:** colores adicionales, tamaños y `Segoe UI` se declaran de
   forma repetida en `app/ui.py`, fuera de los pocos tokens globales.
5. **Resolución:** geometría 1360×860, mínimo 1100×720, sidebar fijo y scaling
   adicional 1.12 reducen margen en pantallas pequeñas o con DPI elevado.
6. **Accesibilidad:** varios iconos son caracteres Unicode; selección y disabled
   dependen mucho del color; el drag no tiene alternativa visible equivalente.
7. **Foco:** la suspensión/restauración de modales por la barra prueba que el
   exceso de ventanas ya impone complejidad de foco específica de Windows.
8. **Feedback:** toasts de menos de dos segundos y messageboxes separan el error
   de la operación que lo produjo.

## 7. Auditoría técnica de la UI

### Monolito y acoplamiento

`app/ui.py` mezcla navegación, presentación, protocolos, estado de proyección,
sincronización, writers, persistencia, OBS, diagnóstico y gestión de errores. El
riesgo no es solo mantenibilidad: mover un widget puede alterar timers, foco,
capturas o el momento de una escritura.

### Renderizado y estado

- `render_page()` destruye hijos del body y reconstruye la página;
- `_smooth_render_page()` mantiene buffers para disimular el reemplazo;
- múltiples cachés de sprites, PC, ROM/MT y overrides live viven en la ventana;
- el estado de selección de cada flujo se conserva mediante atributos y cierres;
- muchas firmas visuales evitan redibujar por HP, pero no forman un contrato de
  presentación explícito.

### Concurrencia

Hay workers y colas para lecturas, sprites, saves y diagnóstico, coordinados con
`after()`. Esto evita varios bloqueos, pero la finalización vuelve directamente a
la clase raíz. Tk es event-driven y cada intérprete pertenece al hilo que lo
creó: cualquier nueva capa debe mantener las mutaciones de widgets en el hilo UI.

### Reconciliación y optimismo actual

La UI ya posee una forma de proyección: cambios pendientes clásicos y cambios
realtime autoaplicados. También existen readback, rollback, lotes revisables y
overrides PC. Sin embargo, estas fases no están expresadas como un modelo común;
cada operación decide cómo presentar “pendiente” y cuándo reconstruir.

### Riesgos que condicionan el rediseño

| Riesgo técnico | Consecuencia para el rediseño |
|---|---|
| Callbacks llaman métodos de `RoleRunManager` | Mantener fachada/adaptador durante migración |
| Estado live repartido en muchos atributos | Crear view models derivados, no duplicar autoridad |
| Toplevels y grabs ligados a barra | Migrar modal por modal y probar foco Windows |
| Page rebuild cancela/preserva scroll y timers | No sustituir todas las páginas a la vez |
| PC combina save, overrides y lectura live | La vista unificada debe consumir una proyección existente |
| Escrituras nacen desde handlers de UI | Encapsular comandos sin cambiar writers en primeras fases |
| Juegos con capacidades distintas | Renderizar capacidades declaradas; no botones que fallen tarde |
| Errores como texto/glyph | Introducir estado tipado antes de rediseñar feedback |

## 8. Diferencias entre juegos que la UI debe respetar

| Familia | Modo principal demostrado | Implicación UX |
|---|---|---|
| DP, Platino, HGSS, BW, B2W2 | motor de save, cambios pendientes | Guardar/Descartar y reinicio/instalación cuando corresponda |
| ORAS | realtime Azahar + save seguro | lectura/escritura live por capacidades; badges automáticos |
| X/Y | realtime Azahar/Citra + save | transporte puede requerir preparación; badges automáticos |
| SM | realtime Azahar + save | party/PC/MT/progreso con pruebas específicas; Kahunas automáticos |
| USUM | realtime Azahar + save | estructuras independientes de SM; Kahunas/medallas automáticos |
| BDSP | realtime Ryujinx HostMapped + save | capacidades validadas por SP 1.3.0; PC, MT, bajas, medallas y utilidades |

No existe evidencia para presentar todas las acciones en todos los juegos. La
interfaz futura necesita una matriz de capacidades por sesión que distinga:
disponible, solo lectura, requiere save, realtime confirmado, temporalmente no
disponible y no implementado.

## 9. Primera conclusión de producto

RoleRun ya tiene una base funcional extensa y una identidad clara. El rediseño no
debe reemplazarla por un dashboard genérico ni reescribir sus backends. Debe
resolver tres fronteras:

1. convertir funciones dispersas en espacios de trabajo coherentes;
2. expresar de forma visible la procedencia y confirmación de cada estado;
3. separar presentación de orquestación sin alterar la lógica demostrada.

