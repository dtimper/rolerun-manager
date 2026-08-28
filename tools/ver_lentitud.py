"""Lee el JSONL de tiempos y cuenta dónde se van los segundos.

Se usa después de `medir_lentitud.bat`: ese abre RoleRun midiendo, y este
resume lo medido en algo que se pueda pegar en una conversación.

Dos vistas, porque responden a preguntas distintas:

1. **Cada vez que sueltas un Pokémon**, la línea de tiempo completa desde que lo
   sueltas hasta que el estado deja de decir «aplicando». Es el número que el
   usuario cuenta con el reloj.
2. **El reparto por operación**, para ver qué se repite mucho aunque cada vez
   cueste poco.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import LOG_DIR  # noqa: E402

# La consola de un .bat es cp1252. Un carácter fuera de esa tabla no da un
# renglón raro: revienta la herramienta entera con UnicodeEncodeError.
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

# Un estado que ya no es «en marcha»: aquí es donde el usuario deja de esperar.
ESTADOS_FINALES = {"done", "failed", "warning", "ready", "idle"}
# Por debajo de esto no merece la pena ni mirarlo.
UMBRAL_MS = 8.0


def cargar() -> tuple[Path | None, list[dict]]:
    archivos = sorted(LOG_DIR.glob("perf_*.jsonl"))
    if not archivos:
        return None, []
    ruta = archivos[-1]
    registros = []
    for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            registros.append(json.loads(linea))
        except Exception:
            continue
    registros.sort(key=lambda r: r.get("t", ""))
    return ruta, ultima_sesion(registros)


def ultima_sesion(registros: list[dict]) -> list[dict]:
    """Se queda con la ultima vez que se abrio RoleRun.

    El JSONL es uno por dia y se abre en modo anadir: un dia de trabajo mezcla
    varias sesiones. Sin este corte, el resumen suma reconstrucciones de
    sesiones anteriores y no hay forma de saber si un arreglo funciono.
    """
    for indice in range(len(registros) - 1, -1, -1):
        if registros[indice].get("op") == "sesion.inicio":
            return registros[indice:]
    # Mediciones anteriores a la marca: se corta por un silencio largo, que es
    # lo que deja cerrar el programa y volver a abrirlo.
    corte = 0
    for indice in range(1, len(registros)):
        anterior = instante(registros[indice - 1])
        actual = instante(registros[indice])
        if anterior and actual and (actual - anterior).total_seconds() > 20:
            corte = indice
    return registros[corte:]


def instante(registro: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(registro["t"])
    except Exception:
        return None


def lineas_de_tiempo(registros: list[dict]) -> None:
    sueltas = [i for i, r in enumerate(registros) if r.get("op") == "ui.drop.soltado"]
    if not sueltas:
        print("  No hay ningun 'soltar' registrado. Se arrastro algun Pokemon")
        print("  mientras corria medir_lentitud.bat?")
        return

    for numero, inicio in enumerate(sueltas, 1):
        cero = instante(registros[inicio])
        if cero is None:
            continue
        cabecera = registros[inicio]
        print()
        print(f"  -- SOLTAR #{numero}: "
              f"{cabecera.get('origen', '?')} -> {cabecera.get('destino', '?')} "
              f"({cabecera.get('t', '')[11:]})")

        total = None
        for registro in registros[inicio + 1:]:
            momento = instante(registro)
            if momento is None:
                continue
            delta = (momento - cero).total_seconds() * 1000.0
            if delta > 30000:                      # 30 s: ya no es esta acción
                break
            op = str(registro.get("op", ""))
            if op == "ui.drop.soltado":
                break                              # empieza la siguiente
            ms = float(registro.get("ms", 0.0) or 0.0)
            if registro.get("kind") == "mark":
                extra = " ".join(
                    f"{k}={v}" for k, v in registro.items()
                    if k not in {"t", "op", "ms", "thread", "kind"}
                )
                print(f"     {delta:8.0f} ms  |  {op:<34} {extra}")
                if op == "ui.estado" and str(registro.get("estado")) in ESTADOS_FINALES:
                    total = delta
                    break
            elif ms >= UMBRAL_MS:
                print(f"     {delta:8.0f} ms  |  {op:<34} tardo {ms:.0f} ms")

        if total is not None:
            print(f"     {'':8}     TOTAL HASTA EL ESTADO FINAL: {total / 1000:.2f} s")
        else:
            print(f"     {'':8}     (no se vio un estado final en 30 s)")


def reparto(registros: list[dict]) -> None:
    """Cuanto cuesta cada operacion. Solo tiempos individuales.

    Las operaciones de alta frecuencia -el sondeo del mando corre a 60 Hz- se
    anotan resumidas por ventana de un segundo, asi que su `ms` es el total de
    la ventana y no el de una llamada. Mezclarlas con el resto hacia que el
    sondeo del mando pareciera la operacion mas cara de la sesion.
    """
    resumen: dict[str, list[float]] = {}
    agregados: dict[str, list[dict]] = {}
    for registro in registros:
        clase = registro.get("kind")
        if clase == "mark":
            continue
        if clase == "aggregate":
            agregados.setdefault(str(registro.get("op", "?")), []).append(registro)
            continue
        ms = float(registro.get("ms", 0.0) or 0.0)
        resumen.setdefault(str(registro.get("op", "?")), []).append(ms)

    filas = []
    for op, muestras in resumen.items():
        muestras.sort()
        filas.append((
            sum(muestras), len(muestras),
            muestras[len(muestras) // 2], muestras[-1], op,
        ))
    filas.sort(reverse=True)

    print(f"  {'total':>9}  {'veces':>6}  {'mediana':>8}  {'peor':>8}   operacion")
    print(f"  {'-' * 9}  {'-' * 6}  {'-' * 8}  {'-' * 8}   {'-' * 30}")
    for total, veces, mediana, peor, op in filas[:22]:
        if total < 20:
            continue
        print(f"  {total:8.0f}ms  {veces:6d}  {mediana:7.0f}ms  {peor:7.0f}ms   {op}")

    if not agregados:
        return
    print()
    print("  (alta frecuencia, resumido por ventana de un segundo)")
    print(f"  {'por llamada':>12}  {'por segundo':>12}  {'peor':>8}   operacion")
    for op, muestras in sorted(agregados.items()):
        llamadas = sum(int(m.get("count", 0) or 0) for m in muestras)
        total = sum(float(m.get("ms", 0.0) or 0.0) for m in muestras)
        peor = max(float(m.get("max_ms", 0.0) or 0.0) for m in muestras)
        por_segundo = sum(
            float(m.get("calls_per_s", 0.0) or 0.0) for m in muestras
        ) / max(1, len(muestras))
        media = total / llamadas if llamadas else 0.0
        print(f"  {media:11.2f}ms  {por_segundo:9.0f}/s  {peor:7.1f}ms   {op}")


def reconstrucciones(registros: list[dict]) -> None:
    """Cuantas veces se rehizo la pagina entera, y por que.

    Reconstruir cuesta entre 626 y 937 ms medidos -30.255 llamadas a Tcl-, asi
    que cada motivo que aparezca aqui son segundos de espera con nombre.
    """
    motivos: dict[str, int] = {}
    for registro in registros:
        if registro.get("op") == "ui.render.reconstruye":
            motivo = str(registro.get("motivo", "?"))
            motivos[motivo] = motivos.get(motivo, 0) + 1
    en_sitio = sum(1 for r in registros if r.get("op") == "ui.render.en_sitio")
    caros = [
        float(r.get("ms", 0.0) or 0.0)
        for r in registros if r.get("op") == "ui.render_page"
    ]

    if not motivos and not en_sitio:
        print("  (nada anotado: la pagina no se repinto en esta sesion)")
        return
    print(f"  actualizadas en sitio ......... {en_sitio}")
    if caros:
        caros.sort()
        print(f"  reconstruidas ................. {len(caros)}"
              f"   (mediana {caros[len(caros) // 2]:.0f} ms,"
              f" total {sum(caros) / 1000:.1f} s)")
    print()
    for motivo, veces in sorted(motivos.items(), key=lambda par: -par[1]):
        print(f"    {veces:3d} x  {motivo}")


def main() -> int:
    ruta, registros = cargar()
    if ruta is None:
        print()
        print("  No hay ninguna medicion todavia.")
        print(f"  Se buscaba en: {LOG_DIR}")
        print()
        print("  Abre RoleRun con medir_lentitud.bat, haz lo que va lento,")
        print("  cierra el programa y vuelve a ejecutar esto.")
        return 1

    print()
    print(f"  Medicion: {ruta.name}   ({len(registros)} anotaciones)")
    print()
    print("  === CADA VEZ QUE SE SOLTO UN POKEMON ===")
    lineas_de_tiempo(registros)
    print()
    print("  === POR QUE SE RECONSTRUYO LA PAGINA ===")
    print()
    reconstrucciones(registros)
    print()
    print("  === REPARTO POR OPERACION (toda la sesion) ===")
    print()
    reparto(registros)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
