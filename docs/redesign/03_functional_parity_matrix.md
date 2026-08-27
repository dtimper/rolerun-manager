# Matriz de paridad funcional

Esta matriz es el contrato de no regresión del rediseño. “Destino” describe la
interfaz futura; no implica que el backend soporte esa función en todos los
juegos. Todas las filas están en estado **no migrado**.

## Convenciones

- **Riesgo:** B bajo, M medio, A alto, C crítico.
- **Lógica reutilizada:** módulo o flujo actual que debe permanecer como autoridad.
- **Tests actuales:** familias representativas, no sustituyen la selección exacta
  que se hará en cada fase.
- **Tests nuevos:** requisito mínimo de UI/presentación para migrar la fila.
- **Estado futuro:** `pendiente` → `dual` → `piloto` → `paridad` → `clásica retirada`.

## 1. Shell, run y navegación

| Función actual | Ubicación actual | Destino | Lógica reutilizada | Riesgo | Tests actuales | Tests nuevos | Estado |
|---|---|---|---|---:|---|---|---|
| Splash y selector de 10 juegos | bienvenida | selector de run/juego | `GAME_OPTIONS`, perfiles de fuente | M | source service | snapshot/teclado/errores | pendiente |
| Configurar save + ROM/fuente | tarjetas de juego + diálogos | asistente de fuente | `GameSourceProfileService`, load de run | A | `test_game_source_service.py` | cancelación, fuente inválida, run existente | pendiente |
| Abrir run configurada | bienvenida | selector reciente | carga actual | A | tests UI/live por juego | progreso, error y reintento | pendiente |
| Cambiar run/archivos | pie del sidebar | selector persistente | `_return_to_welcome` | A | live recovery | pendientes y cancelación | pendiente |
| Sidebar principal | shell fija | sidebar contraíble | navegación actual | B | — | rutas, foco, modo compacto | pendiente |
| Cabecera de página | shell | toolbar contextual | estado de sesión | M | tests UI parciales | prioridad/overflow/resolución | pendiente |
| Revisar cambios | cabecera + Toplevel | Centro de cambios | pending + live review batches | A | `test_live_review.py`, live UI | estados por operación, revertir/fallo | pendiente |
| Guardar/Descartar clásico | cabecera | Centro de cambios, solo save | SaveService/GameEngine | C | save/engine relacionados | backup, cancelación, cierre de app | pendiente |
| Deshacer/rehacer edición | Ctrl+Z / Ctrl+Shift+Z | Centro + atajos | snapshots de edición | A | role/TM tests | foco, límites, estado consolidado | pendiente |
| Ayuda | página | Ayuda contextual + guía | contenido actual | B | — | enlaces/contexto/teclado | pendiente |

## 2. Inicio, contadores y progreso

| Función actual | Ubicación actual | Destino | Lógica reutilizada | Riesgo | Tests actuales | Tests nuevos | Estado |
|---|---|---|---|---:|---|---|---|
| Resumen de run | Dashboard | Inicio | proyección/RunProject | M | run service | view model con/sin run | pendiente |
| Resumen de seis roles | Dashboard/barra | Inicio compacto | role rules + proyección | M | roles/floating | duplicación/selección | pendiente |
| Vidas +/- manual | Dashboard/barra/hotkey | Progreso + quick control | `adjust_counter` | A | automatic counters/run service | origen, límites, historial | pendiente |
| Curaciones +/- | Dashboard/barra/hotkey | Progreso | `adjust_counter` | M | automatic counters | idem | pendiente |
| Drafteos +/- | Dashboard/barra/hotkey | Progreso | `adjust_counter` | M | run service/drafts | consumo y undo | pendiente |
| Medallas +/- manual | Dashboard/barra/hotkey | Progreso | `adjust_counter` | A | automatic counters | capacidad por juego | pendiente |
| Medallas automáticas ORAS/X/Y | contador sin +/- | Progreso automático | adapters/Core/run | C | ORAS/XY badge suites | origen, stale, no retroceso | pendiente |
| Kahunas/medallas SM/USUM | contador genérico | Progreso por juego | badge readers/adapters | C | SM kahuna/USUM suites | etiquetas, reconnect, duplicados | pendiente |
| Medallas BDSP | estado de run | Progreso por juego | BDSP system flags | C | BDSP adapter/UI | readback visual/procedencia | pendiente |
| Dinero | utilidad en Equipo | Progreso > Recursos | writer actual | C | alpha20 XY, BDSP write/UI | pending/readback/rollback | pendiente |
| Caramelos Raros | utilidad en Equipo | Progreso > Recursos | inventory writer | C | inventory/BDSP tests | cantidad, ausencia, rollback | pendiente |
| Repelentes Máximos | utilidad en Equipo | Progreso > Recursos | inventory writer/ID validado | C | BDSP write/UI | identidad del item, cantidad, vecino | pendiente |
| Acciones rápidas semánticas | solo código, no control visible | por decidir en Progreso | `apply_quick_action` | M | `test_run_service.py` | decisión de exposición + UI | pendiente |
| Deshacer último contador | solo código, no control visible | Actividad/Progreso | `undo_last_counter_event` | M | run service | control visible e historial | pendiente |

