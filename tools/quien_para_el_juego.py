"""¿Quién para el juego? Mide, no supone. No escribe nada.

El usuario reporta que el sonido del juego se corta **justo cuando RoleRun tiene
el foco**, y que vuelve al pulsar cualquier otra aplicación —no hace falta que
sea el emulador—. Eso descarta la explicación cómoda: si fuera Ryujinx
pausándose al perder el foco, con Chrome delante tampoco lo tendría y el sonido
tampoco volvería.

Van tres hipótesis vivas y no hay con qué elegir entre ellas:

1. Ryujinx se pausa por algo que RoleRun hace **solo mientras está delante**.
2. RoleRun le quita CPU al emulador justo en esa situación.
3. Es cosa de Windows y RoleRun solo coincide.

Esta herramienta las separa. Cada segundo apunta cuatro cosas a la vez:

===================  =========================================================
reloj del juego      si avanza, el juego corre; si se repite, está parado
ventana activa       qué proceso tiene el foco en ese instante
CPU de RoleRun       cuánto está gastando
CPU de Ryujinx       cuánto está gastando
===================  =========================================================

Con eso, la correlación se ve sola: si el reloj se para **solo** en las filas
donde el foco es RoleRun, es RoleRun. Si además su CPU se dispara ahí, es que le
está quitando el sitio. Y si el reloj se para con el foco en cualquier sitio, no
es RoleRun.

**Hay que trastear mientras corre**: pasar el ratón por RoleRun, pinchar en otra
ventana, volver. Lo interesante son los cambios.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

from app.bdsp_live import BDSP_SP_130_HOST_PROFILE, read_bdsp_play_time  # noqa: E402
from app.ryujinx_host_memory import RyujinxHostMappedClient  # noqa: E402
from app.ventana_activa import proceso_en_primer_plano  # noqa: E402

SEGUNDOS = 30

_PROCESS_QUERY_LIMITED = 0x1000
_TH32CS_SNAPPROCESS = 0x00000002


class _Entrada(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260),
    ]


def procesos() -> dict[int, str]:
    """PID → nombre del ejecutable, de todo lo que corre ahora."""
    salida: dict[int, str] = {}
    kernel = ctypes.windll.kernel32
    kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    foto = kernel.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not foto or foto == ctypes.c_void_p(-1).value:
        return salida
    try:
        entrada = _Entrada()
        entrada.dwSize = ctypes.sizeof(_Entrada)
        kernel.Process32First.argtypes = (ctypes.c_void_p, ctypes.POINTER(_Entrada))
        kernel.Process32Next.argtypes = (ctypes.c_void_p, ctypes.POINTER(_Entrada))
        if not kernel.Process32First(ctypes.c_void_p(foto), ctypes.byref(entrada)):
            return salida
        while True:
            salida[int(entrada.th32ProcessID)] = entrada.szExeFile.decode(
                "latin-1", errors="replace",
            )
            if not kernel.Process32Next(ctypes.c_void_p(foto), ctypes.byref(entrada)):
                break
    finally:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(foto))
    return salida


def cpu_usada(pid: int) -> float | None:
    """Segundos de CPU que lleva gastados ese proceso, o ``None``."""
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = ctypes.c_void_p
    mango = kernel.OpenProcess(_PROCESS_QUERY_LIMITED, False, int(pid))
    if not mango:
        return None
    try:
        creacion = wintypes.FILETIME()
        salida = wintypes.FILETIME()
        kernel_t = wintypes.FILETIME()
        usuario = wintypes.FILETIME()
        ok = kernel.GetProcessTimes(
            ctypes.c_void_p(mango), ctypes.byref(creacion), ctypes.byref(salida),
            ctypes.byref(kernel_t), ctypes.byref(usuario),
        )
        if not ok:
            return None

        def a_segundos(ft: wintypes.FILETIME) -> float:
            return ((int(ft.dwHighDateTime) << 32) | int(ft.dwLowDateTime)) / 1e7

        return a_segundos(kernel_t) + a_segundos(usuario)
    finally:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(mango))


def _busca(nombres: dict[int, str], parte: str) -> int | None:
    """El primer proceso cuyo nombre contenga eso, sin contarse a sí mismo.

    Esta herramienta también es un `python.exe`, así que sin la exclusión se
    elegiría a sí misma como RoleRun y mediría su propia CPU.
    """
    import os

    parte = parte.lower()
    yo = os.getpid()
    for pid, nombre in nombres.items():
        if pid != yo and parte in nombre.lower():
            return pid
    return None


def main() -> int:
    print()
    print("  QUIEN PARA EL JUEGO - solo lectura, no escribe nada")
    print()
    nombres = procesos()
    pid_ryujinx = _busca(nombres, "ryujinx")
    pid_rolerun = _busca(nombres, "rolerun") or _busca(nombres, "python")
    if pid_ryujinx is None:
        print("  No encuentro Ryujinx abierto.")
        return 1
    print(f"  Ryujinx  pid {pid_ryujinx}   ({nombres.get(pid_ryujinx)})")
    print(f"  RoleRun  pid {pid_rolerun}   ({nombres.get(pid_rolerun)})")
    print()
    try:
        cliente = RyujinxHostMappedClient(BDSP_SP_130_HOST_PROFILE)
        cliente.connect()
    except Exception as error:
        print(f"  No se pudo conectar al juego: {error}")
        return 1

    print(f"  Durante {SEGUNDOS} segundos: trastea. Pon RoleRun delante, pincha")
    print("  en otra ventana, vuelve. Lo interesante son los cambios.")
    print()
    print("   seg  juego   ventana activa        CPU RoleRun  CPU Ryujinx")
    print("   ---  ------  --------------------  -----------  -----------")

    anterior_reloj = None
    anterior_cpu: dict[int, float] = {}
    for segundo in range(SEGUNDOS):
        reloj = read_bdsp_play_time(cliente)
        activo = proceso_en_primer_plano()
        quien = nombres.get(int(activo or 0)) or procesos().get(int(activo or 0), "?")
        avanza = "corre " if reloj != anterior_reloj else "PARADO"
        if anterior_reloj is None:
            avanza = "  ?   "
        anterior_reloj = reloj

        gastos = []
        for pid in (pid_rolerun, pid_ryujinx):
            actual = cpu_usada(pid) if pid else None
            if actual is None:
                gastos.append("     ?     ")
                continue
            previo = anterior_cpu.get(pid)
            anterior_cpu[pid] = actual
            gastos.append(
                "     -     " if previo is None else f"   {100*(actual-previo):5.1f}%  "
            )
        print(f"   {segundo:>3}  {avanza}  {str(quien)[:20]:<20}  "
              f"{gastos[0]}  {gastos[1]}")
        time.sleep(1.0)

    print()
    print("  Como leerlo:")
    print("   - PARADO solo con RoleRun delante  -> lo para RoleRun")
    print("   - PARADO con cualquier ventana     -> no es RoleRun")
    print("   - PARADO y la CPU de RoleRun alta  -> le esta quitando el sitio")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
