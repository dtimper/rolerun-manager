"""La lane de batalla, contrastada con la traza física del 27-08-2026.

Los bytes de estas pruebas no están inventados: son las filas reales que
``tools_b2w2_battle_faint_capture.py`` registró en un combate de Negro 2 con seis
miembros en el equipo (`diagnostics/manual/b2w2_battle_faint_latest.json`).

Lo que esa traza demostró:

1. El **bloque de party de Gen 5 no refleja el daño durante el combate**. A los
   27 s la copia de presentación mostraba a Patrat con 3/16 PS y la party seguía
   diciendo 16/16. A los 39 s la presentación decía 0 y la party seguía en 16/16.
   La party solo se actualizó a los 47 s, al terminar el combate.

2. La **segunda fila estaba obsoleta durante todo el combate**: describía a otro
   miembro del equipo, sin moverse, y con un nivel imposible (516). Como
   ``parse_battle_copies`` exigía que ambas filas coincidieran en identidad,
   rechazaba la lectura entera.

Sumado: RoleRun descartaba la única fuente que sí tenía el dato y caía al bloque
de party, que no se actualiza hasta el final. Por eso ni los PS ni la baja
aparecían en tiempo real.

3. El byte de estado se mantuvo en 0 todo el combate, incluso con el Pokémon ya
   debilitado. La sospecha de que un estado no demostrado rompía la lane queda
   **descartada** por esta traza.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.b2w2_live import (  # noqa: E402
    BATTLE_READ_SIZE,
    BATTLE_ROW_SIZE,
    BATTLE_STATUS_OFFSET,
    B2W2LiveError,
    B2W2MelonDSReader,
    B2W2Pokemon,
)

# Filas exactas de la traza. Orden: especie, PS máx, PS, aux, aux, habilidad, nivel.
PRESENTACION_INICIO = [504, 16, 16, 0, 0, 51, 3]     # Patrat entero
PRESENTACION_HERIDO = [504, 16, 3, 0, 0, 51, 3]      # Patrat a 3 PS (t = 27 s)
PRESENTACION_CAIDO = [504, 16, 0, 0, 0, 51, 3]       # Patrat a 0 PS (t = 39 s)
SEGUNDA_FILA_OBSOLETA = [506, 18, 18, 0, 0, 72, 516]  # Lillipup, nivel imposible
VACIA = [0, 0, 0, 0, 0, 0, 0]


def _fila(valores, status: int = 0) -> bytes:
    crudo = bytearray(BATTLE_READ_SIZE)
    struct.pack_into("<7H", crudo, 0, *valores)
    crudo[BATTLE_STATUS_OFFSET] = status
    return bytes(crudo)


def _patrat() -> B2W2Pokemon:
    """El miembro real del equipo al que apunta la fila de presentación."""
    return B2W2Pokemon(
        slot=0, pid=111, tid=1, sid=2, species_id=504, form=0, nickname="Patrat",
        level=3, held_item_id=0, ability_id=51, move_ids=(33, 0, 0, 0),
        move_pp=(35, 0, 0, 0), move_pp_ups=(0, 0, 0, 0), markings=(False,) * 6,
        nature_id=0, is_egg=False, status_condition=0,
        stats=(16, 8, 7, 6, 6, 9), ivs=(0,) * 6, evs=(0,) * 6,
        current_hp=16, max_hp=16,
    )


def _otro() -> B2W2Pokemon:
    """El miembro al que apuntaba la fila obsoleta, con su nivel real."""
    return B2W2Pokemon(
        slot=1, pid=222, tid=1, sid=2, species_id=506, form=0, nickname="Lillipup",
        level=4, held_item_id=0, ability_id=72, move_ids=(33, 0, 0, 0),
        move_pp=(35, 0, 0, 0), move_pp_ups=(0, 0, 0, 0), markings=(False,) * 6,
        nature_id=0, is_egg=False, status_condition=0,
        stats=(18, 9, 9, 9, 9, 13), ivs=(0,) * 6, evs=(0,) * 6,
        current_hp=18, max_hp=18,
    )


EQUIPO = (_patrat(), _otro())


# --------------------------------------------------------------------------
# El caso que rompía: segunda fila obsoleta
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("presentacion", "ps"),
    [(PRESENTACION_INICIO, 16), (PRESENTACION_HERIDO, 3), (PRESENTACION_CAIDO, 0)],
)
def test_una_segunda_fila_obsoleta_ya_no_anula_la_lectura(presentacion, ps) -> None:
    """Es la traza real: la presentación bajaba 16 -> 3 -> 0 y se descartaba."""
    lectura = B2W2MelonDSReader.parse_battle_copies(
        _fila(presentacion), _fila(SEGUNDA_FILA_OBSOLETA), EQUIPO,
    )

    assert lectura.active is True
    assert lectura.party_slot == 0, "debe identificar a Patrat, no al de la fila obsoleta"
    assert lectura.current_hp == ps
    assert lectura.max_hp == 16


def test_el_ko_en_combate_se_puede_ver() -> None:
    """Sin esto, la baja solo aparecía al terminar el combate."""
    lectura = B2W2MelonDSReader.parse_battle_copies(
        _fila(PRESENTACION_CAIDO), _fila(SEGUNDA_FILA_OBSOLETA), EQUIPO,
    )
    assert lectura.current_hp == 0


# --------------------------------------------------------------------------
# Lo que no se relaja
# --------------------------------------------------------------------------

def test_la_presentacion_sigue_teniendo_que_ser_un_miembro_del_equipo() -> None:
    ajena = [999, 50, 25, 0, 0, 10, 20]
    with pytest.raises(B2W2LiveError, match="forma única"):
        B2W2MelonDSReader.parse_battle_copies(
            _fila(ajena), _fila(SEGUNDA_FILA_OBSOLETA), EQUIPO,
        )


def test_unos_ps_imposibles_siguen_rechazandose() -> None:
    incoherente = [504, 16, 99, 0, 0, 51, 3]     # 99 PS de un máximo de 16
    with pytest.raises(B2W2LiveError, match="incoherentes"):
        B2W2MelonDSReader.parse_battle_copies(
            _fila(incoherente), _fila(SEGUNDA_FILA_OBSOLETA), EQUIPO,
        )


def test_un_estado_no_demostrado_sigue_rechazandose() -> None:
    """La traza mostró estado 0 todo el combate; el resto sigue sin demostrarse."""
    with pytest.raises(B2W2LiveError, match="no demostrado"):
        B2W2MelonDSReader.parse_battle_copies(
            _fila(PRESENTACION_HERIDO, status=8),
            _fila(SEGUNDA_FILA_OBSOLETA), EQUIPO,
        )


def test_fuera_de_combate_ambas_filas_estan_vacias() -> None:
    lectura = B2W2MelonDSReader.parse_battle_copies(_fila(VACIA), _fila(VACIA), EQUIPO)
    assert lectura.active is False


def test_sin_copia_de_presentacion_no_se_publica_nada() -> None:
    """No se adelanta el daño usando la otra fila como sustituta."""
    lectura = B2W2MelonDSReader.parse_battle_copies(
        _fila(VACIA), _fila(SEGUNDA_FILA_OBSOLETA), EQUIPO,
    )
    assert lectura.active is False


# --------------------------------------------------------------------------
# Con corroboración, el comportamiento validado en alpha.5 no cambia
# --------------------------------------------------------------------------

def test_con_las_dos_filas_de_acuerdo_manda_la_presentacion() -> None:
    """La copia lógica adelanta el golpe; la HUD sigue mostrando la presentación."""
    lectura = B2W2MelonDSReader.parse_battle_copies(
        _fila(PRESENTACION_HERIDO),                 # presentación: 3 PS
        _fila([504, 16, 0, 0, 0, 51, 3]),           # lógica: ya en 0
        EQUIPO,
    )

    assert lectura.current_hp == 3, "no se adelanta el KO a la animación"
    assert lectura.mirror_hp == 3
    assert lectura.immediate_hp == 0
    assert lectura.converged is False


def test_cuando_ambas_coinciden_se_declara_convergido() -> None:
    lectura = B2W2MelonDSReader.parse_battle_copies(
        _fila(PRESENTACION_CAIDO), _fila(PRESENTACION_CAIDO), EQUIPO,
    )
    assert lectura.converged is True
    assert lectura.current_hp == 0


def test_sin_corroboracion_no_se_finge_una_convergencia_pendiente() -> None:
    lectura = B2W2MelonDSReader.parse_battle_copies(
        _fila(PRESENTACION_HERIDO), _fila(SEGUNDA_FILA_OBSOLETA), EQUIPO,
    )
    assert lectura.converged is True
    assert lectura.immediate_hp == lectura.mirror_hp