## 3. Equipo, PC, roles y bajas

| Función actual | Ubicación actual | Destino | Lógica reutilizada | Riesgo | Tests actuales | Tests nuevos | Estado |
|---|---|---|---|---:|---|---|---|
| Leer/ver party | Equipo/Dashboard/barra | Equipo y PC + Inicio | GameEngine/snapshot | C | todos los adapters/live | view model por capacidad/stale | pendiente |
| Ver habilidad/objeto/nivel | tarjetas Equipo/PC | inspector | parsers actuales | A | boxed metadata/live readers | ausencia de campo, localización | pendiente |
| Añadir PC → party con hueco | Toplevel PC | drag/botón Equipo y PC | PendingTeamChange/writers | C | SM/USUM/BDSP PC write | 5→6, readback, cancelación | pendiente |
| Retirar party → PC | tarjeta Equipo | drag/botón Equipo y PC | PendingTeamChange/writers | C | BDSP/SM/ORAS write | 6→5, destino, vecinos | pendiente |
| Swap party↔PC 1:1 | selectores encadenados | drag/botón con preview | writers actuales | C | XY/SM/USUM/BDSP/ORAS suites | gesto, preflight, rollback visual | pendiente |
| Reordenar party desde juego | reconciliación automática | vista actualizada | snapshot/reconcile | C | BDSP reorder, LivePartyWatch | selección estable y animación | pendiente |
| Reordenar party desde RoleRun | no uniforme/no declarado | control condicionado | solo si capacidad demostrada | C | específicos si existen | por backend antes de habilitar | pendiente |
| Leer caja | Toplevel PC | panel central | read_boxes/live matrix | C | PC suites por juego | carga/stale/error conservando anterior | pendiente |
| Navegar caja anterior/siguiente | Toplevel | toolbar de caja | estado de caja | B | pc browser | límites/teclado | pendiente |
| Saltar a caja | Toplevel | selector de caja | validación actual | B | pc browser | entrada inválida/foco | pendiente |
| Buscar PC | Toplevel | búsqueda persistente | `pc_browser.py` | M | `test_alpha44_pc_browser.py` | debounce, accents, vacío | pendiente |
| Filtrar por especie/apodo/habilidad/move | búsqueda textual | filtros + búsqueda | pc browser | M | pc browser | combinación y clear | pendiente |
| Seleccionar y ver detalle | cards + panel | selección compartida | SavePokemon/proyección | M | boxed metadata | teclado y scroll | pendiente |
| Refresco PC live externo | poll/reconcile al abrir | estado discreto del panel | reconciliación actual | C | PC mirror/coherence/BDSP UI | no duplicar party-PC, stale | pendiente |
| Movimiento PC→PC externo | poll BDSP | actualización de rejilla | poll acotado | C | BDSP realtime UI | preservar selección y caja | pendiente |
| Mover PC→PC desde RoleRun | capacidad parcial por backend | drag condicionado | writer solo si declarado | C | específicos | matriz completa/rollback | pendiente |
| Cambiar rol en party | editor modal | inspector/chip | role rules + pending/live write | C | role swap/guards/markers | ocupado, readback, no reordenar | pendiente |
| Cambiar rol en PC | editor modal | acción secundaria | managed roles/writer | A | SM PC tests/boxed metadata | capacidad por juego; se puede ocultar | pendiente |
| Transferir rol al sustituto | lógica automática | preview de operación | role inheritance transaction | C | SM alpha29, BDSP UI | party llena/hueco/reconnect | pendiente |
| Resolver rol ocupado | cadena de modales | panel de conflicto | reglas actuales | A | role swap | preview de desplazados | pendiente |
| Resolver Pokémon sin rol | modal | bandeja de atención | reglas actuales | A | role tests | flujo no modal, foco | pendiente |
| Activar/desactivar reglas | Dashboard | Ajustes de run/Inicio atención | role rules activation | A | alpha17/role tests | revisión de impacto | pendiente |
| Mostrar/ocultar rol OBS | Dashboard/barra | Emisión + Inicio rápido | RunProject/OBS | M | floating roles/OBS | coherencia de vistas | pendiente |
| Drag de roles | Dashboard/barra | chips/destinos explícitos | role drag actual | A | floating role suites | teclado, verbo, no mover party | pendiente |
| Detectar KO | monitor invisible | Inicio/Actividad | LivePartyWatch/Core | C | health suites por juego | presentación sin alterar timing | pendiente |
| Restar vida por KO | monitor + run | Progreso/Actividad | RunProjectService | C | faint/watch/automatic counters | exactamente una vez/reconnect | pendiente |
| Abrir sustituto tras KO | Toplevel automático | bandeja + diálogo específico | faint picker | C | faint picker/BDSP/USUM | varios KO, foco, cierre/reapertura | pendiente |
| Enviar baja al Cementerio | selector de sustituto | operación transaccional | writers/run service | C | graveyard/write suites | caja llena/vecinos/rollback visual | pendiente |
| Lista histórica de Cementerio | no hay vista | Registro > Cementerio | `graveyard_pokemon`, history | A | run service | composición, duplicados, datos ausentes | pendiente |
| Bajas pendientes persistidas | modal/reapertura | bandeja persistente | `pending_faints` | C | run service/faint picker | restart/múltiples pendientes | pendiente |

