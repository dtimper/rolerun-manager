"""Un error de lectura no puede confundirse con un dato.

``_oras_live_snapshot_matches_disk`` decide si una diferencia entre la RAM y la
vista actual es un Reset/state-load o una edición hecha dentro del juego. Cuando
el motor fallaba al leer ``main`` devolvía ``False``, exactamente lo mismo que
«comprobado: no coincide». Con eso RoleRun daba por buena una huella viva que
nunca llegó a verificar y perdía la capacidad de detectar el Reset más tarde.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.save_engine_client import SaveEngineError  # noqa: E402
from app.ui import RoleRunManager  # noqa: E402


class _Snapshot:
    def __init__(self, game) -> None:
        self.game = game


def _manager(*, lectura) -> SimpleNamespace:
    """``lectura`` es lo que hace el motor: devolver una partida o fallar."""

    def read(path):
        if isinstance(lectura, Exception):
            raise lectura
        return lectura

    return SimpleNamespace(
        current_save=SimpleNamespace(path=Path("main")),
        save_engine=SimpleNamespace(read=read),
        _oras_live_disk_compare_error=None,
    )


def test_una_lectura_imposible_devuelve_desconocido_y_no_un_no() -> None:
    manager = _manager(lectura=SaveEngineError("el motor no respondió"))

    resultado = RoleRunManager._oras_live_snapshot_matches_disk(
        manager, _Snapshot(object()),
    )

    assert resultado is None, "un fallo del motor no puede parecer «no coincide»"
    assert manager._oras_live_disk_compare_error is not None
    assert "el motor no respondió" in manager._oras_live_disk_compare_error


def test_sin_partida_asociada_tambien_es_desconocido() -> None:
    manager = _manager(lectura=object())
    manager.current_save = None

    assert RoleRunManager._oras_live_snapshot_matches_disk(
        manager, _Snapshot(object()),
    ) is None


def test_una_comparacion_real_sigue_devolviendo_si_o_no(monkeypatch) -> None:
    import app.ui as ui

    huellas = {}
    monkeypatch.setattr(ui, "live_party_fingerprint", lambda game: huellas[id(game)])

    guardado, vivo = object(), object()
    huellas[id(guardado)] = "misma"
    huellas[id(vivo)] = "misma"
    manager = _manager(lectura=guardado)
    assert RoleRunManager._oras_live_snapshot_matches_disk(manager, _Snapshot(vivo)) is True
    assert manager._oras_live_disk_compare_error is None

    huellas[id(vivo)] = "distinta"
    assert RoleRunManager._oras_live_snapshot_matches_disk(manager, _Snapshot(vivo)) is False


def test_un_exito_posterior_limpia_el_rastro_del_error(monkeypatch) -> None:
    import app.ui as ui

    monkeypatch.setattr(ui, "live_party_fingerprint", lambda game: "igual")
    manager = _manager(lectura=object())
    manager._oras_live_disk_compare_error = "fallo anterior"

    RoleRunManager._oras_live_snapshot_matches_disk(manager, _Snapshot(object()))

    assert manager._oras_live_disk_compare_error is None
