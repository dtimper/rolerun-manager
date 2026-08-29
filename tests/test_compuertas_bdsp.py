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
    from app.ui import PC_A_PC_GAME_KEYS

    assert "bdsp" in PC_A_PC_GAME_KEYS


def test_pintar_el_destino_y_ejecutarlo_usan_la_misma_lista() -> None:
    """Estaban escritas dos veces y no decian lo mismo.

    La que ejecuta el movimiento incluia Perla Reluciente; la que decide de que
    color se pinta el destino mientras arrastras, no. Resultado: en BDSP TODAS
    las casillas del PC salian en rojo —tanto las que iban a funcionar como las
    que no— y solo lo descubrias al soltar. Con las dos leyendo la misma lista
    no pueden volver a discrepar.
    """
    ejecutar = inspect.getsource(RoleRunManager._team_pc_drop)
    pintar = inspect.getsource(RoleRunManager._team_pc_can_drop)

    for fuente, nombre in ((ejecutar, "_team_pc_drop"), (pintar, "_team_pc_can_drop")):
        indice = fuente.index('intent.operation == "move-box-slot"')
        trozo = fuente[indice:indice + 260]
        assert "PC_A_PC_GAME_KEYS" in trozo, nombre
        assert '"usum"' not in trozo, f"{nombre} vuelve a llevar su propia lista"


def test_un_aviso_de_arrastre_no_se_queda_ahi_para_siempre() -> None:
    """El usuario lo leyó como el resultado de un movimiento que sí funcionó.

    *«después de probar un par de cambios entre casillas del PC exitosamente, me
    he fijado y pone abajo DESTINO NO HABILITADO… ya no sé qué pensar»*. El
    aviso era correcto cuando se escribió —había soltado en una casilla
    ocupada—, pero seguía abajo mucho después del gesto que lo provocó.
    """
    from app.ui_state.operation_status import OperationStatusStore

    tienda = OperationStatusStore()
    aviso = tienda.publish(
        "warning", "AHI NO SE PUEDE SOLTAR", "Esa casilla ya está ocupada.",
        persistent=False,
    )

    assert aviso.may_auto_collapse is True, "se quedaria hasta que otra cosa lo tape"
    assert tienda.collapse_if_current(aviso.revision) is True
    assert tienda.message.kind == "neutral"
    assert "confirmado" not in tienda.message.detail, (
        "un aviso no confirma nada, y decirlo es el mismo malentendido"
    )


def test_un_fallo_de_verdad_sigue_sin_irse_solo() -> None:
    from app.ui_state.operation_status import OperationStatusStore

    tienda = OperationStatusStore()
    fallo = tienda.publish("failed", "NO SE PUDO", "La escritura no se verificó.")

    assert fallo.may_auto_collapse is False
    assert tienda.collapse_if_current(fallo.revision) is False


def test_el_rechazo_de_soltar_ya_no_se_publica_como_permanente() -> None:
    fuente = inspect.getsource(RoleRunManager._team_pc_drop)
    indice = fuente.index("if intent.operation is None:")
    rechazo = fuente[indice:indice + 700]

    assert "persistent=False" in rechazo
    assert "DESTINO NO HABILITADO" not in rechazo, (
        "ese titulo se lee como que ha fallado lo ultimo que hiciste"
    )