## 4. Movimientos, compatibilidad, MT y drafteos

| Función actual | Ubicación actual | Destino | Lógica reutilizada | Riesgo | Tests actuales | Tests nuevos | Estado |
|---|---|---|---|---:|---|---|---|
| Ver cuatro movimientos | Equipo | inspector/Movimientos | SavePokemon | A | readers/UI | slots vacíos/PP/nombres | pendiente |
| Catálogo por rol | Movimientos | Movimientos > Explorar | DraftEngine/catalog | M | role rules | filtros y teclado | pendiente |
| Buscar movimiento | Movimientos | buscador común | filtro actual | B | — | acentos/sin resultados | pendiente |
| Compatible/no compatible por rol | listas + rojo en Equipo | motivo estructurado | `role_rules.py` | A | role tests | cada motivo visible | pendiente |
| Revisión global de incompatibilidades | función sin acceso visible | bandeja/Movimientos | `_open_team_review` lógica | A | TM replacement | decidir exposición y paridad | pendiente |
| Eliminar movimiento incompatible | Equipo | inspector/Movimientos | PendingChange/writer | C | TM replacement/live write | confirmación, PP, rollback | pendiente |
| Selector Support para retirar daño | modal específico | diálogo contextual | reglas Support | A | role/move tests | candidatos/ninguno | pendiente |
| Enseñar en slot vacío | botón `+` en Equipo | Movimientos/MT | selector actual | C | TM UI por juego | slot changed/readback | pendiente |
| Sustituir movimiento por MT | Equipo → modal | MT + inspector | PendingTMTeach/writer | C | TM replacement + live suites | preview/consumo/rollback | pendiente |
| Leer inventario MT | al abrir selector | MT | adapters/GameEngine | C | ORAS/SM/USUM/BDSP TM suites | carga, stale, lane opcional | pendiente |
| Fuente ROM/capa real | prompts del selector/Ajustes | Ajustes + estado MT | servicios ROM por juego | C | ROM TM suites | invalidación y explicación | pendiente |
| Tabla/IDs MT | selector | lista MT | perfiles actuales | C | TM profile suites | campos ausentes y localización | pendiente |
| Filtro especie/posesión/rol | selector | compatibilidad de equipo | servicios actuales | C | TM UI | motivos separados | pendiente |
| Movimiento ya conocido | selector | estado por Pokémon | datos actuales | A | TM tests | duplicados/slot | pendiente |
| Consumo de MT/cantidad | autoaplicado/write | operación MT | writer/inventory readback | C | BDSP/3DS live write | antes/después/rollback | pendiente |
| Wizard de drafteo | Drafteos | Drafteos refinado | DraftEngine/RunSession | A | draft/alpha17 | steps y restore | pendiente |
| Elegir rol de drafteo | wizard | stepper | role names/rules | M | role tests | ocupado/no elegible | pendiente |
| Elegir Pokémon | wizard | selector común | proyección | A | drafts | selección persistente | pendiente |
| Generar/reroll movimientos | wizard | candidatos comparables | DraftEngine | A | alpha17 | determinismo/contador | pendiente |
| Elegir slot a sustituir | wizard | resumen | PendingTM/move change | C | TM replacement | incompatibilidad concurrente | pendiente |
| Consumir drafteo | confirmación | Progreso + historial | adjust counter | A | run service | una vez/fallo de write | pendiente |

