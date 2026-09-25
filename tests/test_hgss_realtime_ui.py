"""HeartGold/SoulSilver: un `(0, 0)` suelto en combate no puede vaciar la vista.

Encontrado con un vídeo del usuario el 07-09-2026: incluso con
`HgssMelonDSReader.read_battle_probe` ya arreglado para no dar un combate
por terminado con un solo `(0, 0)` (exige dos seguidos, ver
`tests/test_hgss_battle_lane.py`), la barra de PS de una tarjeta de rol
seguía parpadeando -se vaciaba y se rellenaba de golpe- durante los turnos.

Causa real: un `(0, 0)` suelto en la dirección ya confirmada SÍ sigue
publicándose como `state="unknown"` para ese sondeo -es la señal correcta,
ninguna mentira-, pero `_finish_oras_live_reconciliation` trataba
"unknown" exactamente igual que "sin combate": caía al bloque de party
(`snapshot.game`) en ESE MISMO sondeo. Para ORAS/B2W2 eso es correcto -su
tabla trae un PS por miembro incluso fuera de un sondeo "battle"
confirmado, así que no hay nada que destripar (ver
`test_b2w2_health_and_floating_flicker.py`)-, pero HGSS NO tiene esa
tabla: fuera de un sondeo "battle", ni siquiera el propio combatiente
activo trae PS en vivo en `snapshot.game` -se queda con el valor de antes
de entrar en combate-, así que caer ahí publica un salto a PS completo que
el siguiente sondeo corrige él solo: el parpadeo del vídeo.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.save_engine_client import SaveGameData, SavePokemon  # noqa: E402
from app.ui import RoleRunManager  # noqa: E402


def _mon(*, hp: int, max_hp: int = 51, pid: int = 158) -> SavePokemon:
    return SavePokemon(
        slot=0, species_id=158, species="Totodile", nickname="Totodile", level=15,
        held_item="Ninguno", ability="Torrente", moves=["Mordisco"],
        move_ids=[44], is_egg=False, markings=[False] * 6, role="Mago",
        role_symbol="•", pid=pid, tid=1, sid=2,
        current_hp=hp, max_hp=max_hp,
    )


def _game(pokemon) -> SaveGameData:
    return SaveGameData("HG", "SAV4HGSS", 4, "Diego", [pokemon], {})


def _monitor(probe) -> SimpleNamespace:
    """Lo mínimo para recorrer la rama de cuarta del monitor."""
    publicados = []
    retrasos = []
    manager = SimpleNamespace(
        _oras_live_monitor_in_progress=True,
        _oras_live_monitor_token=5,
        _session_generation=1,
        project=SimpleNamespace(slug="run"),
        current_game=_game(_mon(hp=42)),
        _oras_live_monitor_failures=0,
        _oras_battle_probe_last_state="none",
        _oras_live_health_snapshot=None,
        _live_sync_in_progress=False,
        publicados=publicados,
        retrasos=retrasos,
        _active_azahar_realtime_key=lambda: "hgss",
        _oras_live_reconciliation_is_active=lambda: True,
        _cancel_oras_initial_auto_sync=lambda: None,
        _discard_b2w2_ghost_team_changes=lambda: 0,
        _live_metadata_is_missing=lambda current, live: False,
        _publish_oras_live_snapshot=lambda snapshot, **kwargs: None,
        _update_top_status=lambda: None,
        _schedule_oras_live_reconciliation=lambda delay: retrasos.append(delay),
        _sync_live_layout=lambda refresh_floating=True: None,
        _schedule_team_integrity_check=lambda: None,
        _sync_hgss_levelup_moves=lambda game: None,
        _probe=probe,
        estados_de_combate=[],
        reconciliaciones=[],
    )
    manager._process_oras_battle_state = lambda state: (
        manager.estados_de_combate.append(state)
    )
    manager._process_six_mon_battle_probe = lambda probe, state: None
    manager._reconcile_pending_faints_against_party = lambda game: (
        manager.reconciliaciones.append(game)
    )
    manager._pokemon_identity = lambda pokemon: (
        int(pokemon.species_id), int(pokemon.pid or 0),
        int(pokemon.tid or 0), int(pokemon.sid or 0),
    )

    def procesar(game, *, source="overworld"):
        publicados.append((game, source))
        manager._oras_live_health_snapshot = game

    manager._process_oras_health_snapshot = procesar
    return manager


def _run_monitor(manager, snapshot) -> None:
    RoleRunManager._finish_oras_live_reconciliation(
        manager, 1, "run", 5, None, snapshot, None, battle_probe=manager._probe,
    )


def test_un_unknown_tras_battle_no_publica_nada_y_conserva_el_ultimo_ps() -> None:
    """El caso real del vídeo: Totodile en pleno combate, un `(0, 0)`

    suelto en la dirección ya confirmada. No debe verse absolutamente
    nada -ni una publicación, ni un cambio de snapshot-.
    """
    presentacion = _game(_mon(hp=22))
    manager = _monitor(SimpleNamespace(state="unknown", health_game=None))
    manager._oras_battle_probe_last_state = "battle"
    manager._oras_live_health_snapshot = presentacion
    vivo = _game(_mon(hp=42))  # el bloque de party, con el PS de ANTES del combate

    _run_monitor(manager, SimpleNamespace(game=vivo))

    assert manager.publicados == [], "no debía publicarse nada -ni el de reserva ni ningún otro-"
    assert manager._oras_live_health_snapshot is presentacion, "el último PS en vivo debía conservarse intacto"
    # No se toca: seguimos en el mismo combate, solo que este sondeo no lo confirmó.
    assert manager._oras_battle_probe_last_state == "battle"


def test_un_desmayo_real_durante_el_margen_si_se_publica() -> None:
    """Caso real medido con el usuario el 07-09-2026: un Rattata rematado

    en dos golpes apareció a 0/14 en el bloque de equipo mientras la
    pantalla del juego seguía pidiendo sustituto -el combate NO había
    terminado todavía-. El bloque de equipo SÍ se escribe al instante en
    cuanto alguien se desmaya, así que esta transición concreta -a
    diferencia del salto a PS completo que hay que evitar- debe dejarse
    pasar aunque estemos dentro del margen de "unknown tras battle".
    """
    presentacion = _game(_mon(hp=5))  # bajo pero vivo, la última lectura buena
    manager = _monitor(SimpleNamespace(state="unknown", health_game=None))
    manager._oras_battle_probe_last_state = "battle"
    manager._oras_live_health_snapshot = presentacion
    desmayado = _game(_mon(hp=0))  # el bloque de equipo ya refleja la muerte

    _run_monitor(manager, SimpleNamespace(game=desmayado))

    assert manager.publicados == [(desmayado, "overworld")]
    assert manager._oras_live_health_snapshot is desmayado


def test_un_battle_confirmado_tras_el_parpadeo_vuelve_a_publicar_en_vivo() -> None:
    presentacion = _game(_mon(hp=20))
    manager = _monitor(SimpleNamespace(state="battle", health_game=presentacion))
    manager._oras_battle_probe_last_state = "battle"
    vivo = _game(_mon(hp=42))

    _run_monitor(manager, SimpleNamespace(game=vivo))

    assert manager.publicados == [(presentacion, "battle-visible")]
    assert manager._oras_live_health_snapshot is presentacion


def test_un_unknown_sin_combate_previo_si_manda_el_bloque_de_party() -> None:
    """Sin ninguna prueba anterior de que hay combate, no hay nada que

    conservar -cae al bloque de party, igual que ORAS/B2W2-.
    """
    manager = _monitor(SimpleNamespace(state="unknown", health_game=None))
    manager._oras_battle_probe_last_state = "none"
    vivo = _game(_mon(hp=51))

    _run_monitor(manager, SimpleNamespace(game=vivo))

    assert manager.publicados == [(vivo, "overworld")]
    assert manager._oras_battle_probe_last_state == "none"


def test_un_unknown_tras_battle_sigue_sondeando_al_ritmo_rapido() -> None:
    """El bug real medido el 07-09-2026, séptima vuelta: al ritmo lento

    (950 ms) tras un `"unknown"`, un parpadeo real de HeartGold que dura
    más de un sondeo tenía margen de sobra para que la SEGUNDA
    comprobación -la que decide si el combate terminó de verdad, ver
    `COMBATE_SEGUNDOS_DE_CERO_PARA_CONFIRMAR_FIN` en `hgss_live.py`- cayera
    TAMBIÉN dentro de la ventana mala, confirmando un final que no era
    real -medido: Totodile seguía a 45/51 en pantalla cuando el lector ya
    había dado el combate por terminado-. Reintentar al ritmo rápido
    mientras se siga considerando que hay combate le da a esa segunda
    comprobación una ventana mucho más ajustada.
    """
    manager = _monitor(SimpleNamespace(state="unknown", health_game=None))
    manager._oras_battle_probe_last_state = "battle"

    _run_monitor(manager, SimpleNamespace(game=_game(_mon(hp=45))))

    assert manager.retrasos == [250]


def test_un_none_de_verdad_vuelve_al_ritmo_lento() -> None:
    manager = _monitor(SimpleNamespace(state="none", health_game=None))
    manager._oras_battle_probe_last_state = "battle"

    _run_monitor(manager, SimpleNamespace(game=_game(_mon(hp=51))))

    assert manager.retrasos == [950]


def test_sin_combate_confirmado_de_verdad_si_manda_el_bloque_de_party() -> None:
    """`state="none"` no es el `(0, 0)` suelto -son dos ceros seguidos en

    el lector, ver `test_hgss_battle_lane.py`-, así que sigue siendo una
    señal fiable de que el combate terminó.
    """
    manager = _monitor(SimpleNamespace(state="none", health_game=None))
    manager._oras_battle_probe_last_state = "battle"
    manager._oras_live_health_snapshot = _game(_mon(hp=5))
    vivo = _game(_mon(hp=51))

    _run_monitor(manager, SimpleNamespace(game=vivo))

    assert manager.publicados == [(vivo, "overworld")]
    assert manager._oras_battle_probe_last_state == "none"
