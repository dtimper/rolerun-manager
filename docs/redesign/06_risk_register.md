# Registro priorizado de riesgos y decisiones

## 1. Hechos demostrados

- `app/ui.py` es la raíz de composición, presentación y orquestación y supera las
  16 000 líneas.
- `render_page()` destruye y reconstruye el body; existe una capa adicional para
  suavizar el reemplazo y preservar scroll.
- Equipo, PC y MT no comparten un espacio de trabajo: PC y MT se abren mediante
  `Toplevel` desde otros contextos.
- El estado visual combina save base, cambios pendientes, snapshots live, caché
  y overrides.
- Los cinco backends realtime usan un Core común, pero estructuras, transports y
  capacidades específicas.
- Los writers ya contienen precondiciones, readback y rollback en sus operaciones
  demostradas; el rediseño no necesita reemplazarlos.
- La barra flotante depende de comportamiento de foco/ventanas Windows y tiene
  regresiones específicas.
- La UI actual se basa en CustomTkinter/Tk y usa workers + `after()` para volver al
  hilo gráfico.

## 2. Problemas observados

- navegación fragmentada para operaciones que comparten Pokémon y contexto;
- tarjetas demasiado altas y exceso de scroll en Equipo;
- funciones importantes poco descubribles y funciones internas sin control;
- estado de conexión/error comprimido en una etiqueta y mensajes transitorios;
- Configuración mezcla preferencias, emisión y diagnóstico;
- Cementerio carece de vista;
- MT solo admite recorrido Pokémon-primero;
- controles y estilos repetidos sin sistema de diseño central;
- alta complejidad de foco por cadenas de ventanas;
- selección, foco y disabled no tienen un contrato accesible uniforme.

## 3. Hipótesis pendientes de medir

- CustomTkinter puede requerir virtualización propia para 1 200 slots;
- una shell modular dentro de Tk puede alcanzar la densidad y accesibilidad
  objetivo sin migrar a Qt;
- una command palette aportaría valor real al usuario;
- algunas funciones internas sin acceso visible pueden ser legado intencional.

Ninguna hipótesis se usa como fundamento de una implementación. La hoja de ruta
incluye la medición o verificación correspondiente.

## 4. Decisiones técnicas ya fundamentadas

- mantener readers/writers/Core y poner una capa de presentación delante;
- diferenciar capabilities en tiempo de ejecución;
- mantener UI clásica con flag;
- empezar por pantallas de solo lectura;
- modelar confirmado/proyectado/pendiente/fallido;
- separar comandos de swap, resize, reorder, rol y sustitución por muerte;
- ofrecer alternativa a drag/drop;
- no decidir Qt antes del benchmark de Equipo/PC;
- migrar selector de bajas sin cambiar detección ni temporización.

## 5. Decisiones de producto abiertas

Se limitan a densidad, nombres, confirmación de swaps reversibles, tamaño de
sprites, command palette y juego piloto. Están desarrolladas en
`05_open_questions.md` con un default recomendado.

## 6. Riesgos priorizados

| Prioridad | Riesgo | Tipo | Daño posible | Mitigación / prueba |
|---:|---|---|---|---|
| P0 | UI nueva emite comando contra identidad/slot stale | datos/RAM | Pokémon equivocado o corrupción | preflight inmediato, identidad estable, writer actual, readback, rollback |
| P0 | proyección se muestra como confirmada | sincronización | usuario actúa sobre estado falso | estado tipado y badge pendiente hasta readback |
| P0 | vista genérica habilita capacidad no demostrada | específico por juego | escritura inválida | capability matrix fail-closed y tests por backend |
| P0 | swap se reutiliza para 5↔6 o baja | funcional | séptimo miembro, duplicado, pérdida | comandos y pruebas independientes |
| P0 | selector nuevo altera timing de muerte | realtime | cobro temprano/tardío o duplicado | no tocar monitor; replay y validación física |
| P1 | dos fuentes de verdad entre UI clásica/nueva | datos | vistas divergentes | view model de solo lectura sobre autoridades comunes; nunca persistencia propia |
| P1 | selección cambia durante poll/reconciliación | sincronización | acción sobre otro Pokémon | selección por identidad, invalidación y cancelación del comando |
| P1 | cierre/cambio de run pierde operación | datos | cambio pendiente olvidado | Centro de operaciones y mismas barreras de cierre actuales |
| P1 | modal/barra bloquea foco | UI/Windows | app aparentemente congelada | migración modal a modal, suites floating y prueba física Windows |
| P1 | error de lane opcional invalida party | realtime | equipo desaparece | conservar lane válido y señalar error acotado |
| P1 | render masivo bloquea loop Tk | rendimiento | congelación, timer atrasado | benchmark, actualización localizada, workers sin tocar widgets |
| P1 | PC completo consume demasiados widgets/sprites | rendimiento | apertura lenta/memoria | render por caja, caché acotada, virtualización si la medición lo exige |
| P2 | color comunica rol/estado sin texto | accesibilidad | información perdida | chips con símbolo+nombre, foco, contraste |
| P2 | drag es única ruta | accesibilidad | operación imposible con teclado | botón/menú equivalente y grid navegable |
| P2 | fixed sizes fallan con DPI | visual | clipping/scroll excesivo | matriz de resolución/DPI y layouts responsive |
| P2 | migrar a Qt rompe empaquetado/hotkeys | tecnología | distribución inestable | prototipo aislado y decisión separada después de métricas |
| P2 | outputs OBS cambian durante rediseño | integración | escenas rotas | conservar ObsSyncService y comparar salidas |
| P3 | terminología nueva confunde | producto | curva de aprendizaje | labels directos, ayuda contextual, preferencias revisables |

## 7. Riesgos específicos por familia

### Saves clásicos

- ocultar Guardar/Descartar o sugerir aplicación instantánea;
- cerrar sin consolidar;
- confundir save preparado con juego ya actualizado.

### 3DS

- presentar Azahar y Citra como transporte idéntico;
- compartir capacidades/errores entre ORAS, X/Y, SM y USUM;
- hacer que una lectura pesada de PC/MT vuelva al hilo Tk;
- invalidar snapshot completo por un lane opcional.

### BDSP/Ryujinx

- reactivar GDB como requisito cuando HostMapped es el transporte permanente;
- confundir objetos runtime, copias de save y BattleProc;
- mantener polls de PC fuera de su página;
- romper contratos físicos de SP 1.3.0 al generalizar otro juego.

## 8. Riesgos de empaquetado y mantenimiento

- una dependencia GUI nueva aumenta tamaño, DLLs, licencias y superficie de
  antivirus/instalación;
- mantener dos frameworks dentro del mismo proceso añade loops y foco difíciles
  de probar;
- duplicar assets y estilos durante mucho tiempo puede divergir;
- retirar la UI clásica antes de paridad elimina el rollback más barato.

Por ello la opción recomendada no añade framework en las fases iniciales y limita
la dualidad a dos capas de presentación sobre los mismos servicios.