## 5. Historial, OBS, barra y diagnóstico

| Función actual | Ubicación actual | Destino | Lógica reutilizada | Riesgo | Tests actuales | Tests nuevos | Estado |
|---|---|---|---|---:|---|---|---|
| Ver historial cronológico | Historial | Registro > Actividad | `history()` | M | run service | filtros, tipos desconocidos | pendiente |
| Render eventos por tipo | cards | timeline | event schema actual | A | run service | fixture por cada tipo | pendiente |
| Limpiar historial | botón principal | mantenimiento secundario | `clear_history` | A | — | confirmación/alcance/error | pendiente |
| Marcar evento revertido | historial/review | timeline | undo metadata | A | run service/live review | vínculo original/inversa | pendiente |
| Exportar/abrir carpeta OBS | Configuración | Emisión | ObsSyncService | M | OBS implícito | ruta inválida/permisos | pendiente |
| Publicar contadores/roles/sprites | invisible | preview Emisión | ObsSyncService | A | role/floating suites | comparación de archivos | pendiente |
| Detectar conflictos OBS | cabecera/estado | Emisión/atención | ObsSyncService | A | role tests | mensaje y resolución | pendiente |
| Abrir barra flotante | cabecera | Emisión/acceso rápido | lógica actual | A | floating suites | navegación nueva/foco | pendiente |
| Autoabrir barra al minimizar | ventana raíz | se conserva | Win32/focus logic | C | alpha52/faint floating | todas las páginas/modal nuevo | pendiente |
| Contadores en barra | barra | se conserva refinado | counter service | A | floating tests | automático/manual | pendiente |
| Roles/visibilidad en barra | barra | se conserva refinado | proyección/OBS | A | SM floating roles | drag/teclado | pendiente |
| F5 sincronización | barra/Config/hotkey | estado conexión + atajo | Core/adapters | C | realtime suites | concurrencia/fallo | pendiente |
| Estado corto live | cabecera | indicador persistente | `sync_status` actual como entrada | A | UI suites | tipado/prioridad/stale | pendiente |
| Estado detallado | Configuración | Diagnóstico | diagnostic report | A | realtime core | lane parcial/copiable | pendiente |
| Iniciar grabación | Configuración | Diagnóstico | recorder | M | realtime core | ciclo, cierre, permisos | pendiente |
| Detener/generar paquete | Configuración | Diagnóstico | recorder/export | M | realtime core | acción expresa, error, privacidad | pendiente |
| Abrir replay | Configuración | Diagnóstico | replay parser | M | realtime core | archivo corrupto/cancelación | pendiente |
| Abrir carpeta diagnósticos | Configuración | Diagnóstico | ruta actual | B | — | no existe/permisos | pendiente |
| Toasts de éxito | varias | toast no crítico | handlers actuales | M | UI parciales | duración/foco/duplicado | pendiente |
| Messageboxes informativos | varias | inline/banner cuando proceda | mensajes actuales | A | UI mocks | clasificación y fallback | pendiente |
| Errores de operación | modal/cabecera | panel persistente | excepción + diagnostics | C | live recovery | causa, retry, rollback | pendiente |

