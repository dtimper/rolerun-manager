from pathlib import Path


def test_alpha27_sm_monitor_hooks_party_changes_into_live_pc_reconcile() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "ui.py").read_text(encoding="utf-8")
    marker = 'if self._active_azahar_realtime_key() == "sm":\n            before_game = self.current_game'
    start = source.index(marker)
    end = source.index('# Alpha.33: la salud de batalla', start)
    branch = source[start:end]
    assert 'getattr(difference, "party_changed", False)' in branch
    assert '_schedule_oras_external_pc_reconcile(before_game, snapshot.game)' in branch
    # Alpha.29 conserva el hook y la party se publica primero. La intención de rol
    # se deduce/retiene antes de arrancar PC, pero la ESCRITURA queda fuera de esta
    # rama y solo se dispara cuando el worker PC confirma host↔guest.
    assert branch.index('_publish_oras_live_snapshot') < branch.index('_incoming_oras_role_changes')
    assert branch.index('_incoming_oras_role_changes') < branch.index('_schedule_oras_external_pc_reconcile')
    assert '_save_oras_live_changes(' not in branch
