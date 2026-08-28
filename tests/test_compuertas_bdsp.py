"""Lo que el writer sabe escribir tiene que atravesar todas las compuertas.

Al añadir el movimiento dentro del PC, el writer quedó listo y la interfaz lo
ofrecía… pero **dos compuertas de la UI seguían sin conocerlo**. El resultado
fue el peor posible: el cambio se creaba, el rótulo decía «MOVIENDO EN EL PC ·
Verificando Caja 1, posición 11 → Caja 1, posición 3», y ahí se quedaba para
siempre. Nadie llegaba a escribir nada y nada avisaba de ello.

Esas compuertas existen por buenas razones —no aplicar a ciegas una cola entera,
y avisar de lo que no se puede aplicar en vivo—, pero son listas escritas a mano
en sitios distintos del que declara las operaciones. Esta prueba las ata.
"""

from __future__ import annotations

import inspect
import re

from app.bdsp_live import BDSPLiveWriter
from app.ui import RoleRunManager

#: Las que el writer de BDSP sabe ejecutar, cada una con su transacción propia.
OPERACIONES = {
    "replace-fainted",
    "swap-party-box",
    "party-to-box",
    "box-to-party",
    "move-box-slot",
}


def _rama_bdsp(fuente: str) -> str:
    """El trozo que decide para Perla Reluciente, sin el de los demás juegos."""
    marcas = [
        m.start() for m in re.finditer(
            r'(live_key == "bdsp"|_active_azahar_realtime_key\(\) == "bdsp")', fuente,
        )
    ]
    assert marcas, "no se encontró la rama de BDSP"
    inicio = marcas[0]
    # Hasta que empiece la de otro juego.
    siguiente = re.search(
        r'(live_key in MELONDS|_active_azahar_realtime_key\(\) in GEN7|live_key == "xy")',
        fuente[inicio:],
    )
    return fuente[inicio:inicio + (siguiente.start() if siguiente else len(fuente))]


def test_el_writer_declara_las_cinco_operaciones() -> None:
    fuente = inspect.getsource(BDSPLiveWriter.apply)

    faltan = [op for op in OPERACIONES if f'"{op}"' not in fuente]
    assert not faltan, f"el writer ya no despacha: {faltan}"


def test_la_compuerta_de_aplicacion_automatica_las_deja_pasar_todas() -> None:
    """Sin esto el cambio se crea, se anuncia y no lo escribe nadie."""
    rama = _rama_bdsp(inspect.getsource(RoleRunManager._request_oras_live_auto_apply))

    faltan = [op for op in OPERACIONES if f'"{op}"' not in rama]
    assert not faltan, (
        "la interfaz ofrece estas operaciones y luego las descarta antes de "
        f"llegar al writer: {faltan}"
    )


def test_ninguna_se_anuncia_como_no_aplicable_en_vivo() -> None:
    """Avisar de que algo no se puede aplicar cuando si se puede confunde igual."""
    rama = _rama_bdsp(inspect.getsource(RoleRunManager._oras_live_unsupported_changes))

    faltan = [op for op in OPERACIONES if f'"{op}"' not in rama]
    assert not faltan, f"se declararian no aplicables en vivo: {faltan}"


def test_la_interfaz_ofrece_mover_dentro_del_pc_en_bdsp() -> None:
    """Si la compuerta lo acepta pero el gesto se rechaza, no sirve de nada."""
    fuente = inspect.getsource(RoleRunManager._team_pc_drop)
    indice = fuente.index('intent.operation == "move-box-slot"')
    permitidos = fuente[indice:indice + 260]

    assert '"bdsp"' in permitidos