## 6. Ajustes, hotkeys y seguridad

| Función actual | Ubicación actual | Destino | Lógica reutilizada | Riesgo | Tests actuales | Tests nuevos | Estado |
|---|---|---|---|---:|---|---|---|
| Idioma | Configuración | Ajustes > Apariencia/idioma | servicio actual | M | — | restart/render | pendiente |
| Cambiar save/fuente | Configuración | Ajustes > Run y fuentes | profile/load | C | game source | pendientes, invalidación live | pendiente |
| Datos de run | Configuración | Ajustes > Run | RunProjectService | A | run service | migración/validación | pendiente |
| Ruta OBS | Configuración | Ajustes + Emisión | ObsSyncService | A | — | permisos/cancelación | pendiente |
| Hotkeys globales | Configuración | Ajustes > Atajos | WindowsHotkeyManager | A | hotkey implícito | conflicto/captura/disabled | pendiente |
| Atajos de contadores | global | se conserva | hotkey mapping | A | automatic counters | juego automático y numpad | pendiente |
| Alt+1…6 visibilidad | global | se conserva/documenta | hotkey mapping | A | floating roles | foco y conflicto | pendiente |
| F5 | global | se conserva | hotkey mapping/Core | C | realtime suites | operación ya en curso | pendiente |
| Ctrl+Z/redo | global UI | Centro de cambios | edit snapshots | A | role/TM | foco de inputs | pendiente |
| Backups de save | invisible/carpeta | Ajustes > Seguridad | SaveService | C | save service/engine | mostrar sin permitir borrar | pendiente |
| Reemplazo atómico y restore | operación Guardar | sin cambio visual salvo estado | SaveService | C | engine/save tests | simulación de fallo | pendiente |
| Cierre con pendientes | WM_DELETE | diálogo/centro | `_on_close` | C | live recovery | realtime/save/diagnóstico activo | pendiente |

## 7. Paridad por backend

Estas filas impiden que una vista genérica borre diferencias demostradas.

| Capacidad | Clásicos DS/5ª | ORAS | X/Y | SM | USUM | BDSP | Regla de migración |
|---|---|---|---|---|---|---|---|
| Modelo de cambio | save pendiente | realtime + save | realtime + save | realtime + save | realtime + save | realtime + save | badge de procedencia obligatorio |
| Transporte | archivo | Azahar RPC | Azahar/Citra | Azahar RPC | Azahar RPC | Ryujinx HostMapped | no abstraer errores en “desconectado” genérico |
| Party live | no | sí | sí | sí | sí | sí | consumir snapshot existente |
| PC live | no | capacidad específica | específica | matriz validada | matriz validada | matriz validada | conservar último valor válido ante fallo |
| Escrituras | save | por capacidad | por capacidad | por capacidad | por capacidad | por capacidad | control visible solo si capability permite |
| Medallas/progreso automático | no demostrado | sí | sí | Kahunas/medallas | Kahunas/medallas | flags BDSP | etiqueta específica y fuente |
| Selector baja | manual/no realtime | live | live | live | live | live | no cambiar temporización del monitor |
| MT | save/perfil | ROM+inventario | capa efectiva | ROM+mochila | ROM+mochila | Masterdatas+mochila | IDs y disponibilidad por juego |
| Utilidades | save si soporta | específicas | específicas | específicas | específicas | tres validadas | no mostrar paridad ficticia |

## 8. Criterio de paridad

Una fila no pasa a `paridad` hasta que:

1. el control clásico y el nuevo producen el mismo comando semántico;
2. se han cubierto vacío, carga, éxito, bloqueo, error y cancelación;
3. las pruebas de backend existentes siguen intactas;
4. existe regresión de presentación nueva;
5. una prueba manual mínima valida cualquier interacción dependiente de timing,
   foco, emulador o RAM;
6. la interfaz clásica sigue disponible como rollback hasta completar toda la
   sección funcional.

