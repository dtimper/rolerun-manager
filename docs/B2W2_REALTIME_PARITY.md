# B2/W2 / melonDS — matriz maestra de paridad realtime

Fecha de corte: 2026-08-26. Objetivo de versión: `v0.2.6`.

Esta lista cerrada impide olvidar capacidades al llevar B2/W2 al nivel de los
backends 3DS y BDSP. Paridad significa reproducir comportamiento, no reutilizar
direcciones, estructuras o writers. Cada unidad debe demostrarse para juego,
revisión, región y melonDS concretos.

| Área | Capacidad completa de referencia | Estado B2/W2 | Evidencia siguiente |
|---|---|---|---|
| Sesión | Proceso, juego/revisión, conexión, reconexión e invalidación | Negro 2 España/melonDS 1.1 conectado: **VALIDADO**; reconexión **PENDIENTE** | Cerrar/reabrir melonDS y demostrar resincronización |
| Seguridad | Candidato único, doble lectura, identidad save, stale y lanes aislados | Party: **IMPLEMENTADO · TEST · VALIDADO** | Extender por separado a cada lane |
| Equipo | Conteo, identidad, orden, especie, forma, apodo y huevo | Conteo, identidad, orden y seis miembros **VALIDADOS FÍSICAMENTE**; forma/apodo/huevo **IMPLEMENTADOS** | Equipo controlado con forma/apodo/huevo |
| Ficha | Nivel, PS, estado, stats, naturaleza, IV y EV | IV/EV/nivel/PS **VALIDADOS FÍSICAMENTE**; resto **IMPLEMENTADO · TEST** | Cambiar estado/naturaleza y observar UI |
| Ataques | IDs, orden, PP, PP Up, habilidad y objeto | Movimientos/habilidad/objeto **VALIDADOS FÍSICAMENTE**; PP interno sin presentación visual | Gastar PP para contrastar reader mediante diagnóstico, no UI |
| Roles | Leer seis marcas y actualizar ficha/barra/OBS · **escribir rol y EV** | Lectura y writer de rol+EV con recálculo de estadísticas: **IMPLEMENTADO · TEST · VALIDADO FÍSICAMENTE** (27-08-2026, alpha.24/25) | Repetir con Líbero y sus dos características elegidas |
| Combate | Entrada/salida, filas, identidad, PS, cambio y animación | **IMPLEMENTADO · TEST · VALIDADO FÍSICAMENTE**, incluido el daño en tiempo real (alpha.32). Limitación demostrada: durante el combate solo se conoce el PS del Pokémon **activo**; el resto sale del bloque de party, que Gen 5 no actualiza hasta el final | Probar cambio con varios miembros y otros estados |
| Muertes | Baseline, >0→0, varios KO, selector, sustituto y evento único | **VALIDADO FÍSICAMENTE** al completo (27-08-2026, alpha.32): daño y KO en el momento, descuento de vida, selector, sustitución y recuperación al curar | Repetir con varias bajas seguidas y con estados alterados |
| PC lectura | Dimensiones, nombres/caja actual, matriz y vacíos válidos | Matriz 24×30: **DEMOSTRADA · IMPLEMENTADA · TEST · VALIDADA FÍSICAMENTE** | Contrastar nombres de cajas y otras cajas ocupadas |
| PC cambios externos | PC↔PC y Equipo↔PC por identidad | **IMPLEMENTADO · TEST · VALIDADO FÍSICAMENTE** (27-08-2026, Negro 2 España/melonDS 1.1, alpha.19). Hasta alpha.18 el sondeo era inalcanzable: exigía una página `"pc"` a la que la vista unificada no llega | Repetir con varias cajas y con el equipo lleno |
| PC escritura | Swap, depósito, retirada, compactación, tamaño 1–6 | PC→PC, 1:1 y **tamaño 1–6: VALIDADO FÍSICAMENTE** (retirada 5→6 confirmada el 27-08-2026 en Negro 2 España/melonDS 1.1 tras corregir B1 en alpha.16). Hasta alpha.15 la fila decía «TEST» sin que existiera ninguna prueba del writer, y la retirada no podía superar su propio readback | Repetir con objeto equipado y con el equipo lleno |
| Sustitución | Baja→Cementerio, sustituto, rol heredado | **IMPLEMENTADO · TEST · VALIDADO FÍSICAMENTE** (27-08-2026, Negro 2 España/melonDS 1.1, alpha.30) | Repetir con el equipo lleno y con varias bajas seguidas |
| Mochila | Bolsillos, MT/cantidades y utilidades | **ANCLA DEMOSTRADA** (27-08-2026): bolsillo de medicinas en `0x0221E17C`, pares (id, cantidad) de 16 bits, confirmado con dos estados (Poción 2→3 en esa misma dirección) y corroborado por un Antiparalizador contiguo que la búsqueda no pedía. Falta mapear el resto de bolsillos | Ejecutar `mapear_mochila_b2w2.bat` |
| MT/drafteo | Compatibilidad, posesión, enseñar/borrar y consumo Gen 5 | Lectura de ataques lista; resto **PENDIENTE** | Reader mochila antes de cualquier writer |
| Curación | PS, estado y PP de todo el equipo | **IMPLEMENTADO · TEST · VALIDADO FÍSICAMENTE** (27-08-2026, Negro 2 España/melonDS 1.1, alpha.26). PP base Gen 5 extraídos de PKHeX.Core | Repetir con Más PP y varios estados alterados |
| Utilidades | Caramelo Raro, Repelente Máximo y dinero | Dinero: **ANCLA DEMOSTRADA** en `0x022266A4`, u32, confirmado con dos estados (4524→4224). Objetos, pendientes del mapa de bolsillos. Writer cerrado | Confirmar el dinero tras reiniciar el juego |
| Progreso | Medallas/gimnasios sin retroceso ni duplicado | **PENDIENTE** | Flags antes/después de medalla |
| UI | Barra, ficha, PC, avisos live/stale/inválido y compuertas | Equipo y miembros SIN ROL en barra **VALIDADOS FÍSICAMENTE**; resto por lane | Validación visible por incorporación |
| Estado | Run, historial, contadores, metadata PC y recuperación | Base común activa; integración **PENDIENTE** | Regresión por evento |
| Salidas | OBS y barra flotante sin guardar | Equipo/PS **VALIDADOS**; resto **PENDIENTE** | Validación por evento |
| Diagnóstico | Log por lane, grabación/replay y fixture anonimizado | Party diagnosticada; replay específico **PENDIENTE** | Captura reproducible |

## Orden seguro

1. validar los metadatos del PK5 ya demostrado;
2. instrumentar batalla y KO sin escribir;
3. leer PC y reconciliar cambios externos;
4. leer mochila/MT y progreso;
5. abrir writers uno por uno: roles/movimientos/curación, utilidades y por
   último cambios de tamaño Equipo↔PC;
6. validar recorridos combinados de reconexión, persistencia, historial y OBS.
