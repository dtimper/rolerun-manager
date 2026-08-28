"""¿Se quedó el juego colgado? Lee la traza de BDSP y lo dice. No escribe nada.

RoleRun anota en cada captura el reloj del juego —horas, minutos y segundos de
`PlayerWork._saveData`— y quién tiene la ventana activa. Con esas dos cosas un
tramo sin avanzar deja de ser ambiguo:

===================  ==========  ==========================================
reloj parado         con foco    **el juego está colgado**
reloj parado         sin foco    normal: el emulador está en pausa
reloj avanzando      cualquiera  el juego corre
===================  ==========  ==========================================

Hizo falta porque la traza no podía ver un congelado: tras la escritura de una MT
siguió leyendo con normalidad 68 segundos, ya que un juego colgado se ve igual
desde fuera —proceso vivo, memoria legible— y con el personaje quieto ni los PS
ni el equipo cambian.

Y hizo falta el foco porque el reloj **también** se para al perder la ventana:
medido, 24,5 segundos parado solo por abrir RoleRun.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

from app.config import LOG_DIR  # noqa: E402

RUTA = LOG_DIR / "bdsp_realtime_trace_latest.jsonl"

#: Por debajo de esto es ruido: entre dos capturas hay 0,75 s y el reloj del
#: juego solo tiene resolucion de segundo.
UMBRAL = 2.0


def cargar() -> list[dict]:
    if not RUTA.is_file():
        return []
    filas = []
    for linea in RUTA.read_text(encoding="utf-8", errors="replace").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            filas.append(json.loads(linea))
        except Exception:
            continue
    return filas


def segundos(reloj) -> int | None:
    try:
        return int(reloj[0]) * 3600 + int(reloj[1]) * 60 + int(reloj[2])
    except Exception:
        return None


def tramos(filas: list[dict]) -> list[dict]:
    """Cada racha en la que el reloj del juego no avanzo."""
    capturas = [
        f for f in filas
        if f.get("event") == "snapshot" and segundos(f.get("reloj")) is not None
    ]
    salida: list[dict] = []
    abierto: dict | None = None
    for anterior, siguiente in zip(capturas, capturas[1:]):
        avanzo = segundos(siguiente["reloj"]) != segundos(anterior["reloj"])
        if avanzo:
            if abierto is not None:
                abierto["fin"] = anterior["timestamp"]
                salida.append(abierto)
                abierto = None
            continue
        if abierto is None:
            abierto = {
                "inicio": anterior["timestamp"],
                "reloj": anterior["reloj"],
                "con_foco": 0,
                "sin_foco": 0,
                "sin_saber": 0,
            }
        foco = siguiente.get("foco")
        clave = "sin_saber" if foco is None else ("con_foco" if foco else "sin_foco")
        abierto[clave] += 1
        abierto["fin"] = siguiente["timestamp"]
    if abierto is not None:
        salida.append(abierto)
    return salida


def main() -> int:
    filas = cargar()
    print()
    if not filas:
        print("  No hay traza de BDSP todavia.")
        print(f"  Se buscaba en: {RUTA}")
        return 1

    version = filas[-1].get("version", "?")
    con_reloj = [f for f in filas if f.get("event") == "snapshot" and f.get("reloj")]
    print(f"  Traza: {RUTA.name}   ({len(filas)} anotaciones, version {version})")
    print(f"  capturas con reloj ....... {len(con_reloj)}")
    print()

    if not con_reloj:
        print("  Ninguna captura trae el reloj. Hace falta la 0.2.6-alpha.114")
        print("  o posterior, y volver a abrir RoleRun con la partida cargada.")
        return 1

    colgados, pausas, dudosos = [], [], []
    for tramo in tramos(filas):
        duracion = float(tramo["fin"]) - float(tramo["inicio"])
        if duracion < UMBRAL:
            continue
        # Tres cajones, no dos. Con el foco desconocido no se puede decir que
        # fuera una pausa normal: eso seria inventarse la respuesta.
        if tramo["con_foco"] > max(tramo["sin_foco"], tramo["sin_saber"]):
            colgados.append((tramo, duracion))
        elif tramo["sin_foco"] > tramo["sin_saber"]:
            pausas.append((tramo, duracion))
        else:
            dudosos.append((tramo, duracion))

    if colgados:
        print("  EL JUEGO SE QUEDO COLGADO:")
        for tramo, duracion in colgados:
            cuando = datetime.fromtimestamp(tramo["inicio"]).strftime("%H:%M:%S")
            print(f"     {cuando}   {duracion:5.1f}s parado, con el juego en primer plano")
            print(f"                 el reloj se quedo en {tramo['reloj']}")
    else:
        print("  No se vio ningun tramo parado con el juego en primer plano.")

    print()
    print(f"  pausas normales (sin foco, de {UMBRAL:.0f}s o mas): {len(pausas)}")
    for tramo, duracion in pausas[:8]:
        cuando = datetime.fromtimestamp(tramo["inicio"]).strftime("%H:%M:%S")
        print(f"     {cuando}   {duracion:5.1f}s   (mirando otra ventana)")

    if dudosos:
        print()
        print(f"  tramos parados sin saber quien tenia la ventana: {len(dudosos)}")
        print("  (capturas anteriores a la 0.2.6-alpha.115, que aun no lo anotaba)")
        for tramo, duracion in dudosos[:8]:
            cuando = datetime.fromtimestamp(tramo["inicio"]).strftime("%H:%M:%S")
            print(f"     {cuando}   {duracion:5.1f}s")

    arrastres = [
        f for f in filas if str(f.get("event", "")).startswith("arrastre.")
    ]
    if arrastres:
        print()
        print("  arrastres de esta traza:")
        for f in arrastres[-25:]:
            cuando = datetime.fromtimestamp(f["timestamp"]).strftime("%H:%M:%S")
            extra = " ".join(
                f"{k}={v}" for k, v in f.items()
                if k not in ("version", "timestamp", "event")
            )
            print(f"     {cuando}   {str(f['event']):<22} {extra}")
        print()
        print("  un 'empieza' sin su 'se_mueve' es un arrastre que se quedo")
        print("  en el sitio: el raton se movio y el aviso no llego al widget.")

    escrituras = [f for f in filas if f.get("event") == "write-verified"]
    if escrituras:
        print()
        print("  escrituras de esta traza:")
        for f in escrituras:
            cuando = datetime.fromtimestamp(f["timestamp"]).strftime("%H:%M:%S")
            cambios = f.get("cambios") or []
            que = ", ".join(
                f"{c.get('tipo')}: {c.get('pokemon', '')} {c.get('new_move', '')}".strip()
                for c in cambios
            ) or f"{f.get('applied_count')} cambio(s)"
            print(f"     {cuando}   reloj {f.get('reloj')}  foco {f.get('foco')}   {que}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
