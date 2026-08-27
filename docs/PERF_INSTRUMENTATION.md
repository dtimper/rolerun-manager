# Instrumentación de rendimiento (`ROLERUN_PERF`)

Fase 1 de la auditoría técnica del 27-08-2026. Su único propósito es **sustituir
hipótesis por mediciones reales en Windows** antes de tocar arquitectura.

La regla fundamental del proyecto —ninguna implementación por suposición— se
aplica también al rendimiento: no se optimiza lo que parece lento, se optimiza
lo que se ha medido lento en la máquina real, con su NTFS y su antivirus.

## Cómo se activa

```bash
ROLERUN_PERF=1 py -3 main.py
```

Cualquiera de `1`, `true`, `yes`, `on`, `si`, `sí` la enciende. Sin la variable
—el caso normal del usuario— la instrumentación está **apagada** y su coste es
exactamente cero: `perf.timed` devuelve la función original sin envolverla, así
que no hay ni una llamada extra ni un `perf_counter` de más.

El estado se congela al importar. Una sesión entera se mide o no se mide; no hay
mezclas a medias que hagan irreproducible una comparación.

## Dónde escribe

`Documents/RoleRun Manager/Logs/perf_<AAAA-MM-DD>.jsonl`, una línea JSON por
operación:

```json
{"t": "2026-08-27T04:12:33.481", "op": "engine.run", "ms": 214.7, "thread": "tk", "command": "read"}
```

- `thread` vale `tk` cuando la operación corrió en el hilo de la interfaz. Es el
  campo más importante del registro: todo lo que aparezca como `tk` y dure
  decenas de milisegundos es congelación percibida por el usuario.
- Los campos extra dependen de la operación (`command`, `adapter`, `regions`,
  `events`, `changes`, `error`…).

La escritura **nunca ocurre en el hilo medido**: los registros se encolan y los
vuelca un hilo demonio propio. Si escribiéramos el JSONL desde el hilo Tk
estaríamos midiendo nuestra propia instrumentación en lugar del programa.

## Qué se mide y por qué

| Operación | Punto | Qué pregunta responde |
|---|---|---|
| `engine.run` | `save_engine_client._run` | Coste real de cada invocación del motor .NET, separado por comando (`read`, `read-boxes`, `valid-moves`, escrituras). |
| `realtime.capture_monitor` · `capture_full` · `read_pc` · `apply_changes` | `realtime/core.py` | Coste por ciclo y por backend. El Core es el único punto por el que pasan los seis juegos, así que la comparativa sale sin tocar ningún adaptador. |
| `b2w2.region_walk` | `b2w2_live._read_process` | Regiones y allocations recorridas por ciclo en melonDS. Dimensiona la caché de base que plantea la Fase 5. |
| `b2w2.read_party` · `b2w2.read_pc` | `b2w2_live` | Las dos lecturas caras de B2/W2. |
| `ui.smooth_render_page` · `ui.render_page` | `ui.py` | La reconstrucción total de página, señalada como el bloqueo dominante del hilo Tk. |
| `ui.navigation_transition` | `ui.py` | `ImageGrab.grab` + `ImageEnhance` por navegación. |
| `ui.poll_gamepad` | `ui.py` | Bucle de 60 Hz. **Se agrega por ventana de un segundo**, no línea por tick: 3.600 líneas por minuto convertirían la medición en el problema. |
| `ui.save_pending_changes` · `ui.save_live_changes` · `ui.finalize_live_changes` | `ui.py` | La cadena completa de una confirmación. |
| `ui.start_team_pc_load` · `ui.finish_team_pc_load` | `ui.py` | La cascada posterior a una escritura. |
| `ui.reload_from_watched_save` | `ui.py` | La micro-congelación tras guardar dentro del juego. |
| `obs.sync` | `obs_sync.py` | Los 24 archivos por sincronización, en NTFS con antivirus. |
| `run.append_history` | `run_service.py` | Reescritura completa del historial por evento, con su número de eventos para ver la pendiente. |

## Garantías

- **No cambia el comportamiento.** Se conservan valor de retorno, excepciones y
  firma. Los errores se anotan en el campo `error` y se vuelven a lanzar.
- **No puede tumbar una operación real.** Todo el camino de registro está
  protegido; un fallo de disco pierde la muestra y nada más. `record` se invoca
  desde bloques `finally`, así que su cuerpo entero está dentro de un `try`.
- **No rompe la suite existente.** `functools.wraps` conserva `__wrapped__` e
  `inspect.getsource` lo desenvuelve, de modo que los tests que afirman «esta
  cadena existe en el cuerpo de este método» siguen siendo válidos con la
  medición encendida.
- **Cota de memoria.** Si el disco no acompaña, el buffer se limita y se pierden
  muestras antes que crecer sin control.

Las regresiones están en `tests/test_perf_instrumentation.py`, incluida una que
falla si alguien borra un punto de medición acordado.

## Mediciones ya obtenidas en esta máquina

| Medida | Valor | Método |
|---|---|---|
| Suelo por invocación del motor .NET | **~72 ms** (mín. 71,1 · mediana 72,4) | 7 repeticiones de `RoleRun.SaveEngine.exe` sin argumentos, sin abrir ningún save. |
| `run.append_history` con historial de 1–3 eventos | **2,5 – 8,1 ms** | Ejecución real contra `Documents`, NTFS. |

El suelo de ~72 ms es **antes** de cargar PKHeX.Core y de leer la partida: lo
paga íntegro cada una de las invocaciones. Con la carga de una run encadenando
`inspect` + `read` + `valid-moves` + `read-boxes`, son ya ≥290 ms de puro
arranque de procesos, y `save_pending_changes` ejecuta `N+k+2` de estas
invocaciones **en el hilo Tk**.

Pendiente de medir con partida real cargada: el coste añadido de PKHeX.Core y
del propio save por comando, el render completo en Windows, `ImageGrab.grab`,
`obs.sync` con antivirus y el walk de `VirtualQueryEx` de melonDS.
